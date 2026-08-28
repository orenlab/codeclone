# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one owner of the ``allowed_files`` scope grammar.

``allowed_files`` is a **write-authority boundary**, not a search language. Its
grammar is therefore deliberately small: an entry is either an exact file or a
directory prefix, and nothing else.

.. code-block:: text

    "src/foo.py"    -> ExactFile("src/foo.py")
    "tests/"        -> DirectoryTree("tests")
    "src/**/*.py"   -> refused
    "foo?.py"       -> refused

A directory prefix is a **scope primitive, not shorthand for the glob**
``dir/**``. Accepting the glob spelling as a synonym is how glob semantics
would come back to one consumer at a time; ``entries_overlap`` and
``entry_contains_path`` treat a prefix as literal text, so a directory whose
real name contains ``[`` is matched, not interpreted.

Why not glob: authorising a write and detecting a conflict both need the
overlap of two entries, and the overlap of two glob expressions is a different
language -- one that five independent implementations would each approximate
differently. That is the state this module replaces: the predicate "is this
path inside that intent's scope?" was computed by five consumers in four ways,
and the three deciding ones disagreed on a directory entry and on a glob entry
in opposite directions.

Ring r0 on purpose. ``workspace_intent`` and ``controller_insights`` are r2p,
the MCP surface is r4, and those two rings share only r0 and r1 -- so a shared
answer has to live here or be restated, which is exactly the defect. This
follows the precedent set when the run-identity tier moved into ``contracts``
for the same reason.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum
from pathlib import Path
from typing import Final, NamedTuple, TypeAlias

#: Machine-readable refusal reasons. Stable tokens: a caller may branch on them.
SCOPE_ENTRY_GLOB_FORBIDDEN: Final = "scope_entry_glob_forbidden"
SCOPE_ENTRY_ABSOLUTE: Final = "scope_entry_absolute"
SCOPE_ENTRY_TRAVERSAL: Final = "scope_entry_traversal"
SCOPE_ENTRY_EMPTY: Final = "scope_entry_empty"

#: Characters that make a string a pattern rather than a path.
_GLOB_METACHARACTERS: Final[frozenset[str]] = frozenset("*?[]")

_NEXT_STEP: Final[dict[str, str]] = {
    SCOPE_ENTRY_GLOB_FORBIDDEN: (
        'list the files explicitly (for example "pkg/mod.py"), or declare the '
        "directory prefix they live under, written with a trailing slash "
        '(for example "pkg/")'
    ),
    SCOPE_ENTRY_ABSOLUTE: (
        "declare the path relative to the repository root, without a leading slash"
    ),
    SCOPE_ENTRY_TRAVERSAL: (
        'declare the path relative to the repository root, without ".."'
    ),
    SCOPE_ENTRY_EMPTY: (
        'name a file (for example "pkg/mod.py") or a directory prefix written '
        'with a trailing slash (for example "pkg/"); the repository root is '
        "not a declarable scope"
    ),
}

_WHY: Final[dict[str, str]] = {
    SCOPE_ENTRY_GLOB_FORBIDDEN: (
        "glob patterns are not part of the allowed_files grammar; allowed_files "
        "is an authority boundary, not a search language"
    ),
    SCOPE_ENTRY_ABSOLUTE: "scope entries are repository-relative",
    SCOPE_ENTRY_TRAVERSAL: "scope entries may not escape the repository root",
    SCOPE_ENTRY_EMPTY: "a scope entry must name something",
}


class ScopeGrammarError(ValueError):
    """A textual scope entry that the ratified grammar does not accept.

    Carries the machine-readable ``reason`` and an executable ``next_step`` so
    that a refusal at the input door is a typed outcome an agent can act on,
    not prose it has to parse.

    A ``ValueError`` on purpose: the MCP declare path already converts
    ``ValueError`` into a service contract error, so the refusal reaches the
    caller through the established channel.
    """

    __slots__ = ("entry", "next_step", "reason")

    def __init__(self, *, entry: str, reason: str) -> None:
        next_step = _NEXT_STEP[reason]
        super().__init__(
            f"scope entry {entry!r} is not allowed: {_WHY[reason]} "
            f"(reason: {reason}). next_step: {next_step}."
        )
        self.entry = entry
        self.reason = reason
        self.next_step = next_step


class ScopeEntryKind(str, Enum):
    """The closed vocabulary of scope entry forms."""

    FILE = "file"
    TREE = "tree"


class ExactFile(NamedTuple):
    """One file, matched by equality."""

    path: str
    #: Discriminator. Both forms carry a single path string, so without it
    #: ``ExactFile("tests") == DirectoryTree("tests")`` under tuple equality,
    #: and any consumer reaching for ``set(a) & set(b)`` would silently
    #: resurrect the literal comparison this grammar exists to delete.
    kind: ScopeEntryKind = ScopeEntryKind.FILE


class DirectoryTree(NamedTuple):
    """Everything under one directory prefix, matched by path-boundary prefix."""

    prefix: str
    kind: ScopeEntryKind = ScopeEntryKind.TREE


AllowedScopeEntry: TypeAlias = ExactFile | DirectoryTree


def parse_scope_entry(text: str) -> AllowedScopeEntry:
    """Parse one declared scope entry, refusing everything outside the grammar.

    This is the input door's parser. Use :func:`read_scope_entry` for text that
    was already persisted.
    """

    raw = str(text).replace("\\", "/").strip()
    if any(char in _GLOB_METACHARACTERS for char in raw):
        raise ScopeGrammarError(entry=text, reason=SCOPE_ENTRY_GLOB_FORBIDDEN)
    if raw.startswith("/") or Path(raw).is_absolute():
        raise ScopeGrammarError(entry=text, reason=SCOPE_ENTRY_ABSOLUTE)
    segments = [segment for segment in raw.split("/") if segment not in ("", ".")]
    if ".." in segments:
        raise ScopeGrammarError(entry=text, reason=SCOPE_ENTRY_TRAVERSAL)
    if not segments:
        raise ScopeGrammarError(entry=text, reason=SCOPE_ENTRY_EMPTY)
    joined = "/".join(segments)
    if raw.endswith("/"):
        return DirectoryTree(joined)
    return ExactFile(joined)


def read_scope_entry(text: str) -> AllowedScopeEntry:
    """Read one entry from a persisted record, without ever refusing it.

    Registry records written before this grammar may hold a form the door now
    rejects. Reading such a record must not fail -- the refusal belongs at the
    door, and a stored intent that cannot be read is a coordination boundary
    that has silently disappeared. The conservative reading is the literal one:
    the entry covers exactly the text it spells, which is what the finish scope
    check has always done with it.
    """

    try:
        return parse_scope_entry(text)
    except ScopeGrammarError:
        return ExactFile(str(text).replace("\\", "/").strip())


def read_scope_entries(texts: Iterable[str]) -> tuple[AllowedScopeEntry, ...]:
    """Read a persisted scope, dropping blanks and preserving order-free identity."""

    return tuple(read_scope_entry(text) for text in texts if str(text).strip())


def render_scope_entry(entry: AllowedScopeEntry) -> str:
    """The canonical text of an entry. ``parse_scope_entry`` round-trips it."""

    if isinstance(entry, DirectoryTree):
        return f"{entry.prefix}/"
    return entry.path


def normalize_scope_entry_text(text: str) -> str:
    """Canonical text for a declared entry, or a typed refusal."""

    return render_scope_entry(parse_scope_entry(text))


def entry_contains_path(entry: AllowedScopeEntry, path: str) -> bool:
    """Whether ``path`` (repository-relative, POSIX) is inside ``entry``."""

    if isinstance(entry, DirectoryTree):
        return path == entry.prefix or path.startswith(f"{entry.prefix}/")
    return path == entry.path


def scope_contains_path(entries: Iterable[AllowedScopeEntry], path: str) -> bool:
    """Whether any entry of a scope contains ``path``."""

    return any(entry_contains_path(entry, path) for entry in entries)


def entries_overlap(left: AllowedScopeEntry, right: AllowedScopeEntry) -> bool:
    """Whether two entries can authorise a write to the same file.

    The three ratified rules, and only these:

    ``File(a) x File(b)``
        ``a == b``
    ``Tree(p) x File(f)``
        ``f`` is inside ``p``
    ``Tree(p) x Tree(q)``
        ``p`` contains ``q`` or ``q`` contains ``p``
    """

    if isinstance(left, DirectoryTree):
        if isinstance(right, DirectoryTree):
            return entry_contains_path(left, right.prefix) or entry_contains_path(
                right, left.prefix
            )
        return entry_contains_path(left, right.path)
    if isinstance(right, DirectoryTree):
        return entry_contains_path(right, left.path)
    return left.path == right.path


def overlapping_entries(
    left: Sequence[str],
    right: Sequence[str],
) -> tuple[str, ...]:
    """The canonical text of every ``left`` entry overlapping some ``right`` entry.

    Both sides are persisted text, so both are read with the total reader. The
    caller's own entries are reported because that is the side the caller can
    act on: two spellings of one scope normalise to one IR before they are
    compared, and only afterwards is anything named.
    """

    right_entries = read_scope_entries(right)
    return tuple(
        sorted(
            {
                render_scope_entry(entry)
                for entry in read_scope_entries(left)
                if any(entries_overlap(entry, other) for other in right_entries)
            }
        )
    )


__all__ = [
    "SCOPE_ENTRY_ABSOLUTE",
    "SCOPE_ENTRY_EMPTY",
    "SCOPE_ENTRY_GLOB_FORBIDDEN",
    "SCOPE_ENTRY_TRAVERSAL",
    "AllowedScopeEntry",
    "DirectoryTree",
    "ExactFile",
    "ScopeEntryKind",
    "ScopeGrammarError",
    "entries_overlap",
    "entry_contains_path",
    "normalize_scope_entry_text",
    "overlapping_entries",
    "parse_scope_entry",
    "read_scope_entries",
    "read_scope_entry",
    "render_scope_entry",
    "scope_contains_path",
]
