# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The parser reads a shortened report flag as the report flag it names.

The CLI decides whether a report path was given or defaulted by scanning the
command line for the five report flags, and resolves a shortened spelling
that names exactly one of them to that flag
(``tests/test_cli_report_flag_abbreviations.py``). That is right only while
argparse agrees: every spelling it accepts must fill that same report, and a
spelling shared with another option must be refused as ambiguous. A new
option that is itself a prefix of a report flag would break the agreement
silently; this suite is where it fails.
"""

from __future__ import annotations

import argparse
import contextlib
import io

import pytest

from codeclone.config.argparse_builder import build_parser

_REPORT_DEST_BY_FLAG = {
    "--html": "html_out",
    "--json": "json_out",
    "--md": "md_out",
    "--sarif": "sarif_out",
    "--text": "text_out",
}


def _filled(parser: argparse.ArgumentParser, token: str) -> set[str] | None:
    """The report dests argparse filled for ``token``, ``None`` if refused."""

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            namespace, _rest = parser.parse_known_args([token])
    except SystemExit:
        return None
    return {
        dest
        for dest in _REPORT_DEST_BY_FLAG.values()
        if getattr(namespace, dest, None) is not None
    }


_CASES = [
    flag[:end] for flag in _REPORT_DEST_BY_FLAG for end in range(3, len(flag) + 1)
]


@pytest.mark.parametrize("token", _CASES)
def test_an_accepted_prefix_fills_the_report_it_uniquely_names(token: str) -> None:
    named = [flag for flag in _REPORT_DEST_BY_FLAG if flag.startswith(token)]

    filled = _filled(build_parser("test"), token)

    if filled is None:
        return
    assert len(named) == 1, (token, named, filled)
    assert filled == {_REPORT_DEST_BY_FLAG[named[0]]}, (token, filled)


def test_the_parser_accepts_shortened_report_flags() -> None:
    """Probe validity: abbreviation is on, so the cases reach the parser."""

    parser = build_parser("test")
    assert parser.allow_abbrev
    assert _filled(parser, "--htm") == {"html_out"}
