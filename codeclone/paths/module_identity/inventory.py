# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical one-walk module inventory and immutable registry construction."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Literal

import orjson

from ...models import (
    DigestObject,
    ImportMount,
    ModuleIdentityManifest,
    ModuleIdentityStrategy,
    ModuleInventoryEntry,
    ModuleInventoryIndex,
    ModuleRegistryHandle,
    PackagePrefix,
    ResolvedSourceIdentity,
)
from ...observability import span
from ...scanner import HARD_SAFETY_EXCLUDES, discover_python_files
from .manifest import ModuleIdentityCollisionError, build_module_identity_manifest
from .resolver import normalize_import_mounts

_REGISTRY_DIGEST_DOMAIN = b"codeclone.module-registry.v1\0"
DEFAULT_ANALYSIS_EXCLUDES = ("alembic", "migrations")


class ModuleRegistryCollisionError(ValueError):
    """Two inventory facts claim one module or one mount path ambiguously."""

    def __init__(self, collisions: tuple[str, ...]) -> None:
        self.collisions = collisions
        super().__init__(f"module registry collision ({'|'.join(collisions)})")


def _import_mounts_from_source_roots(
    source_roots: tuple[str, ...],
) -> tuple[ImportMount, ...]:
    mounts: list[ImportMount] = []
    for source_root in source_roots or (".",):
        origin: Literal["explicit", "conventional_src", "root"]
        if source_root == ".":
            origin = "root"
        elif source_root == "src":
            origin = "conventional_src"
        else:
            origin = "explicit"
        mounts.append(ImportMount(path=source_root, module_prefix="", origin=origin))
    return normalize_import_mounts(tuple(mounts))


def _validate_mount_ambiguity(import_mounts: tuple[ImportMount, ...]) -> None:
    by_path: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for mount in import_mounts:
        by_path[mount.path].add((mount.module_prefix, mount.origin))
    collisions = tuple(
        f"mount:{path}"
        for path, definitions in sorted(by_path.items())
        if len(definitions) > 1
    )
    if collisions:
        raise ModuleRegistryCollisionError(collisions)


def _is_analyzed(path: str, analysis_excludes: frozenset[str]) -> bool:
    return not any(part in analysis_excludes for part in PurePosixPath(path).parts)


def _entry_sort_key(entry: ModuleInventoryEntry) -> tuple[object, ...]:
    identity = entry.identity
    module = identity.python_module
    return (
        identity.file.path,
        module.module if module is not None else "",
        module.package if module is not None else "",
        module.is_package if module is not None else False,
        module.mount_path if module is not None else "",
        module.origin if module is not None else "",
        module.node_kind if module is not None else "",
        entry.analyzed,
    )


def _package_prefixes(
    *,
    identities: tuple[ResolvedSourceIdentity, ...],
    import_mounts: tuple[ImportMount, ...],
) -> tuple[PackagePrefix, ...]:
    regular_packages = {
        identity_module.module
        for identity in identities
        if (identity_module := identity.python_module) is not None
        and identity_module.is_package
    }
    synthetic_prefixes: set[str] = set()
    for mount in import_mounts:
        parts = tuple(part for part in mount.module_prefix.split(".") if part)
        synthetic_prefixes.update(
            ".".join(parts[:index]) for index in range(1, len(parts) + 1)
        )

    contributions: dict[str, list[ResolvedSourceIdentity]] = defaultdict(list)
    for identity in identities:
        module = identity.python_module
        if module is None:
            continue
        module_parts = module.module.split(".")
        for index in range(1, len(module_parts)):
            prefix = ".".join(module_parts[:index])
            if prefix not in regular_packages:
                contributions[prefix].append(identity)

    prefixes = []
    for prefix_module, contributors in sorted(contributions.items()):
        mount_paths = tuple(
            sorted(
                {
                    identity.python_module.mount_path
                    for identity in contributors
                    if identity.python_module is not None
                }
            )
        )
        contributing_paths = tuple(
            sorted({identity.file.path for identity in contributors})
        )
        prefixes.append(
            PackagePrefix(
                module=prefix_module,
                node_kind=(
                    "synthetic_prefix"
                    if prefix_module in synthetic_prefixes
                    else "namespace_package"
                ),
                mount_paths=mount_paths,
                contributing_paths=contributing_paths,
            )
        )
    return tuple(
        sorted(
            prefixes,
            key=lambda prefix: (
                prefix.module,
                prefix.node_kind,
                prefix.mount_paths,
                prefix.contributing_paths,
            ),
        )
    )


def _registry_digest_payload(
    *,
    manifest_digest: str,
    entries: tuple[ModuleInventoryEntry, ...],
    package_prefixes: tuple[PackagePrefix, ...],
) -> dict[str, object]:
    inventory_rows: list[dict[str, object]] = []
    for entry in entries:
        identity = entry.identity
        module = identity.python_module
        inventory_rows.append(
            {
                "file": identity.file.path,
                "module": module.module if module is not None else None,
                "package": module.package if module is not None else None,
                "is_package": module.is_package if module is not None else False,
                "mount_path": module.mount_path if module is not None else None,
                "origin": module.origin if module is not None else None,
                "node_kind": module.node_kind if module is not None else None,
                "analyzed": entry.analyzed,
            }
        )
    return {
        "manifest_digest": manifest_digest,
        "inventory": inventory_rows,
        "package_prefixes": [
            {
                "module": prefix.module,
                "node_kind": prefix.node_kind,
                "mount_paths": list(prefix.mount_paths),
                "contributing_paths": list(prefix.contributing_paths),
            }
            for prefix in package_prefixes
        ],
    }


