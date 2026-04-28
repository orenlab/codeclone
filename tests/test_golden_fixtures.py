# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.findings.clones.golden_fixtures import (
    GoldenFixturePatternError,
    build_suppressed_clone_groups,
    normalize_golden_fixture_patterns,
    path_matches_golden_fixture_pattern,
    split_clone_groups_for_golden_fixtures,
)


def test_normalize_golden_fixture_patterns_rejects_non_test_scope() -> None:
    with pytest.raises(GoldenFixturePatternError, match="must target tests/"):
        normalize_golden_fixture_patterns(["pkg/golden_*"])


@pytest.mark.parametrize(
    ("pattern", "message"),
    [
        ("", "must be non-empty"),
        ("/tmp/golden_*", "must be repo-relative"),
        ("tests/../fixtures/golden_*", "must not contain '..'"),
    ],
)
def test_normalize_golden_fixture_patterns_rejects_invalid_entries(
    pattern: str,
    message: str,
) -> None:
    with pytest.raises(GoldenFixturePatternError, match=message):
        normalize_golden_fixture_patterns([pattern])


def test_path_matches_golden_fixture_pattern_matches_directory_subtrees() -> None:
    assert path_matches_golden_fixture_pattern(
        "tests/fixtures/golden_project/alpha.py",
        "tests/fixtures/golden_*",
    )
    assert not path_matches_golden_fixture_pattern(
        "tests/helpers/golden_project/alpha.py",
        "tests/fixtures/golden_*",
    )


def test_path_matches_golden_fixture_pattern_rejects_empty_relative_path() -> None:
    assert not path_matches_golden_fixture_pattern("", "tests/fixtures/golden_*")


def test_split_clone_groups_for_golden_fixtures_requires_full_group_match() -> None:
    split = split_clone_groups_for_golden_fixtures(
        groups={
            "golden": [
                {"filepath": "/repo/tests/fixtures/golden_project/a.py"},
                {"filepath": "/repo/tests/fixtures/golden_project/b.py"},
            ],
            "mixed": [
                {"filepath": "/repo/tests/fixtures/golden_project/c.py"},
                {"filepath": "/repo/pkg/mod.py"},
            ],
        },
        kind="function",
        golden_fixture_paths=("tests/fixtures/golden_*",),
        scan_root="/repo",
    )

    assert set(split.active_groups) == {"mixed"}
    assert set(split.suppressed_groups) == {"golden"}
    assert split.matched_patterns == {
        "golden": ("tests/fixtures/golden_*",),
    }


def test_split_clone_groups_for_golden_fixtures_keeps_missing_or_unmatched_items() -> (
    None
):
    split = split_clone_groups_for_golden_fixtures(
        groups={
            "missing": [
                {"filepath": ""},
                {"filepath": "/repo/tests/fixtures/golden_project/b.py"},
            ],
            "unmatched": [
                {"filepath": "/repo/tests/golden_project/a.py"},
                {"filepath": "/repo/tests/golden_project/b.py"},
            ],
        },
        kind="function",
        golden_fixture_paths=("tests/fixtures/golden_*",),
        scan_root="/repo",
    )

    assert set(split.active_groups) == {"missing", "unmatched"}
    assert split.suppressed_groups == {}
    assert split.matched_patterns == {}


def test_build_suppressed_clone_groups_carries_rule_and_patterns() -> None:
    suppressed = build_suppressed_clone_groups(
        kind="function",
        groups={
            "golden": [
                {
                    "filepath": "/repo/tests/fixtures/golden_project/a.py",
                    "qualname": "tests.fixtures.golden_project.a:run",
                }
            ]
        },
        matched_patterns={"golden": ("tests/fixtures/golden_*",)},
    )

    assert len(suppressed) == 1
    group = suppressed[0]
    assert group.group_key == "golden"
    assert group.matched_patterns == ("tests/fixtures/golden_*",)
    assert group.suppression_rule == "golden_fixture"
    assert group.suppression_source == "project_config"


def test_build_suppressed_clone_groups_skips_blank_pattern_bindings() -> None:
    suppressed = build_suppressed_clone_groups(
        kind="function",
        groups={
            "golden": [
                {
                    "filepath": "/repo/tests/fixtures/golden_project/a.py",
                    "qualname": "tests.fixtures.golden_project.a:run",
                }
            ]
        },
        matched_patterns={"golden": ("", "   ")},
    )

    assert suppressed == ()
