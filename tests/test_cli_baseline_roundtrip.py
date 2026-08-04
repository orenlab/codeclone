# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI-surface guard: a published baseline must always read back.

The lane-level round trip lives in ``tests/test_baseline_lane_roundtrip.py``;
this module pins the same defect class end to end through the CLI, staying on
the r4 surface only so the Phase 39S boundary ratchet keeps one ring per test
module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import codeclone.surfaces.cli.workflow as cli

_SCOPE_ID = "019f7fa1-8866-7242-b0bf-0ff282cafbcb"


def _run_cli(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["codeclone", *args])
    cli.main()


def test_cli_reloads_published_baseline_with_escaping_relative_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool must always re-read a baseline it just published.

    The fixture repeats the Django corpus shape: a relative import whose
    level escapes the package, leaving an unresolved import that still
    names its requested module.
    """

    sources = {
        "app/__init__.py": "",
        "app/models.py": (
            'class Item:\n    def label(self) -> str:\n        return "item"\n'
        ),
        "app/views.py": (
            "from ...models import Item\n\n\ndef render() -> str:\n"
            "    return Item().label()\n"
        ),
        "pyproject.toml": (f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n'),
    }
    for relative, content in sources.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, "utf-8")
    baseline = tmp_path / "baseline.json"
    common = [str(tmp_path), "--baseline", str(baseline), "--no-progress"]

    _run_cli(monkeypatch, [*common, "--update-baseline"])
    assert baseline.is_file()
    _run_cli(monkeypatch, common)
