# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical module-identity manifest bytes, digest, and observed batch owner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Final

from codeclone.contracts import MODULE_IDENTITY_VERSION
from codeclone.models import (
    AnalysisMount,
    ImportMount,
    ModuleIdentityBuildResult,
    ModuleIdentityManifest,
    ModuleIdentityStrategy,
    PathNormalizationPolicy,
    PortablePathIssue,
)
from codeclone.observability import span

from .portable import normalize_identity_path, validate_portable_paths
from .resolver import (
    normalize_import_mounts,
    repository_relative_path,
    resolve_source_identity,
)

_MANIFEST_DIGEST_DOMAIN: Final = b"ccmi2:manifest\x00"
_COLLISION_KINDS: Final = frozenset({"case_collision", "nfc_collision"})

LEGACY_MODULE_IDENTITY_KILL_INVENTORY: Final[tuple[tuple[str, str], ...]] = (
    ("codeclone/analysis/blast_radius.py", "39P"),
    ("codeclone/core/worker.py", "39H"),
    ("codeclone/memory/ingest/extractors.py", "39Q"),
    ("codeclone/memory/paths.py", "39Q"),
    ("codeclone/memory/project.py", "39Q"),
    ("codeclone/report/document/_design_groups.py", "39O"),
    ("codeclone/report/html/sections/_overview.py", "39R"),
    ("codeclone/report/overview.py", "39O"),
    ("codeclone/report/suggestions.py", "39O"),
    ("codeclone/scanner/__init__.py", "39H"),
    ("codeclone/surfaces/mcp/_blast_radius.py", "39P"),
    ("codeclone/surfaces/mcp/_implementation_context.py", "39P"),
)


class ModuleIdentityCollisionError(ValueError):
    """A normalized identity set cannot be represented portably."""

    def __init__(
        self,
        *,
        manifest_digest: str,
        issues: tuple[PortablePathIssue, ...],
    ) -> None:
        self.manifest_digest = manifest_digest
        self.issues = issues
        issue_text = ", ".join(
            f"{issue.kind}:{'|'.join(issue.paths)}" for issue in issues
        )
        super().__init__(f"module identity collision ({issue_text})")


def _manifest_payload(manifest: ModuleIdentityManifest) -> dict[str, object]:
    return {
        "module_identity_version": manifest.module_identity_version,
        "strategy": manifest.strategy,
        "import_mounts": [
            {
                "path": mount.path,
                "module_prefix": mount.module_prefix,
                "origin": mount.origin,
            }
            for mount in manifest.import_mounts
        ],
        "analysis_mount": {
            "path": manifest.analysis_mount.path,
            "origin": manifest.analysis_mount.origin,
        },
        "normalization": {
            "path_form": manifest.normalization.path_form,
            "case_sensitive": manifest.normalization.case_sensitive,
        },
    }


def manifest_json(manifest: ModuleIdentityManifest) -> str:
    return json.dumps(
        _manifest_payload(manifest),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def manifest_digest(manifest_bytes: str) -> str:
    return hashlib.sha256(
        _MANIFEST_DIGEST_DOMAIN + manifest_bytes.encode("utf-8")
    ).hexdigest()


def _normalized_analysis_mount_path(path: str) -> str:
    normalized = normalize_identity_path(path)
    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise ValueError("analysis mount path must be repository-relative")
    return normalized


def build_module_identity_manifest(
    *,
    root: Path,
    paths: Iterable[Path],
    import_mounts: tuple[ImportMount, ...],
    strategy: ModuleIdentityStrategy,
    analysis_mount_path: str = ".",
) -> ModuleIdentityBuildResult:
    """Build one deterministic identity batch under one owning observer span."""

    with span(name="manifest.build") as manifest_span:
        source_paths = tuple(paths)
        mounts = normalize_import_mounts(import_mounts)
        manifest = ModuleIdentityManifest(
            module_identity_version=MODULE_IDENTITY_VERSION,
            strategy=strategy,
            import_mounts=mounts,
            analysis_mount=AnalysisMount(
                path=_normalized_analysis_mount_path(analysis_mount_path)
            ),
            normalization=PathNormalizationPolicy(),
        )
        canonical_json = manifest_json(manifest)
        digest = manifest_digest(canonical_json)
        relative_paths = tuple(
            repository_relative_path(root=root, path=path) for path in source_paths
        )
        portability = validate_portable_paths(relative_paths)
        collision_issues = tuple(
            issue for issue in portability.issues if issue.kind in _COLLISION_KINDS
        )
        portability_failures = tuple(
            issue for issue in portability.issues if issue.kind not in _COLLISION_KINDS
        )
        identities = tuple(
            sorted(
                (
                    resolve_source_identity(
                        root=root,
                        path=path,
                        import_mounts=mounts,
                    )
                    for path in source_paths
                ),
                key=lambda identity: identity.file.path,
            )
        )
        resolved_count = sum(
            identity.python_module is not None for identity in identities
        )
        manifest_span.set_counter("manifest_input_files", len(identities))
        manifest_span.set_counter("manifest_resolved_modules", resolved_count)
        manifest_span.set_counter(
            "manifest_null_modules", len(identities) - resolved_count
        )
        manifest_span.set_counter("manifest_mounts", len(mounts))
        manifest_span.set_counter("manifest_collisions", len(collision_issues))
        manifest_span.set_counter(
            "manifest_portability_failures", len(portability_failures)
        )
        if collision_issues:
            raise ModuleIdentityCollisionError(
                manifest_digest=digest,
                issues=collision_issues,
            )

        return ModuleIdentityBuildResult(
            manifest=manifest,
            manifest_json=canonical_json,
            manifest_digest=digest,
            identities=identities,
            portability=portability,
        )


__all__ = [
    "LEGACY_MODULE_IDENTITY_KILL_INVENTORY",
    "ModuleIdentityCollisionError",
    "build_module_identity_manifest",
    "manifest_digest",
    "manifest_json",
]
