# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The audit lane never loses a path record to normalization.

A path the current normalizer cannot express repo-relative is not evidence
that the path was never declared.  Every raw entry reaches the audit reader
under exactly one of four outcomes -- ``normalized``, ``unresolved``,
``legacy_invalid``, ``unsupported`` -- and the three refusing outcomes carry
the raw value plus a reason.  The normalized projection may be unavailable;
it may never be silently absent.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

from codeclone.audit.events import (
    EVENT_INTENT_CHECKED,
    EVENT_INTENT_DECLARED,
    AuditEvent,
    AuditPayloadMode,
    compact_payload_for_event,
    event_core_for_event,
    projection_supplement_facts_from_payload,
    repo_root_digest,
)
from codeclone.audit.reader import read_audit_event_core_records
from codeclone.audit.validation import MAX_EVENT_CORE_JSON_LEN, validate_event_row
from codeclone.audit.writer import SqliteAuditWriter, event_to_row

WITNESS_KEY = "path_projection_unavailable"
WITNESS_COUNT_KEY = "path_projection_unavailable_count"
WITNESS_TRUNCATED_KEY = "path_projection_unavailable_truncated"


def _event(
    root: Path,
    *,
    event_type: str = EVENT_INTENT_DECLARED,
    payload: dict[str, object],
) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        severity="info",
        repo_root_digest=repo_root_digest(root),
        agent_pid=4321,
        agent_label="path-outcome-agent",
        run_id="run98765",
        intent_id="intent-run98765-001",
        status="active",
        payload=payload,
    )


def _facts(event: AuditEvent) -> dict[str, object]:
    core = event_core_for_event(event)
    facts = core["facts"]
    assert isinstance(facts, dict)
    return facts


def _witness(facts: dict[str, object]) -> list[dict[str, object]]:
    entries = facts.get(WITNESS_KEY, [])
    assert isinstance(entries, list), f"{WITNESS_KEY} must be a list, got {entries!r}"
    return [cast(dict[str, object], entry) for entry in entries]


def _paths(facts: dict[str, object], key: str) -> list[str]:
    value = facts.get(key, [])
    assert isinstance(value, list)
    return [str(item) for item in value]


def _stored_row(db_path: Path) -> tuple[str, str]:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT event_core_json, payload_json FROM controller_events"
        ).fetchone()
    finally:
        conn.close()
    return (str(row[0]), str(row[1]))


def _emit(
    tmp_path: Path,
    event: AuditEvent,
    *,
    payloads: AuditPayloadMode = "compact",
) -> Path:
    db_path = tmp_path / "audit.sqlite3"
    writer = SqliteAuditWriter(db_path=db_path, payloads=payloads, retention_days=30)
    try:
        assert writer.emit(event) is not None, "the audit row itself must be written"
    finally:
        writer.close()
    return db_path


# --------------------------------------------------------------------------
# 1. The disappearance itself, measured end to end through the audit lane.
# --------------------------------------------------------------------------


def test_declared_absolute_scope_entry_is_not_erased_from_the_audit_lane(
    tmp_path: Path,
) -> None:
    """Under the default compact payload mode the event core is the only
    place a declared scope path is stored.  If normalization refuses it and
    says nothing, the whole audit lane forgets the entry was ever declared."""

    raw = "/Volumes/elsewhere/pkg/legacy.py"
    event = _event(
        tmp_path,
        payload={
            "intent_description": "legacy intent",
            "scope": {"allowed_files": ["pkg/kept.py", raw]},
        },
    )

    db_path = _emit(tmp_path, event)
    event_core_json, payload_json = _stored_row(db_path)

    stored = f"{event_core_json}\n{payload_json}"
    assert raw in stored, (
        "the declared scope entry vanished from every stored column: "
        f"event_core_json={event_core_json} payload_json={payload_json}"
    )