def _freeze_registry(
    *,
    manifest_digest: str,
    manifest: ModuleIdentityManifest,
    identities: tuple[ResolvedSourceIdentity, ...],
    import_mounts: tuple[ImportMount, ...],
    analysis_excludes: frozenset[str],
) -> ModuleRegistryHandle:
    entries = tuple(
        sorted(
            (
                ModuleInventoryEntry(
                    identity=identity,
                    analyzed=_is_analyzed(identity.file.path, analysis_excludes),
                    internality=(
                        "analyzed"
                        if _is_analyzed(identity.file.path, analysis_excludes)
                        else "known_internal_not_analyzed"
                    ),
                )
                for identity in identities
            ),
            key=_entry_sort_key,
        )
    )
    by_module: dict[str, ModuleInventoryEntry] = {}
    collisions: list[str] = []
    for entry in entries:
        module = entry.identity.python_module
        if module is None:
            continue
        if module.module in by_module:
            collisions.append(f"module:{module.module}")
        else:
            by_module[module.module] = entry
    if collisions:
        raise ModuleRegistryCollisionError(tuple(sorted(set(collisions))))

    package_prefixes = _package_prefixes(
        identities=identities,
        import_mounts=import_mounts,
    )
    payload = _registry_digest_payload(
        manifest_digest=manifest_digest,
        entries=entries,
        package_prefixes=package_prefixes,
    )
    canonical = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    digest_value = hashlib.sha256(_REGISTRY_DIGEST_DOMAIN + canonical).hexdigest()
    return ModuleRegistryHandle(
        manifest=manifest,
        manifest_digest=DigestObject(
            domain="ccmi2:manifest",
            algorithm="sha256",
            value=manifest_digest,
        ),
        entries_by_path=ModuleInventoryIndex(
            rows=tuple((entry.identity.file.path, entry) for entry in entries)
        ),
        entries_by_module=ModuleInventoryIndex(rows=tuple(sorted(by_module.items()))),
        package_prefixes=package_prefixes,
        digest=DigestObject(
            domain="codeclone.module-registry.v1",
            algorithm="sha256",
            value=digest_value,
        ),
    )


def build_module_registry(
    *,
    root: Path,
    source_roots: tuple[str, ...] = (".",),
    import_mounts: tuple[ImportMount, ...] | None = None,
    strategy: ModuleIdentityStrategy | None = None,
    analysis_excludes: tuple[str, ...] = DEFAULT_ANALYSIS_EXCLUDES,
    max_files: int = 100_000,
    on_unreadable_path: Callable[[str], None] | None = None,
) -> ModuleRegistryHandle:
    """Build the complete inventory and analyzed subset from one safe walk.

    ``on_unreadable_path`` receives every directory the walk could not read.
    It is a side channel rather than a field on the returned handle because
    the handle is serialized whole into the source-observation digest: a
    permission fault is a property of one run, and putting it in the registry
    would move baseline identity. The caller folds these paths into the
    skipped-file counters that already own lost input.
    """

    with span(name="registry.build") as registry_span:
        paths, hard_excluded, unreadable_paths = discover_python_files(
            str(root),
            hard_excludes=HARD_SAFETY_EXCLUDES,
            max_files=max_files,
        )
        if on_unreadable_path is not None:
            for unreadable_path in unreadable_paths:
                on_unreadable_path(unreadable_path)
        # No span counter for unreadable paths: the observability vocabulary
        # is a reviewed, closed catalogue, and the fact already rides the
        # skipped-file counters that every consumer already reads.
        registry_span.set_counter("registry_discovered", len(paths))
        registry_span.set_counter("registry_inventoried", 0)
        registry_span.set_counter("registry_analyzed", 0)
        registry_span.set_counter("registry_known_internal_not_analyzed", 0)
        registry_span.set_counter("registry_hard_excluded", hard_excluded)
        registry_span.set_counter("registry_null_modules", 0)
        registry_span.set_counter("registry_collisions", 0)
        registry_span.set_counter("registry_worker_installs", 0)
        requested_mounts = (
            import_mounts
            if import_mounts is not None
            else _import_mounts_from_source_roots(source_roots)
        )
        if any(not mount.path for mount in requested_mounts):
            raise ValueError("import mount paths must be repository-relative")
        mounts = normalize_import_mounts(requested_mounts)
        try:
            _validate_mount_ambiguity(mounts)
            resolved_strategy = strategy or (
                mounts[0].origin if len(mounts) == 1 else "explicit"
            )
            build_result = build_module_identity_manifest(
                root=root,
                paths=(Path(path) for path in paths),
                import_mounts=mounts,
                strategy=resolved_strategy,
            )
            registry = _freeze_registry(
                manifest_digest=build_result.manifest_digest,
                manifest=build_result.manifest,
                identities=build_result.identities,
                import_mounts=mounts,
                analysis_excludes=frozenset(analysis_excludes),
            )
        except (ModuleIdentityCollisionError, ModuleRegistryCollisionError) as exc:
            collision_count = (
                len(exc.issues)
                if isinstance(exc, ModuleIdentityCollisionError)
                else len(exc.collisions)
            )
            registry_span.set_counter("registry_collisions", collision_count)
            raise

        entries = tuple(registry.entries_by_path.values())
        analyzed = sum(entry.analyzed for entry in entries)
        null_modules = sum(entry.identity.python_module is None for entry in entries)
        registry_span.set_counter("registry_inventoried", len(entries))
        registry_span.set_counter("registry_analyzed", analyzed)
        registry_span.set_counter(
            "registry_known_internal_not_analyzed", len(entries) - analyzed
        )
        registry_span.set_counter("registry_null_modules", null_modules)
        return registry


__all__ = [
    "DEFAULT_ANALYSIS_EXCLUDES",
    "ModuleRegistryCollisionError",
    "build_module_registry",
]
