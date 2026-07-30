# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Standing red set for the per-lane B+ baseline doctrine on the CLI surface.

One untrusted lane must not condemn the whole container. The CLI degrades
per lane: a lane no active gate depends on is reported opaque and its novelty
is honestly nulled, while a lane an active gate *does* depend on stays
fail-closed. Degrading is not ignoring.

The CLI runs as a real subprocess here, so the assertions read the true
process exit code rather than an in-process ``SystemExit``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from codeclone.baseline import Baseline, current_python_tag
from codeclone.baseline.container import read_container_v3
from codeclone.baseline.container_digest import (
    canonical_container_bytes,
    compute_lane_digest,
    compute_root_digest,
)
from codeclone.contracts.errors import BaselineValidationError
from codeclone.models import BaselineLaneIndex, ContainerReadSuccess

_SCOPE_ID = "3f2b8c1e-7a41-4d90-9c62-5b0e8a7d4f13"
_LIMIT_BYTES = 64 * 1024 * 1024
_REPO_ROOT = Path(__file__).resolve().parents[1]

_MODULE_SOURCE = '''"""One module so the run has real observations."""


def greet(name: str) -> str:
    """Return a greeting."""
    return f"hello {name}"


class Greeter:
    """Tiny public surface for the api_surface lane."""

    def greet(self, name: str) -> str:
        """Return a greeting."""
        return greet(name)
'''


def _write_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "mod.py").write_text(_MODULE_SOURCE, "utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        "utf-8",
    )
    return root


_CLI_ENTRY = "from codeclone.surfaces.cli.workflow import main; main()"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CLI_ENTRY, *args],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
    )


def _downgrade_api_surface_lane(baseline_path: Path) -> None:
    """Move only the api_surface lane payload schema 3 -> 2, re-authenticating.

    The container stays root-authentic; exactly one lane becomes semantically
    outdated against the current runtime contract.
    """

    result = read_container_v3(baseline_path, limit_bytes=_LIMIT_BYTES)
    assert isinstance(result, ContainerReadSuccess)
    container = result.container
    assert container.lanes["api_surface"].descriptor.payload_schema == "3"

    descriptor = replace(
        container.lanes["api_surface"].descriptor,
        payload_schema="2",
    )
    lane = replace(container.lanes["api_surface"], descriptor=descriptor)
    lane = replace(lane, digest=compute_lane_digest(lane))
    changed = replace(
        container,
        lanes=BaselineLaneIndex(
            rows=tuple(
                (key, lane if key == "api_surface" else existing)
                for key, existing in container.lanes.rows
            )
        ),
    )
    changed = replace(
        changed,
        observation_contract=replace(
            changed.observation_contract,
            descriptors=tuple(
                descriptor if item.name == "api_surface" else item
                for item in changed.observation_contract.descriptors
            ),
        ),
    )
    changed = replace(
        changed,
        meta=replace(changed.meta, root_digest=compute_root_digest(changed)),
    )
    baseline_path.write_bytes(canonical_container_bytes(changed) + b"\n")


@pytest.fixture
def degraded_baseline(tmp_path: Path) -> Path:
    root = _write_repo(tmp_path)
    baseline_path = tmp_path / "codeclone.baseline.json"
    published = _run_cli(
        str(root),
        "--baseline",
        str(baseline_path),
        "--api-surface",
        "--update-baseline",
        "--no-progress",
    )
    assert published.returncode == 0, published.stdout + published.stderr
    _downgrade_api_surface_lane(baseline_path)
    return baseline_path


def test_case_a_untrusted_lane_no_active_gate_needs_completes(
    tmp_path: Path,
    degraded_baseline: Path,
) -> None:
    """--fail-on-new needs only the clone lanes; api_surface opacity must not fail."""

    report_path = tmp_path / "report.json"
    result = _run_cli(
        str(tmp_path / "repo"),
        "--baseline",
        str(degraded_baseline),
        "--api-surface",
        "--fail-on-new",
        "--json",
        str(report_path),
        "--no-progress",
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # The opaque lane is named, once, rather than silently dropped.
    assert "Baseline lanes are opaque for this run" in result.stdout
    assert result.stdout.count("api_surface:payload_schema_outdated") == 1

    # Novelty for the opaque lane is nulled honestly; every other lane keeps
    # its baseline comparison. One stale lane must not blind the rest.
    summary = json.loads(report_path.read_text("utf-8"))["metrics"]["summary"]
    assert summary["api_surface"]["baseline_diff_available"] is False
    for family in ("complexity", "coupling", "dependencies", "dead_code", "health"):
        assert summary[family]["baseline_diff_available"] is True, family


def test_case_b_untrusted_lane_an_active_gate_needs_stays_fail_closed(
    tmp_path: Path,
    degraded_baseline: Path,
) -> None:
    """--fail-on-api-break needs api_surface; opacity must stay a contract error."""

    result = _run_cli(
        str(tmp_path / "repo"),
        "--baseline",
        str(degraded_baseline),
        "--api-surface",
        "--fail-on-new",
        "--fail-on-api-break",
        "--no-progress",
    )
    assert result.returncode == 2, result.stdout + result.stderr

    # Degrading is not ignoring: the established wording is preserved exactly.
    assert (
        "Baseline lane compatibility failed: api_surface:payload_schema_outdated"
        in result.stdout
    )
    assert "Baseline lanes are opaque for this run" not in result.stdout


def test_verify_compatibility_still_condemns_any_untrusted_lane(
    degraded_baseline: Path,
) -> None:
    """The MCP path is unchanged: verify_compatibility stays all-or-nothing.

    MCP catches this and degrades on its own terms. If this ever stops
    raising, the MCP surface has silently changed behaviour.
    """

    baseline = Baseline(degraded_baseline)
    baseline.load(max_size_bytes=_LIMIT_BYTES)

    with pytest.raises(BaselineValidationError, match="api_surface"):
        baseline.verify_compatibility(
            current_python_tag=current_python_tag(),
            baseline_scope_id=UUID(_SCOPE_ID),
        )

    # The additive reader returns the same fact without raising.
    unavailable = baseline.unavailable_lanes(
        current_python_tag=current_python_tag(),
        baseline_scope_id=UUID(_SCOPE_ID),
    )
    assert [(item.name, item.reason) for item in unavailable] == [
        ("api_surface", "payload_schema_outdated")
    ]
