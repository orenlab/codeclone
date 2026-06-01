# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib.util
import subprocess
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS_ROOT = _REPO_ROOT / "docs"
_LINT_SCRIPT = _REPO_ROOT / "scripts" / "lint_mkdocs_admonitions.py"


def _load_lint_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "lint_mkdocs_admonitions",
        _LINT_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docs_admonition_indentation_is_valid() -> None:
    lint = _load_lint_module()
    violations: list[str] = []
    for path in lint.iter_doc_files(_DOCS_ROOT):
        text = path.read_text(encoding="utf-8")
        violations.extend(lint.validate_markdown(text, path.relative_to(_REPO_ROOT)))
    assert violations == []


def test_mkdocs_build_strict() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "mkdocs",
            "--with",
            "mkdocs-material",
            "mkdocs",
            "build",
            "--strict",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout
