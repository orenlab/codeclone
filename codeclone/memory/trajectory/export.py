# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from ...audit.events import repo_root_digest
from ...config.memory import MemoryConfig
from ...report.meta import current_report_timestamp_utc
from ...utils.json_io import json_text
from ...utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from ..exceptions import MemoryContractError
from ..models import MemoryProject
from ..sqlite_store import SqliteEngineeringMemoryStore
from .export_context import (
    build_export_context,
    build_export_record,
    resolve_export_scope_paths,
    trajectory_index_for_export,
    trajectory_path_subjects,
)
from .models import Trajectory
from .profiles import (
    TRAJECTORY_EXPORT_SCHEMA_VERSION,
    resolve_export_profile,
    trajectory_eligible_for_export,
)


class TrajectoryExportManifest(TypedDict):
    schema_version: str
    profile: str
    profile_schema_version: str
    exported_at_utc: str
    project_id: str
    repo_root_digest: str
    record_count: int
    bytes_written: int
    truncated_records: int
    skipped_ineligible: int
    deduplicated_workflows: int


@dataclass(frozen=True, slots=True)
class TrajectoryExportResult:
    output_path: Path
    manifest: TrajectoryExportManifest
    records_written: int


@dataclass
class _JsonlExportAccumulator:
    bytes_written: int = 0
    truncated_records: int = 0
    records_written: int = 0
    lines: list[str] = field(default_factory=list)

    def try_append(
        self,
        line: str,
        *,
        record_limit: int,
        file_limit: int,
    ) -> bool:
        encoded_len = len(line.encode("utf-8"))
        if encoded_len > record_limit:
            self.truncated_records += 1
            return False
        projected = self.bytes_written + encoded_len + 1
        if projected > file_limit:
            return False
        self.lines.append(line)
        self.bytes_written = projected
        self.records_written += 1
        return True


def resolve_export_output_path(
    *,
    root_path: Path,
    raw_path: str,
    allow_external_out: bool,
) -> Path:
    policy = RepoPathPolicy(
        allow_absolute=True,
        allow_external=allow_external_out,
    )
    try:
        return resolve_under_repo_root(root_path, raw_path, policy=policy)
    except PathOutsideRepoError as exc:
        msg = (
            f"Export output path escapes repository root: {raw_path}. "
            "Pass --allow-external-out for an explicit external destination."
        )
        raise MemoryContractError(msg) from exc


def export_trajectories_jsonl(
    *,
    store: SqliteEngineeringMemoryStore,
    project: MemoryProject,
    root_path: Path,
    config: MemoryConfig,
    profile_name: str,
    output_path: Path,
    include_payloads: bool | None = None,
    max_record_bytes: int | None = None,
    max_file_bytes: int | None = None,
    force_enabled: bool = False,
) -> TrajectoryExportResult:
    if not config.trajectory_export_enabled and not force_enabled:
        raise MemoryContractError(
            "Trajectory export is disabled. Set "
            "[tool.codeclone.memory].trajectory_export_enabled=true or pass "
            "--force on the CLI export command."
        )
    profile = resolve_export_profile(profile_name)
    include = (
        config.trajectory_export_include_payloads
        if include_payloads is None
        else include_payloads
    )
    record_limit = max_record_bytes or config.trajectory_export_max_record_bytes
    file_limit = max_file_bytes or config.trajectory_export_max_file_bytes
    loaded = store.list_canonical_trajectories_for_export(
        project_id=project.id,
        limit=10_000,
    )
    deduplicated = len(loaded)
    eligible = [
        trajectory
        for trajectory in sorted(loaded, key=_trajectory_sort_key)
        if trajectory_eligible_for_export(trajectory, profile=profile)
    ]
    skipped = deduplicated - len(eligible)
    canonical_index = trajectory_index_for_export(eligible, profile=profile)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    accumulator = _JsonlExportAccumulator()
    for trajectory in eligible:
        patch_trail_payload = store.load_trajectory_patch_trail(
            trajectory_id=trajectory.id
        )
        scope_paths = trajectory_path_subjects(
            trajectory, relations={"about", "touched"}
        )
        enrichment = build_export_context(
            store.connection,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=scope_paths,
            patch_trail_payload=patch_trail_payload,
            canonical_by_workflow=canonical_index,
        )
        record = build_export_record(
            trajectory=trajectory,
            profile=profile,
            project=project,
            include_payloads=include,
            enrichment=enrichment,
            scope_paths=resolve_export_scope_paths(
                trajectory,
                patch_trail_payload=patch_trail_payload,
            ),
        )
        accumulator.try_append(
            _canonical_json_line(record),
            record_limit=record_limit,
            file_limit=file_limit,
        )
    manifest: TrajectoryExportManifest = {
        "schema_version": TRAJECTORY_EXPORT_SCHEMA_VERSION,
        "profile": profile.name,
        "profile_schema_version": profile.schema_version,
        "exported_at_utc": current_report_timestamp_utc(),
        "project_id": project.id,
        "repo_root_digest": repo_root_digest(root_path.resolve()),
        "record_count": accumulator.records_written,
        "bytes_written": accumulator.bytes_written,
        "truncated_records": accumulator.truncated_records,
        "skipped_ineligible": skipped,
        "deduplicated_workflows": deduplicated,
    }
    payload = "\n".join(accumulator.lines)
    if payload:
        payload += "\n"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, output_path)
    return TrajectoryExportResult(
        output_path=output_path,
        manifest=manifest,
        records_written=accumulator.records_written,
    )


def _trajectory_sort_key(trajectory: Trajectory) -> tuple[str, str]:
    return (trajectory.finished_at_utc, trajectory.id)


def _canonical_json_line(payload: dict[str, object]) -> str:
    return json_text(payload, sort_keys=True)


__all__ = [
    "TrajectoryExportManifest",
    "TrajectoryExportResult",
    "export_trajectories_jsonl",
    "resolve_export_output_path",
]