def test_reader_sees_the_refused_scope_entry_with_outcome_and_reason(
    tmp_path: Path,
) -> None:
    raw = "/Volumes/elsewhere/pkg/legacy.py"
    event = _event(
        tmp_path,
        payload={
            "intent_description": "legacy intent",
            "scope": {"allowed_files": ["pkg/kept.py", raw]},
        },
    )
    db_path = _emit(tmp_path, event)

    records = read_audit_event_core_records(
        db_path=db_path,
        repo_root_digest=repo_root_digest(tmp_path),
    )
    assert len(records) == 1
    core_json = records[0].event_core_json
    assert core_json is not None
    facts = json.loads(core_json)["facts"]

    assert facts["scope_paths"] == ["pkg/kept.py"]
    assert facts[WITNESS_COUNT_KEY] == 1
    assert _witness(facts) == [
        {
            "field": "scope.allowed_files",
            "outcome": "unresolved",
            "raw": raw,
            "reason": "absolute_path",
        }
    ]


# --------------------------------------------------------------------------
# 2. Closed outcome set: every refusal is one of four, each with a reason.
# --------------------------------------------------------------------------


def test_every_refusing_outcome_reaches_the_event_core(tmp_path: Path) -> None:
    event = _event(
        tmp_path,
        payload={
            "scope": {
                "allowed_files": [
                    "pkg/ok.py",
                    "/abs/outside.py",
                    "pkg/../escape.py",
                    "..",
                    ".",
                    "   ",
                    17,
                ]
            }
        },
    )

    facts = _facts(event)
    by_raw = {str(entry["raw"]): entry for entry in _witness(facts)}

    assert facts["scope_paths"] == ["pkg/ok.py"]
    assert by_raw["/abs/outside.py"]["outcome"] == "unresolved"
    assert by_raw["/abs/outside.py"]["reason"] == "absolute_path"
    assert by_raw["pkg/../escape.py"]["outcome"] == "unresolved"
    assert by_raw["pkg/../escape.py"]["reason"] == "parent_traversal"
    assert by_raw[".."]["outcome"] == "unresolved"
    assert by_raw[".."]["reason"] == "parent_traversal"
    assert by_raw["."]["outcome"] == "legacy_invalid"
    assert by_raw["."]["reason"] == "dot_only_value"
    # The raw witness is verbatim: a whitespace-only entry is recorded as the
    # producer wrote it, not as the empty string the normalizer saw.
    assert by_raw["   "]["outcome"] == "legacy_invalid"
    assert by_raw["   "]["reason"] == "empty_value"
    assert by_raw["17"]["outcome"] == "unsupported"
    assert by_raw["17"]["reason"] == "non_string_value"
    assert {str(entry["outcome"]) for entry in _witness(facts)} <= {
        "unresolved",
        "legacy_invalid",
        "unsupported",
    }


def test_refused_entries_never_enter_the_normalized_projection(
    tmp_path: Path,
) -> None:
    """The projection stays unavailable rather than inventing a path."""

    event = _event(
        tmp_path,
        payload={
            "scope": {
                "allowed_files": ["/abs/outside.py", "pkg/../escape.py", "..", ".", 17]
            }
        },
    )

    facts = _facts(event)

    assert facts.get("scope_paths", []) == []
    for entry in _witness(facts):
        assert entry.get("path") is None, entry
        assert entry["outcome"] != "normalized", entry


# --------------------------------------------------------------------------
# 3. Conservation: inputs in == outcomes out.  No arithmetic hole.
# --------------------------------------------------------------------------


