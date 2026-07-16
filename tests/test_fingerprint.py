# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import sys
from pathlib import Path

from codeclone.analysis.fingerprint import (
    _cfg_fingerprint_and_complexity,
    bucket_loc,
    sha256_hex,
)
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.phase_ledger import PhaseLedger
from codeclone.blocks import stmt_hashes

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FP_RE = re.compile(r"[0-9a-f]{64}\Z")
_CFG = NormalizationConfig()


def _function(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    node = ast.parse(source).body[0]
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    return node


def _fingerprint(source: str, *, active_ledger: bool = False) -> str:
    node = _function(source)
    _graph, fingerprint, _complexity = _cfg_fingerprint_and_complexity(
        node,
        _CFG,
        f"test:{node.name}",
        phase_ledger=PhaseLedger(active=active_ledger),
    )
    return fingerprint


def test_sha256_helper_is_domain_separated_and_hex64() -> None:
    payload = "Return(value=Name(id=_VAR_))"
    function_hash = sha256_hex(b"ccfp2:fn\x00", payload)
    statement_hash = sha256_hex(b"ccfp2:stmt\x00", payload)
    assert _FP_RE.fullmatch(function_hash)
    assert _FP_RE.fullmatch(statement_hash)
    assert function_hash != statement_hash


def test_bucket_loc_ranges() -> None:
    assert bucket_loc(0) == "0-19"
    assert bucket_loc(19) == "0-19"
    assert bucket_loc(20) == "20-49"
    assert bucket_loc(49) == "20-49"
    assert bucket_loc(50) == "50-99"
    assert bucket_loc(99) == "50-99"
    assert bucket_loc(100) == "100+"


def test_function_fingerprint_is_hex64() -> None:
    assert _FP_RE.fullmatch(_fingerprint("def f(value):\n    return value\n"))


def test_async_and_sync_functions_are_distinct() -> None:
    sync = _fingerprint("def f(value):\n    return value\n")
    async_ = _fingerprint("async def f(value):\n    return value\n")
    assert sync != async_


def test_signature_shape_is_part_of_fingerprint() -> None:
    positional = _fingerprint("def f(value):\n    return value\n")
    keyword_only = _fingerprint("def f(*, value):\n    return value\n")
    with_default = _fingerprint("def f(value=1):\n    return value\n")
    assert len({positional, keyword_only, with_default}) == 3


def test_decorators_remain_outside_fingerprint() -> None:
    undecorated = _fingerprint("def f(value):\n    return value\n")
    decorated = _fingerprint("@route\ndef f(value):\n    return value\n")
    assert undecorated == decorated


def test_match_constants_and_delimiter_payloads_normalize() -> None:
    one = _fingerprint(
        "def f(value):\n    match value:\n        case 1:\n            return 1\n"
    )
    two = _fingerprint(
        "def f(value):\n    match value:\n        case 2:\n            return 2\n"
    )
    injected = _fingerprint(
        'def f(value):\n    match value:\n        case "a|SUCCESSORS:0":\n'
        "            return 1\n"
    )
    innocuous = _fingerprint(
        'def f(value):\n    match value:\n        case "ordinary":\n'
        "            return 2\n"
    )
    assert one == two
    assert injected == innocuous


def test_exception_types_and_try_kind_are_semantic() -> None:
    value_error = _fingerprint(
        "def f():\n"
        "    try:\n"
        "        work()\n"
        "    except ValueError:\n"
        "        recover()\n"
    )
    type_error = _fingerprint(
        "def f():\n    try:\n        work()\n    except TypeError:\n        recover()\n"
    )
    try_star = _fingerprint(
        "def f():\n"
        "    try:\n"
        "        work()\n"
        "    except* ValueError:\n"
        "        recover()\n"
    )
    assert value_error != type_error
    assert value_error != try_star


def test_phase_ledger_does_not_change_fingerprint_bytes() -> None:
    source = (
        "def f(value):\n    if value:\n        return work(value)\n    return None\n"
    )
    assert _fingerprint(source) == _fingerprint(source, active_ledger=True)


def test_statement_hashes_are_hex64_and_read_only() -> None:
    statement = ast.parse("value = source + 1").body[0]
    before = ast.dump(statement, annotate_fields=True, include_attributes=True)
    hashes = stmt_hashes([statement], _CFG)
    after = ast.dump(statement, annotate_fields=True, include_attributes=True)
    assert len(hashes) == 1
    assert _FP_RE.fullmatch(hashes[0])
    assert before == after


def test_fingerprint_subprocesses_are_deterministic() -> None:
    script = """
import ast
import json
import pathlib
import sys
from codeclone.analysis.fingerprint import _cfg_fingerprint_and_complexity
from codeclone.analysis.normalizer import NormalizationConfig

config = NormalizationConfig()
rows = []
for raw_path in sys.argv[1:]:
    path = pathlib.Path(raw_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _graph, fingerprint, _ = _cfg_fingerprint_and_complexity(
                node, config, f"fixture:{node.name}"
            )
            rows.append((path.name, node.name, node.lineno, fingerprint))
sys.stdout.write(json.dumps(sorted(rows), separators=(",", ":")))
"""
    fixture_root = _REPO_ROOT / "tests" / "fixtures" / "wire_corpus"
    fixtures = [fixture_root / "core_syntax.py", fixture_root / "pattern_syntax.py"]
    outputs = [
        subprocess.run(
            [sys.executable, "-c", script, *(str(path) for path in fixtures)],
            cwd=_REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for _ in range(3)
    ]
    assert outputs[0] == outputs[1] == outputs[2]
    assert (
        hashlib.sha256(outputs[0].encode("utf-8")).hexdigest()
        == "c561edaebf3b9b75a5caa9770e6494003dc6ab716b3d50064eeef215ccb426fb"
    )
