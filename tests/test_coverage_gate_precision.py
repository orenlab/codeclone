# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The coverage gate refuses a total one hundredth below its threshold.

pytest-cov takes its exit status from ``coverage.results.should_fail_under``,
which rounds the total to ``[tool.coverage.report] precision`` decimals before
comparing it with the threshold; its terminal summary compares the unrounded
total.  With the default precision 0, a 98.98% total rounds to 99, passes
``--cov-fail-under=99`` and still prints "FAIL Required test coverage".
"""

from __future__ import annotations

import re
from pathlib import Path

import coverage
from coverage.config import CoverageConfig
from coverage.results import should_fail_under

REPO_ROOT = Path(__file__).resolve().parents[1]


def _coverage_config() -> CoverageConfig:
    # Read through coverage itself, as pytest-cov does, not by parsing TOML.
    return coverage.Coverage(config_file=str(REPO_ROOT / "pyproject.toml")).config


def _ci_fail_unders() -> list[float]:
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    return [
        float(value)
        for value in re.findall(r"--cov-fail-under=(\d+(?:\.\d+)?)", workflow)
    ]


def test_ci_coverage_gate_uses_the_configured_threshold() -> None:
    assert _ci_fail_unders() == [_coverage_config().fail_under]


def test_coverage_gate_refuses_a_total_one_hundredth_below_the_threshold() -> None:
    config = _coverage_config()
    threshold = config.fail_under

    assert should_fail_under(threshold - 0.01, threshold, config.precision)
    assert not should_fail_under(threshold, threshold, config.precision)