def test_scope_entries_are_conserved_between_projection_and_witness(
    tmp_path: Path,
) -> None:
    raw_entries: list[object] = [
        "pkg/a.py",
        "pkg/b.py",
        "./pkg/c.py",
        "/abs/d.py",
        "pkg/../e.py",
        "..",
        ".",
        "",
        None,
    ]
    event = _event(tmp_path, payload={"scope": {"allowed_files": raw_entries}})

    facts = _facts(event)
    normalized = _paths(facts, "scope_paths")
    witness = _witness(facts)

    # Conservation alone is satisfiable by reclassifying a normalized entry as
    # a refusal, so pin both sides of the split, not only the total.
    assert normalized == ["pkg/a.py", "pkg/b.py", "pkg/c.py"]
    for entry in witness:
        assert entry["outcome"] in {"unresolved", "legacy_invalid", "unsupported"}
    assert len(normalized) + int(cast(int, facts[WITNESS_COUNT_KEY])) == len(
        raw_entries
    )
    assert len(witness) == facts[WITNESS_COUNT_KEY]
    assert facts.get(WITNESS_TRUNCATED_KEY) is None


def test_check_event_conserves_every_declared_and_changed_entry(
    tmp_path: Path,
) -> None:
    event = _event(
        tmp_path,
        event_type=EVENT_INTENT_CHECKED,
        payload={
            "status": "violated",
            "declared_scope": ["pkg/a.py", "/abs/declared.py"],
            "actual_changed_files": ["pkg/a.py", "/abs/changed.py"],
            "unexpected_files": ["../unexpected.py"],
            "forbidden_touched": [".."],
        },
    )

    facts = _facts(event)
    fields = {str(entry["field"]): str(entry["raw"]) for entry in _witness(facts)}

    assert facts[WITNESS_COUNT_KEY] == 4
    assert fields == {
        "declared_scope": "/abs/declared.py",
        "actual_changed_files": "/abs/changed.py",
        "unexpected_files": "../unexpected.py",
        "forbidden_touched": "..",
    }


def test_untouched_claim_names_the_field_whose_projection_is_incomplete(
    tmp_path: Path,
) -> None:
    """``untouched_in_declared`` is derived from the normalized changed set.

    When a changed-file entry could not be normalized, the derived claim is
    computed from an incomplete set -- the reader must be able to see which
    field lost an entry, otherwise "declared but untouched" reads as a fact.
    """

    event = _event(
        tmp_path,
        event_type=EVENT_INTENT_CHECKED,
        payload={
            "status": "clean",
            "declared_scope": ["pkg/a.py"],
            "actual_changed_files": ["/abs/repo/pkg/a.py"],
        },
    )

    facts = _facts(event)

    assert _paths(facts, "untouched_in_declared") == ["pkg/a.py"]
    assert [str(entry["field"]) for entry in _witness(facts)] == [
        "actual_changed_files"
    ]


# --------------------------------------------------------------------------
# 4. Reading historical evidence uses the same closed outcome set.
# --------------------------------------------------------------------------


def test_historical_payload_reread_keeps_the_witness(tmp_path: Path) -> None:
    """Re-deriving facts from a stored payload is a read of past evidence.

    A newer normalizer may not understand an old entry; it still may not
    erase it.
    """

    payload = {
        "intent_description": "legacy intent",
        "scope": {"allowed_files": ["pkg/a.py", "/abs/legacy.py"]},
    }
    payload_json = json.dumps(payload)

    supplement = projection_supplement_facts_from_payload(
        EVENT_INTENT_DECLARED,
        payload_json,
    )

    assert supplement["scope_paths"] == ["pkg/a.py"]
    assert supplement[WITNESS_COUNT_KEY] == 1
    entries = cast(list[dict[str, object]], supplement[WITNESS_KEY])
    assert entries[0]["raw"] == "/abs/legacy.py"
    assert entries[0]["outcome"] == "unresolved"


def test_compact_payload_is_unchanged_by_the_witness(tmp_path: Path) -> None:
    """The compact payload is the human forensic lane and keeps its shape."""

    payload = {
        "intent_description": "legacy intent",
        "scope": {"allowed_files": ["pkg/a.py", "/abs/legacy.py"]},
    }
    compact = compact_payload_for_event(
        event_type=EVENT_INTENT_DECLARED,
        payload=payload,
    )

    assert compact["scope_file_count"] == 2
    assert WITNESS_KEY not in compact


