# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import json
from pathlib import Path

from tests._import_graph import (
    _iter_import_edges,
    _iter_local_imports,
    _module_name_from_path,
)

_BOUNDARY_ALLOWLIST_PATH = Path(__file__).with_name(
    "architecture_boundary_allowlist.json"
)
_BOUNDARY_ALLOWLIST_POLICY = "phase39s-s0-observe-shrink-only"

_RING_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("codeclone.observability.store", "r2p"),
    ("codeclone.observability.analysis_phases", "r2p"),
    ("codeclone.observability.db_fingerprint", "r2p"),
    ("codeclone.observability.models", "r2p"),
    ("codeclone.observability.profile", "r2p"),
    ("codeclone.observability.query", "r2p"),
    ("codeclone.observability.render_html", "r2p"),
    ("codeclone.observability.render_json", "r2p"),
    ("codeclone.observability.sqlite_access", "r2p"),
    ("codeclone.observability.views", "r2p"),
    ("codeclone.observability", "r1"),
    ("codeclone.report.renderers", "r4"),
    ("codeclone.report.html", "r4"),
    ("codeclone.report.messages", "r4"),
    ("codeclone.report", "r2"),
    ("codeclone.controller_insights", "r2p"),
    ("codeclone.workspace_intent", "r2p"),
    ("codeclone.analytics", "r2p"),
    ("codeclone.audit", "r2p"),
    ("codeclone.memory", "r2p"),
    ("codeclone.surfaces", "r4"),
    ("codeclone.ui_messages", "r4"),
    ("codeclone.main", "r4"),
    ("codeclone.__init__", "r4"),
    ("codeclone.contracts.compatibility", "r2"),
    ("codeclone.contracts", "r0"),
    ("codeclone.utils", "r1"),
    ("codeclone.api", "r3"),
    ("codeclone.analysis", "r2"),
    ("codeclone.baseline", "r2"),
    ("codeclone.blocks", "r2"),
    ("codeclone.budget", "r2"),
    ("codeclone.cache", "r2"),
    ("codeclone.config", "r2"),
    ("codeclone.core", "r2"),
    ("codeclone.domain", "r2"),
    ("codeclone.findings", "r2"),
    ("codeclone.meta_markers", "r2"),
    ("codeclone.metrics", "r2"),
    ("codeclone.models", "r2"),
    ("codeclone.paths", "r2"),
    ("codeclone.qualnames", "r2"),
    ("codeclone.scanner", "r2"),
    ("codeclone", "r4"),
    ("extensions", "r4"),
    ("plugins", "r4"),
)

_ALLOWED_IMPORT_RINGS: dict[str, frozenset[str]] = {
    "r0": frozenset({"r0"}),
    "r1": frozenset({"r0", "r1"}),
    "r2": frozenset({"r0", "r1", "r2"}),
    "r2p": frozenset({"r0", "r1", "r2p"}),
    "r3": frozenset({"r0", "r1", "r2", "r2p", "r3"}),
    "r4": frozenset({"r0", "r1", "r3", "r4"}),
}

_R2P_DTO_PREFIXES = (
    "codeclone.models",
    "codeclone.report.document",
)

