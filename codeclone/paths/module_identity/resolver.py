# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Pure manifest-relative file and Python-module identity resolution."""

from __future__ import annotations

import keyword
from pathlib import Path, PurePosixPath

from codeclone.models import (
    FileIdentity,
    ImportMount,
    PythonModuleIdentity,
    ResolvedSourceIdentity,
)

from .portable import normalize_identity_path


def _dotted_segments(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(value.split("."))


def _segments_are_importable(segments: tuple[str, ...]) -> bool:
    return bool(segments) and all(
        segment.isidentifier() and not keyword.iskeyword(segment)
        for segment in segments
    )


def _normalized_mount(mount: ImportMount) -> ImportMount:
    path = normalize_identity_path(mount.path)
    pure_path = PurePosixPath(path)
    if not path or pure_path.is_absolute() or ".." in pure_path.parts:
        raise ValueError("import mount paths must be repository-relative")
    prefix = _dotted_segments(mount.module_prefix)
    if prefix and not _segments_are_importable(prefix):
        raise ValueError("import mount prefixes must contain valid identifiers")
    return ImportMount(
        path=path,
        module_prefix=mount.module_prefix,
        origin=mount.origin,
    )


def normalize_import_mounts(
    import_mounts: tuple[ImportMount, ...],
) -> tuple[ImportMount, ...]:
    """Normalize and deterministically order an import-mount policy."""

    normalized = {_normalized_mount(mount) for mount in import_mounts}
    return tuple(
        sorted(
            normalized,
            key=lambda mount: (mount.path, mount.module_prefix, mount.origin),
        )
    )


def repository_relative_path(*, root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "source path must be inside the resolved repository root"
        ) from exc
    normalized = normalize_identity_path(relative.as_posix())
    if normalized in {"", "."} or ".." in PurePosixPath(normalized).parts:
        raise ValueError("source path must name a repository file")
    return normalized


def _mount_relative_path(
    file_path: str,
    mount: ImportMount,
) -> PurePosixPath | None:
    try:
        return PurePosixPath(file_path).relative_to(PurePosixPath(mount.path))
    except ValueError:
        return None


def _selected_mount(
    file_path: str,
    import_mounts: tuple[ImportMount, ...],
) -> tuple[ImportMount, PurePosixPath] | None:
    candidates: list[tuple[ImportMount, PurePosixPath]] = []
    for mount in normalize_import_mounts(import_mounts):
        relative = _mount_relative_path(file_path, mount)
        if relative is not None:
            candidates.append((mount, relative))
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (
            -len(PurePosixPath(item[0].path).parts),
            item[0].path,
            item[0].module_prefix,
            item[0].origin,
        ),
    )


def _python_module_identity(
    *,
    mount: ImportMount,
    relative: PurePosixPath,
) -> PythonModuleIdentity | None:
    if relative.suffix != ".py":
        return None
    is_package = relative.name == "__init__.py"
    relative_segments = (
        relative.parent.parts if is_package else relative.with_suffix("").parts
    )
    module_segments = (*_dotted_segments(mount.module_prefix), *relative_segments)
    if not _segments_are_importable(module_segments):
        return None
    module = ".".join(module_segments)
    package = (
        module
        if is_package
        else module.rsplit(".", maxsplit=1)[0]
        if "." in module
        else ""
    )
    return PythonModuleIdentity(
        module=module,
        package=package,
        is_package=is_package,
        mount_path=mount.path,
        origin="import_mount",
        node_kind="regular_package" if is_package else "module_file",
    )


def resolve_source_identity(
    *,
    root: Path,
    path: Path,
    import_mounts: tuple[ImportMount, ...],
) -> ResolvedSourceIdentity:
    """Resolve one source without reading sys.path or importing packages."""

    file_path = repository_relative_path(root=root, path=path)
    selected = _selected_mount(file_path, import_mounts)
    python_module = None
    if selected is not None:
        mount, relative = selected
        python_module = _python_module_identity(mount=mount, relative=relative)
    return ResolvedSourceIdentity(
        file=FileIdentity(path=file_path),
        python_module=python_module,
    )


__all__ = [
    "normalize_import_mounts",
    "repository_relative_path",
    "resolve_source_identity",
]
