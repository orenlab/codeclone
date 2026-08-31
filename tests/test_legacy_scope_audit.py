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

import ast
import os
import time
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
        # Sampled, not a literal: a 1970 epoch on this live pid describes an
        # agent the kernel already reaped, and reads as recoverable.
        agent_start_epoch=int(time.time()),
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


# --------------------------------------------------------------------------
# The owner moved to ring r0. These pins prove the edge, not the spelling.
# --------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OWNER_PATH = _REPO_ROOT / "codeclone" / "contracts" / "legacy_scope.py"
_RECORD_PATH = _REPO_ROOT / "codeclone" / "workspace_intent" / "contract.py"
_SURFACE_PATH = _REPO_ROOT / "codeclone" / "surfaces" / "mcp" / "_workspace_intents.py"

#: The vocabulary whose owner the ruling moved. Named here, resolved by AST.
_OWNED_NAMES = frozenset(
    {
        "CURRENT_GRAMMAR",
        "HISTORICAL_PRODUCER_SPECIFIC",
        "HISTORICAL_UNAMBIGUOUS",
        "LEGACY_AMBIGUOUS",
        "SCOPE_INTERPRETER_FIELD",
        "AuditScopeEntry",
        "LegacyScope",
        "ScopeGeneration",
        "ScopeInterpretation",
        "ScopeRelation",
        "audit_scope_payload",
        "audit_scope_relation",
        "read_audit_scope",
        "read_audit_scope_entry",
        "read_stored_scope_entry",
        "scope_interpreter_from_record",
    }
)


def _module_tree(path: Path) -> ast.Module:
    """Parse a module's source; an import would measure runtime, not authority."""

    return ast.parse(path.read_text("utf-8"))


def _imported_names(tree: ast.Module) -> dict[str, str]:
    """Where each module-level name comes from, as ``name -> source module``.

    Both spellings of the same edge are read, because the pin has to survive a
    legitimate rewrite: ``from X import n`` and ``n = x.n`` after ``import X as
    x`` bind the same authority, and a pin that only accepts one of them dies
    on a rename instead of on a severed edge.
    """

    module_aliases: dict[str, str] = {}
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                bindings[alias.asname or alias.name] = module
                module_aliases[alias.asname or alias.name] = f"{module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module_aliases[alias.asname or alias.name] = alias.name
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in module_aliases
        ):
            bindings[node.targets[0].id] = module_aliases[node.value.value.id]
    return bindings


def _assigned_or_defined_names(tree: ast.Module) -> set[str]:
    """Every name a module itself binds at module level by definition."""

    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_the_interpretation_owner_is_the_ring_zero_contract_module() -> None:
    """The ruling's edge: r4 asks r0, and r2p no longer answers.

    A behavioural pin cannot see this. Re-implementing the reader inside
    ``workspace_intent/contract.py`` is byte-identical at runtime, and the
    two-ring consumer set (r2p and r4, sharing only r0 and r1) is exactly the
    argument that placed the ``allowed_files`` grammar in ``contracts``.
    """

    assert _OWNER_PATH.exists(), (
        f"the interpretation owner must live at {_OWNER_PATH.relative_to(_REPO_ROOT)}"
    )
    surface_imports = _imported_names(_module_tree(_SURFACE_PATH))
    for name in sorted(_OWNED_NAMES):
        assert surface_imports.get(name, "").endswith("contracts.legacy_scope"), (
            f"{name} must reach the surface from the r0 owner, not from "
            f"{surface_imports.get(name)!r}"
        )
    record_tree = _module_tree(_RECORD_PATH)
    restated = _OWNED_NAMES & (
        _assigned_or_defined_names(record_tree) | set(_imported_names(record_tree))
    )
    assert restated == set(), (
        f"the record contract must not own or restate the reading: {sorted(restated)}"
    )


