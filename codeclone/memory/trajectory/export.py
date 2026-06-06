# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from ...config.memory import MemoryConfig
from ...report.meta import current_report_timestamp_utc
from ...utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from ..exceptions import MemoryContractError
from ..models import MemoryProject
from ..sqlite_store import SqliteEngineeringMemoryStore
from .models import Trajectory
from .profiles import (
    TRAJECTORY_EXPORT_SCHEMA_VERSION,
    TrajectoryExportProfile,
    resolve_export_profile,
    trajectory_eligible_for_export,
)
from .retrieval import compact_step_text

_REDACT_HOME = re.compile(r"(?i)(/Users/[^/\s]+|/home/[^/\s]+)")


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


@dataclass(frozen=True, slots=True)
class TrajectoryExportResult:
    output_path: Path
    manifest: TrajectoryExportManifest
    records_written: int


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
    trajectories = _load_trajectories_for_export(
        store,
        project_id=project.id,
        limit=10_000,
    )
    eligible = [
        trajectory
        for trajectory in sorted(trajectories, key=_trajectory_sort_key)
        if trajectory_eligible_for_export(trajectory, profile=profile)
    ]
    skipped = len(trajectories) - len(eligible)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    bytes_written = 0
    truncated_records = 0
    records_written = 0
    lines: list[str] = []
    for trajectory in eligible:
        record = _serialize_export_record(
            trajectory=trajectory,
            profile=profile,
            project=project,
            include_payloads=include,
        )
        line = _canonical_json_line(record)
        if len(line.encode("utf-8")) > record_limit:
            truncated_records += 1
            continue
        projected = bytes_written + len(line.encode("utf-8")) + 1
        if projected > file_limit:
            break
        lines.append(line)
        bytes_written = projected
        records_written += 1
    manifest: TrajectoryExportManifest = {
        "schema_version": TRAJECTORY_EXPORT_SCHEMA_VERSION,
        "profile": profile.name,
        "profile_schema_version": profile.schema_version,
        "exported_at_utc": current_report_timestamp_utc(),
        "project_id": project.id,
        "repo_root_digest": _repo_root_digest(root_path),
        "record_count": records_written,
        "bytes_written": bytes_written,
        "truncated_records": truncated_records,
        "skipped_ineligible": skipped,
    }
    payload = "\n".join(lines)
    if payload:
        payload += "\n"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, output_path)
    return TrajectoryExportResult(
        output_path=output_path,
        manifest=manifest,
        records_written=records_written,
    )


def _load_trajectories_for_export(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    limit: int,
) -> list[Trajectory]:
    items = store.list_trajectories(project_id=project_id, limit=limit)
    hydrated: list[Trajectory] = []
    for item in items:
        trajectory = store.find_trajectory(item.id)
        if trajectory is not None:
            hydrated.append(trajectory)
    return hydrated


def _serialize_export_record(
    *,
    trajectory: Trajectory,
    profile: TrajectoryExportProfile,
    project: MemoryProject,
    include_payloads: bool,
) -> dict[str, object]:
    scope_paths = _path_subjects(trajectory, relations={"about", "touched"})
    actions = [
        {
            "type": _redact_text(step.event_type),
            "result": _redact_text(step.status or ""),
            "summary": _redact_text(step.summary or ""),
        }
        for step in trajectory.steps[:12]
    ]
    record: dict[str, object] = {
        "schema_version": profile.schema_version,
        "profile": profile.name,
        "trajectory_id": trajectory.id,
        "project_fingerprint": project.id,
        "task": {
            "intent_summary": _redact_text(trajectory.summary),
            "scope": {"paths": [_redact_text(path) for path in scope_paths]},
        },
        "context": {
            "memory_precedents": [],
            "trajectory_precedents": [],
        },
        "actions": actions,
        "outcome": {
            "label": trajectory.outcome,
            "quality_tier": trajectory.quality_tier,
        },
        "lessons": list(trajectory.labels),
        "citations": [],
        "digests": {
            "trajectory_digest": f"sha256:{trajectory.trajectory_digest}",
            "source_event_stream_digest": (
                f"sha256:{trajectory.source_event_stream_digest}"
            ),
        },
    }
    if include_payloads:
        record["steps"] = compact_step_text(trajectory)
    return record


def _path_subjects(
    trajectory: Trajectory,
    *,
    relations: Iterable[str],
) -> tuple[str, ...]:
    allowed = set(relations)
    paths = [
        subject.subject_key
        for subject in trajectory.subjects
        if subject.subject_kind == "path" and subject.relation in allowed
    ]
    return tuple(sorted(set(paths)))


def _trajectory_sort_key(trajectory: Trajectory) -> tuple[str, str]:
    return (trajectory.finished_at_utc, trajectory.id)


def _repo_root_digest(root_path: Path) -> str:
    return hashlib.sha256(str(root_path.resolve()).encode("utf-8")).hexdigest()


def _canonical_json_line(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _redact_text(value: str) -> str:
    if not value:
        return value
    return _REDACT_HOME.sub("<redacted-home>", value)


__all__ = [
    "TrajectoryExportManifest",
    "TrajectoryExportResult",
    "export_trajectories_jsonl",
    "resolve_export_output_path",
]
