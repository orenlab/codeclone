# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Reading a persisted intent scope for audit never re-decides its past.

Ratified 2026-08-28: a parser governs new decisions and gains no right to
change, after the fact, what already-written evidence meant.

    legacy scope syntax
    raw value preserved
    historical interpretation ambiguous / producer-specific
    NOT reinterpreted under current grammar

Two facts are measured on this repository and are the whole basis of the split
below. First, the live registry holds 47 closed intents whose ``allowed_files``
carries a glob (152 occurrences) and 46 whose ``allowed_related`` does (73),
none of them unclosed. Second, before the grammar owner landed, three deciding
predicates disagreed about a directory entry and a glob entry in opposite
directions -- so a stored entry has no single "old meaning" to restore either.

The live lane is deliberately untouched: today's grammar decides today's
writes, and :func:`test_the_live_predicate_keeps_its_conservative_answer`
fails if this module's work leaks into it.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from codeclone.contracts.scope_grammar import (
    read_scope_entries,
    scope_contains_path,
)
from codeclone.surfaces.mcp._workspace_intents import (
    WorkspaceIntentRecord,
    compute_scope_digest,
    format_utc,
    utc_now,
    workspace_intent_to_payload,
)

_GLOB_ENTRY = "tools/review/**"
_GLOB_INSIDE = "tools/review/report.py"


def _record(
    *allowed_files: str,
    allowed_related: tuple[str, ...] = (),
    status: str = "clean",
) -> WorkspaceIntentRecord:
    """A persisted record, written straight to the contract.

    Deliberately not through ``normalize_intent_scope``: the door now refuses a
    glob, so the only way to hold one is to be older than the door -- which is
    exactly the situation of the 47 records in the live registry.
    """

    declared_at = utc_now()
    scope: dict[str, object] = {
        "allowed_files": list(allowed_files),
        "allowed_related": list(allowed_related),
        "forbidden": [],
    }
    return WorkspaceIntentRecord(
        intent_id="intent-legacy-scope-audit",
        agent_pid=os.getpid(),
        agent_start_epoch=100,
        agent_label="agent-legacy",
        run_id="abcdef1234567890",
        declared_at_utc=format_utc(declared_at),
        expires_at_utc=format_utc(declared_at + timedelta(hours=1)),
        ttl_seconds=3600,
        status=status,
        intent="an intent written before the grammar",
        scope=scope,
        scope_digest=compute_scope_digest(scope),
        blast_radius_summary={"radius_level": "medium"},
        lease_renewed_at_utc=format_utc(declared_at),
        lease_seconds=300,
        report_digest="digest-legacy",
    )


# --------------------------------------------------------------------------
# The live lane, which this work may not touch
# --------------------------------------------------------------------------


def test_the_live_predicate_keeps_its_conservative_answer() -> None:
    """A new write is still authorised by the current grammar, literally.

    The total reader gives a stored glob its literal reading, so the live
    answer is ``False``. That is correct for authorising a write and it is the
    one thing the audit lane may not repeat, because as an answer *about the
    past* it is a verdict this grammar has no standing to give.
    """

    entries = read_scope_entries((_GLOB_ENTRY,))
    assert scope_contains_path(entries, _GLOB_INSIDE) is False


# --------------------------------------------------------------------------
# The audit reader
# --------------------------------------------------------------------------


def test_a_legacy_entry_is_returned_verbatim_and_marked_ambiguous() -> None:
    from codeclone.surfaces.mcp._workspace_intents import (
        LEGACY_AMBIGUOUS,
        read_audit_scope_entry,
    )

    entry = read_audit_scope_entry(_GLOB_ENTRY)
    assert entry.raw == _GLOB_ENTRY
    assert entry.status == LEGACY_AMBIGUOUS
    assert entry.kind is None
    assert entry.refusal_reason == "scope_entry_glob_forbidden"
    assert entry.next_step


_MIXED_SCOPE = (_GLOB_ENTRY, "./pkg/b.py", "  ", "pkg/a.py", "tests/")


