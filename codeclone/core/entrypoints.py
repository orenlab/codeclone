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

from ..utils.coerce import as_mapping

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from ..models import DeadCandidate


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


__all__ = [
    "collect_project_distributed_packages",
    "collect_project_entrypoint_qualnames",
]


def collect_project_distributed_packages(root: Path) -> frozenset[str] | None:
    """What ``root`` declares that it ships, or ``None`` if it declares nothing.

    Read here rather than beside the population owner because ``metrics`` may
    not import ``config`` and this module already owns the interpreter-split
    TOML reader; a third copy of it is what this placement avoids.

    Three build backends are read because the axis this input exists for is
    external repositories, and a reader that only understood this project's own
    backend would be a manifest owner that works on exactly one repository.
    ``None`` and ``frozenset()`` are different answers: the first is "no
    manifest", the second is "a manifest that ships nothing", and only the
    first leaves the population alone.
    """

    payload = _load_toml_payload(root / "pyproject.toml")
    tool = payload.get("tool")
    if not isinstance(tool, dict):
        return None
    declared: set[str] = set()
    declared.update(_setuptools_packages(tool.get("setuptools")))
    declared.update(_hatch_packages(tool.get("hatch")))
    declared.update(_poetry_packages(tool.get("poetry")))
    return frozenset(declared) if declared else None


def _setuptools_packages(table: object) -> set[str]:
    if not isinstance(table, dict):
        return set()
    names = set(_string_list(table.get("packages")))
    packages = table.get("packages")
    if isinstance(packages, dict):
        find = packages.get("find")
        if isinstance(find, dict):
            names.update(_glob_prefixes(_string_list(find.get("include"))))
    return {name for name in names if name}


def _hatch_packages(table: object) -> set[str]:
    if not isinstance(table, dict):
        return set()
    build = table.get("build")
    if not isinstance(build, dict):
        return set()
    targets = build.get("targets")
    if not isinstance(targets, dict):
        return set()
    wheel = targets.get("wheel")
    if not isinstance(wheel, dict):
        return set()
    return {_module_of_path(entry) for entry in _string_list(wheel.get("packages"))} - {
        ""
    }


def _poetry_packages(table: object) -> set[str]:
    if not isinstance(table, dict):
        return set()
    entries = table.get("packages")
    if not isinstance(entries, list):
        return set()
    return {
        _module_of_path(str(entry["include"]))
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("include"), str)
    } - {""}


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(entry for entry in value if isinstance(entry, str))


def _glob_prefixes(patterns: tuple[str, ...]) -> set[str]:
    """``codeclone*`` and ``codeclone.*`` both declare the ``codeclone`` tree.

    Only the literal head of a pattern is kept. A pattern is a search
    expression over module names, and the owner needs a prefix it can compare
    against a dotted module identity, so anything from the first wildcard on is
    dropped rather than guessed at.
    """

    prefixes: set[str] = set()
    for pattern in patterns:
        head = pattern.split("*", maxsplit=1)[0].rstrip(".")
        if head:
            prefixes.add(head)
    return prefixes


def _module_of_path(value: str) -> str:
    """``src/example`` and ``example/`` both name the module ``example``."""

    parts = [
        part for part in value.replace("\\", "/").split("/") if part and part != "."
    ]
    if not parts:
        return ""
    if len(parts) > 1 and parts[0] in {"src", "lib"}:
        parts = parts[1:]
    return ".".join(parts)
