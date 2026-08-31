# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Every ring-r4 consumer of ``allowed_files`` answers from the same grammar.

Measured before this wave: the predicate "is this path inside that intent's
scope?" was computed by five consumers in four different ways -- exact set
membership (the finish scope check), exact-or-``fnmatchcase`` (the patch
contract), exact-or-directory-prefix (workspace hygiene), and literal string
intersection (the intent conflict detector, and the controller-insights
contested verdict). The three deciding predicates disagreed on both a directory
entry and a glob entry, in opposite directions.

The agreement is asserted by computing all three answers over a case table and
requiring them equal -- not by restating an expected column per consumer, which
would stay green if two consumers drifted together.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeclone.contracts.scope_grammar import ScopeGrammarError
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._intent import (
    IntentRecord,
    IntentScope,
    IntentStatus,
    normalize_intent_scope,
)
from codeclone.surfaces.mcp._session_intent_mixin import _MCPSessionIntentMixin
from codeclone.surfaces.mcp._session_patch_contract_mixin import (
    _MCPSessionPatchContractMixin,
)
from codeclone.surfaces.mcp._workspace_hygiene import paths_in_declared_scope
from codeclone.surfaces.mcp._workspace_intents import WorkspaceIntentRecord


def _scope_check_honours(scope: IntentScope, changed: str) -> bool:
    """Consumer 1: the finish scope check (``_intent_check_result``)."""

    record = IntentRecord(
        intent_id="intent-scope-grammar",
        run_id="0" * 8,
        root=Path("/nonexistent"),
        report_digest="0" * 64,
        status=IntentStatus.ACTIVE,
        declared_at_utc="2026-01-01T00:00:00Z",
        scope=scope,
        intent_description="scope grammar probe",
        expected_effects=(),
        guards=(),
    )
    result = _MCPSessionIntentMixin._intent_check_result(
        cast(Any, None),
        intent=record,
        actual=(changed,),
    )
    return result.status is not IntentStatus.VIOLATED


def _patch_contract_in_scope(scope: IntentScope, changed: str) -> bool:
    """Consumer 2: the patch contract's regression attribution."""

    return _MCPSessionPatchContractMixin._path_in_scope(
        cast(Any, None),
        path=changed,
        scope=scope,
    )


def _hygiene_in_scope(scope: IntentScope, changed: str) -> bool:
    """Consumer 3: workspace hygiene's declared-scope filter."""

    return bool(
        paths_in_declared_scope(
            [changed],
            allowed_files=list(scope.allowed_files),
            allowed_related=list(scope.allowed_related),
        )
    )


_DECIDERS = (
    ("scope_check", _scope_check_honours),
    ("patch_contract", _patch_contract_in_scope),
    ("hygiene", _hygiene_in_scope),
)

#: ``(declared entry, changed path, the one true answer)``.
_CASES = (
    ("src/foo.py", "src/foo.py", True),
    ("src/foo.py", "src/bar.py", False),
    ("tests/", "tests/test_api.py", True),
    ("tests/", "tests/unit/test_api.py", True),
    ("tests/", "testsuite/test_api.py", False),
    ("tests/", "src/mod.py", False),
)


@pytest.mark.parametrize(("declared", "changed", "expected"), _CASES)
def test_every_decider_gives_the_same_answer(
    declared: str,
    changed: str,
    expected: bool,
) -> None:
    scope = normalize_intent_scope({"allowed_files": [declared]})
    answers = {name: decide(scope, changed) for name, decide in _DECIDERS}
    assert set(answers.values()) == {expected}, (
        f"deciders disagree on {declared!r} vs {changed!r}: {answers}"
    )


def test_a_stored_legacy_glob_is_read_literally_by_every_decider() -> None:
    """A glob the door no longer accepts may still sit in an older record.

    ``fnmatchcase`` in the patch contract made that entry cover a whole subtree
    for one consumer and nothing for the other two. Reading it literally is the
    conservative answer and, more importantly, the same answer everywhere.
    """

    scope = IntentScope(allowed_files=("src/**/*.py",))
    answers = {name: decide(scope, "src/pkg/mod.py") for name, decide in _DECIDERS}
    assert set(answers.values()) == {False}, answers


