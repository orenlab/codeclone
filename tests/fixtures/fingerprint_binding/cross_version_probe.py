# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Emit the cross-interpreter wire/fingerprint projection for one corpus.

Run under every supported interpreter; the output must be byte-identical on
all of them (39Y-FP M21). Kept as a fixture rather than a test helper because
it is executed by a bare interpreter over ``PYTHONPATH`` with no test
framework and no installed package.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import sys

from codeclone.analysis.binding import build_module_bindings
from codeclone.analysis.fingerprint import _cfg_fingerprint_and_complexity
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.wire import emit_wire

_CONFIG = NormalizationConfig()


def _resolve(node: ast.ImportFrom) -> str | None:
    return (node.module or "") if node.level == 0 else None


_Row = tuple[str, str, int, str, str]


def _rows(paths: list[pathlib.Path]) -> list[_Row]:
    rows: list[_Row] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        bindings = build_module_bindings(tree, resolve_from_import=_resolve)
        module_wire = emit_wire(tree, _CONFIG, bindings)
        rows.append(
            (
                path.name,
                "<module>",
                0,
                hashlib.sha256(module_wire.encode("utf-8")).hexdigest(),
                "",
            )
        )
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            scope = bindings.enter(node)
            _graph, fingerprint, _complexity = _cfg_fingerprint_and_complexity(
                node, _CONFIG, f"fixture:{node.name}", scope
            )
            wire = emit_wire(node, _CONFIG, bindings)
            rows.append(
                (
                    path.name,
                    node.name,
                    node.lineno,
                    hashlib.sha256(wire.encode("utf-8")).hexdigest(),
                    fingerprint,
                )
            )
    rows.sort()
    return rows


def main() -> None:
    paths = [pathlib.Path(argument) for argument in sys.argv[1:]]
    rows = _rows(paths)
    payload = json.dumps(rows, separators=(",", ":"), sort_keys=True)
    sys.stdout.write(
        json.dumps(
            {
                "corpus_digest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "row_count": len(rows),
                "rows": rows,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
