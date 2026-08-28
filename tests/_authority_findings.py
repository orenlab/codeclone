# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A report document whose ``authority`` findings came out of the producer.

This repository's own run reports ``authority: 0``, so any assertion about how
a surface treats an authority finding is unobservable on it: green before a
change and green after. A consumer of this module gets the missing
observation -- a document that really carries authority findings, and carries
two of them at different addresses so a path filter can be shown to separate
them rather than to pass everything.

Every hop from source text to finding group is production code:

    source modules
      -> ``analysis.units.extract_units_and_stats_from_source``  (contract IR facts)
      -> ``semantics.authority.build_semantic_authority``        (the violations)
      -> ``core.metrics_payload._semantic_authority_payload``    (the metrics family)
      -> ``report.document.builder``                             (the finding groups)

Only the four fixture modules and the registry rows are authored. That is the
point: a hand-typed finding group pins the test author's belief about the
producer's shape, and the shape is exactly what the consumer depends on.

The advisory tiers are built the same way, by their own payload producers, for
the consumers that must show a tier record never enters a published total.

It lives in an underscore module because a ``tests/test_*.py`` module that
reaches an ``r4`` surface may not also reach ``r2`` internals -- the boundary
ratchet's allowlist is shrink-only, so the r2 half of the chain lives here,
next to ``_report_fixtures``, and the test module imports this instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.core.metrics_payload import _semantic_authority_payload
from codeclone.models import (
    FunctionContractSummary,
    FunctionRelationshipFacts,
    NearMissMember,
    NearMissPair,
    RenamedStructureGroup,
    RenamedStructureMember,
)
from codeclone.paths.module_identity.inventory import build_module_registry
from codeclone.report.document._findings_groups import (
    build_near_miss_payload,
    build_renamed_structure_payload,
)
from codeclone.semantics.authority import build_semantic_authority
from codeclone.semantics.registry import parse_authority_registry

from ._report_fixtures import build_test_report_document

#: The canonical owner of the fixture contract, and two functions that reach
#: the same governed shape without passing through it. Each of those is a
#: *shadow* sink, which is the authority violation class ``owner_bypass``.
#: The three bodies are deliberately different so no clone cohort or discovery
#: candidate folds them together and adds violations no consumer asked for.
_OWNER_SOURCE = """def canonical_normalize(value: str) -> str:
    payload = value
    return payload
"""

_SHADOW_IN_SOURCE = """def shadow_normalize_in(value: str, extra: str) -> str:
    first = value
    second = extra
    payload = first
    return payload
"""

_SHADOW_OUT_SOURCE = """def shadow_normalize_out(value: str) -> str:
    alpha = value
    beta = alpha
    gamma = beta
    return gamma
"""

#: Repository-relative address of the violation a caller's diff touches.
SHADOW_IN_PATH = "pkg/shadow_in.py"
#: Repository-relative address of the violation the same diff does not touch.
SHADOW_OUT_PATH = "pkg/shadow_out.py"
#: A path in the same package that carries no finding at all.
UNTOUCHED_PATH = "pkg/untouched.py"
#: ``SHADOW_IN_PATH`` cut mid-component: a prefix that is not a path segment.
PARTIAL_SEGMENT_PATH = "pkg/shadow_i"

CONTRACT_ID = "changed-scope-fixture.normalize/v1"

_SCAN_ROOT = "/repo"


def _registry() -> Any:
    """The reviewed registry rows, frozen by the production parser.

    Governing by ``forbidden_raw_inputs`` -- a contract-IR input token --
    rather than by provenance root is what puts three separately rooted
    functions under one contract without giving them a shared call, which is
    what keeps each one's contract resolved and therefore enforceable.
    """

    return parse_authority_registry(
        [
            {
                "contract_id": CONTRACT_ID,
                "canonical_owner": "pkg.canon:canonical_normalize",
                "allowed_adapters": [],
                "forbidden_raw_inputs": ["param:0"],
                "required_provenance": ["producer:pkg.canon:canonical_normalize"],
            }
        ]
    )


