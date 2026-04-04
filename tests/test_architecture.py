# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from pathlib import Path


def _module_name_from_path(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    return ".".join(parts)


def _resolve_import(module_name: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    parts = module_name.split(".")
    prefix_parts = parts[: -node.level]
    if node.module:
        return ".".join([*prefix_parts, node.module])
    return ".".join(prefix_parts)


def _iter_codeclone_modules(root: Path) -> list[tuple[str, Path]]:
    return [
        (_module_name_from_path(path.relative_to(root)), path)
        for path in sorted((root / "codeclone").rglob("*.py"))
    ]


def _iter_local_imports(module_name: str, source: str) -> list[str]:
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(_resolve_import(module_name, node))
    return [
        import_name for import_name in imports if import_name.startswith("codeclone")
    ]


def _violates(import_name: str, forbidden_prefixes: tuple[str, ...]) -> bool:
    return any(
        import_name == prefix or import_name.startswith(prefix + ".")
        for prefix in forbidden_prefixes
    )


def _matches_module_prefix(module_name: str, module_prefix: str) -> bool:
    return module_name.startswith((module_prefix, module_prefix + "."))


def _is_allowed_import(import_name: str, allowed_prefixes: tuple[str, ...]) -> bool:
    return any(
        import_name == prefix or import_name.startswith(prefix + ".")
        for prefix in allowed_prefixes
    )


def test_architecture_layer_violations() -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []

    forbidden_by_module_prefix: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "codeclone.report.",
            (
                "codeclone.ui_messages",
                "codeclone.html_report",
                "codeclone.cli",
                "codeclone._html_",
                "codeclone._html_report",
            ),
        ),
        (
            "codeclone.extractor",
            (
                "codeclone.report",
                "codeclone.cli",
                "codeclone.baseline",
            ),
        ),
        (
            "codeclone.grouping",
            (
                "codeclone.cli",
                "codeclone.baseline",
                "codeclone.html_report",
            ),
        ),
        (
            "codeclone.baseline",
            (
                "codeclone.cli",
                "codeclone.ui_messages",
                "codeclone.html_report",
            ),
        ),
        (
            "codeclone.cache",
            (
                "codeclone.cli",
                "codeclone.ui_messages",
                "codeclone.html_report",
            ),
        ),
        (
            "codeclone.domain.",
            (
                "codeclone.cli",
                "codeclone.pipeline",
                "codeclone.report",
                "codeclone.html_report",
                "codeclone.ui_messages",
                "codeclone.baseline",
                "codeclone.cache",
            ),
        ),
    )

    for module_name, path in _iter_codeclone_modules(root):
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))

        for module_prefix, forbidden_prefixes in forbidden_by_module_prefix:
            if _matches_module_prefix(module_name, module_prefix):
                violations.extend(
                    [
                        (
                            f"{module_name} -> {import_name} "
                            f"(forbidden: {forbidden_prefixes})"
                        )
                        for import_name in imports
                        if _violates(import_name, forbidden_prefixes)
                    ]
                )

        if module_name == "codeclone.models":
            allowed_prefixes = ("codeclone.contracts", "codeclone.errors")
            unexpected_imports = [
                import_name
                for import_name in imports
                if not _is_allowed_import(import_name, allowed_prefixes)
            ]
            violations.extend(
                [
                    f"codeclone.models imports unexpected local module: {import_name}"
                    for import_name in unexpected_imports
                ]
            )

        if (
            module_name.startswith("codeclone.domain.")
            and module_name != "codeclone.domain.__init__"
        ):
            violations.extend(
                [
                    "codeclone.domain submodule imports unexpected local module: "
                    f"{module_name} -> {import_name}"
                    for import_name in imports
                ]
            )

    assert violations == []