# --------------------------------------------------------------------------
# Consumer 4: the intent conflict detector
# --------------------------------------------------------------------------


def _foreign_record(
    *allowed_files: str,
    status: str = "active",
) -> WorkspaceIntentRecord:
    """A live foreign intent: the only kind the conflict detector considers.

    ``agent_pid`` is this process and ``agent_start_epoch`` is not, which is
    what makes the record foreign and its owner demonstrably alive. A dead pid
    classifies as ``recoverable`` and is skipped, so the probe would pass over
    an empty scan and prove nothing about overlap.

    The epoch is sampled rather than written as a literal: liveness compares it
    against the live process's real start time, so a 1970 literal would describe
    a recycled pid and be skipped for exactly the reason above.
    """

    declared_at = workspace_intents.utc_now()
    scope_payload: dict[str, object] = {
        "allowed_files": list(allowed_files),
        "allowed_related": [],
        "forbidden": [],
    }
    return WorkspaceIntentRecord(
        intent_id="intent-foreign-scope-grammar",
        agent_pid=os.getpid(),
        agent_start_epoch=int(time.time()),
        agent_label="agent-a",
        run_id="abcdef1234567890",
        declared_at_utc=workspace_intents.format_utc(declared_at),
        expires_at_utc=workspace_intents.format_utc(declared_at + timedelta(hours=1)),
        ttl_seconds=3600,
        status=status,
        intent="edit tests",
        scope=scope_payload,
        scope_digest=workspace_intents.compute_scope_digest(scope_payload),
        blast_radius_summary={"radius_level": "medium"},
        lease_renewed_at_utc=workspace_intents.format_utc(declared_at),
        lease_seconds=workspace_intents.DEFAULT_LEASE_SECONDS,
        report_digest="digest-a",
    )


def _relations(new_allowed: list[str], foreign_allowed: list[str]) -> list[str]:
    relations = workspace_intents.detect_workspace_relations(
        new_scope={
            "allowed_files": new_allowed,
            "allowed_related": [],
            "forbidden": [],
        },
        existing=(_foreign_record(*foreign_allowed),),
        own_pid=os.getpid(),
        own_start_epoch=200,
    )
    return [str(relation["relation"]) for relation in relations]


def test_a_directory_scope_conflicts_with_a_file_inside_it() -> None:
    """Agent A declaring ``tests/`` and agent B declaring ``tests/test_api.py``.

    Two textual forms of one allowed scope normalise to one IR before they are
    compared, so this is an overlap however each side spelled it.
    """

    assert _relations(["tests/"], ["tests/test_api.py"]) == ["edit_overlap"]
    assert _relations(["tests/test_api.py"], ["tests/"]) == ["edit_overlap"]
    assert _relations(["tests/unit/"], ["tests/"]) == ["edit_overlap"]


def test_disjoint_scopes_still_do_not_conflict() -> None:
    assert _relations(["tests/"], ["src/mod.py"]) == []
    assert _relations(["tests/"], ["testsuite/"]) == []


# --------------------------------------------------------------------------
# The input door
# --------------------------------------------------------------------------


def test_a_declared_directory_stops_being_untouched_once_a_file_inside_changes() -> (
    None
):
    """``untouched_in_declared`` compares entries to changed files, not text.

    A directory entry never equals a changed path, so a set difference over
    the declared text reported every prefix entry as untouched forever.
    """

    scope = normalize_intent_scope({"allowed_files": ["tests/", "src/foo.py"]})
    record = IntentRecord(
        intent_id="intent-scope-grammar",
        run_id="0" * 8,
        root=Path("/nonexistent"),
        report_digest="0" * 64,
        status=IntentStatus.ACTIVE,
        declared_at_utc="2026-01-01T00:00:00Z",
        scope=scope,
        intent_description="scope grammar probe",
        expected_effects=(),
        guards=(),
    )
    result = _MCPSessionIntentMixin._intent_check_result(
        cast(Any, None),
        intent=record,
        actual=("tests/unit/test_api.py",),
    )
    assert result.status is IntentStatus.CLEAN
    assert result.untouched_in_declared == ("src/foo.py",)