def _write_tree(root: Path) -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "canon.py").write_text(_OWNER_SOURCE, "utf-8")
    (package / "shadow_in.py").write_text(_SHADOW_IN_SOURCE, "utf-8")
    (package / "shadow_out.py").write_text(_SHADOW_OUT_SOURCE, "utf-8")


def _semantic_facts(
    root: Path,
) -> tuple[list[FunctionContractSummary], list[FunctionRelationshipFacts]]:
    """Lower the fixture tree with the real extractor, file by file."""

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


def build_authority_report_document(root: Path) -> dict[str, object]:
    """Write the fixture tree under ``root`` and return its report document.

    The two violations are asserted here rather than in a consumer: if the
    authority analyser ever stops seeing this shape, the fixture has stopped
    distinguishing anything and every consumer's assertion about it would
    become vacuous instead of red.
    """

    _write_tree(root)
    summaries, relationships = _semantic_facts(root)
    result = build_semantic_authority(
        summaries,
        relationships,
        registry=_registry(),
    )
    kinds = [violation.kind for violation in result.violations]
    if kinds != ["owner_bypass", "owner_bypass"]:
        raise AssertionError(
            f"fixture stopped producing its two shadow violations: {kinds}"
        )
    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={"semantic_authority": _semantic_authority_payload(result)},
    )


def with_advisory_tiers(document: Mapping[str, object]) -> dict[str, object]:
    """Return a copy whose tier containers carry real, producer-built records.

    Both records address ``SHADOW_IN_PATH`` -- the file a caller's diff
    touches -- so a consumer that let a tier into a path-filtered total would
    show it here rather than nowhere. The two tiers are shaped differently on
    purpose, because that is how the producers shape them: ``renamed_structure``
    nests its records under ``groups`` and a family walk reaches them, while
    ``near_miss`` keys its list ``pairs`` and the same walk finds nothing.
    Neither record carries ``items``.
    """

    copy = dict(document)
    findings = dict(cast(Mapping[str, object], copy["findings"]))
    groups = dict(cast(Mapping[str, object], findings["groups"]))
    groups["near_miss"] = build_near_miss_payload(
        [
            NearMissPair(
                pair_key="nm-fixture",
                members=(
                    NearMissMember(
                        qualname="pkg.shadow_in:shadow_normalize_in",
                        filepath=f"{_SCAN_ROOT}/{SHADOW_IN_PATH}",
                        start_line=1,
                        end_line=5,
                    ),
                    NearMissMember(
                        qualname="pkg.canon:canonical_normalize",
                        filepath=f"{_SCAN_ROOT}/pkg/canon.py",
                        start_line=1,
                        end_line=3,
                    ),
                ),
                edit_statements=1,
                edit_kind="insert",
                token_domain="y8",
            )
        ],
        scan_root=_SCAN_ROOT,
    )
    groups["renamed_structure"] = build_renamed_structure_payload(
        [
            RenamedStructureGroup(
                group_key="rs-fixture",
                members=(
                    RenamedStructureMember(
                        qualname="pkg.shadow_in:shadow_normalize_in",
                        filepath=f"{_SCAN_ROOT}/{SHADOW_IN_PATH}",
                        start_line=1,
                        end_line=5,
                        fingerprint="fp-in",
                    ),
                    RenamedStructureMember(
                        qualname="pkg.shadow_out:shadow_normalize_out",
                        filepath=f"{_SCAN_ROOT}/{SHADOW_OUT_PATH}",
                        start_line=1,
                        end_line=5,
                        fingerprint="fp-out",
                    ),
                ),
                distinct_exact_fingerprints=2,
            )
        ],
        scan_root=_SCAN_ROOT,
    )
    findings["groups"] = groups
    copy["findings"] = findings
    return copy


__all__ = [
    "CONTRACT_ID",
    "PARTIAL_SEGMENT_PATH",
    "SHADOW_IN_PATH",
    "SHADOW_OUT_PATH",
    "UNTOUCHED_PATH",
    "build_authority_report_document",
    "with_advisory_tiers",
]
