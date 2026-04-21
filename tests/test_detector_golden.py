# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.baseline import current_python_tag
from codeclone.findings.clones.grouping import build_block_groups, build_groups
from codeclone.scanner import module_name_from_path
from tests._assertions import snapshot_python_tag


def _detect_group_keys(project_root: Path) -> tuple[list[str], list[str]]:
    cfg = NormalizationConfig()
    all_units: list[dict[str, object]] = []
    all_blocks: list[dict[str, object]] = []

    for path in sorted(project_root.glob("*.py")):
        source = path.read_text("utf-8")
        module_name = module_name_from_path(str(project_root), str(path))
        units, blocks, _segments, _source_stats, _file_metrics, _sf = (
            extract_units_and_stats_from_source(
                source=source,
                filepath=str(path),
                module_name=module_name,
                cfg=cfg,
                min_loc=1,
                min_stmt=1,
            )
        )
        all_units.extend(asdict(unit) for unit in units)
        all_blocks.extend(asdict(block) for block in blocks)

    function_group_keys = sorted(build_groups(all_units).keys())
    block_group_keys = sorted(build_block_groups(all_blocks).keys())
    return function_group_keys, block_group_keys


def test_detector_output_matches_golden_fixture() -> None:
    fixture_root = Path("tests/fixtures/golden_project").resolve()
    expected_path = fixture_root / "golden_expected_ids.json"
    expected = json.loads(expected_path.read_text("utf-8"))
    expected_python_tag = snapshot_python_tag(expected)

    # Golden fixture is a detector snapshot for one canonical Python tag.
    # Cross-version behavior is covered by contract/invariant tests.
    runtime_tag = current_python_tag()
    if runtime_tag != expected_python_tag:
        pytest.skip(
            "Golden detector fixture is canonicalized for "
            f"{expected_python_tag}; runtime is {runtime_tag}."
        )

    function_group_keys, block_group_keys = _detect_group_keys(fixture_root)

    assert function_group_keys == expected["function_group_keys"]
    assert block_group_keys == expected["block_group_keys"]
