# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.docs_script_loader import load_script_module

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS_ROOT = _REPO_ROOT / "docs"
_LINT_SCRIPT = _REPO_ROOT / "scripts" / "lint_admonitions.py"


def _require_docs_source() -> None:
    if not (_DOCS_ROOT / "index.md").is_file():
        pytest.skip("repo docs source tree is not present")


def test_docs_admonition_indentation_is_valid() -> None:
    _require_docs_source()
    lint = load_script_module(
        module_name="lint_admonitions",
        script_path=_LINT_SCRIPT,
    )
    violations: list[str] = []
    for path in lint.iter_doc_files(_DOCS_ROOT):
        text = path.read_text(encoding="utf-8")
        violations.extend(lint.validate_markdown(text, path.relative_to(_REPO_ROOT)))
    assert violations == []


def _build_docs_site(tmp_path: Path) -> Path:
    """Build the site from a copy of the docs tree, never inside the checkout.

    The docs are this repository's and stay its measurement subject; the BUILD
    is what moved. ``zensical build`` writes ``site/`` beside the config it is
    handed and ``uv run`` in a project directory syncs that project's
    environment, so building in the checkout rewrote ``<root>/site/`` twice per
    suite and let uv touch the checkout's own ``.venv``. zensical resolves
    ``docs_dir`` relative to the config file and refuses an absolute one
    (measured 2026-09-07: ``invariant: Id(Format(Path(RootDir)))``), so the
    copy carries the config alongside; ``--no-project`` keeps uv out of the
    checkout's environment.
    """

    stage = tmp_path / "docs-stage"
    stage.mkdir()
    shutil.copytree(_DOCS_ROOT, stage / "docs")
    shutil.copy2(_REPO_ROOT / "zensical.toml", stage / "zensical.toml")
    result = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            "zensical==0.0.46",
            "zensical",
            "build",
            "--clean",
            "--strict",
        ],
        cwd=stage,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return stage / "site"


def test_docs_build_strict(tmp_path: Path) -> None:
    _require_docs_source()
    site_root = _build_docs_site(tmp_path)
    assert (site_root / "index.html").is_file()


def test_sample_report_built_page_has_absolute_artifact_links(tmp_path: Path) -> None:
    _require_docs_source()
    site_root = _build_docs_site(tmp_path)
    candidates = (
        site_root / "examples" / "report" / "index.html",
        site_root / "examples" / "report.html",
    )
    page = next((path for path in candidates if path.is_file()), None)
    assert page is not None, "expected built sample report HTML page"
    text = page.read_text(encoding="utf-8")
    assert 'href="live/' not in text
    assert 'href="./live/' not in text
    assert "examples/report/live/index.html" in text
