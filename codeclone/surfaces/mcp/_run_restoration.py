# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A run found again after the process that analysed it is gone.

The surface keeps, of every run whose payload it let go, its resident
identity (``_session_shared.MCPRunIdentity``): the request, the comparison
settings, the clone counts, the execution event with every witness and the
store link, and the run summary's memory-only fields.  That identity is
exactly what a process that never held the run needs to answer from the
run store as the publisher answers after a payload drop, so it is what the
execution registry carries (the execution overlay, RFC 2026-09-02 III.1):

* :func:`encode_resident_run` -- the identity as canonical JSON, compressed:
  no pickle (III.2: the store path lives in the analysed repository, so its
  bytes are input, not code);
* :func:`decode_resident_run` -- a validating decoder: an unknown key, a
  missing key or a value of the wrong type is a refusal, the decompression
  is bounded, and the execution's witnesses are re-derived by the event
  itself and must equal the stored ones;
* :class:`StoreRunRestorer` -- the registry's miss hook: the R3 door's
  answer, decoded and proven against the request (root, run id, the
  record's own execution and store run), or :class:`MCPRunUnavailableError`
  with the door's typed reason.

Nothing here turns an identity back into a record: a restored run is
answered by the readings with a store road, and refused typed by the rest,
exactly like a run whose payload this process dropped.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable, Mapping
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Final, TypeVar, cast

import orjson

from ...api.execution_event import ExecutionEvent
from ...api.run_residence import RunSummaryResidue
from ...api.run_restoration import (
    PUBLICATION_RETENTION,
    RESTORATION_RETRYABLE,
    RESTORATION_RUN_EXPIRED,
    RESTORATION_RUN_NOT_FOUND,
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_LINK_UNRECORDED,
    ExecutionRecordError,
    FileStat,
    RunRestoration,
    RunSnapshotLink,
    finalize_execution_record,
    restore_run,
)
from ...api.run_store_serving import (
    SERVING_REASON_INCOMPATIBLE_GENERATION,
    SERVING_REASON_INTEGRITY,
    SERVING_REASON_SERVED,
)
from ._run_residence import resident_identity
from ._session_helpers import _short_run_id
from ._session_shared import (
    CodeCloneMCPRunStore,
    MCPAnalysisRequest,
    MCPHeldRun,
    MCPRunIdentity,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPRunUnavailableError,
    MCPServiceContractError,
)
from ._workspace_hygiene import DirtySnapshot, dirty_snapshot_from_payload
from .messages.run_restoration import (
    RUN_NOT_RESTORABLE_WARNING,
    RUN_UNAVAILABLE_MESSAGES,
    RUN_UNAVAILABLE_NEXT_STEPS,
    RUN_UNAVAILABLE_STATUS,
)

#: The contract a resident run is written under.  It names this codec: a
#: record written under another contract is a record of another generation
#: and is refused ``incompatible_generation``, never guessed at.
RESIDENT_RUN_CONTRACT: Final = "codeclone.mcp.resident_run/1"

#: The decompressed overlay a decoder accepts at most.  Measured 2026-10-12
#: on the self-repository (1375 files): 280 171 bytes of JSON.  A bound three
#: orders of magnitude above it refuses a decompression bomb and admits any
#: real checkout.
_MAX_OVERLAY_BYTES: Final = 256 * 1024 * 1024

_T = TypeVar("_T")


class OverlayRefusal(ValueError):
    """A stored overlay this codec cannot decode into a resident run."""


def _sorted_mapping(mapping: Mapping[str, object] | None) -> dict[str, object] | None:
    return None if mapping is None else {key: mapping[key] for key in sorted(mapping)}


def _execution_payload(execution: ExecutionEvent) -> dict[str, object]:
    dirty = execution.dirty_snapshot
    link = execution.run_snapshot_link
    manifest = execution.manifest
    return {
        "execution_event_id": execution.execution_event_id,
        "root": str(execution.root),
        "semantic_report_id": execution.semantic_report_id,
        "manifest": None
        if manifest is None
        else {path: dict(manifest[path]) for path in sorted(manifest)},
        "content_manifest": _sorted_mapping(execution.content_manifest),
        "dirty_snapshot": None
        if not isinstance(dirty, DirtySnapshot)
        else dirty.to_payload(),
        "warnings": list(execution.warnings),
        "failures": list(execution.failures),
        "analysis_started_at_utc": execution.analysis_started_at_utc,
        "scope_source": execution.scope_source,
        "report_generated_at_utc": execution.report_generated_at_utc,
        "code_digest": execution.code_digest,
        "run_snapshot_link": None if link is None else asdict(link),
        "source_state_digest": execution.source_state_digest,
        "workspace_witness": execution.workspace_witness,
    }


def encode_resident_run(identity: MCPRunIdentity) -> bytes:
    """The execution overlay of one run: its resident identity as canonical
    JSON (sorted keys, no whitespace), zlib-compressed."""
    payload = {
        "run_id": identity.run_id,
        "root": str(identity.root),
        "request": asdict(identity.request),
        "comparison_settings": list(identity.comparison_settings),
        "changed_paths": list(identity.changed_paths),
        "func_clones_count": identity.func_clones_count,
        "block_clones_count": identity.block_clones_count,
        "execution": _execution_payload(identity.execution),
        "summary_residue": asdict(identity.summary_residue),
    }
    return zlib.compress(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS), 6)


