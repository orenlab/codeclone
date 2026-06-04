# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Memory ingest extractors exercised on tmp_path git repos (CI-safe)."""

from __future__ import annotations

from pathlib import Path

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
)
from tests.memory_fixtures import (
    enrich_report_with_api_surface,
    git_repo_with_cached_report,
    run_memory_extractor_smoke,
)

_MEMORY_EXTRACTORS = (
    extract_module_roles,
    extract_contract_notes,
    extract_public_surfaces,
    extract_risk_notes,
    extract_git_hotspots,
    extract_contradictions,
    extract_test_anchors,
    extract_document_links,
)


@pytest.mark.parametrize("extractor", _MEMORY_EXTRACTORS)
def test_memory_extractors_on_fixture_git_repo(
    tmp_path: Path,
    extractor: object,
) -> None:
    root, _report_path, base_report = git_repo_with_cached_report(
        tmp_path,
        py_sources={"pkg/mod.py": "def f():\n    return 1\n"},
        registry_items=["pkg/mod.py"],
    )
    report_document = enrich_report_with_api_surface(
        base_report, module_path="pkg/mod.py"
    )
    counts = run_memory_extractor_smoke(
        root=root,
        extractor=extractor,  # type: ignore[arg-type]
        report_document=report_document,
    )
    assert isinstance(counts, dict)
