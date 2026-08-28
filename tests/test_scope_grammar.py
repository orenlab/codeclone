# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""The ``allowed_files`` grammar owner, and the one r2p consumer that asks it.

``allowed_files`` is an authority boundary, not a search language. The ratified
grammar is exactly two forms -- an exact file and a directory prefix -- with one
typed IR, one membership predicate and one overlap predicate, so that every
consumer answers "is this path in that scope?" identically.

This module deliberately imports only ring r0 (the grammar) and ring r2p
(``controller_insights``). The four ring-r4 consumers are pinned in
``test_scope_grammar_consumers.py``: a test module's ring is the highest ring it
imports, and an r4 module reaching ``controller_insights`` would be a new
boundary violation the architecture ratchet refuses to absorb.
"""

from __future__ import annotations

import pytest

from codeclone.contracts.scope_grammar import (
    SCOPE_ENTRY_ABSOLUTE,
    SCOPE_ENTRY_EMPTY,
    SCOPE_ENTRY_GLOB_FORBIDDEN,
    SCOPE_ENTRY_TRAVERSAL,
    AllowedScopeEntry,
    DirectoryTree,
    ExactFile,
    ScopeGrammarError,
    entries_overlap,
    entry_contains_path,
    overlapping_entries,
    parse_scope_entry,
    read_scope_entry,
    render_scope_entry,
    scope_contains_path,
)
from codeclone.controller_insights.session_stats import (
    AgentSnapshot,
    IntentSnapshot,
    _has_scope_overlap,
)


def _intent(*allowed_files: str) -> IntentSnapshot:
    return IntentSnapshot(
        intent_id="intent-a",
        status="active",
        ownership="foreign_active",
        scope_file_count=len(allowed_files),
        allowed_files=allowed_files,
        declared_at_utc="2026-01-01T00:00:00Z",
        lease_remaining_seconds=60,
    )


def _agent(pid: int, *allowed_files: str) -> AgentSnapshot:
    return AgentSnapshot(
        pid=pid,
        start_epoch=100,
        label=f"agent-{pid}",
        alive=True,
        intents=(_intent(*allowed_files),),
    )


# --------------------------------------------------------------------------
# The grammar: two forms, and nothing else
# --------------------------------------------------------------------------


def test_an_exact_file_parses_to_exact_file() -> None:
    assert parse_scope_entry("src/foo.py") == ExactFile("src/foo.py")


def test_a_trailing_slash_parses_to_a_directory_tree() -> None:
    assert parse_scope_entry("tests/") == DirectoryTree("tests")


def test_a_leading_dot_slash_is_normalised_away() -> None:
    assert parse_scope_entry("./pkg/a.py") == ExactFile("pkg/a.py")
    assert parse_scope_entry("./pkg/") == DirectoryTree("pkg")


@pytest.mark.parametrize(
    "entry",
    ["src/**/*.py", "foo?.py", "src/*", "pkg/[ab].py", "docs/**"],
)
def test_every_glob_form_is_refused_with_a_typed_reason(entry: str) -> None:
    with pytest.raises(ScopeGrammarError) as excinfo:
        parse_scope_entry(entry)
    assert excinfo.value.reason == SCOPE_ENTRY_GLOB_FORBIDDEN
    assert excinfo.value.entry == entry
    assert excinfo.value.next_step


def test_a_directory_prefix_is_a_primitive_not_shorthand_for_a_glob() -> None:
    """``dir/**`` is not a second spelling of ``dir/``.

    The boundary the ruling draws: a directory prefix is a scope primitive. If
    ``dir/**`` were accepted as a synonym for ``DirectoryTree("dir")`` the
    grammar would be half a shell glob again, and a consumer would eventually
    apply glob semantics to it.
    """

    assert parse_scope_entry("tests/") == DirectoryTree("tests")
    with pytest.raises(ScopeGrammarError) as excinfo:
        parse_scope_entry("tests/**")
    assert excinfo.value.reason == SCOPE_ENTRY_GLOB_FORBIDDEN


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        ("/abs/path.py", SCOPE_ENTRY_ABSOLUTE),
        ("../escape.py", SCOPE_ENTRY_TRAVERSAL),
        ("pkg/../../escape.py", SCOPE_ENTRY_TRAVERSAL),
        (".", SCOPE_ENTRY_EMPTY),
        ("", SCOPE_ENTRY_EMPTY),
        ("   ", SCOPE_ENTRY_EMPTY),
    ],
)
def test_non_glob_refusals_carry_their_own_reason(entry: str, reason: str) -> None:
    with pytest.raises(ScopeGrammarError) as excinfo:
        parse_scope_entry(entry)
    assert excinfo.value.reason == reason


def test_the_two_forms_are_never_equal_even_on_the_same_text() -> None:
    """``ExactFile("tests")`` and ``DirectoryTree("tests")`` are different scopes.

    Both carry one path string. Without a discriminator they would compare
    equal, and any consumer that reached for ``set(a) & set(b)`` would silently
    resurrect the literal string comparison this grammar exists to delete.
    """

    file_entry: AllowedScopeEntry = ExactFile("tests")
    tree_entry: AllowedScopeEntry = DirectoryTree("tests")
    assert file_entry != tree_entry
    assert {file_entry} & {tree_entry} == set()


def test_the_canonical_text_round_trips_through_the_parser() -> None:
    for entry in (ExactFile("src/foo.py"), DirectoryTree("tests")):
        assert parse_scope_entry(render_scope_entry(entry)) == entry
    assert render_scope_entry(DirectoryTree("tests")) == "tests/"
    assert render_scope_entry(ExactFile("src/foo.py")) == "src/foo.py"


# --------------------------------------------------------------------------
# Membership: one predicate, literal prefixes
# --------------------------------------------------------------------------


def test_exact_file_membership_accepts_its_own_path() -> None:
    assert entry_contains_path(ExactFile("src/foo.py"), "src/foo.py")


def test_exact_file_membership_rejects_anything_else() -> None:
    """An exact file never covers children, however directory-shaped it looks."""

    assert not entry_contains_path(ExactFile("src/foo.py"), "src/foo.pyi")
    assert not entry_contains_path(ExactFile("src"), "src/foo.py")


def test_directory_tree_membership_accepts_everything_under_the_prefix() -> None:
    assert entry_contains_path(DirectoryTree("tests"), "tests/test_api.py")
    assert entry_contains_path(DirectoryTree("tests"), "tests/unit/test_api.py")
    assert entry_contains_path(DirectoryTree("tests"), "tests")


def test_directory_tree_membership_stops_at_the_path_boundary() -> None:
    """``tests`` is not a prefix of ``testsuite``: the separator is required."""

    assert not entry_contains_path(DirectoryTree("tests"), "testsuite/test_api.py")
    assert not entry_contains_path(DirectoryTree("tests"), "src/tests/test_api.py")


def test_a_directory_prefix_matches_literally_not_as_a_pattern() -> None:
    """A prefix is text, so glob metacharacters in a real directory name are text.

    Implementing the prefix as ``fnmatch(path, prefix + "/**")`` reads ``[ab]``
    as a character class and drops the very files the scope names.
    """

    assert entry_contains_path(DirectoryTree("pkg/[ab]"), "pkg/[ab]/mod.py")
    assert not entry_contains_path(DirectoryTree("pkg/[ab]"), "pkg/a/mod.py")


def test_scope_membership_is_any_entry() -> None:
    entries = (ExactFile("src/foo.py"), DirectoryTree("tests"))
    assert scope_contains_path(entries, "src/foo.py")
    assert scope_contains_path(entries, "tests/unit/test_api.py")
    assert not scope_contains_path(entries, "src/bar.py")


# --------------------------------------------------------------------------
# Overlap: the three ratified rules
# --------------------------------------------------------------------------


# Each rule is pinned by two tests, one per direction of error. A single test
# holding both halves would let an over-permissive and an over-restrictive
# mutation red the same name, which proves only that something moved.


def test_file_by_file_overlap_accepts_the_same_file() -> None:
    assert entries_overlap(ExactFile("a.py"), ExactFile("a.py"))


def test_file_by_file_overlap_rejects_different_files() -> None:
    assert not entries_overlap(ExactFile("a.py"), ExactFile("b.py"))


def test_tree_by_file_overlap_accepts_a_file_inside_in_either_order() -> None:
    tree = DirectoryTree("tests")
    inside = ExactFile("tests/test_api.py")
    assert entries_overlap(tree, inside)
    assert entries_overlap(inside, tree)


def test_tree_by_file_overlap_rejects_a_file_outside_in_either_order() -> None:
    tree = DirectoryTree("tests")
    outside = ExactFile("src/test_api.py")
    assert not entries_overlap(tree, outside)
    assert not entries_overlap(outside, tree)


def test_tree_by_tree_overlap_accepts_containment_in_either_order() -> None:
    assert entries_overlap(DirectoryTree("tests"), DirectoryTree("tests/unit"))
    assert entries_overlap(DirectoryTree("tests/unit"), DirectoryTree("tests"))
    assert entries_overlap(DirectoryTree("tests"), DirectoryTree("tests"))


def test_tree_by_tree_overlap_rejects_disjoint_trees() -> None:
    assert not entries_overlap(DirectoryTree("tests"), DirectoryTree("src"))
    assert not entries_overlap(DirectoryTree("tests"), DirectoryTree("testsuite"))


def test_overlapping_entries_reports_the_callers_own_entries() -> None:
    assert overlapping_entries(("tests/",), ("tests/test_api.py",)) == ("tests/",)
    assert overlapping_entries(("tests/test_api.py",), ("tests/",)) == (
        "tests/test_api.py",
    )
    assert overlapping_entries(("src/a.py",), ("tests/",)) == ()


# --------------------------------------------------------------------------
# Stored records: the reader is total, and never raises on a legacy form
# --------------------------------------------------------------------------


def test_a_stored_legacy_glob_reads_as_an_exact_file_and_never_raises() -> None:
    """Registry records written before this grammar may hold a glob.

    Reading such a record must not fail: the refusal belongs at the input door.
    The conservative reading is the literal one -- the entry covers exactly the
    path it spells, which is what the finish scope check always did with it.
    """

    entry = read_scope_entry("src/**/*.py")
    assert entry == ExactFile("src/**/*.py")
    assert not entry_contains_path(entry, "src/pkg/mod.py")
    assert entry_contains_path(entry, "src/**/*.py")


def test_the_reader_still_understands_both_ratified_forms() -> None:
    assert read_scope_entry("tests/") == DirectoryTree("tests")
    assert read_scope_entry("src/foo.py") == ExactFile("src/foo.py")


# --------------------------------------------------------------------------
# Consumer 5 (ring r2p): the contested verdict
# --------------------------------------------------------------------------


def test_contested_sees_a_directory_scope_covering_a_foreign_file() -> None:
    """Agent A holding ``tests/`` and agent B holding ``tests/test_api.py`` collide.

    Literal string intersection reports no overlap here, so two agents editing
    the same file were reported as an uncontested workspace.
    """

    assert _has_scope_overlap([_agent(1, "tests/"), _agent(2, "tests/test_api.py")])


def test_contested_still_separates_genuinely_disjoint_scopes() -> None:
    assert not _has_scope_overlap([_agent(1, "tests/"), _agent(2, "src/mod.py")])
    assert not _has_scope_overlap([_agent(1, "tests/"), _agent(2, "testsuite/")])
