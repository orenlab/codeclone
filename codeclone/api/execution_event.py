# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The execution event: the one owner of every per-execution fact of a run.

Two objects, two identity laws (RULING-2026-09-02; RFC 2026-09-02 §III.1).
The report is content-addressed -- ``run_id`` names what was stated, and two
executions that state the same thing share it by design.  The execution is an
EVENT: it names the reading of one particular source state, is never shared
and never deduplicated.  Everything that varies per execution lives on the
event and nowhere else: the checkout, what the run read, what git said, the
run's own complaints, its provenance, and the outcome of publishing its
analysis snapshot.

Placed in the R3 door on purpose.  The MCP session produces the event today
and the persistence lane (an R2 store) will read it, so neither ring may own
it, and the model-store ratchet admits no new frozen structure on a surface.
R3 cannot name the surface's ``DirtySnapshot``, so the git witness is typed by
what the event reads of it (:class:`DirtySnapshotWitness`), which the surface
type and :class:`~codeclone.api.workspace.WorkspaceDirtySnapshotDTO` both
satisfy structurally.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..models import FileStat, RunSnapshotLink

# Domain separators of the two execution witnesses.  Kept beside the event
# rather than in ``codeclone.contracts`` for now: nothing persists these
# digests yet, and a contracts constant must declare the cache lane that
# stores its output (``test_every_contracts_constant_declares_its_cache_lane``).
# They move to the contracts owner together with the lane that will carry
# them, in the persistence step -- not before.
EXECUTION_SOURCE_STATE_DIGEST_DOMAIN = "codeclone.execution.source_state.v1\0"
EXECUTION_WORKSPACE_WITNESS_DOMAIN = "codeclone.execution.workspace_witness.v1\0"


class DirtyEntryWitness(Protocol):
    """One path git reported, as the execution witness reads it."""

    @property
    def path(self) -> str: ...

    @property
    def status_xy(self) -> str: ...

    @property
    def digest(self) -> str | None: ...

    @property
    def digest_status(self) -> str: ...


class DirtySnapshotWitness(Protocol):
    """What git said about the working tree when the execution ran."""

    @property
    def git_available(self) -> bool: ...

    @property
    def entries(self) -> Sequence[DirtyEntryWitness]: ...


def digest_source_state(content_manifest: Mapping[str, str] | None) -> str | None:
    """Digest of the exact source bytes one execution analysed.

    Built from the analysis's own read (``ProcessingResult.source_digest_by_file``
    -- worker digests for what was parsed, proven cache digests for what was
    reused), never from a second walk of the filesystem: a stat is forgeable
    with ``os.utime`` and a re-read can race the editor.  Order-free by its own
    sort.  ``None`` when the execution recorded no content witness at all, so
    an absent witness is never an empty one.
    """

    if content_manifest is None:
        return None
    digest = hashlib.sha256(EXECUTION_SOURCE_STATE_DIGEST_DOMAIN.encode("utf-8"))
    for path, value in sorted(content_manifest.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(value).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def digest_workspace(
    *,
    source_state: str | None,
    dirty_snapshot: DirtySnapshotWitness | None,
) -> str | None:
    """The state of the checkout one execution ran against.

    The source witness plus what git said about the working tree.  The
    capture time stays OUTSIDE the value: two executions are compared by what
    they read, never by when they read it.  ``None`` when neither witness
    exists, which is a different fact from two witnesses that agree.
    """

    if source_state is None and dirty_snapshot is None:
        return None
    digest = hashlib.sha256(EXECUTION_WORKSPACE_WITNESS_DOMAIN.encode("utf-8"))
    digest.update((source_state or "").encode("utf-8"))
    digest.update(b"\0")
    if dirty_snapshot is None:
        digest.update(b"no_snapshot")
        return digest.hexdigest()
    digest.update(b"git" if dirty_snapshot.git_available else b"no_git")
    for entry in sorted(dirty_snapshot.entries, key=lambda item: item.path):
        for part in (
            entry.path,
            entry.status_xy,
            entry.digest or "",
            entry.digest_status,
        ):
            digest.update(b"\0")
            digest.update(part.encode("utf-8"))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionEvent:
    """One execution of the analysis: the event that produced a semantic report.

    ``source_state_digest`` and ``workspace_witness`` are derived here and
    only here: ``dataclasses.replace`` recomputes them from the carriers, so no
    caller can hand this class a witness that disagrees with the bytes it
    describes.  The execution id is minted by the producing surface and never
    enters ``run_id``.
    """

    execution_event_id: str
    root: Path
    #: The report this execution produced: the record's ``run_id``.
    semantic_report_id: str
    #: Which files the run scanned, by stat.  Navigation and topology, never
    #: trust: a same-size rewrite keeps (mtime_ns, size) intact.
    manifest: Mapping[str, FileStat] | None = None
    #: Repo-relative path -> sha256 of the bytes the analysis consumed.
    content_manifest: Mapping[str, str] | None = None
    dirty_snapshot: DirtySnapshotWitness | None = None
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    #: Provenance, kept beside the witnesses and never inside them.
    analysis_started_at_utc: str = ""
    report_generated_at_utc: str = ""
    code_digest: str = ""
    #: The outcome of publishing this execution's analysis snapshot (ruling
    #: 2026-09-03: the execution event is its long-term owner -- a physical
    #: outcome, never a semantic fact of the report).  ``None`` when the run
    #: produced no bridge at all.
    run_snapshot_link: RunSnapshotLink | None = None
    source_state_digest: str | None = field(init=False)
    workspace_witness: str | None = field(init=False)

    def __post_init__(self) -> None:
        if not self.execution_event_id.strip():
            raise ValueError("an execution event carries a non-empty id")
        if not self.semantic_report_id:
            raise ValueError("an execution event names the report it produced")
        source_state = digest_source_state(self.content_manifest)
        object.__setattr__(self, "source_state_digest", source_state)
        object.__setattr__(
            self,
            "workspace_witness",
            digest_workspace(
                source_state=source_state,
                dirty_snapshot=self.dirty_snapshot,
            ),
        )


__all__ = [
    "DirtyEntryWitness",
    "DirtySnapshotWitness",
    "ExecutionEvent",
    "digest_source_state",
    "digest_workspace",
]
