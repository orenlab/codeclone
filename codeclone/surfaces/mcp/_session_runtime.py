# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Final

from ...utils.repo_paths import RepoPathPolicy, resolve_under_repo_root

# Single source of truth for which file shapes each MCP artifact kind may take
# when it is allowed to live outside the repository root. All current artifacts
# are CodeClone-format files: JSON baselines/cache and Cobertura XML coverage.
_ARTIFACT_EXTERNAL_SUFFIXES: Final[dict[str, frozenset[str]]] = {
    "baseline": frozenset({".json"}),
    "metrics_baseline": frozenset({".json"}),
    "cache": frozenset({".json"}),
    "coverage_xml": frozenset({".xml"}),
}

# Operators may extend (never replace) the permitted external roots with an
# os.pathsep-separated list. Env/CLI are trusted operator configuration and do
# not widen the MCP request schema.
EXTERNAL_ARTIFACT_ROOTS_ENV: Final = "CODECLONE_EXTERNAL_ARTIFACT_ROOTS"


def _external_artifact_roots(root_path: Path) -> tuple[Path, ...]:
    """Resolved roots an external artifact may live under (Tier 2 anchoring).

    Defaults: the repository root, the system temp dir (CI coverage), and the
    per-user CodeClone cache dir. Extended by ``EXTERNAL_ARTIFACT_ROOTS_ENV``.
    """

    candidates: list[Path] = [
        root_path,
        Path(tempfile.gettempdir()),
        Path("~/.cache/codeclone").expanduser(),
    ]
    env_value = os.environ.get(EXTERNAL_ARTIFACT_ROOTS_ENV, "")
    for chunk in env_value.split(os.pathsep):
        text = chunk.strip()
        if text:
            candidates.append(Path(text).expanduser())
    resolved: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            real = candidate.resolve(strict=False)
        except OSError:
            continue
        if real not in seen:
            seen.add(real)
            resolved.append(real)
    return tuple(resolved)


def resolve_artifact_path(
    raw_value: str,
    root_path: Path,
    *,
    kind: str | None = None,
    allow_external_artifacts: bool = False,
    allow_repo_absolute: bool = False,
) -> Path:
    """Resolve an optional MCP artifact path under one shared policy.

    ``kind`` selects the external extension allowlist and enables external-root
    anchoring plus special-file rejection (Tier 1+2 hardening). When ``kind`` is
    ``None`` the policy is identical to the historical resolver, so legacy
    callers keep their exact behaviour.
    """

    if kind is None:
        external_suffixes: frozenset[str] = frozenset()
        external_roots: tuple[Path, ...] = ()
        reject_special_files = False
    else:
        external_suffixes = _ARTIFACT_EXTERNAL_SUFFIXES[kind]
        external_roots = (
            _external_artifact_roots(root_path) if allow_external_artifacts else ()
        )
        reject_special_files = True
    policy = RepoPathPolicy(
        allow_absolute=allow_external_artifacts or allow_repo_absolute,
        allow_external=allow_external_artifacts,
        external_suffixes=external_suffixes,
        external_roots=external_roots,
        reject_special_files=reject_special_files,
    )
    return resolve_under_repo_root(root_path, raw_value, policy=policy)


def validate_numeric_args(args: object) -> bool:
    return bool(
        not (
            _int_attr(args, "max_baseline_size_mb") < 0
            or _int_attr(args, "max_cache_size_mb") < 0
            or _int_attr(args, "fail_threshold", -1) < -1
            or _int_attr(args, "fail_complexity", -1) < -1
            or _int_attr(args, "fail_coupling", -1) < -1
            or _int_attr(args, "fail_cohesion", -1) < -1
            or _int_attr(args, "fail_health", -1) < -1
            or _int_attr(args, "min_typing_coverage", -1) < -1
            or _int_attr(args, "min_typing_coverage", -1) > 100
            or _int_attr(args, "min_docstring_coverage", -1) < -1
            or _int_attr(args, "min_docstring_coverage", -1) > 100
            or _int_attr(args, "coverage_min") < 0
            or _int_attr(args, "coverage_min") > 100
        )
    )


def resolve_cache_path(*, root_path: Path, args: object) -> Path:
    raw_value = getattr(args, "cache_path", None)
    if isinstance(raw_value, str) and raw_value.strip():
        allow_external_artifacts = bool(
            getattr(args, "allow_external_artifacts", False)
        )
        return resolve_artifact_path(
            raw_value,
            root_path,
            kind="cache",
            allow_external_artifacts=allow_external_artifacts,
            allow_repo_absolute=True,
        )
    from ...paths.workspace import default_cache_path

    return default_cache_path(root_path)


def _int_attr(args: object, name: str, default: int = 0) -> int:
    value = getattr(args, name, default)
    return value if isinstance(value, int) else default
