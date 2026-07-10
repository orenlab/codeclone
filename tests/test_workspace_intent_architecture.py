# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from tests._import_graph import _iter_local_imports, _module_name_from_path


def test_workspace_intent_does_not_import_mcp_private_modules() -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for path in sorted((root / "codeclone" / "workspace_intent").rglob("*.py")):
        module_name = _module_name_from_path(path.relative_to(root))
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))
        violations.extend(
            f"{module_name} -> {import_name}"
            for import_name in imports
            if import_name.startswith("codeclone.surfaces.mcp")
        )
    assert violations == []
