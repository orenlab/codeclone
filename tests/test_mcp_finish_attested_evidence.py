# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""End-to-end proof that the finish flow feeds attested evidence to memory.

The controller's finish path holds every attested identifier of the finished
change. These pins prove the feed is wired end to end: ``_finish`` builds the
bundle and passes it to ``finish_propose_memory`` (Pin 1), and
``finish_propose_memory`` enriches commit/branch from the project and writes the
receipt/patch-trail/commit digests as durable ``memory_evidence`` rows on the
proposed candidates (Pin 2).
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

import codeclone.surfaces.mcp._workspace_hygiene as mcp_workspace_hygiene_mod
from codeclone.surfaces.mcp._workspace_hygiene import WorkspaceHygieneResult
from codeclone.surfaces.mcp.service import CodeCloneMCPService

from .memory_fixtures import cli_memory_repo, init_git_repo
from .test_mcp_service import _seed_docs_intent

_RECEIPT_DIGEST = "a" * 64
_PATCH_TRAIL_DIGEST = "b" * 64


def test_finish_propose_memory_writes_attested_evidence(tmp_path: Path) -> None:
    """_finish_propose_memory writes durable evidence rows and enriches commit."""
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, store):
        init_git_repo(root)
        (root / "pkg").mkdir(parents=True, exist_ok=True)
        (root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        service = CodeCloneMCPService(history_limit=2)
        hook = service.finish_propose_memory(
            root_path=root,
            changed_files=["pkg/mod.py"],
            claims_text="Patch keeps the module surface stable.",
            review_text=None,
            verification_profile="python_structural",
            attested_evidence={
                "receipt_digest": _RECEIPT_DIGEST,
                "patch_trail_digest": _PATCH_TRAIL_DIGEST,
                "run_id": "run-e2e12345",
            },
        )
        candidates = cast("list[dict[str, object]]", hook["memory_candidates"])
        # Evidence rides the candidates that assert something. The scope walk
        # used to also mint a contentless module_role echo and this pin read it;
        # the claims-derived change_rationale is the carrier now.
        carrier_id = next(
            str(item["id"])
            for item in candidates
            if item.get("type") == "change_rationale"
        )
        by_kind = {
            row.evidence_kind: row for row in store.list_evidence_for_memory(carrier_id)
        }

    assert by_kind["receipt"].digest == _RECEIPT_DIGEST
    assert by_kind["audit_event"].digest == _PATCH_TRAIL_DIGEST
    # commit is absent from the passed bundle; the enrichment fills it from the
    # project git head, so its ref is the actual repository HEAD.
    assert by_kind["git_commit"].ref == head


def test_finish_flow_feeds_attested_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real finish(propose_memory=true) passes the attested bundle down.

    The mutation target: dropping the bundle at the _finish call reds this pin.
    """
    service, intent_id = _seed_docs_intent(tmp_path)
    monkeypatch.setattr(
        service,
        "_patch_contract_verify",
        lambda **_: {
            "status": "accepted",
            "reason": None,
            "verification_profile": "documentation_only",
            "structural_delta": {
                "verdict": "stable",
                "health_delta": 0,
                "regressions": [],
            },
            "worsened": [],
            "claim_validation_recommended": False,
        },
    )
    monkeypatch.setattr(
        mcp_workspace_hygiene_mod,
        "finish_hygiene_check",
        lambda **_: WorkspaceHygieneResult(
            git_available=True,
            dirty_paths=("README.md",),
            dirty_paths_in_scope=("README.md",),
            dirty_paths_outside_scope=(),
            foreign_dirty_overlaps=(),
            blocks_edit=False,
        ),
    )
    captured: dict[str, object] = {}

    def _capture(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(service, "finish_propose_memory", _capture)
    service.finish_controlled_change(
        intent_id=intent_id,
        changed_files=["README.md"],
        create_receipt=False,
        auto_clear=False,
        propose_memory=True,
    )

    bundle = captured.get("attested_evidence")
    assert isinstance(bundle, Mapping)
    assert bundle.get("run_id")
    assert bundle.get("patch_trail_digest")
