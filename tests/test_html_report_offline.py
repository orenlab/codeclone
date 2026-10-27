# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Opening the HTML report loads nothing from the network.

The privacy policy promises no third-party requests. The report used to pull
its fonts from fonts.googleapis.com and fonts.gstatic.com as soon as it was
opened, and its badge dialog loaded a shields.io image; it now uses locally
installed or system fonts and shows the badge address as text. The scan covers
every way markup or CSS can fetch a resource by address: ``<link href>``,
``@import``, ``url()`` and ``src``/``srcset``, absolute or protocol-relative.
The report's scripts are scanned too: no ``fetch``, no ``XMLHttpRequest``, no
``new Image``, no element that loads by address created or written into the
page. A link the user clicks (``<a href>``) is navigation, not a load, and text
shown for copying is not markup.
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


_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_LOADER_TAG = r"<(?:img|script|link|iframe|source|video|audio|embed|object)\b"
_SCRIPT_NETWORK_LOAD = re.compile(
    r"\bfetch\s*\("
    r"|\bXMLHttpRequest\b"
    r"|\bnew\s+(?:Image|WebSocket|EventSource|Worker|SharedWorker)\b"
    r"|\bnavigator\.sendBeacon\b"
    r"|\bimport\s*\("
    r"|\bdocument\.write(?:ln)?\s*\("
    r"|\bcreateElement\(\s*[\"'](?:img|script|link|iframe|source|video|audio|embed|object)[\"']"
    r"|\.(?:src|srcset)\s*=\s*[\"'`]\s*(?:https?:)?//[^\"'`]*"
    r"|\.setAttribute\(\s*[\"'](?:src|srcset)[\"']"
    r"|\.(?:innerHTML|outerHTML)\s*\+?=[^;]*?" + _LOADER_TAG + r"[^;]*"
    r"|\binsertAdjacentHTML\s*\([^;]*?" + _LOADER_TAG + r"[^;]*",
    re.IGNORECASE,
)


def script_network_loads(html: str) -> list[str]:
    """Every place in the page's scripts that can make the browser fetch."""

    return [
        match.group(0)
        for script in _SCRIPT.finditer(html)
        for match in _SCRIPT_NETWORK_LOAD.finditer(script.group(1))
    ]


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


def test_the_script_scan_sees_each_way_a_script_can_load() -> None:
    # Positive control: each loading form is found; copy text, navigation and
    # local markup are not.
    probe = (
        "<script>"
        "fetch('/api');var x=new XMLHttpRequest();var i=new Image();"
        "navigator.sendBeacon('/b');import('./m.js');document.write('x');"
        "var s=document.createElement('script');"
        "img.src='https://img.example/a.png';el.setAttribute('src',u);"
        "prev.innerHTML='<img src=\"'+url+'\" alt=\"\">';"
        "box.insertAdjacentHTML('beforeend','<iframe src=\"'+u+'\">');"
        "code.textContent='<img src=\"'+url+'\">';"
        "a.href='https://example.com/docs';"
        "btn.innerHTML='<svg viewBox=\"0 0 16 16\"></svg>';"
        "</script>"
    )

    assert script_network_loads(probe) == [
        "fetch(",
        "XMLHttpRequest",
        "new Image",
        "navigator.sendBeacon",
        "import(",
        "document.write(",
        "createElement('script'",
        ".src='https://img.example/a.png",
        ".setAttribute('src'",
        ".innerHTML='<img src=\"'+url+'\" alt=\"\">'",
        "insertAdjacentHTML('beforeend','<iframe src=\"'+u+'\">')",
    ]


def _report_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
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
    return report.read_text(encoding="utf-8")


def test_the_html_report_loads_nothing_from_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert external_loads(_report_html(tmp_path, monkeypatch)) == []


def test_the_html_report_scripts_load_nothing_from_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    html = _report_html(tmp_path, monkeypatch)

    assert _SCRIPT.search(html) is not None
    assert script_network_loads(html) == []


def test_the_badge_dialog_still_offers_the_badge_to_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other side of the fix: the preview shows the badge address as text
    # and the Markdown and HTML snippets stay ready to copy.
    scripts = "".join(
        script.group(1)
        for script in _SCRIPT.finditer(_report_html(tmp_path, monkeypatch))
    )

    for expected in (
        "url='https://img.shields.io/badge/codeclone-'",
        "if(prev)prev.textContent=url;",
        "if(md)md.textContent='!['+alt+']('+url+')';",
        "if(ht)ht.textContent='<img src=\"'+url+'\" alt=\"'+alt+'\">';",
    ):
        assert expected in scripts, expected