def test_a_legacy_entry_is_never_dropped() -> None:
    """An audit that silently shortens a record has misreported it.

    The live reader drops blanks because a blank cannot authorise a write.
    Here every stored position keeps its own entry.
    """

    from codeclone.surfaces.mcp._workspace_intents import read_audit_scope

    entries = read_audit_scope(_MIXED_SCOPE)
    assert len(entries) == len(_MIXED_SCOPE)
    assert sum(1 for entry in entries if entry.is_legacy) == 2


def test_a_legacy_entry_is_never_rewritten() -> None:
    """Raw text survives byte for byte, blanks and ``./`` included.

    Rewriting is how ``./pkg/b.py`` would become ``pkg/b.py`` and the record's
    ``scope_digest`` would stop matching the scope the door wrote.
    """

    from codeclone.surfaces.mcp._workspace_intents import read_audit_scope

    entries = read_audit_scope(_MIXED_SCOPE)
    assert tuple(entry.raw for entry in entries) == _MIXED_SCOPE


def test_a_current_entry_keeps_its_typed_reading() -> None:
    from codeclone.surfaces.mcp._workspace_intents import (
        CURRENT_GRAMMAR,
        read_audit_scope,
    )

    file_entry, tree_entry = read_audit_scope(("pkg/a.py", "tests/"))
    assert (file_entry.status, file_entry.kind) == (CURRENT_GRAMMAR, "file")
    assert (tree_entry.status, tree_entry.kind) == (CURRENT_GRAMMAR, "tree")
    assert file_entry.refusal_reason is None
    # The exact file is the one form the three pre-grammar predicates read
    # alike; the directory prefix is the form on which they split.
    assert file_entry.historical_reading == "unambiguous"
    assert tree_entry.historical_reading == "producer_specific"


def test_the_audit_read_refuses_a_scope_verdict_on_a_legacy_entry() -> None:
    """The whole ruling in one assertion: no ``inside``/``outside`` here."""

    from codeclone.surfaces.mcp._workspace_intents import (
        ScopeRelation,
        audit_scope_relation,
    )

    relation = audit_scope_relation((_GLOB_ENTRY,), _GLOB_INSIDE)
    assert relation.value not in {
        ScopeRelation.INSIDE.value,
        ScopeRelation.OUTSIDE.value,
    }
    assert relation is ScopeRelation.LEGACY_AMBIGUOUS


@pytest.mark.parametrize(
    ("entry", "path", "expected"),
    [
        # An exact file is the one form the three pre-grammar predicates all
        # read the same way, so it still answers.
        ("pkg/a.py", "pkg/a.py", "inside"),
        ("pkg/a.py", "pkg/b.py", "outside"),
        # A directory prefix is the measured divergence: exact membership and
        # fnmatch said no, hygiene said yes.
        ("tests/", "tests/test_api.py", "legacy_ambiguous"),
        ("tests/", "tests", "legacy_ambiguous"),
        # ... but only for paths it could have covered. Outside its own
        # prefix every historical reading said no, so the audit still answers.
        ("tests/", "testsuite/test_api.py", "outside"),
        ("tests/", "src/mod.py", "outside"),
        # A glob is ambiguous under its literal head and answerable outside it:
        # no historical reading of "tools/review/**" reached "docs/x.py".
        (_GLOB_ENTRY, _GLOB_INSIDE, "legacy_ambiguous"),
        (_GLOB_ENTRY, "docs/x.py", "outside"),
        ("tests/test_*.py", "tests/test_api.py", "legacy_ambiguous"),
        ("tests/test_*.py", "tests/conftest.py", "outside"),
    ],
)
def test_the_audit_relation_is_total_over_the_measured_forms(
    entry: str,
    path: str,
    expected: str,
) -> None:
    from codeclone.surfaces.mcp._workspace_intents import audit_scope_relation

    assert audit_scope_relation((entry,), path).value == expected