# --------------------------------------------------------------------------
# 5. Bounds are honest, and the bound never costs the whole event.
# --------------------------------------------------------------------------


def test_witness_truncation_is_declared_and_the_count_stays_exact(
    tmp_path: Path,
) -> None:
    refused = [f"/abs/{index}.py" for index in range(120)]
    event = _event(tmp_path, payload={"scope": {"allowed_files": refused}})

    facts = _facts(event)

    assert facts[WITNESS_COUNT_KEY] == 120
    assert len(_witness(facts)) < 120
    assert facts[WITNESS_TRUNCATED_KEY] is True


def test_long_raw_witness_is_bounded_and_says_so(tmp_path: Path) -> None:
    raw = "/abs/" + ("x" * 4000) + ".py"
    event = _event(tmp_path, payload={"scope": {"allowed_files": [raw]}})

    entry = _witness(_facts(event))[0]

    assert len(str(entry["raw"])) < len(raw)
    assert raw.startswith(str(entry["raw"]))
    assert entry["raw_truncated"] is True


def test_entries_sharing_a_bounded_prefix_stay_separate_refusals(
    tmp_path: Path,
) -> None:
    """Bounding the witness text must not merge distinct declarations.

    Deduplication reads the producer's full text; keying it on the bounded
    prefix would report many refused paths as one.
    """

    refused = ["/abs/" + ("x" * 4000) + f"/{index}.py" for index in range(3)]
    event = _event(tmp_path, payload={"scope": {"allowed_files": refused}})

    facts = _facts(event)

    assert facts[WITNESS_COUNT_KEY] == 3
    assert len(_witness(facts)) == 3


def test_witness_order_is_deterministic_across_fields(tmp_path: Path) -> None:
    """The witness rides inside ``event_core_sha256``, so its order is data.

    Producer order must not leak into the stored row: two runs that declare
    the same refusals in a different order must hash the same.
    """

    event = _event(
        tmp_path,
        event_type=EVENT_INTENT_CHECKED,
        payload={
            "status": "violated",
            "declared_scope": ["/z.py", "/a.py"],
            "actual_changed_files": ["/m.py"],
            "unexpected_files": ["../u.py"],
            "forbidden_touched": [".."],
        },
    )

    entries = _witness(_facts(event))

    assert [(str(e["field"]), str(e["raw"])) for e in entries] == [
        ("actual_changed_files", "/m.py"),
        ("declared_scope", "/a.py"),
        ("declared_scope", "/z.py"),
        ("forbidden_touched", ".."),
        ("unexpected_files", "../u.py"),
    ]


def test_repeated_identical_entries_are_recorded_once(tmp_path: Path) -> None:
    event = _event(
        tmp_path,
        payload={"scope": {"allowed_files": ["/abs/same.py", "/abs/same.py"]}},
    )

    facts = _facts(event)

    assert facts[WITNESS_COUNT_KEY] == 1


def test_worst_case_witness_still_fits_the_event_core_contract(
    tmp_path: Path,
) -> None:
    """The bound exists so a refusing event is never dropped as oversized.

    ``SqliteAuditWriter.emit`` swallows validation failures, so an event core
    that overflows ``MAX_EVENT_CORE_JSON_LEN`` costs the entire row.  Pin the
    bound to that basis, not to a literal.
    """

    refused = [f"/abs/{index}/" + ("x" * 4000) + ".py" for index in range(200)]
    kept = [f"pkg/{index}/{'d' * 180}.py" for index in range(200)]
    event = _event(
        tmp_path,
        payload={"scope": {"allowed_files": [*kept, *refused]}},
    )

    row = event_to_row(event=event, payloads="compact")
    assert row.event_core_json is not None
    assert len(row.event_core_json) <= MAX_EVENT_CORE_JSON_LEN
    validate_event_row(row)

    db_path = _emit(tmp_path, event)
    records = read_audit_event_core_records(
        db_path=db_path,
        repo_root_digest=repo_root_digest(tmp_path),
    )
    assert len(records) == 1