def _inflate(overlay: bytes) -> object:
    inflater = zlib.decompressobj()
    try:
        raw = inflater.decompress(overlay, _MAX_OVERLAY_BYTES)
    except zlib.error as fault:
        raise OverlayRefusal(f"overlay is not a zlib stream: {fault}") from fault
    if inflater.unconsumed_tail or not inflater.eof:
        raise OverlayRefusal("overlay exceeds the decoder's bound or is truncated")
    try:
        return orjson.loads(raw)
    except orjson.JSONDecodeError as fault:
        raise OverlayRefusal(f"overlay is not JSON: {fault}") from fault


def _object(value: object, where: str, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise OverlayRefusal(f"{where} is not an object with exactly its keys")
    return {str(key): item for key, item in value.items()}


def _typed(value: object, kind: type[_T], where: str) -> _T:
    # ``bool`` is an ``int`` to Python and never one to this codec.
    if isinstance(value, bool) is not (kind is bool) or not isinstance(value, kind):
        raise OverlayRefusal(f"{where} is not a {kind.__name__}")
    return value


def _optional(value: object, kind: type[_T], where: str) -> _T | None:
    return None if value is None else _typed(value, kind, where)


def _strings(value: object, where: str) -> tuple[str, ...]:
    return tuple(_typed(item, str, where) for item in _typed(value, list, where))


def _string_map(value: object, where: str) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        _typed(key, str, where): _typed(item, str, where)
        for key, item in _typed(value, dict, where).items()
    }


def _json_map(value: object, where: str) -> dict[str, object]:
    mapping = _typed(value, dict, where)
    return {_typed(key, str, where): item for key, item in mapping.items()}


def _manifest(value: object) -> dict[str, FileStat] | None:
    if value is None:
        return None
    manifest: dict[str, FileStat] = {}
    for path, stat in _typed(value, dict, "manifest").items():
        entry = _object(stat, "manifest entry", frozenset({"mtime_ns", "size"}))
        manifest[_typed(path, str, "manifest path")] = FileStat(
            mtime_ns=_typed(entry["mtime_ns"], int, "mtime_ns"),
            size=_typed(entry["size"], int, "size"),
        )
    return manifest


_LINK_KEYS: Final = frozenset(field.name for field in fields(RunSnapshotLink))
_REQUEST_FIELDS: Final = {field.name: field for field in fields(MCPAnalysisRequest)}
_RESIDUE_KEYS: Final = frozenset(field.name for field in fields(RunSummaryResidue))
_EXECUTION_KEYS: Final = frozenset(
    {
        "execution_event_id",
        "root",
        "semantic_report_id",
        "manifest",
        "content_manifest",
        "dirty_snapshot",
        "warnings",
        "failures",
        "analysis_started_at_utc",
        "scope_source",
        "report_generated_at_utc",
        "code_digest",
        "run_snapshot_link",
        "source_state_digest",
        "workspace_witness",
    }
)
_IDENTITY_KEYS: Final = frozenset(
    {
        "run_id",
        "root",
        "request",
        "comparison_settings",
        "changed_paths",
        "func_clones_count",
        "block_clones_count",
        "execution",
        "summary_residue",
    }
)


def _link(value: object) -> RunSnapshotLink | None:
    if value is None:
        return None
    payload = _object(value, "run_snapshot_link", _LINK_KEYS)
    try:
        return RunSnapshotLink(
            **{key: _typed(item, str, f"link {key}") for key, item in payload.items()}
        )
    except ValueError as refusal:
        raise OverlayRefusal(f"run_snapshot_link: {refusal}") from refusal


