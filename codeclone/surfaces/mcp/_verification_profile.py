# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Verification profile classifier for the patch contract.

Classifies a patch by its changed file types to determine which structural
checks are applicable.  The profile is **derived** from actual changed files,
never declared by the agent.

Priority chain (highest wins):
1. State artifact patterns  → STATE_ARTIFACT_CHANGE
2. Python source extensions → PYTHON_STRUCTURAL
3. Governance config        → GOVERNANCE_CONFIG
4. Documentation patterns   → DOCUMENTATION_ONLY
5. Fallback                 → NON_PYTHON_PATCH

Invariants:
- ``classify_patch`` is a pure function: same input always yields same profile.
- A single file from a higher-priority category overrides the rest.
- Scope/forbidden checks are **not** gated by profile — they always run.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from fnmatch import fnmatchcase
from typing import Final

from ...paths.workspace import FORBIDDEN_WORKSPACE_GLOBS
from .messages.verification import (
    EMPTY_PROFILE_REASON,
    PROFILE_REASONS,
)
from .messages.verification import (
    profile_accepted_message as _profile_accepted_message,
)
from .messages.verification import (
    profile_limitations as _profile_limitations,
)
from .messages.verification import (
    profile_unverified_message as _profile_unverified_message,
)


class VerificationProfile(str, Enum):
    """Verification depth derived from the patch diff."""

    PYTHON_STRUCTURAL = "python_structural"
    DOCUMENTATION_ONLY = "documentation_only"
    GOVERNANCE_CONFIG = "governance_config"
    NON_PYTHON_PATCH = "non_python_patch"
    STATE_ARTIFACT_CHANGE = "state_artifact_change"


# ── pattern sets ────────────────────────────────────────────────────

STATE_ARTIFACT_PATTERNS: Final[tuple[str, ...]] = (
    "codeclone.baseline.json",
    *FORBIDDEN_WORKSPACE_GLOBS,
)

PYTHON_SOURCE_EXTENSIONS: Final[tuple[str, ...]] = (".py", ".pyi")

GOVERNANCE_CONFIG_PATTERNS: Final[tuple[str, ...]] = (
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
    "mypy.ini",
    "ruff.toml",
    ".coveragerc",
    "coverage.toml",
    ".pre-commit-config.yaml",
    ".github/workflows/*",
    ".github/workflows/**",
    ".github/actions/*",
    ".github/actions/**",
    "py.typed",
    "Makefile",
    "Dockerfile",
    "docker-compose*.yml",
)

DOCUMENTATION_EXTENSIONS: Final[tuple[str, ...]] = (
    ".md",
    ".rst",
    ".txt",
    ".adoc",
    ".textile",
)

DOCUMENTATION_PATTERNS: Final[tuple[str, ...]] = (
    "docs/**",
    "doc/**",
    "README*",
    "CHANGELOG*",
    "CHANGES*",
    "HISTORY*",
    "NEWS*",
    "LICENSE*",
    "LICENCE*",
    "COPYING*",
    "NOTICE*",
    "CONTRIBUTING*",
    "CONTRIBUTORS*",
    "AUTHORS*",
    "CREDITS*",
    "MAINTAINERS*",
    "THANKS*",
    "SECURITY*",
    "CODE_OF_CONDUCT*",
)


# ── check names ─────────────────────────────────────────────────────

CHECK_PROFILE_CLASSIFICATION: Final = "verification_profile_classification"
CHECK_SCOPE: Final = "scope_check"
CHECK_FORBIDDEN: Final = "forbidden_paths_check"
CHECK_STRUCTURAL_DELTA: Final = "python_structural_delta"
CHECK_GATE_COMPARISON: Final = "gate_comparison"
CHECK_WORSENED_SYMBOLS: Final = "worsened_symbols"

_ALL_STRUCTURAL_CHECKS: Final[tuple[str, ...]] = (
    CHECK_STRUCTURAL_DELTA,
    CHECK_GATE_COMPARISON,
    CHECK_WORSENED_SYMBOLS,
)

_ALWAYS_PERFORMED: Final[tuple[str, ...]] = (
    CHECK_PROFILE_CLASSIFICATION,
    CHECK_SCOPE,
    CHECK_FORBIDDEN,
)


# ── check matrix ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CheckMatrix:
    """Deterministic check matrix for a verification profile."""

    profile: VerificationProfile
    after_run_required: bool
    structural_checks_applicable: bool

    @property
    def checks_performed(self) -> tuple[str, ...]:
        if self.structural_checks_applicable:
            return (*_ALWAYS_PERFORMED, *_ALL_STRUCTURAL_CHECKS)
        return _ALWAYS_PERFORMED

    @property
    def checks_not_applicable(self) -> tuple[str, ...]:
        if self.structural_checks_applicable:
            return ()
        return _ALL_STRUCTURAL_CHECKS


_MATRICES: Final[dict[VerificationProfile, CheckMatrix]] = {
    VerificationProfile.PYTHON_STRUCTURAL: CheckMatrix(
        profile=VerificationProfile.PYTHON_STRUCTURAL,
        after_run_required=True,
        structural_checks_applicable=True,
    ),
    VerificationProfile.GOVERNANCE_CONFIG: CheckMatrix(
        profile=VerificationProfile.GOVERNANCE_CONFIG,
        after_run_required=True,
        structural_checks_applicable=False,
    ),
    VerificationProfile.DOCUMENTATION_ONLY: CheckMatrix(
        profile=VerificationProfile.DOCUMENTATION_ONLY,
        after_run_required=False,
        structural_checks_applicable=False,
    ),
    VerificationProfile.NON_PYTHON_PATCH: CheckMatrix(
        profile=VerificationProfile.NON_PYTHON_PATCH,
        after_run_required=False,
        structural_checks_applicable=False,
    ),
    VerificationProfile.STATE_ARTIFACT_CHANGE: CheckMatrix(
        profile=VerificationProfile.STATE_ARTIFACT_CHANGE,
        after_run_required=False,
        structural_checks_applicable=False,
    ),
}


