# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from tests._import_graph import _iter_local_imports, _module_name_from_path


def _iter_codeclone_modules(root: Path) -> list[tuple[str, Path]]:
    return [
        (_module_name_from_path(path.relative_to(root)), path)
        for path in sorted((root / "codeclone").rglob("*.py"))
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
                "codeclone.report.html",
                "codeclone.surfaces.cli",
                "codeclone._html_",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.extractor",
            (
                "codeclone.report",
                "codeclone.surfaces.cli",
                "codeclone.baseline",
            ),
        ),
        (
            "codeclone.grouping",
            (
                "codeclone.surfaces.cli",
                "codeclone.baseline",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.baseline",
            (
                "codeclone.surfaces.cli",
                "codeclone.ui_messages",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.cache",
            (
                "codeclone.surfaces.cli",
                "codeclone.ui_messages",
                "codeclone.report.html",
            ),
        ),
        (
            "codeclone.core",
            (
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.analysis",
            (
                "codeclone.report",
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.metrics",
            (
                "codeclone.report.document",
                "codeclone.report.renderers",
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.findings",
            (
                "codeclone.report",
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.report.document",
            (
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.report.renderers",
            (
                "codeclone.core",
                "codeclone.analysis",
                "codeclone.metrics",
                "codeclone.findings",
                "codeclone.surfaces",
                "codeclone.config",
            ),
        ),
        (
            "codeclone.domain.",
            (
                "codeclone.surfaces.cli",
                "codeclone.pipeline",
                "codeclone.report",
                "codeclone.report.html",
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
                if module_prefix == "codeclone.report." and module_name.startswith(
                    "codeclone.report.html"
                ):
                    continue
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
            allowed_prefixes = ("codeclone.contracts",)
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
