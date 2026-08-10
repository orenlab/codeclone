# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.findings.clones.golden_fixtures import (
    GoldenFixturePatternError,
    build_suppressed_clone_groups,
    normalize_golden_fixture_patterns,
    path_matches_golden_fixture_pattern,
    split_clone_groups_for_golden_fixtures,
)

REPO_ROOT = Path(__file__).parent.parent


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


# The 39Y fixture corpora. Every one of these trees carries deliberate rename
# twins, because the phase's own mandate is that a fixture states its ground
# truth by pairing an original with a renamed copy. Those pairs are corpus
# construction, not findings about this project, so they belong in the
# suppression channel with a visible counter rather than in the user-facing
# clone list.
_DELIBERATE_TWIN_FIXTURE_TREES = (
    "tests/fixtures/clone_tiers",
    "tests/fixtures/design_metrics",
    "tests/fixtures/fingerprint_binding",
    "tests/fixtures/liveness_policy",
    "tests/fixtures/near_miss_witness",
    "tests/fixtures/source_kind",
    "tests/fixtures/statement_reachability",
)


def _project_golden_fixture_patterns() -> tuple[str, ...]:
    from codeclone.config.pyproject_loader import load_pyproject_config

    config = load_pyproject_config(REPO_ROOT)
    declared = config.get("golden_fixture_paths", ())
    assert isinstance(declared, (list, tuple)), (
        "pyproject [tool.codeclone] no longer declares golden_fixture_paths as a "
        "list; the suppression channel would silently carry nothing"
    )
    return normalize_golden_fixture_patterns([str(entry) for entry in declared])


@pytest.mark.parametrize("tree", _DELIBERATE_TWIN_FIXTURE_TREES)
def test_project_routes_every_deliberate_twin_tree_through_suppression(
    tree: str,
) -> None:
    """Each 39Y fixture corpus must reach the golden_fixture channel.

    Parametrised per tree on purpose: a single aggregate assertion would let
    five trees carry a sixth that nothing covers.
    """

    split = split_clone_groups_for_golden_fixtures(
        groups={
            "twins": [
                {"filepath": f"/repo/{tree}/original.py"},
                {"filepath": f"/repo/{tree}/renamed.py"},
            ]
        },
        kind="function",
        golden_fixture_paths=_project_golden_fixture_patterns(),
        scan_root="/repo",
    )

    assert set(split.suppressed_groups) == {"twins"}, (
        f"{tree} is not covered by golden_fixture_paths, so its deliberate "
        f"twins are reported as findings about this project"
    )
    suppressed = build_suppressed_clone_groups(
        kind="function",
        groups=split.suppressed_groups,
        matched_patterns=split.matched_patterns,
    )
    assert [group.suppression_rule for group in suppressed] == ["golden_fixture"]


def test_declared_patterns_never_reach_production_code() -> None:
    """The source-kind guard holds however the patterns are written.

    Suppression is a statement about corpus construction, so it may never
    silence a finding about shipped code. Two independent refusals carry that:
    a pattern outside the test scope is rejected outright, and a group is kept
    active as soon as one member is production -- even when every declared
    pattern would otherwise match the rest of it.
    """

    with pytest.raises(GoldenFixturePatternError, match="must target tests/"):
        normalize_golden_fixture_patterns(["codeclone/*"])

    patterns = _project_golden_fixture_patterns()
    split = split_clone_groups_for_golden_fixtures(
        groups={
            "leaks_into_production": [
                {"filepath": "/repo/tests/fixtures/clone_tiers/original.py"},
                {"filepath": "/repo/codeclone/analysis/units.py"},
            ]
        },
        kind="function",
        golden_fixture_paths=patterns,
        scan_root="/repo",
    )

    assert set(split.active_groups) == {"leaks_into_production"}
    assert split.suppressed_groups == {}
