# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast
from pathlib import Path


def _python_sources() -> list[Path]:
    roots = (Path("codeclone"), Path("tests"))
    paths: list[Path] = []
    for root in roots:
        paths.extend(
            path for path in root.rglob("*.py") if "__pycache__" not in path.parts
        )
    return sorted(paths)


def test_repo_syntax_is_compatible_with_python_310_and_311() -> None:
    for minor in (10, 11):
        for path in _python_sources():
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path), feature_version=minor)
