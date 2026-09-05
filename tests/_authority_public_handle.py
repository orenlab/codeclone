# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One contract, two violations on one sink: the producer half.

``tests/_authority_findings`` gives two violations at two *addresses*, which
separates a path filter. It cannot separate anything keyed on the violation
itself: its two handles already differ in ``sink_identity``, so a handle that
forgot ``kind`` -- or a public finding id that forgot the handle -- stays
distinguishing there by accident.

This fixture supplies the case the ratified requirement names
(``specs/canonical-model-F3.md`` SS ``violation_id``): the SAME contract and the
SAME sink carrying two violations that differ ONLY in ``kind``, plus two
distinct discovery candidates whose independent-producer projections coincide
-- the natural-key collision the producer's dedup exists to fold.

Both properties come out of production code from source text:

    source modules
      -> ``analysis.units.extract_units_and_stats_from_source``
      -> ``semantics.authority.build_semantic_authority``

Shape, and why each part is load-bearing:

* ``canonical_normalize`` is the contract's canonical owner (authoritative).
* ``shadow_a`` and ``shadow_b`` are byte-identical apart from their names, so
  they share one contract-IR wire and form an ``exact_contract_ir`` candidate
  over exactly the two of them.
* all three share one effect signature, so they also form a
  ``same_effect_signature`` candidate over three producers.
* those two candidates have different ``producers`` tuples -- the key the
  candidate table is built on -- but the same *independent* projection, because
  the owner is authoritative and is filtered out. Two emits, one natural key.

It lives in an underscore module because a ``tests/test_*.py`` module that
reaches an ``r4`` surface may not also reach these ``r2`` internals.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.findings.ids import authority_group_id
from codeclone.models import (
    AuthorityViolation,
    FunctionContractSummary,
    FunctionRelationshipFacts,
)
from codeclone.paths.module_identity.inventory import build_module_registry
from codeclone.semantics.authority import build_semantic_authority
from codeclone.semantics.registry import parse_authority_registry

CONTRACT_ID = "wire-freeze-fixture.normalize/v1"
CANONICAL_OWNER = "pkg.canon:canonical_normalize"
SHADOW_A = "pkg.shadow_a:shadow_a"
SHADOW_B = "pkg.shadow_b:shadow_b"

#: The pyproject rows a real run reads the same registry from.
PYPROJECT = f"""[project]
name = "authority-public-handle-fixture"
version = "0"

[[tool.codeclone.authority]]
contract_id = "{CONTRACT_ID}"
canonical_owner = "{CANONICAL_OWNER}"
allowed_adapters = []
forbidden_raw_inputs = ["param:0"]
required_provenance = ["producer:{CANONICAL_OWNER}"]
"""

_SOURCES: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/canon.py": (
        "def canonical_normalize(value: str) -> str:\n"
        "    payload = value\n"
        "    return payload\n"
    ),
    # byte-identical bodies under different names: one shared contract-IR wire
    "pkg/shadow_a.py": (
        "def shadow_a(value: str, extra: str) -> str:\n"
        "    first = value\n"
        "    second = extra\n"
        "    payload = first\n"
        "    return payload\n"
    ),
    "pkg/shadow_b.py": (
        "def shadow_b(value: str, extra: str) -> str:\n"
        "    first = value\n"
        "    second = extra\n"
        "    payload = first\n"
        "    return payload\n"
    ),
}


def write_tree(root: Path) -> None:
    """Write the fixture repository, ``pyproject.toml`` included."""

    (root / "pyproject.toml").write_text(PYPROJECT, "utf-8")
    for relative, text in _SOURCES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")


def _semantic_facts(
    root: Path,
) -> tuple[list[FunctionContractSummary], list[FunctionRelationshipFacts]]:
    registry = build_module_registry(root=root)
    summaries: list[FunctionContractSummary] = []
    relationships: list[FunctionRelationshipFacts] = []
    for path in sorted(root.rglob("*.py")):
        relative = str(path.relative_to(root))
        entry = registry.entries_by_path[relative]
        _units, _blocks, _segments, _stats, metrics, _findings = (
            extract_units_and_stats_from_source(
                source=path.read_text("utf-8"),
                filepath=relative,
                identity=entry.identity,
                registry=registry,
                cfg=NormalizationConfig(),
                min_loc=100,
                min_stmt=100,
            )
        )
        summaries.extend(metrics.semantic_facts.function_contract_summaries)
        relationships.extend(metrics.function_relationship_facts)
    return summaries, relationships


def producer_violations(root: Path) -> tuple[AuthorityViolation, ...]:
    """Run the real producer over the fixture tree and prove its shape.

    Asserted here rather than in a consumer: if the analyser stops producing
    this shape, the fixture has stopped distinguishing anything and every
    consumer's assertion about it would go vacuous instead of red.
    """

    summaries, relationships = _semantic_facts(root)
    result = build_semantic_authority(
        summaries,
        relationships,
        registry=parse_authority_registry(
            [
                {
                    "contract_id": CONTRACT_ID,
                    "canonical_owner": CANONICAL_OWNER,
                    "allowed_adapters": [],
                    "forbidden_raw_inputs": ["param:0"],
                    "required_provenance": [f"producer:{CANONICAL_OWNER}"],
                }
            ]
        ),
    )
    violations = result.violations

    # The two candidates whose producer tuples differ but whose independent
    # projections coincide: without both, the dedup below folds nothing and
    # its guard is unreached.
    producer_tuples = {candidate.producers for candidate in result.candidates}
    assert producer_tuples == {
        (SHADOW_A, SHADOW_B),
        (CANONICAL_OWNER, SHADOW_A, SHADOW_B),
    }, producer_tuples
    assert all(candidate.independence for candidate in result.candidates)

    # One sink, two kinds: the only pair that separates `kind` inside the
    # handle preimage, because everything else about them is equal.
    on_shadow_a = {v.kind for v in violations if v.sink_identity == SHADOW_A}
    assert on_shadow_a == {"owner_bypass", "multiple_independent_producers"}, (
        on_shadow_a
    )
    return violations


def expected_public_ids(root: Path) -> Mapping[str, str]:
    """The public finding ids the producer's violations must appear under.

    Built through the one owner of the projection, ``findings.ids`` -- a
    consumer that re-spells ``f"authority:{contract}:{violation}"`` would
    follow the formula wherever it went and stay green, which is how a
    collapsed public handle survives.  The mapping is id -> kind, and it
    being a mapping of the same size as the violation list is itself the
    uniqueness assertion the persistent handle owes.
    """

    violations = producer_violations(root)
    public: Mapping[str, str] = {
        authority_group_id(
            violation.contract_id, violation.violation_id
        ): violation.kind
        for violation in violations
    }
    assert len(public) == len(violations), (
        "authority findings collapsed onto a shared public id: "
        f"{len(violations)} violations, {len(public)} ids"
    )
    return public


__all__ = [
    "CANONICAL_OWNER",
    "CONTRACT_ID",
    "PYPROJECT",
    "SHADOW_A",
    "SHADOW_B",
    "expected_public_ids",
    "producer_violations",
    "write_tree",
]