def _dirty(value: object) -> DirtySnapshot | None:
    if value is None:
        return None
    decoded = dirty_snapshot_from_payload(value)
    if decoded is None:
        raise OverlayRefusal("dirty_snapshot does not decode")
    return decoded


def _execution(value: object) -> ExecutionEvent:
    payload = _object(value, "execution", _EXECUTION_KEYS)
    try:
        execution = ExecutionEvent(
            execution_event_id=_typed(payload["execution_event_id"], str, "event id"),
            root=Path(_typed(payload["root"], str, "execution root")),
            semantic_report_id=_typed(payload["semantic_report_id"], str, "report"),
            manifest=_manifest(payload["manifest"]),
            content_manifest=_string_map(payload["content_manifest"], "content"),
            dirty_snapshot=_dirty(payload["dirty_snapshot"]),
            warnings=_strings(payload["warnings"], "warnings"),
            failures=_strings(payload["failures"], "failures"),
            analysis_started_at_utc=_typed(
                payload["analysis_started_at_utc"], str, "analysis_started_at_utc"
            ),
            scope_source=_typed(payload["scope_source"], str, "scope_source"),
            report_generated_at_utc=_typed(
                payload["report_generated_at_utc"], str, "report_generated_at_utc"
            ),
            code_digest=_typed(payload["code_digest"], str, "code_digest"),
            run_snapshot_link=_link(payload["run_snapshot_link"]),
        )
    except ValueError as refusal:
        raise OverlayRefusal(f"execution: {refusal}") from refusal
    if execution.content_manifest is None:
        # Every execution this surface produces records what it read
        # (``build_run_content_manifest`` never answers ``None``), and the
        # intent registry's abstention for two witness-less executions rests
        # on that: a stored execution without one is no execution of ours.
        raise OverlayRefusal("the execution records no content witness")
    stored = (
        _optional(payload["source_state_digest"], str, "source_state_digest"),
        _optional(payload["workspace_witness"], str, "workspace_witness"),
    )
    if stored != (execution.source_state_digest, execution.workspace_witness):
        raise OverlayRefusal("the execution's witnesses do not re-derive")
    return execution


#: How each request field is read back, by its declared annotation: the
#: value's type and whether ``None`` is admitted.  A field whose annotation is
#: not here is refused, so a request field added without a reading cannot be
#: decoded by guess (``test_every_request_field_has_a_reading``).
_REQUEST_READINGS: Final[dict[str, tuple[type, bool]]] = {
    "str | None": (str, True),
    "AnalysisMode": (str, False),
    "bool": (bool, False),
    "bool | None": (bool, True),
    "int | None": (int, True),
}


def _request_value(name: str, value: object) -> object:
    if name == "changed_paths":
        return _strings(value, "request changed_paths")
    annotation = str(_REQUEST_FIELDS[name].type)
    if annotation not in _REQUEST_READINGS:
        raise OverlayRefusal(f"request field {name} has no reading")
    kind, optional = _REQUEST_READINGS[annotation]
    if optional:
        return _optional(value, kind, f"request {name}")
    return _typed(value, kind, f"request {name}")


def _request(value: object) -> MCPAnalysisRequest:
    payload = _object(value, "request", frozenset(_REQUEST_FIELDS))
    read = {name: _request_value(name, item) for name, item in payload.items()}
    # Every value was read against its field's own annotation above, which
    # is the typing the constructor's signature cannot see through ``**``;
    # the key set is the field set exactly, so the constructor cannot refuse.
    build = cast("Callable[..., MCPAnalysisRequest]", MCPAnalysisRequest)
    return build(**read)


def _residue(value: object) -> RunSummaryResidue:
    payload = _object(value, "summary_residue", _RESIDUE_KEYS)
    counts = payload["entity_counts"]
    return RunSummaryResidue(
        version=_typed(payload["version"], str, "version"),
        schema=_typed(payload["schema"], str, "schema"),
        cache=_json_map(payload["cache"], "cache"),
        baseline_execution=_json_map(payload["baseline_execution"], "baseline"),
        entity_counts=None if counts is None else _json_map(counts, "entity_counts"),
        security_presentation=_json_map(
            payload["security_presentation"], "security_presentation"
        ),
    )


def _comparison_settings(value: object) -> tuple[object, ...]:
    items = _typed(value, list, "comparison_settings")
    for item in items:
        if not isinstance(item, (str, int)) or isinstance(item, bool):
            raise OverlayRefusal("comparison_settings holds a value of another type")
    return tuple(items)


