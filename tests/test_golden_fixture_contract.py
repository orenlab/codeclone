# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

_FIXTURES_ROOT = Path(__file__).parent / "fixtures"
_DOMAINS = (
    "liveness_policy",
    "source_kind",
    "clone_tiers",
    "design_metrics",
    "statement_reachability",
)


def _load_ground_truth(domain: str) -> tuple[Path, dict[str, Any]]:
    domain_root = _FIXTURES_ROOT / domain
    payload = json.loads((domain_root / "ground_truth.json").read_text())
    return domain_root, payload


def _definition_names(path: Path) -> set[str]:
    names: set[str] = set()
    parents: list[str] = []

    class DefinitionVisitor(ast.NodeVisitor):
        def _visit_definition(self, node: ast.ClassDef | ast.FunctionDef) -> None:
            qualified_name = ".".join((*parents, node.name))
            names.add(qualified_name)
            parents.append(node.name)
            self.generic_visit(node)
            parents.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._visit_definition(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_definition(node)

    DefinitionVisitor().visit(ast.parse(path.read_text(), filename=str(path)))
    return names


@pytest.mark.parametrize("domain", _DOMAINS)
def test_golden_ground_truth_is_complete(domain: str) -> None:
    domain_root, payload = _load_ground_truth(domain)

    assert payload["schema_version"] == 1
    assert payload["domain"] == domain
    assert payload["golden"] is True

    cases = payload["cases"]
    cases_by_id = {case["id"]: case for case in cases}
    assert cases
    assert len(cases_by_id) == len(cases)
    for case in cases:
        assert (domain_root / case["path"]).is_file()

    for original_id, renamed_id in payload["rename_twins"]:
        assert (
            cases_by_id[original_id]["expected"] == cases_by_id[renamed_id]["expected"]
        )

    for left_id, right_id in payload["negative_twins"]:
        assert left_id in cases_by_id
        assert right_id in cases_by_id


@pytest.mark.parametrize("domain", _DOMAINS)
def test_golden_case_symbols_exist(domain: str) -> None:
    domain_root, payload = _load_ground_truth(domain)
    definitions_by_path: dict[str, set[str]] = {}

    for case in payload["cases"]:
        if "symbol" not in case and "members" not in case:
            continue
        relative_path = case["path"]
        definitions = definitions_by_path.setdefault(
            relative_path,
            _definition_names(domain_root / relative_path),
        )
        expected_symbols = [case["symbol"]] if "symbol" in case else case["members"]
        assert set(expected_symbols) <= definitions


@pytest.mark.parametrize("domain", _DOMAINS)
def test_golden_python_fixtures_compile(domain: str) -> None:
    domain_root, _payload = _load_ground_truth(domain)

    python_paths = sorted(domain_root.rglob("*.py"))
    assert python_paths
    for path in python_paths:
        compile(path.read_text(), str(path), "exec")


def _declared_twin_pairs(payload: dict[str, Any]) -> set[str]:
    return {
        f"{left}|{right}"
        for group in ("rename_twins", "negative_twins")
        for left, right in payload.get(group, ())
    }


def _assert_parked_cases_valid(domain_root: Path, payload: dict[str, Any]) -> None:
    """Validate the optional ``parked_cases`` metadata block.

    Parked cases record a rule that was rolled back: they must stay real
    (file and symbol still present, so they can be reinstated verbatim) and
    must never shadow an active case id.
    """
    block = payload.get("parked_cases")
    if block is None:
        return

    assert isinstance(block, dict), "parked_cases must be an object"
    assert str(block.get("rationale", "")).strip(), (
        "parked_cases must record why the cases are parked"
    )

    cases = block.get("cases")
    assert isinstance(cases, list) and cases, "parked_cases must list at least one case"

    parked_ids = [case["id"] for case in cases]
    assert len(set(parked_ids)) == len(parked_ids), "parked case ids must be unique"

    active_ids = {case["id"] for case in payload.get("cases", ())}
    assert not (set(parked_ids) & active_ids), (
        "a parked case id must not shadow an active case id"
    )

    for case in cases:
        case_path = domain_root / case["path"]
        assert case_path.is_file(), f"parked case path is missing: {case['path']}"
        # Reinstatement has to stay possible, so the parked subjects must still
        # exist - whether the case names one symbol or a member set.
        expected_symbols = case.get("members", [])
        if "symbol" in case:
            expected_symbols = [case["symbol"], *expected_symbols]
        if expected_symbols:
            definitions = _definition_names(case_path)
            assert set(expected_symbols) <= definitions, (
                f"parked case subject is missing: {sorted(expected_symbols)}"
            )

    known_ids = set(parked_ids) | active_ids
    for group in ("rename_twins", "negative_twins"):
        for left, right in block.get(group, ()):
            assert left in known_ids and right in known_ids, (
                f"parked {group} reference an unknown case id: {left}, {right}"
            )


def _assert_twin_axes_valid(payload: dict[str, Any]) -> None:
    """Validate the optional ``twin_axes`` metadata block.

    Declaring axes is opt-in, but once a domain declares them every key must
    document a real twin pair and every negative twin must be documented -
    an undocumented discriminating pair is the failure this fences.
    """
    axes = payload.get("twin_axes")
    if axes is None:
        return

    assert isinstance(axes, dict), "twin_axes must be an object"
    declared = _declared_twin_pairs(payload)

    for key, description in axes.items():
        assert key.count("|") == 1, f"twin_axes key must be 'LEFT|RIGHT': {key}"
        left, _, right = key.partition("|")
        assert left and right, f"twin_axes key must name two cases: {key}"
        assert key in declared, f"twin_axes documents an undeclared pair: {key}"
        assert str(description).strip(), f"twin_axes entry is empty: {key}"

    for left, right in payload.get("negative_twins", ()):
        assert f"{left}|{right}" in axes, (
            f"negative twin is undocumented in twin_axes: {left}|{right}"
        )


@pytest.mark.parametrize("domain", _DOMAINS)
def test_golden_metadata_blocks_are_valid(domain: str) -> None:
    domain_root, payload = _load_ground_truth(domain)
    _assert_parked_cases_valid(domain_root, payload)
    _assert_twin_axes_valid(payload)


def test_exactly_one_domain_parks_cases_today() -> None:
    """The park ledger, asserted rather than described in a comment.

    ``clone_tiers`` parks two classes. ``PAIR-INT-02`` / ``R-PAIR-INT-02``:
    the pair is a single multi-line statement, below the clone lane's
    eligibility floor, so the tier the golden claimed for it was unreachable -
    deferred to the Y7 ``min_stmt`` review. ``PAIR-T4-AGG-01`` /
    ``R-PAIR-T4-AGG-01`` (39Y-FP): the customer/supplier aggregation is one
    computation parametrizable by a single extracted helper, provable only
    over the 39D contract-IR canonicalization in the post-39R Type-4 phase;
    claiming it today would need symbol identity erased, which is refused, so
    the case is promoted into that phase's corpus instead of being dropped.
    Any further park - or an un-park - must land here deliberately instead of
    drifting in unnoticed.
    """

    parked_by_domain = {
        domain: sorted(
            case["id"]
            for case in _load_ground_truth(domain)[1]["parked_cases"]["cases"]
        )
        for domain in _DOMAINS
        if _load_ground_truth(domain)[1].get("parked_cases") is not None
    }
    assert parked_by_domain == {
        "clone_tiers": [
            "PAIR-INT-02",
            "PAIR-T4-AGG-01",
            "R-PAIR-INT-02",
            "R-PAIR-T4-AGG-01",
        ],
    }


def test_golden_metadata_validation_rejects_malformed_blocks() -> None:
    domain_root, payload = _load_ground_truth("liveness_policy")
    active_id = payload["cases"][0]["id"]
    # liveness_policy parks nothing, so this fence builds its own well-formed
    # block rather than borrowing the clone_tiers one. It still names a real
    # file and a real symbol, because that is exactly what the validator
    # checks.
    parked_case = {
        "id": "SYNTHETIC-PARKED",
        "path": "distillations/roots.py",
        "symbol": "LocalHandler.handle",
        "expected": {"status": "dead", "reason": "unreferenced"},
    }
    _assert_parked_cases_valid(
        domain_root,
        {
            **payload,
            "parked_cases": {
                "rationale": "the synthetic block is itself well-formed",
                "cases": [dict(parked_case)],
                "rename_twins": [],
                "negative_twins": [],
            },
        },
    )

    def parked(**overrides: Any) -> dict[str, Any]:
        block: dict[str, Any] = {
            "rationale": "why these are parked",
            "cases": [dict(parked_case)],
            "rename_twins": [],
            "negative_twins": [],
        }
        block.update(overrides)
        return {**payload, "parked_cases": block}

    # A parked block must carry a non-empty rationale and at least one case.
    with pytest.raises(AssertionError):
        _assert_parked_cases_valid(domain_root, parked(rationale=""))
    with pytest.raises(AssertionError):
        _assert_parked_cases_valid(domain_root, parked(cases=[]))
    # A parked id must not shadow an active case id.
    with pytest.raises(AssertionError):
        _assert_parked_cases_valid(
            domain_root, parked(cases=[{**parked_case, "id": active_id}])
        )
    # Parked cases still point at real files and real symbols.
    with pytest.raises(AssertionError):
        _assert_parked_cases_valid(
            domain_root, parked(cases=[{**parked_case, "path": "does/not/exist.py"}])
        )
    with pytest.raises(AssertionError):
        _assert_parked_cases_valid(
            domain_root, parked(cases=[{**parked_case, "symbol": "no_such_symbol"}])
        )
    # Parked twin pairs may only reference known parked or active ids.
    with pytest.raises(AssertionError):
        _assert_parked_cases_valid(
            domain_root,
            parked(negative_twins=[[parked_case["id"], "UNKNOWN-ID"]]),
        )

    # twin_axes keys must map to declared pairs, and descriptions must be real.
    axes_payload: dict[str, Any] = {
        "cases": [{"id": "A"}, {"id": "B"}],
        "rename_twins": [],
        "negative_twins": [["A", "B"]],
        "twin_axes": {"A|B": "the axis"},
    }
    _assert_twin_axes_valid(axes_payload)
    with pytest.raises(AssertionError):
        _assert_twin_axes_valid({**axes_payload, "twin_axes": {"A|B": "   "}})
    with pytest.raises(AssertionError):
        _assert_twin_axes_valid({**axes_payload, "twin_axes": {"A|C": "orphan"}})
    with pytest.raises(AssertionError):
        _assert_twin_axes_valid({**axes_payload, "twin_axes": {"AB": "malformed key"}})
    # Every declared negative twin must be documented once axes are declared.
    with pytest.raises(AssertionError):
        _assert_twin_axes_valid(
            {**axes_payload, "negative_twins": [["A", "B"], ["B", "A"]]}
        )


def test_frozen_source_digests_are_unchanged() -> None:
    domain_root, payload = _load_ground_truth("liveness_policy")

    for relative_path, expected_digest in payload["source_digests"].items():
        actual_digest = hashlib.sha256(
            (domain_root / relative_path).read_bytes()
        ).hexdigest()
        assert actual_digest == expected_digest