def test_one_answering_entry_settles_a_scope_its_neighbour_cannot() -> None:
    """Combination is by strength: a positive fact outranks an unknown."""

    from codeclone.surfaces.mcp._workspace_intents import audit_scope_relation

    scope = (_GLOB_ENTRY, "pkg/a.py")
    assert audit_scope_relation(scope, "pkg/a.py").value == "inside"
    assert audit_scope_relation(scope, _GLOB_INSIDE).value == "legacy_ambiguous"
    assert audit_scope_relation(scope, "docs/x.py").value == "outside"


# --------------------------------------------------------------------------
# Provenance: reported when the record carries it, never invented
# --------------------------------------------------------------------------


def test_no_interpreter_is_invented_for_a_record_that_carries_none() -> None:
    """Measured: no persisted field names the consumer that decided.

    All 733 rows of the live registry carry the same 19 top-level keys and the
    same ``registry_version`` ``"2"``, glob-bearing rows included, and every
    one of the 174 ``intent.*`` audit events carries ``surface='unknown'`` with
    a null ``tool_name``. So the "show its then-interpretation" branch has no
    input, and the honest answer is that there is none.
    """

    from codeclone.surfaces.mcp._workspace_intents import (
        scope_interpreter_from_record,
    )

    record = _record(_GLOB_ENTRY)
    assert scope_interpreter_from_record(record.unsigned_payload()) is None
    assert scope_interpreter_from_record({"scope_interpreter": "hygiene"}) == "hygiene"


def test_an_interpreter_the_caller_knows_is_carried_into_the_entry() -> None:
    from codeclone.surfaces.mcp._workspace_intents import read_audit_scope_entry

    entry = read_audit_scope_entry(_GLOB_ENTRY, interpreter="patch_contract")
    assert entry.interpreter == "patch_contract"
    assert entry.status == "legacy_ambiguous"


# --------------------------------------------------------------------------
# The edge: the audit payload a machine actually reads
# --------------------------------------------------------------------------


def test_the_persisted_record_payload_carries_the_marker() -> None:
    payload = workspace_intent_to_payload(_record(_GLOB_ENTRY))
    audit = cast("dict[str, Any]", payload["scope_audit"])
    assert audit["status"] == "legacy_ambiguous"
    assert audit["next_step"]
    allowed = cast("list[dict[str, Any]]", audit["allowed_files"])
    assert [item["raw"] for item in allowed] == [_GLOB_ENTRY]
    assert allowed[0]["status"] == "legacy_ambiguous"
    assert allowed[0]["refusal_reason"] == "scope_entry_glob_forbidden"
    # No verdict may ride along with the raw value.
    assert "in_scope" not in allowed[0]
    assert "scope_relation" not in allowed[0]


def test_the_audit_payload_leaves_the_raw_scope_untouched() -> None:
    record = _record(_GLOB_ENTRY, allowed_related=("tests/fixtures/**",))
    payload = workspace_intent_to_payload(record)
    scope = cast("dict[str, Any]", payload["scope"])
    assert scope["allowed_files"] == [_GLOB_ENTRY]
    assert scope["allowed_related"] == ["tests/fixtures/**"]
    assert payload["scope_digest"] == record.scope_digest


def test_a_legacy_entry_in_allowed_related_is_marked_too() -> None:
    """Measured: 46 live records carry a glob in ``allowed_related``.

    The field is smaller and easy to forget, which is why it gets its own pin.
    """

    payload = workspace_intent_to_payload(
        _record("pkg/a.py", allowed_related=("tests/fixtures/**",))
    )
    audit = cast("dict[str, Any]", payload["scope_audit"])
    assert audit["status"] == "legacy_ambiguous"
    related = cast("list[dict[str, Any]]", audit["allowed_related"])
    assert related[0]["raw"] == "tests/fixtures/**"
    assert related[0]["status"] == "legacy_ambiguous"


