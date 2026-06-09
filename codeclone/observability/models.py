# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Persisted observability records — the shared shape across runtime (writer),
store, and read model.

Pure data, no clock and no DB: the runtime stamps timestamps/durations and the
writer/reader move these between memory and sqlite.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .reason_kind import ReasonKind


@dataclass(frozen=True, slots=True)
class ProfileSample:
    """Optional resource snapshot (``codeclone[perf]`` / ``profile=true`` only)."""

    rss_mb: float | None = None
    rss_delta_mb: float | None = None
    cpu_user_ms: float | None = None
    cpu_system_ms: float | None = None
    open_fds: int | None = None
    thread_count: int | None = None


@dataclass(frozen=True, slots=True)
class SpanRecord:
    span_id: str
    operation_id: str
    name: str
    started_at_utc: str
    duration_ms: float
    status: str
    parent_span_id: str | None = None
    reason_kind: ReasonKind | None = None
    reason: str | None = None
    dedupe_key: str | None = None
    counters: Mapping[str, int] = field(default_factory=dict)
    profile: ProfileSample | None = None


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation_id: str
    correlation_id: str
    surface: str
    name: str
    started_at_utc: str
    duration_ms: float
    status: str
    parent_operation_id: str | None = None
    error_kind: str | None = None
    session_id: str | None = None
    repo_root_digest: str | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    request_tokens: int | None = None
    response_tokens: int | None = None
    profile: ProfileSample | None = None
    spans: tuple[SpanRecord, ...] = ()


__all__ = ["OperationRecord", "ProfileSample", "SpanRecord"]