def test_the_legacy_relation_cannot_return_inside_by_construction() -> None:
    """The invariant, structurally: no ``INSIDE`` exists in the legacy branch.

    ``test_a_legacy_entry_never_yields_an_inside_verdict`` proves it for the
    inputs it lists. This proves it for every input there could ever be.
    """

    from codeclone.contracts import legacy_scope

    tree = _module_tree(_OWNER_PATH)
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == legacy_scope.LEGACY_RELATION_FUNCTION
    ]
    assert len(functions) == 1, (
        f"exactly one {legacy_scope.LEGACY_RELATION_FUNCTION} must own the "
        "relation of an unreadable entry"
    )
    mentions = {
        node.attr for node in ast.walk(functions[0]) if isinstance(node, ast.Attribute)
    } | {
        node.value
        for node in ast.walk(functions[0])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "INSIDE" not in mentions and "inside" not in mentions


# --------------------------------------------------------------------------
# The third form: LegacyScope(raw, generation, interpretation)
# --------------------------------------------------------------------------


def test_the_contract_expresses_a_third_stored_scope_form() -> None:
    from codeclone.contracts.legacy_scope import (
        LegacyScope,
        read_stored_scope_entry,
    )
    from codeclone.contracts.scope_grammar import DirectoryTree, ExactFile

    assert isinstance(read_stored_scope_entry("pkg/a.py"), ExactFile)
    assert isinstance(read_stored_scope_entry("tests/"), DirectoryTree)
    legacy = read_stored_scope_entry(_GLOB_ENTRY)
    assert isinstance(legacy, LegacyScope)
    assert (legacy.raw, legacy.generation.value, legacy.interpretation.value) == (
        _GLOB_ENTRY,
        "pre_grammar",
        "ambiguous",
    )


def test_the_write_authority_union_still_admits_only_two_forms() -> None:
    """The third form is a reading, never a way to authorise a write."""

    import typing

    from codeclone.contracts import scope_grammar
    from codeclone.contracts.legacy_scope import LegacyScope

    admitted = set(typing.get_args(scope_grammar.AllowedScopeEntry))
    assert LegacyScope not in admitted
    assert admitted == {scope_grammar.ExactFile, scope_grammar.DirectoryTree}
    with pytest.raises(scope_grammar.ScopeGrammarError):
        scope_grammar.parse_scope_entry(_GLOB_ENTRY)


# --------------------------------------------------------------------------
# generation: derived from the two frozen doors, never from the record
# --------------------------------------------------------------------------


def _frozen_pre_grammar_normalise(value: str) -> str:
    """The pre-grammar declaration door, verbatim from its frozen source.

    ``a7385bfc^:codeclone/surfaces/mcp/_intent.py::_normalize_path``. Copied
    here so the owner's rule is checked against the door it claims to model,
    not against a table restating the owner's own answers.
    """

    text = str(value).replace("\\", "/").strip()
    if text == ".":
        return ""
    if text.startswith("./"):
        text = text[2:]
    text = text.rstrip("/")
    if Path(text).is_absolute():
        raise ValueError(text)
    if ".." in Path(text).parts:
        raise ValueError(text)
    return text


def _pre_grammar_door_emits(raw: str) -> bool:
    """Whether some declared input reaches the registry spelled exactly ``raw``."""

    if raw == "":
        # The door mapped "." to "", and "." survives the truthiness filter.
        return _frozen_pre_grammar_normalise(".") == ""
    try:
        return _frozen_pre_grammar_normalise(raw) == raw and bool(raw.strip())
    except ValueError:
        return False


_STORED_TEXT_CORPUS = (
    _GLOB_ENTRY,
    "tests/fixtures/**",
    "tests/test_*.py",
    "foo?.py",
    "pkg/[a-b].py",
    "",
    "   ",
    ".",
    "./pkg/b.py",
    "/abs/pkg/a.py",
    "../escape.py",
    "pkg/../escape.py",
    "pkg/a.py",
    "tests/",
)


def test_generation_re_derives_both_doors_instead_of_restating_a_table() -> None:
    """``generation`` answers which door could have written the stored text.

    The current half is re-derived from the live grammar (the entry must be one
    today's door refuses); the pre-grammar half is re-derived from that door's
    frozen source. A rule keyed off ``refusal_reason`` alone cannot pass: ``""``
    and ``"   "`` share ``scope_entry_empty`` and differ here.
    """

    from codeclone.contracts.legacy_scope import (
        LegacyScope,
        ScopeGeneration,
        read_stored_scope_entry,
    )
    from codeclone.contracts.scope_grammar import (
        ScopeGrammarError,
        parse_scope_entry,
    )

    measured: dict[str, str] = {}
    for raw in _STORED_TEXT_CORPUS:
        entry = read_stored_scope_entry(raw)
        if not isinstance(entry, LegacyScope):
            # Readable today: the current door accepts it, so no legacy form.
            parse_scope_entry(raw)
            continue
        with pytest.raises(ScopeGrammarError):
            parse_scope_entry(raw)
        expected = (
            ScopeGeneration.PRE_GRAMMAR
            if _pre_grammar_door_emits(raw)
            else ScopeGeneration.NO_DECLARATION_DOOR
        )
        assert entry.generation is expected, raw
        measured[raw] = entry.generation.value
    # Both members reached, or the rule is a constant wearing an enum.
    assert set(measured.values()) == {"pre_grammar", "no_declaration_door"}
    assert measured[""] == "pre_grammar"
    assert measured["   "] == "no_declaration_door"


def test_generation_decides_how_wide_the_refusal_reaches() -> None:
    """The two generations are two envelopes, not two labels.

    An entry the pre-grammar door emitted was read by the pre-grammar
    consumers, so the audit must refuse anywhere any of their readings could
    have reached -- the literal head. An entry no door emitted was never read
    by any of them, so the only reading it ever had is its own text.
    """

    from codeclone.surfaces.mcp._workspace_intents import audit_scope_relation

    # pre-grammar: the whole subtree under the literal head stays refused.
    assert audit_scope_relation((_GLOB_ENTRY,), _GLOB_INSIDE).value == (
        "legacy_ambiguous"
    )
    # no declaration door: a path that merely starts with the text is outside.
    assert audit_scope_relation(("/abs/pkg/a.py",), "/abs/pkg/a.py.bak").value == (
        "outside"
    )
    assert audit_scope_relation(("../escape.py",), "../escape.py/x").value == "outside"
    assert audit_scope_relation(("../escape.py",), "../escape.py").value == (
        "legacy_ambiguous"
    )


# --------------------------------------------------------------------------
# interpretation: three values, each reachable, each changing an outcome
# --------------------------------------------------------------------------


def test_an_entry_that_named_nothing_answers_outside_everywhere() -> None:
    """``known`` is the settled reading: it covered nothing, so nothing is in.

    ``""`` is what the pre-grammar door wrote when an agent declared ``"."``.
    Its literal head is empty, so the generation envelope alone would refuse
    every path in the repository; only the settled reading answers.
    """

    from codeclone.surfaces.mcp._workspace_intents import (
        audit_scope_relation,
        read_audit_scope_entry,
    )

    assert read_audit_scope_entry("").interpretation.value == "known"
    for path in ("pkg/a.py", "tests/test_api.py", _GLOB_INSIDE):
        assert audit_scope_relation(("",), path).value == "outside"


def test_a_recorded_producer_moves_the_entry_off_ambiguous() -> None:
    """``producer_specific`` needs a record that names who read it."""

    from codeclone.surfaces.mcp._workspace_intents import read_audit_scope_entry

    assert read_audit_scope_entry(_GLOB_ENTRY).interpretation.value == "ambiguous"
    named = read_audit_scope_entry(_GLOB_ENTRY, interpreter="patch_contract")
    assert named.interpretation.value == "producer_specific"
    assert named.interpreter == "patch_contract"
    assert "patch_contract" in str(named.next_step)


def test_a_readable_entry_keeps_its_settled_reading() -> None:
    """The exact file is the one live form all three predicates read alike."""

    from codeclone.surfaces.mcp._workspace_intents import read_audit_scope

    file_entry, tree_entry = read_audit_scope(("pkg/a.py", "tests/"))
    assert file_entry.interpretation.value == "known"
    assert tree_entry.interpretation.value == "ambiguous"
    assert file_entry.generation is None
    (named,) = read_audit_scope(("pkg/a.py",), interpreter="hygiene")
    # A named producer never demotes a reading every producer agreed on.
    assert named.interpretation.value == "known"


def test_the_interpretation_reaches_the_payload_a_consumer_reads() -> None:
    from codeclone.surfaces.mcp._workspace_intents import audit_scope_payload

    scope = {"allowed_files": [_GLOB_ENTRY, "pkg/a.py"]}
    anonymous = audit_scope_payload(scope)
    named = audit_scope_payload(scope, interpreter="patch_contract")
    entries = cast("list[dict[str, Any]]", anonymous["allowed_files"])
    assert [item["interpretation"] for item in entries] == ["ambiguous", "known"]
    assert [item["generation"] for item in entries] == ["pre_grammar", None]
    named_entries = cast("list[dict[str, Any]]", named["allowed_files"])
    assert named_entries[0]["interpretation"] == "producer_specific"
    assert anonymous["next_step"] != named["next_step"]


def test_the_record_level_interpretation_is_derived_from_its_entries() -> None:
    """Not a literal: the weakest reading among the legacy entries decides."""

    from codeclone.surfaces.mcp._workspace_intents import audit_scope_payload

    assert (
        audit_scope_payload({"allowed_files": [_GLOB_ENTRY]})["interpretation"]
        == "ambiguous"
    )
    assert (
        audit_scope_payload(
            {"allowed_files": [_GLOB_ENTRY]},
            interpreter="patch_contract",
        )["interpretation"]
        == "producer_specific"
    )
    assert audit_scope_payload({"allowed_files": [""]})["interpretation"] == "known"
