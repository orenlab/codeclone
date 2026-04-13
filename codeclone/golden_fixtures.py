# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from .domain.source_scope import SOURCE_KIND_FIXTURES, SOURCE_KIND_TESTS
from .models import (
    GroupItem,
    GroupItemLike,
    GroupMap,
    GroupMapLike,
    SuppressedCloneGroup,
)
from .paths import classify_source_kind, normalize_repo_path, relative_repo_path

CloneGroupKind = Literal["function", "block", "segment"]

GOLDEN_FIXTURE_SUPPRESSION_RULE = "golden_fixture"
GOLDEN_FIXTURE_SUPPRESSION_SOURCE = "project_config"

_ALLOWED_SOURCE_KINDS = frozenset({SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES})


class GoldenFixturePatternError(ValueError):
    """Raised when golden_fixture_paths contains an invalid pattern."""


@dataclass(frozen=True, slots=True)
class GoldenFixtureGroupSplit:
    active_groups: GroupMap
    suppressed_groups: GroupMap
    matched_patterns: dict[str, tuple[str, ...]]


def normalize_golden_fixture_patterns(patterns: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_pattern in patterns:
        pattern = normalize_repo_path(str(raw_pattern))
        while pattern.startswith("./"):
            pattern = pattern[2:]
        pattern = pattern.rstrip("/")
        if not pattern:
            raise GoldenFixturePatternError(
                "tool.codeclone.golden_fixture_paths entries must be non-empty"
            )
        pure_pattern = PurePosixPath(pattern)
        if pure_pattern.is_absolute():
            raise GoldenFixturePatternError(
                "tool.codeclone.golden_fixture_paths entries must be repo-relative"
            )
        if any(part == ".." for part in pure_pattern.parts):
            raise GoldenFixturePatternError(
                "tool.codeclone.golden_fixture_paths entries must not contain '..'"
            )
        source_kind = classify_source_kind(pattern)
        if source_kind not in _ALLOWED_SOURCE_KINDS:
            raise GoldenFixturePatternError(
                "tool.codeclone.golden_fixture_paths entries must target tests/ or "
                "tests/fixtures/ paths"
            )
        if pattern not in seen:
            normalized.append(pattern)
            seen.add(pattern)
    return tuple(normalized)


def path_matches_golden_fixture_pattern(relative_path: str, pattern: str) -> bool:
    normalized_path = normalize_repo_path(relative_path).lstrip("./")
    if not normalized_path:
        return False
    candidate = PurePosixPath(normalized_path)
    candidates = [candidate, *candidate.parents[:-1]]
    return any(path.match(pattern) for path in candidates)


def split_clone_groups_for_golden_fixtures(
    *,
    groups: GroupMapLike,
    kind: CloneGroupKind,
    golden_fixture_paths: Sequence[str],
    scan_root: str = "",
) -> GoldenFixtureGroupSplit:
    active: GroupMap = {}
    suppressed: GroupMap = {}
    matched_patterns: dict[str, tuple[str, ...]] = {}
    if not golden_fixture_paths:
        for group_key in sorted(groups):
            active[group_key] = [_copy_group_item(item) for item in groups[group_key]]
        return GoldenFixtureGroupSplit(
            active_groups=active,
            suppressed_groups=suppressed,
            matched_patterns=matched_patterns,
        )

    for group_key in sorted(groups):
        copied_items = [_copy_group_item(item) for item in groups[group_key]]
        group_patterns = _matched_patterns_for_group(
            copied_items,
            patterns=golden_fixture_paths,
            scan_root=scan_root,
        )
        if group_patterns:
            suppressed[group_key] = copied_items
            matched_patterns[group_key] = group_patterns
        else:
            active[group_key] = copied_items
    return GoldenFixtureGroupSplit(
        active_groups=active,
        suppressed_groups=suppressed,
        matched_patterns=matched_patterns,
    )


def build_suppressed_clone_groups(
    *,
    kind: CloneGroupKind,
    groups: GroupMapLike,
    matched_patterns: Mapping[str, Sequence[str]],
) -> tuple[SuppressedCloneGroup, ...]:
    suppressed_groups: list[SuppressedCloneGroup] = []
    for group_key in sorted(groups):
        patterns = tuple(
            str(pattern).strip()
            for pattern in matched_patterns.get(group_key, ())
            if str(pattern).strip()
        )
        if not patterns:
            continue
        suppressed_groups.append(
            SuppressedCloneGroup(
                kind=kind,
                group_key=group_key,
                items=tuple(_copy_group_item(item) for item in groups[group_key]),
                matched_patterns=patterns,
                suppression_rule=GOLDEN_FIXTURE_SUPPRESSION_RULE,
                suppression_source=GOLDEN_FIXTURE_SUPPRESSION_SOURCE,
            )
        )
    return tuple(suppressed_groups)


def _copy_group_item(item: GroupItemLike) -> GroupItem:
    return {str(key): value for key, value in item.items()}


def _matched_patterns_for_group(
    items: Sequence[GroupItemLike],
    *,
    patterns: Sequence[str],
    scan_root: str,
) -> tuple[str, ...]:
    matched: set[str] = set()
    for item in items:
        filepath = str(item.get("filepath", "")).strip()
        if not filepath:
            return ()
        source_kind = classify_source_kind(filepath, scan_root=scan_root)
        if source_kind not in _ALLOWED_SOURCE_KINDS:
            return ()
        relative_path = relative_repo_path(filepath, scan_root=scan_root)
        item_matches = tuple(
            pattern
            for pattern in patterns
            if path_matches_golden_fixture_pattern(relative_path, pattern)
        )
        if not item_matches:
            return ()
        matched.update(item_matches)
    return tuple(sorted(matched))
