# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.contracts import PATCH_TRAIL_SCHEMA_VERSION
from codeclone.memory.trajectory.dto import (
    BlastRadiusSnapshot,
    HygieneSnapshot,
    PatchTrailEvidenceInput,
    PatchTrailInputs,
    VerifySnapshot,
)
from codeclone.memory.trajectory.patch_trail import compute_patch_trail


def _inputs(
    *,
    declared: tuple[str, ...],
    changed: tuple[str, ...],
    unexpected: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
    scope_status: str = "clean",
) -> PatchTrailInputs:
    return PatchTrailInputs(
        intent_id="intent-test",
        intent_description="test intent",
        declared_files=declared,
        declared_related=(),
        changed_files=changed,
        unexpected_files=unexpected,
        forbidden_touched=forbidden,
        expanded_related_files=(),
        scope_check_status=scope_status,
        blast_radius=BlastRadiusSnapshot(
            do_not_touch_declared=("codeclone.baseline.json",),
            review_context_declared=("codeclone/core/pipeline.py",),
        ),
        verify=VerifySnapshot(
            verification_profile="python_structural",
            verification_status="accepted",
            verification_skipped=("documentation_only",),
            verification_failed=(),
        ),
        hygiene=HygieneSnapshot(
            blocks_finish=False,
            finish_block_reason=None,
            unacknowledged_dirty_in_scope=(),
            dirty_paths_outside_scope=(),
            attribution_counts={"in_scope": 0},
        ),
        evidence=PatchTrailEvidenceInput(
            repo_root_digest="abcd1234",
            report_digest="sha256:deadbeef",
            scope_check_audit_sequence=10,
            patch_verify_audit_sequence=11,
        ),
    )


def test_untouched_in_declared_derivation() -> None:
    trail = compute_patch_trail(
        _inputs(declared=("a.py", "b.py", "c.py"), changed=("a.py",))
    )
    assert trail.untouched_in_declared == ("b.py", "c.py")
    assert trail.scope_check_status == "clean"


def test_violated_scope_leaves_no_untouched_when_extra_changed() -> None:
    trail = compute_patch_trail(
        _inputs(
            declared=("a.py",),
            changed=("a.py", "b.py"),
            unexpected=("b.py",),
            scope_status="violated",
        )
    )
    assert trail.untouched_in_declared == ()
    assert trail.unexpected_files == ("b.py",)


def test_do_not_touch_held_excludes_changed() -> None:
    trail = compute_patch_trail(_inputs(declared=("a.py",), changed=("a.py",)))
    assert trail.do_not_touch_declared == ("codeclone.baseline.json",)
    assert trail.do_not_touch_held == ("codeclone.baseline.json",)


def test_patch_trail_digest_is_stable() -> None:
    first = compute_patch_trail(_inputs(declared=("a.py", "b.py"), changed=("a.py",)))
    second = compute_patch_trail(_inputs(declared=("a.py", "b.py"), changed=("a.py",)))
    assert first.patch_trail_digest == second.patch_trail_digest
    assert first.schema_version == PATCH_TRAIL_SCHEMA_VERSION


def test_summary_payload_uses_counts() -> None:
    trail = compute_patch_trail(
        _inputs(declared=("a.py", "b.py", "c.py"), changed=("a.py",))
    )
    summary = trail.to_payload(detail_level="summary")
    counts = summary["counts"]
    assert isinstance(counts, dict)
    assert counts["untouched_in_declared"] == 2
