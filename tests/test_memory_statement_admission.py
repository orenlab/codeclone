# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Records ingestion builds from file names obey the record_candidate rules.

A ``module_role`` statement names a module path, and the path is chosen by
whoever writes the repository. The Markdown validator that refuses raw HTML,
images and links in an agent's statement admits or refuses these too.
"""

from __future__ import annotations

from pathlib import Path

from codeclone.memory.ingest import InitOptions
from codeclone.memory.ingest.runner import build_init_batch
from codeclone.memory.project import read_git_provenance, resolve_project_identity

from .memory_fixtures import (
    git_repo_with_cached_report,
    load_memory_init_report_document,
)

_HOSTILE_MODULE = "pkg/<img src=x onerror=PWNalert(1)>.py"
_LINK_MODULE = "pkg/[click](pwn:steal).py"


def _module_roles(tmp_path: Path, registry: list[str]) -> list[str]:
    root, _report_path, _document = git_repo_with_cached_report(
        tmp_path,
        py_sources=dict.fromkeys(registry, "x = 1\n"),
        registry_items=registry,
    )
    batch = build_init_batch(
        root_path=root,
        project=resolve_project_identity(root),
        report_document=load_memory_init_report_document(
            registry_items=registry, fallback_root=root
        ),
        git=read_git_provenance(root),
        report_digest=None,
        analysis_fingerprint=None,
        options=InitOptions(include_docs=False, include_tests=False),
    )
    kept = {record.id for record in batch.records if record.type == "module_role"}
    assert {subject.memory_id for subject in batch.subjects} <= {
        record.id for record in batch.records
    }
    return sorted(record.statement for record in batch.records if record.id in kept)


def test_module_role_records_skip_a_statement_the_validator_refuses(
    tmp_path: Path,
) -> None:
    statements = _module_roles(
        tmp_path, ["pkg/alpha.py", _HOSTILE_MODULE, _LINK_MODULE]
    )

    assert statements == [
        "pkg.alpha is an analyzed Python module in project inventory."
    ]


def test_module_role_records_keep_every_benign_module(tmp_path: Path) -> None:
    statements = _module_roles(tmp_path, ["pkg/alpha.py", "pkg/beta.py"])

    assert statements == [
        "pkg.alpha is an analyzed Python module in project inventory.",
        "pkg.beta is an analyzed Python module in project inventory.",
    ]
