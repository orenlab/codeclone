# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from codeclone.memory.models import MemorySubject, generate_memory_id
from codeclone.memory.staleness import apply_scope_staleness
from tests.memory_fixtures import make_module_record, memory_store


def test_apply_scope_staleness_marks_touched_paths(tmp_path: Path) -> None:
    with memory_store(tmp_path) as (_root, project, store, _db_path):
        record = make_module_record(project.id, "pkg.touched")
        store.upsert_record(record)
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="path",
                subject_key="pkg/touched.py",
                relation="about",
            )
        )
        report = apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=["pkg/touched.py"],
        )
        reloaded = store.find_record(record.id)
        assert report.records_marked_stale == 1
        assert reloaded is not None
        assert reloaded.status == "stale"
        assert reloaded.stale_reason == "scope_files_changed"
