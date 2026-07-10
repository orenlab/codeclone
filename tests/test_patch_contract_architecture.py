# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import codeclone.budget.patch_contract as patch_contract
import codeclone.surfaces.mcp._patch_contract as compatibility
from tests._import_graph import _iter_local_imports, _module_name_from_path


def test_patch_contract_compatibility_reexports_preserve_identity() -> None:
    for name in compatibility.__all__:
        assert getattr(compatibility, name) is getattr(patch_contract, name)
    assert compatibility.budgets_from_request is patch_contract.budgets_from_request


def test_non_mcp_modules_do_not_import_private_patch_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = "codeclone.surfaces.mcp._patch_contract"
    violations: list[str] = []
    for path in sorted((root / "codeclone").rglob("*.py")):
        module_name = _module_name_from_path(path.relative_to(root))
        if module_name.startswith("codeclone.surfaces.mcp"):
            continue
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))
        violations.extend(
            f"{module_name} -> {import_name}"
            for import_name in imports
            if import_name == forbidden or import_name.startswith(forbidden + ".")
        )
    assert violations == []


def test_patch_contract_owner_does_not_import_surfaces() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "codeclone" / "budget" / "patch_contract.py"
    imports = _iter_local_imports(
        "codeclone.budget.patch_contract", path.read_text("utf-8")
    )
    assert [name for name in imports if name.startswith("codeclone.surfaces")] == []
