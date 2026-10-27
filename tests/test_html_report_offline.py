# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Opening the HTML report loads nothing from the network.

The privacy policy promises no third-party requests. The report used to pull
its fonts from fonts.googleapis.com and fonts.gstatic.com as soon as it was
opened; it now uses system font stacks. The scan covers every way markup or
CSS can fetch a resource by address: ``<link href>``, ``@import``, ``url()``
and ``src``/``srcset``, absolute or protocol-relative.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._cli_inprocess_run import run_cli

_EXTERNAL_LOAD = re.compile(
    r"<link\b[^>]*\bhref\s*=\s*[\"']?\s*(?:https?:)?//[^\s\"'>]*"
    r"|@import\b[^;]*"
    r"|url\(\s*[\"']?\s*(?:https?:)?//[^\s\"')]*"
    r"|\bsrc(?:set)?\s*=\s*[\"']?\s*(?:https?:)?//[^\s\"'>]*",
    re.IGNORECASE,
)


def external_loads(html: str) -> list[str]:
    """Every address in *html* that a browser would fetch on its own."""

    return [match.group(0) for match in _EXTERNAL_LOAD.finditer(html)]


def test_the_scan_sees_each_way_a_page_can_load_by_address() -> None:
    # Positive control: each form is found; inline and local ones are not.
    probe = (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        "<link href=//cdn.example/x.css rel=stylesheet>"
        "<style>@import 'theme.css';"
        ".a{background:url( 'https://img.example/a.png' )}"
        ".b{background:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E\")}"
        "</style>"
        '<img src="https://img.example/b.png" srcset="//img.example/c.png 2x">'
        '<a href="https://example.com/docs">docs</a>'
    )

    assert external_loads(probe) == [
        '<link rel="preconnect" href="https://fonts.googleapis.com',
        "<link href=//cdn.example/x.css",
        "@import 'theme.css'",
        "url( 'https://img.example/a.png",
        'src="https://img.example/b.png',
        'srcset="//img.example/c.png',
    ]


def test_the_html_report_loads_nothing_from_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    for name in ("a", "b"):
        (repo / "pkg" / f"{name}.py").write_text(
            "def total(rows):\n"
            "    result = 0\n"
            "    for row in rows:\n"
            "        if row:\n"
            "            result += row\n"
            "    return result\n",
            encoding="utf-8",
        )
    report = tmp_path / "report.html"

    assert run_cli(monkeypatch, repo, ".", "--no-progress", "--html", str(report)) == 0

    assert external_loads(report.read_text(encoding="utf-8")) == []
