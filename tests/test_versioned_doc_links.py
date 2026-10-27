# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Documentation links of the 2.0.x package point at this release's own docs.

The old site served ``/book/NN-.../``, ``/mcp/`` and similar paths; the current
site no longer does. README, the PyPI description and the package metadata link
to the ``docs/`` tree of the ``v2.0.3`` tag instead, and every such link must
name a file or directory that exists in this tree, so the tag carries it.
Whether the tag itself resolves is checked at release time, not here. The
same holds for the MCP help topics, the Codex plugin and Claude Desktop bundle
manifests and the extension, plugin and Action READMEs. Site pages that still
exist on the current site (privacy policy, terms of use, the example report,
the site root) keep their site address.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SOURCES = (
    "README.md",
    "docs/README-pypi.md",
    "pyproject.toml",
    ".github/actions/codeclone/README.md",
    "extensions/claude-desktop-codeclone/README.md",
    "extensions/claude-desktop-codeclone/manifest.json",
    "extensions/vscode-codeclone/README.md",
    "plugins/codeclone/README.md",
    "plugins/codeclone/.codex-plugin/plugin.json",
)
_DOCS_TREE = "https://github.com/orenlab/codeclone/tree/v2.0.3/docs"
_VERSIONED = re.compile(
    r"https://github\.com/orenlab/codeclone/(?P<kind>blob|tree)/"
    r"(?P<tag>[^/\s]+)/(?P<path>docs(?:/[^\s)\"'>#]*)?)"
)
_RETIRED = re.compile(
    r"https://orenlab\.github\.io/codeclone/"
    r"(?:book/\d{2}-[a-z0-9-]+|mcp|architecture|cfg|codex-plugin|claude-desktop-bundle"
    r"|sarif)/"
)


def _text(name: str) -> str:
    return (_REPO / name).read_text(encoding="utf-8")


# Only links into docs/ are versioned; links to LICENSE files and to the
# extension folders keep pointing at main.
def _versioned_links() -> Iterator[tuple[str, re.Match[str]]]:
    for name in _SOURCES:
        for match in _VERSIONED.finditer(_text(name)):
            yield name, match


def test_every_versioned_doc_link_names_a_path_in_this_tree() -> None:
    links = list(_versioned_links())
    assert len(links) >= 20, "the versioned links were not found at all"
    missing = [
        f"{name}: {match.group(0)}"
        for name, match in links
        if not (
            (_REPO / match.group("path")).is_file()
            if match.group("kind") == "blob"
            else (_REPO / match.group("path")).is_dir()
        )
    ]

    assert missing == []


def test_versioned_doc_links_name_one_tag() -> None:
    assert {match.group("tag") for _, match in _versioned_links()} == {"v2.0.3"}


def test_no_link_to_a_retired_site_path() -> None:
    retired = [
        f"{name}: {match.group(0)}"
        for name in _SOURCES
        for match in _RETIRED.finditer(_text(name))
    ]

    assert retired == []


def test_package_documentation_url_is_the_versioned_docs_tree() -> None:
    (value,) = re.findall(r'(?m)^Documentation = "([^"]+)"$', _text("pyproject.toml"))

    assert value == _DOCS_TREE


def test_readmes_open_with_the_versioned_docs_note() -> None:
    for name in ("README.md", "docs/README-pypi.md"):
        first_line = _text(name).splitlines()[0]
        assert _DOCS_TREE in first_line, name
        assert "current release" in first_line, name


def test_mcp_help_doc_links_name_versioned_docs_in_this_tree() -> None:
    from codeclone.surfaces.mcp._session_shared import _HELP_TOPIC_SPECS

    urls = sorted(
        {url for spec in _HELP_TOPIC_SPECS.values() for _, url in spec.doc_links}
    )
    assert len(urls) >= 8, "the help topics' doc links were not found"
    unresolved = []
    for url in urls:
        match = _VERSIONED.fullmatch(url)
        if (
            match is None
            or match.group("tag") != "v2.0.3"
            or not (_REPO / match.group("path")).is_file()
        ):
            unresolved.append(url)

    assert unresolved == []
