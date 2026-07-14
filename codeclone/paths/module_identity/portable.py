# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Host-independent path normalization and portable-baseline eligibility."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Final

from codeclone.models import (
    PortablePathIssue,
    PortablePathIssueKind,
    PortablePathVerdict,
)

_PATH_SEPARATOR_RE: Final = re.compile(r"[\\/]")
_WINDOWS_FORBIDDEN_BYTES: Final = frozenset('<>:"|?*')
_WINDOWS_DEVICE_STEMS: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def normalize_identity_path(path: str) -> str:
    """Return a repository-relative POSIX NFC identity string."""

    normalized = unicodedata.normalize("NFC", path.replace("\\", "/"))
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return PurePosixPath(normalized).as_posix()


def _segment_issue_kinds(segment: str) -> tuple[PortablePathIssueKind, ...]:
    kinds: list[PortablePathIssueKind] = []
    if any(ord(character) < 32 for character in segment):
        kinds.append("ascii_control")
    if segment.endswith((".", " ")):
        kinds.append("trailing_dot_or_space")
    if segment.split(".", maxsplit=1)[0].upper() in _WINDOWS_DEVICE_STEMS:
        kinds.append("windows_device")
    if any(character in _WINDOWS_FORBIDDEN_BYTES for character in segment):
        kinds.append("windows_forbidden_byte")
    return tuple(kinds)


def _collision_issues(
    raw_to_normalized: tuple[tuple[str, str], ...],
) -> tuple[PortablePathIssue, ...]:
    by_normalized: dict[str, set[str]] = defaultdict(set)
    for raw_path, normalized_path in raw_to_normalized:
        by_normalized[normalized_path].add(raw_path)

    issues = [
        PortablePathIssue(
            kind="nfc_collision",
            paths=tuple(sorted(raw_paths)),
        )
        for raw_paths in by_normalized.values()
        if len(raw_paths) > 1
    ]

    by_casefold: dict[str, set[str]] = defaultdict(set)
    for _raw_path, normalized_path in raw_to_normalized:
        by_casefold[normalized_path.casefold()].add(normalized_path)
    issues.extend(
        PortablePathIssue(
            kind="case_collision",
            paths=tuple(sorted(normalized_paths)),
        )
        for normalized_paths in by_casefold.values()
        if len(normalized_paths) > 1
    )
    return tuple(issues)


def validate_portable_paths(paths: Iterable[str]) -> PortablePathVerdict:
    """Return sorted typed issues without consulting host filesystem casing."""

    raw_paths = tuple(paths)
    raw_to_normalized = tuple(
        (raw_path, normalize_identity_path(raw_path)) for raw_path in raw_paths
    )
    issues = list(_collision_issues(raw_to_normalized))
    for raw_path, normalized_path in raw_to_normalized:
        segments = tuple(
            segment for segment in _PATH_SEPARATOR_RE.split(raw_path) if segment
        )
        for segment in segments:
            issues.extend(
                PortablePathIssue(kind=kind, paths=(normalized_path,))
                for kind in _segment_issue_kinds(segment)
            )

    ordered_issues = tuple(sorted(issues, key=lambda issue: (issue.kind, issue.paths)))
    return PortablePathVerdict(
        eligible=not ordered_issues,
        normalized_paths=tuple(
            sorted({normalized for _raw, normalized in raw_to_normalized})
        ),
        issues=ordered_issues,
    )


__all__ = ["normalize_identity_path", "validate_portable_paths"]