# --------------------------------------------------------------------------
# Consumer 6: the queued-intent advisory, found by sweep, same defect class
# --------------------------------------------------------------------------


def _queued_context(new_allowed: list[str], queued_allowed: list[str]) -> list[str]:
    session = cast(Any, SimpleNamespace(_agent_pid=1, _agent_start_epoch=1))
    context = _MCPSessionIntentMixin._queued_context_from_workspace(
        session,
        scope=normalize_intent_scope({"allowed_files": new_allowed}),
        workspace_existing=(_foreign_record(*queued_allowed, status="queued"),),
    )
    return [str(item["intent_id"]) for item in context]


def test_a_queued_intent_overlapping_by_directory_is_still_reported() -> None:
    """The queue advisory answers the same question as the conflict detector.

    Not in the measured set of five, found by sweeping every ``allowed_files``
    reader: it intersected declared text literally, so a caller declaring
    ``tests/`` was told nothing was waiting on ``tests/test_api.py``.
    """

    assert _queued_context(["tests/"], ["tests/test_api.py"]) == [
        "intent-foreign-scope-grammar"
    ]
    assert _queued_context(["tests/test_api.py"], ["tests/"]) == [
        "intent-foreign-scope-grammar"
    ]


def test_a_queued_intent_on_a_disjoint_scope_is_not_reported() -> None:
    assert _queued_context(["tests/"], ["src/mod.py"]) == []


def test_the_door_refuses_a_glob_with_an_executable_next_step() -> None:
    with pytest.raises(ValueError) as excinfo:
        normalize_intent_scope({"allowed_files": ["codeclone/**/*.py"]})
    message = str(excinfo.value)
    assert "codeclone/**/*.py" in message
    assert "glob" in message
    assert "directory prefix" in message


def test_the_door_refuses_a_glob_in_allowed_related_too() -> None:
    with pytest.raises(ScopeGrammarError):
        normalize_intent_scope(
            {"allowed_files": ["pkg/a.py"], "allowed_related": ["tests/*.py"]}
        )


def test_the_door_keeps_the_directory_form_it_accepts() -> None:
    scope = normalize_intent_scope({"allowed_files": ["tests/", "src/foo.py"]})
    assert scope.allowed_files == ("src/foo.py", "tests/")


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [("./docs/**", "docs/**"), (".", ""), ("docs/", "docs")],
)
def test_a_forbidden_pattern_keeps_the_old_path_normalisation(
    pattern: str,
    expected: str,
) -> None:
    scope = normalize_intent_scope(
        {"allowed_files": ["pkg/a.py"], "forbidden": [pattern]}
    )
    assert expected in scope.forbidden


@pytest.mark.parametrize(
    ("pattern", "match"),
    [("/abs/docs", "relative"), ("../escape", "traversal")],
)
def test_a_forbidden_pattern_is_still_refused_outside_the_repository(
    pattern: str,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        normalize_intent_scope({"allowed_files": ["pkg/a.py"], "forbidden": [pattern]})


def test_forbidden_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="list of relative paths"):
        normalize_intent_scope({"allowed_files": ["pkg/a.py"], "forbidden": "docs/**"})


def test_forbidden_patterns_are_still_a_glob_deny_list() -> None:
    """``forbidden`` is a different field with different semantics.

    The ruling governs ``allowed_files``: a write boundary. ``forbidden`` is a
    deny list matched with ``fnmatchcase`` and keeps its glob spelling, which
    is what the default ``.codeclone/**`` guard is written in.
    """

    scope = normalize_intent_scope(
        {"allowed_files": ["pkg/a.py"], "forbidden": ["docs/**"]}
    )
    assert "docs/**" in scope.forbidden
    assert ".codeclone/**" in scope.forbidden
