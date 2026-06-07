# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.docs_script_loader import load_script_module

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LINT_SCRIPT = _REPO_ROOT / "scripts/lint_docs_links.py"


def test_docs_internal_links_valid() -> None:
    lint = load_script_module(module_name="lint_docs_links", script_path=_LINT_SCRIPT)
    violations = lint.validate() + lint.validate_site_urls()
    assert violations == [], "\n".join(violations)


def test_docs_build_strict() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "zensical==0.0.43",
            "zensical",
            "build",
            "--clean",
            "--strict",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