def check_matrix(profile: VerificationProfile) -> CheckMatrix:
    """Return the deterministic check matrix for *profile*."""
    return _MATRICES[profile]


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Immutable result of ``classify_patch``."""

    profile: VerificationProfile
    reason: str
    python_source_touched: bool
    state_artifact_touched: bool
    governance_config_touched: bool

    def to_payload(self) -> dict[str, object]:
        matrix = check_matrix(self.profile)
        return {
            "verification_profile": self.profile.value,
            "profile_reason": self.reason,
            "python_source_touched": self.python_source_touched,
            "after_run_required": matrix.after_run_required,
            "checks_performed": list(matrix.checks_performed),
            "checks_not_applicable": list(matrix.checks_not_applicable),
        }


def classify_patch(
    changed_files: Sequence[str],
) -> ClassificationResult:
    """Classify a patch by its changed file set.

    Pure function — deterministic for the same input.  Priority:
    state artifact > Python source > governance config > docs > fallback.

    When *changed_files* is empty, returns ``NON_PYTHON_PATCH`` with a
    dedicated reason.
    """
    if not changed_files:
        return ClassificationResult(
            profile=VerificationProfile.NON_PYTHON_PATCH,
            reason=EMPTY_PROFILE_REASON,
            python_source_touched=False,
            state_artifact_touched=False,
            governance_config_touched=False,
        )

    has_state_artifact, has_python_source, has_governance_config = False, False, False
    all_documentation = True
    normalized_paths = filter(None, (_normalize(p) for p in changed_files))

    for normalized in normalized_paths:
        if _matches_any(normalized, STATE_ARTIFACT_PATTERNS):
            has_state_artifact = True
        elif _is_python_source(normalized):
            has_python_source = True
        elif _matches_any(normalized, GOVERNANCE_CONFIG_PATTERNS):
            has_governance_config = True
        elif _is_documentation(normalized):
            continue

        all_documentation = False

    # Priority chain: state artifact > python > governance > docs > fallback
    if has_state_artifact:
        profile = VerificationProfile.STATE_ARTIFACT_CHANGE
    elif has_python_source:
        profile = VerificationProfile.PYTHON_STRUCTURAL
    elif has_governance_config:
        profile = VerificationProfile.GOVERNANCE_CONFIG
    elif all_documentation:
        profile = VerificationProfile.DOCUMENTATION_ONLY
    else:
        profile = VerificationProfile.NON_PYTHON_PATCH

    return ClassificationResult(
        profile=profile,
        reason=PROFILE_REASONS[profile.value],
        python_source_touched=has_python_source,
        state_artifact_touched=has_state_artifact,
        governance_config_touched=has_governance_config,
    )


def profile_limitations(profile: VerificationProfile) -> tuple[str, ...]:
    """Return human-readable limitations for *profile*."""
    return _profile_limitations(profile.value)


def profile_accepted_message(profile: VerificationProfile) -> str:
    """Return the accepted message for a lightweight-verified profile."""
    return _profile_accepted_message(profile.value)


def profile_unverified_message(profile: VerificationProfile) -> str:
    """Return the unverified message when after_run is missing."""
    return _profile_unverified_message(profile.value)


# ── internals ───────────────────────────────────────────────────────


def _normalize(path: str) -> str:
    text = path.replace("\\", "/").strip()
    if text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _is_python_source(path: str) -> bool:
    return any(path.endswith(ext) for ext in PYTHON_SOURCE_EXTENSIONS)


def _is_documentation(path: str) -> bool:
    if any(path.endswith(ext) for ext in DOCUMENTATION_EXTENSIONS):
        return True
    return _matches_any(path, DOCUMENTATION_PATTERNS)


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    for pattern in patterns:
        if fnmatchcase(path, pattern):
            return True
        # Also match the basename for non-glob patterns (e.g. "pyproject.toml").
        if "/" not in pattern and "*" not in pattern:
            basename = path.rsplit("/", 1)[-1] if "/" in path else path
            if fnmatchcase(basename, pattern):
                return True
    return False


__all__ = [
    "CHECK_FORBIDDEN",
    "CHECK_GATE_COMPARISON",
    "CHECK_PROFILE_CLASSIFICATION",
    "CHECK_SCOPE",
    "CHECK_STRUCTURAL_DELTA",
    "CHECK_WORSENED_SYMBOLS",
    "DOCUMENTATION_EXTENSIONS",
    "DOCUMENTATION_PATTERNS",
    "GOVERNANCE_CONFIG_PATTERNS",
    "PYTHON_SOURCE_EXTENSIONS",
    "STATE_ARTIFACT_PATTERNS",
    "CheckMatrix",
    "ClassificationResult",
    "VerificationProfile",
    "check_matrix",
    "classify_patch",
    "profile_accepted_message",
    "profile_limitations",
    "profile_unverified_message",
]
