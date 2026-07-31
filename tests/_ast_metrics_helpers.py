# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import os
from pathlib import Path
from uuid import UUID

import codeclone.baseline as baseline
from codeclone.analysis import _module_walk as module_walk_mod
from codeclone.analysis.binding import BindingContext, build_module_bindings
from codeclone.contracts import MODULE_IDENTITY_VERSION
from codeclone.models import (
    AnalysisMount,
    DigestObject,
    FileIdentity,
    FileMetrics,
    ImportMount,
    ModuleIdentityManifest,
    ModuleInventoryEntry,
    ModuleInventoryIndex,
    ModuleRegistryHandle,
    PathNormalizationPolicy,
    PythonModuleIdentity,
    ResolvedSourceIdentity,
)
from codeclone.observations.projection import build_observation_bundle
from codeclone.qualnames import QualnameCollector


def bindings_for_tree(tree: ast.Module) -> BindingContext:
    """Module-scope bindings for a tree parsed outside any package context.

    A relative import cannot be resolved without knowing the module's package
    position, so here its alias binds without a proven identity — the same
    answer production gives for a module whose position is unknown.
    """

    return build_module_bindings(
        tree,
        resolve_from_import=lambda node: (
            (node.module or "") if node.level == 0 else None
        ),
    )


def bindings_for_function_node(node: ast.AST) -> BindingContext:
    """Bindings for a standalone function parsed on its own."""

    module = ast.Module(body=[node], type_ignores=[])  # type: ignore[list-item]
    return bindings_for_tree(module).enter(node)


def bindings_for_statements(statements: list[ast.stmt]) -> BindingContext:
    """Function-scope bindings for statements tested outside any function.

    Production only ever wires a statement inside the function that owns it. A
    bare statement is therefore read here under a synthetic function scope, not
    at module scope where every assignment target would be a global and nothing
    would normalize.
    """

    module = ast.parse("def _scope():\n    pass\n")
    function = module.body[0]
    assert isinstance(function, ast.FunctionDef)
    function.body = statements
    return bindings_for_tree(module).enter(function)


def module_registry_context(
    *,
    filepath: str,
    module_name: str | None,
    inventory_modules: tuple[str, ...] = (),
    known_internal_modules: tuple[str, ...] = (),
) -> tuple[ResolvedSourceIdentity, ModuleRegistryHandle]:
    def _identity(path: str, module: str | None) -> ResolvedSourceIdentity:
        is_package = path.endswith("/__init__.py")
        package = ""
        if module is not None:
            package = module if is_package else module.rpartition(".")[0]
        return ResolvedSourceIdentity(
            file=FileIdentity(path=path),
            python_module=(
                PythonModuleIdentity(
                    module=module,
                    package=package,
                    is_package=is_package,
                    mount_path=".",
                    origin="import_mount",
                    node_kind="regular_package" if is_package else "module_file",
                )
                if module is not None
                else None
            ),
        )

    source = _identity(filepath, module_name)
    identities = [source]
    identities.extend(
        _identity(f"{module.replace('.', '/')}.py", module)
        for module in (*inventory_modules, *known_internal_modules)
        if module != module_name
    )
    entries = tuple(
        ModuleInventoryEntry(
            identity=identity,
            analyzed=(
                identity.python_module is None
                or identity.python_module.module not in known_internal_modules
            ),
            internality=(
                "known_internal_not_analyzed"
                if identity.python_module is not None
                and identity.python_module.module in known_internal_modules
                else "analyzed"
            ),
        )
        for identity in sorted(identities, key=lambda item: item.file.path)
    )
    manifest = ModuleIdentityManifest(
        module_identity_version=MODULE_IDENTITY_VERSION,
        strategy="root",
        import_mounts=(ImportMount(path=".", module_prefix="", origin="root"),),
        analysis_mount=AnalysisMount(path="."),
        normalization=PathNormalizationPolicy(),
    )
    return source, ModuleRegistryHandle(
        manifest=manifest,
        manifest_digest=DigestObject(
            domain="ccmi2:manifest",
            algorithm="sha256",
            value="f" * 64,
        ),
        entries_by_path=ModuleInventoryIndex(
            rows=tuple((entry.identity.file.path, entry) for entry in entries)
        ),
        entries_by_module=ModuleInventoryIndex(
            rows=tuple(
                sorted(
                    (module.module, entry)
                    for entry in entries
                    if (module := entry.identity.python_module) is not None
                )
            )
        ),
        package_prefixes=(),
        digest=DigestObject(
            domain="codeclone.module-registry.v1",
            algorithm="sha256",
            value="0" * 64,
        ),
    )


def worker_registry_context(
    *,
    filepath: str,
    root: str,
) -> ModuleRegistryHandle:
    relative_path = Path(os.path.relpath(filepath, root)).as_posix()
    module_parts = list(Path(relative_path).with_suffix("").parts)
    if module_parts[-1] == "__init__":
        module_parts.pop()
    module_name = ".".join(module_parts) or None
    return module_registry_context(
        filepath=relative_path,
        module_name=module_name,
    )[1]


def build_test_module_registry(
    *,
    root: Path,
    source_roots: tuple[str, ...] = (".",),
) -> ModuleRegistryHandle:
    from codeclone.paths.module_identity.inventory import build_module_registry

    return build_module_registry(root=root.resolve(), source_roots=source_roots)


def extract_file_metrics(
    *,
    source: str,
    filepath: str,
    module_registry: ModuleRegistryHandle,
    min_loc: int = 1,
    min_stmt: int = 1,
) -> FileMetrics:
    """Per-file metrics for one already-registered fixture file.

    Extraction lives in a ring the analysis-facing test modules may import,
    but the liveness owners do not. Keeping the plumbing in this shared helper
    lets a test assert an owner's behavior over REAL fixture facts without the
    test module itself reaching across an architectural ring boundary.
    """
    from codeclone.analysis.normalizer import NormalizationConfig
    from codeclone.analysis.units import extract_units_and_stats_from_source

    *_, metrics, _findings = extract_units_and_stats_from_source(
        source=source,
        filepath=filepath,
        identity=module_registry.entries_by_path[filepath].identity,
        registry=module_registry,
        cfg=NormalizationConfig(),
        min_loc=min_loc,
        min_stmt=min_stmt,
    )
    return metrics


def write_native_v3_baseline_fixture(
    path: Path,
    *,
    scope_id: UUID,
    function_clone_keys: tuple[str, ...] = (),
    block_clone_keys: tuple[str, ...] = (),
) -> Path:
    """Write the canonical native-v3 baseline fixture used by surface tests."""
    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        function_clone_keys=tuple(sorted(function_clone_keys)),
        block_clone_keys=tuple(sorted(block_clone_keys)),
    )
    path.write_bytes(
        baseline.canonical_container_bytes(baseline.build_container(bundle, scope_id))
    )
    return path


def tree_collector_and_imports(
    source: str,
    *,
    module_name: str,
) -> tuple[ast.Module, QualnameCollector, frozenset[str]]:
    identity, registry = module_registry_context(
        filepath=f"{module_name.replace('.', '/')}.py",
        module_name=module_name,
    )
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    walk = module_walk_mod._collect_module_walk_data(
        tree=tree,
        source=identity,
        registry=registry,
        collector=collector,
        collect_referenced_names=True,
    )
    return tree, collector, walk.import_names
