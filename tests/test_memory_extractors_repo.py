# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.memory.ingest.extractors import (
    extract_contract_notes,
    extract_contradictions,
    extract_document_links,
    extract_git_hotspots,
    extract_module_roles,
    extract_public_surfaces,
    extract_risk_notes,
    extract_test_anchors,
    merge_batches,
)
from codeclone.memory.ingest.runner import planned_type_counts
from codeclone.memory.project import (
    analysis_fingerprint_from_report,
    read_git_provenance,
    report_digest_from_report,
    resolve_project_identity,
)

from .memory_fixtures import REPO_ROOT, load_memory_init_report_document


def _load_report() -> dict[str, object]:
    try:
        return load_memory_init_report_document()
    except FileNotFoundError:
        pytest.skip("cached report.json not available")


@pytest.mark.parametrize(
    "extractor",
    [
        extract_module_roles,
        extract_contract_notes,
        extract_public_surfaces,
        extract_risk_notes,
        extract_git_hotspots,
        extract_contradictions,
        extract_test_anchors,
        extract_document_links,
    ],
)
def test_memory_extractors_on_codeclone_repo(extractor: object) -> None:
    if not (REPO_ROOT / "codeclone").is_dir():
        pytest.skip("not running inside codeclone checkout")
    project = resolve_project_identity(REPO_ROOT)
    git = read_git_provenance(REPO_ROOT)
    report_document = _load_report()
    digest = report_digest_from_report(report_document)
    fingerprint = analysis_fingerprint_from_report(report_document)
    kwargs: dict[str, object] = {
        "project": project,
        "git": git,
        "report_digest": digest,
        "analysis_fingerprint": fingerprint,
    }
    if extractor in {extract_contract_notes, extract_contradictions}:
        kwargs["root_path"] = REPO_ROOT
    elif extractor is extract_public_surfaces:
        kwargs["root_path"] = REPO_ROOT
        kwargs["report_document"] = report_document
    elif extractor is extract_risk_notes:
        kwargs["report_document"] = report_document
    elif extractor in {
        extract_git_hotspots,
        extract_test_anchors,
        extract_document_links,
    }:
        kwargs["root_path"] = REPO_ROOT
        if extractor is extract_document_links:
            inventory = report_document.get("inventory")
            items: list[str] = []
            if isinstance(inventory, dict):
                registry = inventory.get("file_registry")
                if isinstance(registry, dict):
                    raw_items = registry.get("items")
                    if isinstance(raw_items, list):
                        items = [str(item) for item in raw_items[:50]]
            kwargs["registry_paths"] = frozenset(items)
    else:
        kwargs["report_document"] = report_document

    batch = extractor(**kwargs)  # type: ignore[operator]
    merged = merge_batches([batch])
    counts = planned_type_counts(merged)
    assert isinstance(counts, dict)
