# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A report flag the parser accepted abbreviated is still that report flag.

argparse accepts any unique prefix of a long option (``allow_abbrev``), so
``--htm`` is ``--html``. The scan that decides whether a report path was
given or defaulted compared tokens with the five full flag names, did not
see ``--htm`` at all, and ``--timestamped-report-paths`` -- which stamps only
defaulted paths -- left ``.codeclone/report.html`` to be overwritten.

The scan resolves a spelling that names exactly one of the five report flags
to that flag. ``tests/test_config_report_flag_prefixes.py`` holds the parser
to the same reading, so the day a new option makes a prefix mean something
else, one of the two suites fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.surfaces.cli import reports_output
from tests._cli_child import run_codeclone

_REPORT_FIELD_BY_FLAG = {
    "--html": "html",
    "--json": "json",
    "--md": "md",
    "--sarif": "sarif",
    "--text": "text",
}


def _unique_prefixes() -> list[tuple[str, str]]:
    """Every shortened spelling that names exactly one report flag.

    ``tests/test_config_report_flag_prefixes.py`` pins the other half: the
    real parser accepts such a spelling as that same flag, or refuses it.
    """

    cases: list[tuple[str, str]] = []
    for flag, field in _REPORT_FIELD_BY_FLAG.items():
        for end in range(3, len(flag) + 1):
            token = flag[:end]
            if [name for name in _REPORT_FIELD_BY_FLAG if name.startswith(token)] == [
                flag
            ]:
                cases.append((token, field))
    return cases


_PREFIXES = _unique_prefixes()


def test_the_population_holds_abbreviations() -> None:
    """Probe validity: the cases include shortened spellings at all."""

    assert {"--htm", "--jso", "--sari", "--tex"} <= {token for token, _ in _PREFIXES}


@pytest.mark.parametrize(("token", "field"), _PREFIXES)
@pytest.mark.parametrize("form", ["bare", "valued", "equals"])
def test_the_origin_scan_resolves_a_unique_prefix(
    token: str, field: str, form: str
) -> None:
    if form == "bare":
        argv, origin = [token], "default"
    elif form == "valued":
        argv, origin = [token, f"out.{field}"], "explicit"
    else:
        argv, origin = [f"{token}=out.{field}"], "explicit"

    origins = reports_output._report_path_origins(argv)

    assert origins[field] == origin
    assert [name for name, value in origins.items() if value is not None] == [field]


@pytest.mark.parametrize(
    "argv",
    [[""], ["proj"], ["-", "x"], ["--min-loc", "5"], ["--"], ["--", "--html"]],
)
def test_a_token_that_is_not_a_report_flag_names_no_report(argv: list[str]) -> None:
    """A value, the root, an empty argument, another option, or anything after
    ``--`` is never read as a report flag -- every flag name starts with the
    empty string."""

    assert set(reports_output._report_path_origins(argv).values()) == {None}


@pytest.mark.parametrize("flag", ["--html", "--htm"])
def test_timestamped_paths_never_overwrite_the_plain_default(
    tmp_path: Path, flag: str
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "mod.py").write_text("VALUE = 1\n", "utf-8")

    run = run_codeclone(
        tmp_path, ".", flag, "--timestamped-report-paths", "--quiet", cwd=root
    )

    assert run.returncode == 0, run.stdout + run.stderr
    written = sorted(path.name for path in (root / ".codeclone").glob("report*.html"))
    assert len(written) == 1, written
    assert written != ["report.html"], written
