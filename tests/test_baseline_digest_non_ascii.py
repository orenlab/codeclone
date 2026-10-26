# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A baseline whose stored digest is not ASCII fails integrity, not the run.

The container reader recomputes the lane and root digests and compares them
with the stored ones through ``hmac.compare_digest``, which raises
``TypeError`` for a non-ASCII ``str``. A baseline edited or corrupted that way
ended every run in the internal-error handler, exit 5. A computed digest is
lowercase hex, so a non-ASCII value is simply a mismatch: the baseline is
``integrity_failed`` exactly as with any other wrong digest -- ignored with a
warning in a plain run, a contract error (exit 2) under ``--ci``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._cli_child import run_codeclone

_SCOPE_ID = "0f5c6f3d-9d2e-4a2a-9a5f-6b0f9a1a2b3c"


@pytest.fixture(scope="module")
def published(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, bytes]:
    tmp = tmp_path_factory.mktemp("baseline-digest")
    root = tmp / "proj"
    package = root / "pkg"
    package.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n', "utf-8"
    )
    (package / "__init__.py").write_text("", "utf-8")
    (package / "mod.py").write_text("def f(a: int) -> int:\n    return a\n", "utf-8")
    run = run_codeclone(tmp, str(root), "--update-baseline", "--no-progress")
    assert run.returncode == 0, run.stdout + run.stderr
    return root, (root / "codeclone.baseline.json").read_bytes()


def _tamper(root: Path, pristine: bytes, where: str, value: str) -> None:
    container = json.loads(pristine)
    if where == "root":
        container["meta"]["root_digest"]["value"] = value
    else:
        container["lanes"]["clones.functions"]["digest"]["value"] = value
    (root / "codeclone.baseline.json").write_text(json.dumps(container), "utf-8")


_CASES = [
    pytest.param("root", "0" * 64, id="root-ascii"),
    pytest.param("root", "é" * 64, id="root-non-ascii"),
    pytest.param("lane", "0" * 64, id="lane-ascii"),
    pytest.param("lane", "é" * 64, id="lane-non-ascii"),
]


@pytest.mark.parametrize(("where", "value"), _CASES)
def test_a_tampered_digest_fails_integrity_in_a_plain_run(
    published: tuple[Path, bytes], tmp_path: Path, where: str, value: str
) -> None:
    root, pristine = published
    _tamper(root, pristine, where, value)
    report = tmp_path / "report.json"

    run = run_codeclone(root.parent, str(root), "--no-progress", "--json", str(report))

    output = run.stdout + run.stderr
    assert run.returncode == 0, output
    assert "INTERNAL ERROR" not in output, output
    baseline = json.loads(report.read_text("utf-8"))["meta"]["baseline"]
    assert (baseline["status"], baseline["loaded"]) == ("integrity_failed", False)


@pytest.mark.parametrize(("where", "value"), _CASES)
def test_a_tampered_digest_is_a_contract_error_under_ci(
    published: tuple[Path, bytes], where: str, value: str
) -> None:
    root, pristine = published
    _tamper(root, pristine, where, value)

    run = run_codeclone(root.parent, str(root), "--ci")

    output = run.stdout + run.stderr
    assert run.returncode == 2, output
    assert "INTERNAL ERROR" not in output, output
    assert "Invalid baseline file" in output, output


def test_the_untampered_baseline_is_trusted(
    published: tuple[Path, bytes], tmp_path: Path
) -> None:
    """Positive control: the same fixture, untouched, loads."""

    root, pristine = published
    (root / "codeclone.baseline.json").write_bytes(pristine)
    report = tmp_path / "report.json"

    run = run_codeclone(root.parent, str(root), "--no-progress", "--json", str(report))

    assert run.returncode == 0, run.stdout + run.stderr
    baseline = json.loads(report.read_text("utf-8"))["meta"]["baseline"]
    assert (baseline["status"], baseline["loaded"]) == ("ok", True)
