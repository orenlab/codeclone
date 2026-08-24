# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The advisory tier containers carry an execution witness: ``state``.

T1 of the detection-tier ruling (2026-08-24). ``state`` is the primary
witness of producer execution for the two advisory clone-tier channels,
``near_miss`` and ``renamed_structure``:

- ``disabled`` — the producer was never invoked. The container is exactly
  ``{tier, state, algorithm_revision}``; ``count`` is omitted entirely
  (omission, not 0 and not null), because a tier that never ran has no
  measurement to utter. ``algorithm_revision`` at ``disabled`` is the
  *configured producer revision* — which algorithm WOULD run — never
  evidence that it ran.
- ``complete`` — the producer ran to completion. The law: ``count=0`` MUST
  mean a completed measurement with an empty result, never absence of
  measurement.

Before this contract the container stamped ``count: 0`` unconditionally,
so "never ran" was indistinguishable from "ran and found nothing" — the
empty-root-is-not-unmeasured defect class, and the exact confusion that
misattributed benchmark pair T3-01 to detector capability.

The fixture base carries BOTH distinguishing documents
(``expected_disabled.json`` and ``expected_complete_empty.json``), and the
pins below compare real pipeline output against each. A mutation that
collapses the two branches into one observable state — for example, the
disabled branch stamping ``complete``/``count=0`` — must red here as "the
two documents became indistinguishable": the killer proves the semantic
distinction itself, not the mere presence of a field.
"""

from __future__ import annotations

import json
from pathlib import Path

from codeclone.report.document._findings_groups import (
    build_near_miss_payload,
    build_renamed_structure_payload,
)
from codeclone.report.document.builder import build_report_body
from tests._pipeline_fixtures import (
    analysis_boot,
    package_tree,
    payload_mapping,
    run_pipeline_once,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tier_state"
FIXTURE_MIN_LOC = 6
FIXTURE_MIN_STMT = 4

_TIERS = ("near_miss", "renamed_structure")


def _fixture_document(name: str) -> dict[str, object]:
    """One of the two checked-in distinguishing tier documents."""

    payload = json.loads((FIXTURE_ROOT / name).read_text("utf-8"))
    assert isinstance(payload, dict)
    return {str(key): value for key, value in payload.items()}


def _tier_containers(root: Path, *, enabled: bool) -> dict[str, dict[str, object]]:
    """Both tier containers from a real pipeline run over the fixture tree.

    The run goes through ``core.pipeline.analyze`` and the production
    document builder, so the execution witness must survive the whole wire
    from the opt-in decision to the serialized container — a pin on the
    builder alone could not see an erasure upstream.
    """

    root.mkdir(exist_ok=True)
    package_tree(root, FIXTURE_ROOT / "units.py")
    boot = analysis_boot(
        root,
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
        skip_metrics=True,
        near_miss=enabled,
    )
    boot.args.renamed_structure = enabled
    _cache, run = run_pipeline_once(boot, root / "cache.json", root=root, warm=False)
    if enabled:
        # The complete-empty document proves nothing unless the producers
        # really ran over a non-trivial population and measured nothing.
        assert len(run.processing.units) >= 2, (
            "fixture population collapsed; the complete-empty document would "
            "prove nothing"
        )
    body = build_report_body(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(root)},
        near_miss_pairs=run.result.near_miss_pairs,
        renamed_structure_groups=run.result.renamed_structure_groups,
    )
    groups = payload_mapping(payload_mapping(body["findings"])["groups"])
    return {tier: payload_mapping(groups[tier]) for tier in _TIERS}


def test_disabled_and_complete_empty_builder_payloads_are_distinguishable() -> None:
    """The core pin: ``None`` (not produced) differs from ``()`` (ran, empty)."""

    near_disabled = build_near_miss_payload(None, scan_root=".")
    near_complete = build_near_miss_payload((), scan_root=".")
    assert near_disabled != near_complete, (
        "near_miss: the disabled and the complete-empty tier documents are "
        "indistinguishable"
    )
    renamed_disabled = build_renamed_structure_payload(None, scan_root=".")
    renamed_complete = build_renamed_structure_payload((), scan_root=".")
    assert renamed_disabled != renamed_complete, (
        "renamed_structure: the disabled and the complete-empty tier documents "
        "are indistinguishable"
    )


def test_disabled_containers_match_the_disabled_fixture_document(
    tmp_path: Path,
) -> None:
    """Flag off: no measurement claim of any kind, ``count`` omitted."""

    produced = _tier_containers(tmp_path / "off", enabled=False)
    assert produced == _fixture_document("expected_disabled.json")
    for tier, container in produced.items():
        assert container["state"] == "disabled"
        assert "count" not in container, (
            f"{tier}: a disabled tier must not utter a measurement (count)"
        )


def test_complete_empty_containers_match_the_complete_fixture_document(
    tmp_path: Path,
) -> None:
    """Flag on, empty result: a completed measurement that says ``count=0``."""

    produced = _tier_containers(tmp_path / "on", enabled=True)
    assert produced == _fixture_document("expected_complete_empty.json")
    for tier, container in produced.items():
        assert container["state"] == "complete"
        assert container["count"] == 0, (
            f"{tier}: a completed empty measurement must say count=0"
        )


def test_the_two_fixture_documents_carry_the_distinction(tmp_path: Path) -> None:
    """The semantic distinction survives end to end, on both real documents."""

    fixture_disabled = _fixture_document("expected_disabled.json")
    fixture_complete = _fixture_document("expected_complete_empty.json")
    assert fixture_disabled != fixture_complete, (
        "the fixture base no longer carries two distinguishable tier documents"
    )
    produced_disabled = _tier_containers(tmp_path / "off", enabled=False)
    produced_complete = _tier_containers(tmp_path / "on", enabled=True)
    assert produced_disabled != produced_complete, (
        "the disabled and the complete-empty tier documents became indistinguishable"
    )
    for tier in _TIERS:
        disabled = produced_disabled[tier]
        complete = produced_complete[tier]
        assert "count" not in disabled
        assert complete["count"] == 0
        # At ``disabled`` the revision is the configured producer revision:
        # the same constant the producer would stamp, carried so a reader
        # knows which algorithm the opt-in would have run.
        assert disabled["algorithm_revision"] == complete["algorithm_revision"]