_GENERATED_DIRECTORY_NAMES = frozenset(
    {
        ".gradle",
        ".idea",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)


def _iter_codeclone_modules(root: Path) -> list[tuple[str, Path]]:
    return [
        (_module_name_from_path(path.relative_to(root)), path)
        for path in sorted((root / "codeclone").rglob("*.py"))
    ]


def _iter_production_modules(root: Path) -> list[tuple[str, Path]]:
    modules: list[tuple[str, Path]] = []
    for package in ("codeclone", "extensions", "plugins"):
        package_root = root / package
        if not package_root.exists():
            continue
        modules.extend(
            (_module_name_from_path(path.relative_to(root)), path)
            for path in sorted(package_root.rglob("*.py"))
            if not _GENERATED_DIRECTORY_NAMES.intersection(path.relative_to(root).parts)
        )
    return modules


def _ring_for_module(module_name: str) -> str | None:
    for prefix, ring in _RING_BY_PREFIX:
        if module_name == prefix or module_name.startswith(prefix + "."):
            return ring
    return None


def _is_r2p_dto_import(import_name: str) -> bool:
    return any(
        import_name == prefix or import_name.startswith(prefix + ".")
        for prefix in _R2P_DTO_PREFIXES
    )


def _is_ring_import_allowed(
    source_ring: str,
    target_ring: str,
    import_name: str,
) -> bool:
    if target_ring in _ALLOWED_IMPORT_RINGS[source_ring]:
        return True
    return (
        source_ring == "r2p" and target_ring == "r2" and _is_r2p_dto_import(import_name)
    )


def _add_violation(
    violations: dict[str, set[str]],
    family: str,
    violation: str,
) -> None:
    violations.setdefault(family, set()).add(violation)


def _production_import_violations(
    root: Path,
    violations: dict[str, set[str]],
) -> None:
    for module_name, path in _iter_production_modules(root):
        source_ring = _ring_for_module(module_name)
        if source_ring is None:
            _add_violation(
                violations,
                "ring_assignment:unassigned",
                module_name,
            )
            continue
        for import_name, _line in _iter_import_edges(
            module_name, path.read_text("utf-8")
        ):
            if not import_name.startswith("codeclone"):
                continue
            target_ring = _ring_for_module(import_name)
            if target_ring is None:
                _add_violation(
                    violations,
                    "ring_assignment:unassigned_target",
                    f"{module_name} -> {import_name}",
                )
            elif not _is_ring_import_allowed(source_ring, target_ring, import_name):
                _add_violation(
                    violations,
                    f"production_import:{source_ring}->{target_ring}",
                    f"{module_name} -> {import_name}",
                )


def _test_subject_ring(imports: list[tuple[str, int]]) -> str | None:
    rings = {
        ring
        for import_name, _line in imports
        if (ring := _ring_for_module(import_name)) is not None
    }
    for ring in ("r4", "r3", "r2p", "r2", "r1", "r0"):
        if ring in rings:
            return ring
    return None


def _test_import_violations(
    root: Path,
    violations: dict[str, set[str]],
) -> None:
    for path in sorted((root / "tests").glob("test_*.py")):
        module_name = _module_name_from_path(path.relative_to(root))
        imports = [
            edge
            for edge in _iter_import_edges(module_name, path.read_text("utf-8"))
            if edge[0].startswith("codeclone")
        ]
        source_ring = _test_subject_ring(imports)
        if source_ring is None:
            continue
        for import_name, _line in imports:
            target_ring = _ring_for_module(import_name)
            if target_ring is None:
                _add_violation(
                    violations,
                    "test_ring:unassigned_target",
                    f"{module_name} -> {import_name}",
                )
            elif not _is_ring_import_allowed(source_ring, target_ring, import_name):
                _add_violation(
                    violations,
                    f"test_import:{source_ring}->{target_ring}",
                    f"{module_name} -> {import_name}",
                )


def _expression_name(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name):
            return name
        case ast.Attribute(value=value, attr=attr):
            prefix = _expression_name(value)
            return f"{prefix}.{attr}" if prefix else attr
        case ast.Call(func=func):
            return _expression_name(func)
        case _:
            return ""


def _model_store_violations(
    root: Path,
    violations: dict[str, set[str]],
) -> None:
    for module_name, path in _iter_codeclone_modules(root):
        if module_name == "codeclone.models" or module_name.startswith(
            "codeclone.models."
        ):
            continue
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "pydantic" or alias.name.startswith("pydantic."):
                        _add_violation(
                            violations,
                            "model_store:pydantic_dependency",
                            f"{module_name} -> {alias.name}",
                        )
            elif isinstance(node, ast.ImportFrom):
                imported_module = node.module or ""
                if imported_module == "pydantic" or imported_module.startswith(
                    "pydantic."
                ):
                    _add_violation(
                        violations,
                        "model_store:pydantic_dependency",
                        f"{module_name} -> {imported_module}",
                    )
            elif isinstance(node, ast.ClassDef):
                if any(
                    _expression_name(base).split(".")[-1] == "BaseModel"
                    for base in node.bases
                ):
                    _add_violation(
                        violations,
                        "model_store:base_model_definition",
                        f"{module_name}::{node.name}",
                    )
                if any(
                    _expression_name(decorator).split(".")[-1] == "dataclass"
                    for decorator in node.decorator_list
                ):
                    _add_violation(
                        violations,
                        "model_store:dataclass_definition",
                        f"{module_name}::{node.name}",
                    )


def _architecture_boundary_violations(root: Path) -> dict[str, tuple[str, ...]]:
    violations: dict[str, set[str]] = {}
    _production_import_violations(root, violations)
    _test_import_violations(root, violations)
    _model_store_violations(root, violations)
    return {
        family: tuple(sorted(items))
        for family, items in sorted(violations.items())
        if items
    }


def _string_mapping(value: object, *, field: str) -> dict[str, object]:
    assert isinstance(value, dict), f"{field} must be an object"
    result: dict[str, object] = {}
    for key, item in value.items():
        assert isinstance(key, str), f"{field} keys must be strings"
        result[key] = item
    return result


def _load_boundary_allowlist(
    path: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    document = _string_mapping(json.loads(path.read_text("utf-8")), field="root")
    assert document.get("schema_version") == 1
    assert document.get("policy") == _BOUNDARY_ALLOWLIST_POLICY
    raw_violations = _string_mapping(document.get("violations"), field="violations")
    violations: dict[str, tuple[str, ...]] = {}
    for family, raw_items in raw_violations.items():
        assert isinstance(raw_items, list), f"{family} must be an array"
        validated_items: list[str] = []
        for item in raw_items:
            assert isinstance(item, str), f"{family} entries must be strings"
            validated_items.append(item)
        items = tuple(validated_items)
        assert items == tuple(sorted(set(items))), f"{family} must be sorted/unique"
        violations[family] = items

    raw_counts = _string_mapping(document.get("counts"), field="counts")
    counts: dict[str, int] = {}
    for family, raw_count in raw_counts.items():
        assert isinstance(raw_count, int), f"{family} count must be an integer"
        counts[family] = raw_count
    return violations, counts


def _ratchet_delta(
    current: dict[str, tuple[str, ...]],
    allowed: dict[str, tuple[str, ...]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    unexpected = {
        family: tuple(sorted(set(items) - set(allowed.get(family, ()))))
        for family, items in current.items()
        if set(items) - set(allowed.get(family, ()))
    }
    resolved = {
        family: tuple(sorted(set(items) - set(current.get(family, ()))))
        for family, items in allowed.items()
        if set(items) - set(current.get(family, ()))
    }
    return unexpected, resolved


def test_phase39s_ratchet_detects_growth_and_stale_entries() -> None:
    unexpected, resolved = _ratchet_delta(
        {"edge": ("kept", "new")},
        {"edge": ("kept", "resolved")},
    )
    assert unexpected == {"edge": ("new",)}
    assert resolved == {"edge": ("resolved",)}


def test_phase39s_architecture_boundary_ratchet() -> None:
    root = Path(__file__).resolve().parents[1]
    current = _architecture_boundary_violations(root)
    allowed, counts = _load_boundary_allowlist(_BOUNDARY_ALLOWLIST_PATH)

    expected_counts = {family: len(items) for family, items in sorted(allowed.items())}
    assert counts == expected_counts

    unexpected, resolved = _ratchet_delta(current, allowed)
    assert unexpected == {}, (
        "Phase 39S boundary ratchet found new violations; do not grow the "
        f"allowlist: {unexpected}"
    )
    assert resolved == {}, (
        f"Phase 39S boundary violations were resolved; shrink the allowlist: {resolved}"
    )


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
                "codeclone.observability",
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


def test_non_mcp_surfaces_do_not_import_mcp_blast_radius_module() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = "codeclone.surfaces.mcp._blast_radius"
    violations: list[str] = []
    for module_name, path in _iter_codeclone_modules(root):
        if module_name.startswith("codeclone.surfaces.mcp"):
            continue
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))
        violations.extend(
            f"{module_name} -> {import_name}"
            for import_name in imports
            if import_name == forbidden or import_name.startswith(forbidden + ".")
        )
    assert violations == []


_FORBIDDEN_SURFACE_PREFIXES = (
    "codeclone.surfaces.",
    "codeclone.ui_messages",
    "codeclone.report.html",
)


def _assert_no_forbidden_surface_imports(package_prefix: str) -> None:
    root = Path(__file__).resolve().parents[1]
    violations: list[str] = []
    for module_name, path in _iter_codeclone_modules(root):
        if not module_name.startswith(package_prefix):
            continue
        imports = _iter_local_imports(module_name, path.read_text("utf-8"))
        violations.extend(
            f"{module_name} -> {import_name}"
            for import_name in imports
            if any(
                import_name == prefix.rstrip(".") or import_name.startswith(prefix)
                for prefix in _FORBIDDEN_SURFACE_PREFIXES
            )
        )
    assert violations == []


def test_analytics_package_does_not_import_forbidden_surfaces() -> None:
    _assert_no_forbidden_surface_imports("codeclone.analytics")


def test_memory_package_does_not_import_forbidden_surfaces() -> None:
    _assert_no_forbidden_surface_imports("codeclone.memory")
