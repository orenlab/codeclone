# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Metamorphic contract for the binding-aware fingerprint wire (39Y-FP).

The rows come from ``tests/fixtures/fingerprint_binding/ground_truth.json``,
which is authored by hand from the normative role table and is never generated
from emitter output. Each row states a relation between two fixture modules —
their fingerprints must be equal (rename invariance) or different (identity
sensitivity) — so the corpus pins both directions at once. A normalization that
merges everything satisfies the equal rows and fails the different rows; one
that merges nothing does the reverse.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.analysis.wire import emit_wire
from codeclone.cache.store import Cache
from codeclone.core import discovery as core_discovery
from codeclone.core.parallelism import process
from tests._ast_metrics_helpers import bindings_for_tree, module_registry_context
from tests._pipeline_fixtures import analysis_boot, discover_and_process

_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "fingerprint_binding"
_CONFIG = NormalizationConfig()


def _cross_version_probe() -> ModuleType:
    """Load the probe the interpreter matrix runs, so both share one projection."""

    path = _FIXTURE_ROOT / "cross_version_probe.py"
    spec = importlib.util.spec_from_file_location("_cc_cross_version_probe", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ground_truth() -> dict[str, Any]:
    raw = json.loads((_FIXTURE_ROOT / "ground_truth.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _fingerprints(fixture_name: str) -> dict[str, str]:
    """Return ``local qualname -> fingerprint`` for one fixture module.

    Deliberately routed through the real extraction entry point rather than the
    fingerprint helper: the binding context is an extraction-time product, so a
    test that reached past it would be testing a different pipeline than the one
    that writes units.
    """

    module_name = fixture_name.removesuffix(".py")
    filepath = fixture_name
    source = (_FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8")
    identity, registry = module_registry_context(
        filepath=filepath,
        module_name=module_name,
    )
    units, *_ = extract_units_and_stats_from_source(
        source=source,
        filepath=filepath,
        identity=identity,
        registry=registry,
        cfg=_CONFIG,
        min_loc=1,
        min_stmt=1,
    )
    return {unit.qualname.partition(":")[2]: unit.fingerprint for unit in units}


def _fingerprint(fixture_name: str, function: str) -> str:
    table = _fingerprints(fixture_name)
    assert function in table, (
        f"{fixture_name} has no function {function}: {sorted(table)}"
    )
    return table[function]


_PAIRS = _ground_truth()["fingerprint_pairs"]


@pytest.mark.parametrize(
    "row",
    _PAIRS,
    ids=[str(row["row"]) for row in _PAIRS],
)
def test_metamorphic_fingerprint_row(row: dict[str, str]) -> None:
    left = _fingerprint(row["left"], row["function"])
    right = _fingerprint(row["right"], row["function"])
    if row["relation"] == "equal":
        assert left == right, (
            f"{row['row']} expects equal fingerprints ({row['pins']}): "
            f"{row['left']}={left} {row['right']}={right}"
        )
        return
    assert row["relation"] == "different", row
    assert left != right, (
        f"{row['row']} expects different fingerprints ({row['pins']}): "
        f"both {row['left']} and {row['right']} produced {left}"
    )


def _statement_wire(fixture_name: str, function: str, index: int) -> str:
    """Wire of one statement, read under the scope of its owning function."""

    source = (_FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    bindings = bindings_for_tree(tree)
    owner = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function
    )
    return emit_wire(owner.body[index], _CONFIG, bindings.enter(owner))


_SCOPE_ROWS = _ground_truth()["scope_graph_rows"]


@pytest.mark.parametrize(
    "row",
    _SCOPE_ROWS,
    ids=[str(row["row"]) for row in _SCOPE_ROWS],
)
def test_scope_graph_row(row: dict[str, Any]) -> None:
    """M12-M20 — each row pins exactly one rule of the lexical scope graph.

    The expected wires are written by hand from the role table, never captured
    from the emitter, so a wrong implementation cannot make its own output the
    definition of correct.
    """

    for statement in row["statements"]:
        actual = _statement_wire(row["fixture"], row["function"], statement["index"])
        assert actual == statement["wire"], (
            f"{row['row']} ({row['pins']}): statement {statement['index']} of "
            f"{row['function']} in {row['fixture']}"
        )


def _encode_fingerprint(units: Sequence[Mapping[str, object]]) -> str:
    matches = [unit for unit in units if str(unit["qualname"]).endswith(":encode")]
    assert len(matches) == 1, [unit["qualname"] for unit in units]
    return str(matches[0]["fingerprint"])


def test_cache_invalidates_when_only_the_binding_context_changes(
    tmp_path: Path,
) -> None:
    """M22 — the fingerprint is a function of (AST x binding context).

    ``encode`` has byte-identical statements in both revisions; only the import
    above it changes, so the symbol it calls changes from ``json.dumps`` to
    ``yaml.dumps``. A plain cold==warm comparison would not catch a stale reuse
    here — both modes can honestly agree on the same stale answer — so the cold
    fingerprint is required to MOVE first, and the warm one to move with it.
    """

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    target = package / "consumer.py"
    body = "def encode(value):\n    return codec.dumps(value)\n"

    def write(import_line: str) -> None:
        target.write_text(f"{import_line}\n\n\n{body}", encoding="utf-8")

    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)
    cache_path = tmp_path / "cache.json"

    write("import json as codec")
    cold_cache, _cold_discovery, first = discover_and_process(
        boot, cache_path, root=tmp_path, warm=False
    )
    cold_cache.save()
    json_fingerprint = _encode_fingerprint(first.units)

    write("import yaml as codec")
    _fresh_cache, _second_discovery, second = discover_and_process(
        boot, tmp_path / "cache-cold.json", root=tmp_path, warm=False
    )
    cold_yaml_fingerprint = _encode_fingerprint(second.units)

    assert cold_yaml_fingerprint != json_fingerprint, (
        "the same body calling a different resolved symbol must fingerprint "
        "differently, or identity is not in the wire at all"
    )

    _warm_cache, _warm_discovery, warm = discover_and_process(
        boot, cache_path, root=tmp_path, warm=True
    )
    warm_fingerprint = _encode_fingerprint(warm.units)

    assert warm_fingerprint == cold_yaml_fingerprint, (
        "warm run served a fingerprint the cold run does not produce: the "
        "cache reused an entry whose binding context had moved"
    )
    assert warm_fingerprint != json_fingerprint


def _run_pipeline(
    root: Path,
    cache_path: Path,
    *,
    source_roots: tuple[str, ...],
    warm: bool,
) -> tuple[Cache, list[Mapping[str, object]]]:
    boot = analysis_boot(root, min_loc=1, min_stmt=1, skip_metrics=True)
    boot.args.source_roots = source_roots
    cache = Cache(cache_path, root=root)
    if warm:
        cache.load()
    discovery = core_discovery.discover(boot=boot, cache=cache)
    processing = process(boot=boot, discovery=discovery, cache=cache)
    return cache, list(processing.units)


def test_cache_invalidates_when_the_module_mount_changes(tmp_path: Path) -> None:
    """M22, mount case — package position is a BindingContext input.

    ``from . import helper`` resolves through the importing module's package,
    so the same bytes at the same path fingerprint differently under a
    different source-root mount. Nothing in the file changed, so content
    identity alone cannot reject the stale entry: the cache key has to carry
    the binding context itself. Without that the warm run serves the other
    mount's fingerprint — a wrong answer, not a stale-but-equal one.
    """

    root = tmp_path.resolve()
    package = root / "src" / "pkg"
    package.mkdir(parents=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text(
        "def dumps(value):\n    return value\n", encoding="utf-8"
    )
    (package / "consumer.py").write_text(
        "from . import helper\n\n\n"
        "def encode(value):\n    return helper.dumps(value)\n",
        encoding="utf-8",
    )
    cache_path = root / "cache.json"

    cache_a, units_a = _run_pipeline(root, cache_path, source_roots=(".",), warm=False)
    cache_a.save()
    mounted_at_root = _encode_fingerprint(units_a)

    _cache_b, units_b = _run_pipeline(
        root, root / "cache-b.json", source_roots=("src",), warm=False
    )
    mounted_at_src = _encode_fingerprint(units_b)

    assert mounted_at_root != mounted_at_src, (
        "the same body reaching a different resolved module must fingerprint "
        "differently, or relative-import identity is not in the wire"
    )

    _cache_warm, units_warm = _run_pipeline(
        root, cache_path, source_roots=("src",), warm=True
    )
    assert _encode_fingerprint(units_warm) == mounted_at_src, (
        "warm run served the fingerprint of the other mount: the cache reused "
        "an entry whose binding context had moved"
    )


def test_cross_version_corpus_is_byte_identical() -> None:
    """M21 — the wire and its fingerprints do not depend on the interpreter.

    This is a gate, not a report. The digest below was proven equal on CPython
    3.10, 3.11, 3.12, 3.13 and 3.14; the suite re-checks it on whichever
    interpreter runs, and CI runs all of them. Two processes and two hash seeds
    only ever proved intra-version determinism — a grammar-shaped difference
    between versions would have walked straight into a shared baseline.
    """

    expected = _ground_truth()["cross_version"]
    fixture_root = _FIXTURE_ROOT.parent
    paths = [fixture_root / name for name in expected["corpus"]]
    rows = _cross_version_probe()._rows(paths)
    payload = json.dumps(rows, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert len(rows) == expected["row_count"]
    assert digest == expected["corpus_digest"], (
        "cross-interpreter wire projection moved; a wire that depends on the "
        "running interpreter cannot back a shared baseline"
    )