def test_a_record_the_current_door_could_have_written_is_not_marked_legacy() -> None:
    """The other boundary: the marker must not fire on every record."""

    payload = workspace_intent_to_payload(_record("pkg/a.py", "tests/"))
    audit = cast("dict[str, Any]", payload["scope_audit"])
    assert audit["status"] == "current"
    assert "next_step" not in audit
    allowed = cast("list[dict[str, Any]]", audit["allowed_files"])
    assert [item["status"] for item in allowed] == ["current", "current"]
    assert [item["kind"] for item in allowed] == ["file", "tree"]


def test_the_marker_reaches_the_public_list_workspace_route(tmp_path: Path) -> None:
    """The structural edge, end to end, in this process.

    A live MCP server runs the main checkout's build, so it cannot witness this
    worktree's code; the service is driven in-process on purpose.
    """

    from codeclone.surfaces.mcp._workspace_intents import write_workspace_intent
    from codeclone.surfaces.mcp.service import CodeCloneMCPService

    write_workspace_intent(root=tmp_path, record=_record(_GLOB_ENTRY, status="active"))
    service = CodeCloneMCPService(history_limit=2)
    payload = service.manage_change_intent(
        action="list_workspace",
        root=str(tmp_path),
    )
    intents = cast("list[dict[str, Any]]", payload["workspace_intents"])
    assert len(intents) == 1
    audit = cast("dict[str, Any]", intents[0]["scope_audit"])
    assert audit["status"] == "legacy_ambiguous"
    allowed = cast("list[dict[str, Any]]", audit["allowed_files"])
    assert [item["raw"] for item in allowed] == [_GLOB_ENTRY]


# --------------------------------------------------------------------------
# Every branch of the refusal has an input that reaches it
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entry", "path", "expected", "reason"),
    [
        # A blank entry named nothing, so every reading excluded every path.
        ("   ", "pkg/a.py", "outside", "scope_entry_empty"),
        # An absolute or escaping entry has no metacharacter, so its literal
        # head is the whole string and no repository-relative path starts with
        # it. The negative is safe; the positive is still refused.
        ("/abs/pkg/a.py", "pkg/a.py", "outside", "scope_entry_absolute"),
        ("../escape.py", "pkg/a.py", "outside", "scope_entry_traversal"),
        ("../escape.py", "../escape.py", "legacy_ambiguous", "scope_entry_traversal"),
    ],
)
def test_every_refusal_reason_reaches_a_relation(
    entry: str,
    path: str,
    expected: str,
    reason: str,
) -> None:
    from codeclone.surfaces.mcp._workspace_intents import (
        audit_scope_relation,
        read_audit_scope_entry,
    )

    assert read_audit_scope_entry(entry).refusal_reason == reason
    assert audit_scope_relation((entry,), path).value == expected


def test_a_legacy_entry_never_yields_an_inside_verdict() -> None:
    """The positive half of the refusal, on both unreadable shapes.

    ``outside`` survives only because every pre-grammar reading agreed on it;
    ``inside`` never does, so no path spelled like the stored text buys one.
    """

    from codeclone.surfaces.mcp._workspace_intents import audit_scope_relation

    for entry in (_GLOB_ENTRY, "/abs/pkg/a.py", "../escape.py", "tests/fixtures/**"):
        for path in (entry, entry.rstrip("*"), _GLOB_INSIDE, "pkg/a.py"):
            assert audit_scope_relation((entry,), path).value != "inside"


def test_an_empty_scope_answers_outside() -> None:
    from codeclone.surfaces.mcp._workspace_intents import audit_scope_relation

    assert audit_scope_relation((), "pkg/a.py").value == "outside"


def test_a_scope_missing_a_field_is_read_as_an_empty_one() -> None:
    """A registry row need not carry ``allowed_related``; reading must not fail."""

    from codeclone.surfaces.mcp._workspace_intents import audit_scope_payload

    payload = audit_scope_payload({"allowed_files": ["pkg/a.py"]})
    assert payload["allowed_related"] == []
    assert payload["status"] == "current"
    assert audit_scope_payload({"allowed_files": "pkg/a.py"})["allowed_files"] == []