def decode_resident_run(overlay: bytes) -> MCPRunIdentity:
    """The resident identity an overlay carries, or :class:`OverlayRefusal`."""
    payload = _object(_inflate(overlay), "overlay", _IDENTITY_KEYS)
    return MCPRunIdentity(
        run_id=_typed(payload["run_id"], str, "run_id"),
        root=Path(_typed(payload["root"], str, "root")),
        request=_request(payload["request"]),
        comparison_settings=_comparison_settings(payload["comparison_settings"]),
        changed_paths=_strings(payload["changed_paths"], "changed_paths"),
        func_clones_count=_typed(payload["func_clones_count"], int, "func clones"),
        block_clones_count=_typed(payload["block_clones_count"], int, "block clones"),
        execution=_execution(payload["execution"]),
        summary_residue=_residue(payload["summary_residue"]),
    )


def unavailable_answer(
    *,
    reason: str,
    run_id: str,
    root: Path | None,
    detail: str = "",
    store_next_step: str = "",
    proof: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """The one typed answer about a run no reading answered: the reason,
    whether the same call can succeed later, the step that changes the
    answer, and -- for an expired run -- the record that proves it was."""
    spelled_root = "<absolute repository root>" if root is None else str(root)
    # A refusal the store did not word (a record of another contract) still
    # names a step that changes the answer: a new analysis in this server.
    analyse = RUN_UNAVAILABLE_NEXT_STEPS[RESTORATION_RUN_NOT_FOUND]
    words = {
        "run_id": _short_run_id(run_id),
        "root": spelled_root,
        "detail": detail,
        "store_next_step": store_next_step or analyse.format(root=spelled_root),
        "max_runs": PUBLICATION_RETENTION.max_runs,
        "max_days": PUBLICATION_RETENTION.max_age_seconds // 86400,
    }
    answer: dict[str, object] = {
        "run_id": words["run_id"],
        "root": spelled_root,
        "status": RUN_UNAVAILABLE_STATUS,
        "reason": reason,
        "retryable": RESTORATION_RETRYABLE[reason],
        "next_step": RUN_UNAVAILABLE_NEXT_STEPS[reason].format(**words),
        "message": RUN_UNAVAILABLE_MESSAGES[reason].format(**words),
    }
    if detail:
        answer["detail"] = detail
    if proof is not None:
        answer["expired"] = dict(proof)
    return answer


def _expiry_proof(answer: RunRestoration) -> dict[str, object] | None:
    if answer.reason != RESTORATION_RUN_EXPIRED:
        return None
    return {
        "execution_event_id": answer.execution_event_id,
        "store_run_id": answer.store_run_id,
        "finalized_at": answer.finalized_at,
    }


def _refuse(
    reason: str, detail: str, *, run_id: str, root: Path
) -> MCPRunUnavailableError:
    return MCPRunUnavailableError(
        unavailable_answer(reason=reason, run_id=run_id, root=root, detail=detail)
    )


def restored_identity(
    answer: RunRestoration, *, run_id: str, root: Path
) -> MCPRunIdentity:
    """The resident identity a served answer carries, proven against the
    request and the record it came in; every other answer, and every proof
    that fails, is the typed refusal."""
    if answer.reason != SERVING_REASON_SERVED:
        raise MCPRunUnavailableError(
            unavailable_answer(
                reason=answer.reason,
                run_id=run_id,
                root=root,
                detail=answer.detail,
                store_next_step=answer.next_step,
                proof=_expiry_proof(answer),
            )
        )
    if answer.record_contract != RESIDENT_RUN_CONTRACT:
        raise _refuse(
            SERVING_REASON_INCOMPATIBLE_GENERATION,
            f"execution record written under {answer.record_contract!r}; "
            f"this server reads {RESIDENT_RUN_CONTRACT!r}",
            run_id=run_id,
            root=root,
        )
    try:
        identity = decode_resident_run(answer.overlay)
    except OverlayRefusal as refusal:
        raise _refuse(
            SERVING_REASON_INTEGRITY, str(refusal), run_id=run_id, root=root
        ) from refusal
    link = identity.execution.run_snapshot_link
    proven = (
        identity.root.resolve() == root.resolve()
        and identity.execution.execution_event_id == answer.execution_event_id
        and link is not None
        and link.state == RUN_SNAPSHOT_LINK_LINKED
        and link.store_run_id == answer.store_run_id
        and identity.run_id == link.report_run_identity
    )
    if not proven:
        raise _refuse(
            SERVING_REASON_INTEGRITY,
            "the execution overlay does not describe the record it is stored in",
            run_id=run_id,
            root=root,
        )
    return identity


class RestoringRunStore(CodeCloneMCPRunStore):
    """The session registry that, missing a run, looks for it in the run
    store's execution registry of its root, by the report it names, and
    holds what it finds by its resident identity
    (:meth:`CodeCloneMCPRunStore.restore`), or answers the door's typed
    refusal (:class:`MCPRunUnavailableError`).  An unnamed run ("the latest")
    is this session's alone and is never looked up; neither is an execution
    an intent names (an intent of a process that is gone is recovered whole
    -- the boundary of this restoration)."""

    def _restored_for_root(self, run_id: str | None, *, root: Path) -> MCPHeldRun:
        if run_id is None:
            return super()._restored_for_root(run_id, root=root)
        try:
            answer = restore_run(root=root, run_id=run_id)
        except ExecutionRecordError as ambiguous:
            raise MCPServiceContractError(str(ambiguous)) from ambiguous
        identity = restored_identity(answer, run_id=run_id, root=root)
        if not identity.run_id.startswith(run_id):
            raise _refuse(
                SERVING_REASON_INTEGRITY,
                f"the record found for run {run_id} names run {identity.run_id}",
                run_id=run_id,
                root=root,
            )
        return self.restore(identity)


def restoring_run_store(*, history_limit: int) -> CodeCloneMCPRunStore:
    """The registry an MCP session holds its runs in: one that finds a run it
    does not hold in its root's run store."""
    return RestoringRunStore(history_limit=history_limit)


def _linked_warnings(record: MCPRunRecord, link: RunSnapshotLink) -> tuple[str, ...]:
    """The record's warnings with the stated link's lines exchanged for the
    finalized link's -- and, for a run no other process can find, the line
    that says so."""
    stated = record.execution.run_snapshot_link
    lines = set(record.execution.warnings) - set(
        () if stated is None else stated.warnings()
    )
    lines.update(link.warnings())
    if link.state == RUN_SNAPSHOT_LINK_UNRECORDED:
        lines.add(
            RUN_NOT_RESTORABLE_WARNING.format(run_id=_short_run_id(record.run_id))
        )
    return tuple(sorted(lines))


def record_with_link(record: MCPRunRecord, link: RunSnapshotLink) -> MCPRunRecord:
    """``record`` as its finalization left it: the execution carries the
    finalized link, and the execution and the summary say its lines."""
    warnings = _linked_warnings(record, link)
    return replace(
        record,
        execution=replace(record.execution, run_snapshot_link=link, warnings=warnings),
        summary={**record.summary, "warnings": list(warnings)},
    )


def finalized_record(record: MCPRunRecord, *, lease: str, store: str) -> MCPRunRecord:
    """Make the analysed run findable by its execution, or say why it is not.

    ``lease`` and ``store`` are what the report left for this surface
    (``ReportArtifacts.finalization_lease`` / ``finalization_store``): with
    none, nothing was stored and linked and the record stands as it is.
    Otherwise the run store finalizes the publication with this run's
    resident identity as its execution overlay -- the snapshot, the record,
    the bridge edge and the end of the publisher's lease in one atom -- and
    a link the store left otherwise (``unrecorded``, a refused sweep) is put
    on the record, with its lines.
    """
    link = record.execution.run_snapshot_link
    if not lease or not store or link is None:
        return record
    finalized = finalize_execution_record(
        store_path=Path(store),
        link=link,
        publisher_lease=lease,
        execution_event_id=record.execution.execution_event_id,
        root=record.root,
        record_contract=RESIDENT_RUN_CONTRACT,
        overlay=encode_resident_run(resident_identity(record)),
    )
    if finalized == link:
        return record
    return record_with_link(record, finalized)


def not_found_answer(error: MCPRunNotFoundError) -> dict[str, object]:
    """The typed answer of a run no restoration was asked about: an unnamed
    run ("the latest") this session does not hold, or a run named without a
    root.  The error's own words say what was asked."""
    if isinstance(error, MCPRunUnavailableError):
        return dict(error.answer)
    answer = unavailable_answer(reason=RESTORATION_RUN_NOT_FOUND, run_id="", root=None)
    answer.pop("run_id")
    answer["message"] = str(error)
    return answer


__all__ = [
    "RESIDENT_RUN_CONTRACT",
    "OverlayRefusal",
    "RestoringRunStore",
    "decode_resident_run",
    "encode_resident_run",
    "finalized_record",
    "not_found_answer",
    "record_with_link",
    "restored_identity",
    "restoring_run_store",
    "unavailable_answer",
]
