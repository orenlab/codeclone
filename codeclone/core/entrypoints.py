# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..models import DeadCandidate
from ..utils.coerce import as_mapping

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class _EntryPointRef:
    module: str
    local: str


def _load_toml_payload(path: Path) -> Mapping[str, object]:
    if not path.exists():
        return {}

    # Treat project metadata as repo-local input; symlink escapes are ignored.
    try:
        resolved = path.resolve()
        resolved.relative_to(path.parent.resolve())
    except (OSError, ValueError):
        return {}

    if sys.version_info >= (3, 11):
        import tomllib

        try:
            with path.open("rb") as config_file:
                payload = tomllib.load(config_file)
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    try:
        tomli_module = importlib.import_module("tomli")
    except ModuleNotFoundError:
        return {}
    load_fn = getattr(tomli_module, "load", None)
    if not callable(load_fn):
        return {}
    try:
        with path.open("rb") as config_file:
            payload = load_fn(config_file)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _entrypoint_ref(value: object) -> _EntryPointRef | None:
    if not isinstance(value, str):
        return None
    ref = value.strip().split(maxsplit=1)[0]
    module, separator, local = ref.partition(":")
    if not separator or not module or not local:
        return None
    if not _is_dotted_identifier(module) or not _is_dotted_identifier(local):
        return None
    return _EntryPointRef(module=module, local=local)


def _is_dotted_identifier(value: str) -> bool:
    return all(part.isidentifier() for part in value.split("."))


def _iter_project_entrypoint_refs(
    payload: Mapping[str, object],
) -> Iterable[_EntryPointRef]:
    project = as_mapping(payload.get("project"))
    for table_name in ("scripts", "gui-scripts"):
        for value in as_mapping(project.get(table_name)).values():
            ref = _entrypoint_ref(value)
            if ref is not None:
                yield ref

    for group in as_mapping(project.get("entry-points")).values():
        for value in as_mapping(group).values():
            ref = _entrypoint_ref(value)
            if ref is not None:
                yield ref

    poetry = as_mapping(as_mapping(payload.get("tool")).get("poetry"))
    for value in as_mapping(poetry.get("scripts")).values():
        ref = _entrypoint_ref(value)
        if ref is not None:
            yield ref


def collect_project_entrypoint_qualnames(
    *,
    root: Path,
    dead_candidates: Sequence[DeadCandidate],
) -> frozenset[str]:
    """Resolve package entry points to exact known dead-code candidate qualnames."""
    refs = tuple(
        _iter_project_entrypoint_refs(_load_toml_payload(root / "pyproject.toml"))
    )
    if not refs:
        return frozenset()

    candidate_qualnames = frozenset(candidate.qualname for candidate in dead_candidates)
    resolved: set[str] = set()
    for ref in refs:
        exact = f"{ref.module}:{ref.local}"
        if exact in candidate_qualnames:
            resolved.add(exact)
            continue

        suffix_matches = {
            qualname
            for qualname in candidate_qualnames
            if _matches_entrypoint_suffix(qualname, ref)
        }
        if len(suffix_matches) == 1:
            resolved.update(suffix_matches)

    return frozenset(sorted(resolved))


def _matches_entrypoint_suffix(qualname: str, ref: _EntryPointRef) -> bool:
    module, separator, local = qualname.partition(":")
    return bool(separator) and local == ref.local and module.endswith(f".{ref.module}")


__all__ = ["collect_project_entrypoint_qualnames"]
