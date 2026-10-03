# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The dependency floors the packaging page quotes are the ones pyproject declares.

``docs/internal/surfaces/packaging-release.md`` states the requirement of each
optional extra twice: in the packaging diagram and in the dependency-freeze
table. A dependency bump in ``pyproject.toml`` changes neither, so the page kept
quoting floors the lock no longer declared until a reader compared them by hand.

The requirements are read out of the page -- every ``name>=floor`` with an
optional ``,<ceiling``, where the diagram writes ``&ge;`` for ``>=`` -- and each
one is held to what ``pyproject.toml`` declares for that package. The test
holds no version of its own: the page is the input and the project metadata is
the reference. An environment marker on the declaration is not part of the
requirement the page quotes, so it is dropped before the comparison.

A package declared in more than one extra must carry the same requirement in
all of them: the page names one requirement per package, so a declaration that
drifted away from its siblings makes the quote wrong for some extra.

Finding nothing on the page would read as a pass, so the quotes are counted
first, and both places that quote them have to contribute.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import NamedTuple

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PAGE = _REPO_ROOT / "docs" / "internal" / "surfaces" / "packaging-release.md"
_FENCE = "```"
_DIAGRAM_FENCE_TAG = "mermaid"

#: The fewest quotes the page may yield. The page quotes one requirement for
#: each extra it names, in the diagram and in the table; far fewer than that
#: means the pattern stopped seeing the page, not that the page lost them.
_MIN_QUOTES = 10

_VERSION = r"\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?"
_QUOTE = re.compile(
    rf"(?P<name>[A-Za-z][A-Za-z0-9._-]*) ?(?:>=|&ge;) ?(?P<floor>{_VERSION})"
    rf"(?:, ?(?:<|&lt;) ?(?P<ceiling>{_VERSION}))?"
)


class _Quote(NamedTuple):
    line: int
    in_diagram: bool
    name: str
    specifier: SpecifierSet


def _page_quotes() -> list[_Quote]:
    quotes: list[_Quote] = []
    fence_tag: str | None = None
    lines = _PAGE.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith(_FENCE):
            fence_tag = None if fence_tag is not None else stripped[len(_FENCE) :]
            continue
        for match in _QUOTE.finditer(line):
            ceiling = match["ceiling"]
            requirement = f">={match['floor']}" + (f",<{ceiling}" if ceiling else "")
            quotes.append(
                _Quote(
                    line=number,
                    in_diagram=fence_tag == _DIAGRAM_FENCE_TAG,
                    name=match["name"],
                    specifier=SpecifierSet(requirement),
                )
            )
    return quotes


def _declared_specifiers() -> dict[str, set[SpecifierSet]]:
    """Every requirement ``pyproject.toml`` declares, grouped by package."""

    toml = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    project = toml.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    base: list[str] = project["project"]["dependencies"]
    extras: dict[str, list[str]] = project["project"]["optional-dependencies"]
    declared: dict[str, set[SpecifierSet]] = {}
    for text in [*base, *(item for group in extras.values() for item in group)]:
        requirement = Requirement(text)
        name = canonicalize_name(requirement.name)
        declared.setdefault(name, set()).add(requirement.specifier)
    return declared


def test_the_page_quotes_enough_requirements_for_the_check_to_mean_something() -> None:
    quotes = _page_quotes()

    assert len(quotes) >= _MIN_QUOTES, (
        f"only {len(quotes)} requirements found on {_PAGE.name}; the pattern no "
        "longer reads the page, and the comparison below would pass over nothing"
    )
    assert any(quote.in_diagram for quote in quotes), (
        "no requirement found inside the diagram: its quotes are not being checked"
    )
    assert any(not quote.in_diagram for quote in quotes), (
        "no requirement found outside the diagram: the table is not being checked"
    )


def test_every_requirement_the_page_quotes_is_what_pyproject_declares() -> None:
    declared = _declared_specifiers()
    mismatches: list[str] = []

    for quote in _page_quotes():
        actual = declared.get(canonicalize_name(quote.name), set())
        if actual != {quote.specifier}:
            where = "diagram" if quote.in_diagram else "table"
            mismatches.append(
                f"{_PAGE.name}:{quote.line} ({where}) quotes "
                f"{quote.name}{quote.specifier}, pyproject.toml declares "
                f"{sorted(str(item) for item in actual) or 'no such package'}"
            )

    assert not mismatches, "\n".join(mismatches)
