# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One harness for the report-layer liveness suites.

Both the wildcard re-export suite and the liveness-evidence suite ask the same
question of a generated tree - what did a real run report about dead code? -
and the answer has to come from a SPAWNED CLI: these are statements about what
a user reads, so importing the analysis in-process would leave the wiring
between the owner and the report unpinned, and would put a ring-4 test module
inside ring-2 internals.

The witness chain lives here rather than in each suite because it is the part
that is easy to get wrong once and then copy: a run with no metrics flag
silently degrades to ``clones_only`` and EVERY family reads empty, which is
indistinguishable from a passing assertion about an absence.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

#: The CLI is SPAWNED, never imported.
CLI_ENTRY = "from codeclone.surfaces.cli.workflow import main; main()"

#: Every tree here is three or four tiny files and returns in about a second,
#: so this is a DEADLINE, not a performance budget: it exists to turn a
#: non-terminating walk into a bounded red. A run that has to be killed cannot
#: be told apart from one still working, which is the one failure mode a
#: dead-code analyzer must never have - the user gets no wrong finding, they
#: get nothing, and no reason why.
RUN_DEADLINE_SECONDS = 120.0


def write_tree(root: Path, tree: dict[str, str], *, scope_id: str) -> Path:
    """Materialize one generated project, with a stable canonical scope id."""

    root.mkdir(parents=True, exist_ok=True)
    for name, source in tree.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.lstrip(), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{scope_id}"\n',
        encoding="utf-8",
    )
    return root


def run_bounded(argv: list[str], *, name: str) -> subprocess.CompletedProcess[str]:
    """Spawn one analysis under a deadline, and fail loudly if it is hit.

    ``subprocess.run`` without a timeout turns a non-terminating walk into a
    hung suite, which reads exactly like a slow one. The deadline converts that
    into an ordinary red naming the duty that broke.
    """

    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=RUN_DEADLINE_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"analysis of tree {name!r} did not terminate within "
            f"{RUN_DEADLINE_SECONDS:.0f}s: the re-export walk must converge on "
            f"every input, including a cyclic one"
        )


def dead_code_family(
    tmp_path: Path,
    tree: dict[str, str],
    name: str,
    *,
    scope_id: str,
    expect_warm_cache: bool = False,
) -> dict[str, object]:
    """The dead-code family of one generated tree, behind the witness chain.

    The producer, the mode and the family are asserted before a single row is
    read. ``expect_warm_cache`` additionally proves the run REUSED the cache
    rather than merely opening it.
    """

    # Rewriting the tree for a second run is what defeats the cache: the bytes
    # are identical and the run still re-analyzed every file. Measured on the
    # wildcard suite, while a "warm" pin was reading a cold run.
    project_root = (
        tmp_path / name
        if expect_warm_cache
        else write_tree(tmp_path / name, tree, scope_id=scope_id)
    )
    report_path = tmp_path / f"{name}-report.json"
    completed = run_bounded(
        [
            sys.executable,
            "-c",
            CLI_ENTRY,
            str(project_root),
            "--baseline",
            str(tmp_path / f"{name}-baseline.json"),
            "--cache-path",
            str(tmp_path / f"{name}-cache.json"),
            "--json",
            str(report_path),
            "--no-skip-metrics",
            "--no-skip-dead-code",
            "--no-progress",
        ],
        name=name,
    )
    assert report_path.exists(), completed.stdout + completed.stderr
    payload = json.loads(report_path.read_text("utf-8"))
    assert isinstance(payload, dict)
    meta = payload["meta"]
    assert isinstance(meta, dict)
    assert meta["analysis_mode"] == "full", meta["analysis_mode"]
    assert "dead_code" in meta["computed_metric_families"]
    # ``cache.used`` is not the warm witness: it says the cache FILE was read,
    # and a run can load a cache and then re-analyze every file in it. The hit
    # count is the witness, and it was measured - with only ``cache.used``
    # asserted, dropping the star-binding fact from the cached row left the
    # wildcard suite green.
    if expect_warm_cache:
        assert meta["cache"]["used"] is True, meta["cache"]
        files = payload["inventory"]["files"]
        assert files["cached"] == files["total_found"], files
        assert files["analyzed"] == 0, files
    family = payload["metrics"]["families"]["dead_code"]
    assert isinstance(family, dict)
    return family


def dead_qualnames(family: dict[str, object]) -> frozenset[str]:
    """Qualnames the run called dead."""

    items = family["items"]
    assert isinstance(items, list)
    return frozenset(str(item["qualname"]) for item in items)


def live_root_reason_by_qualname(family: dict[str, object]) -> dict[str, str]:
    """The evidence lane: what the run says holds each rooted symbol live."""

    rows = family["live_root_reasons"]
    assert isinstance(rows, list)
    return {str(row["qualname"]): str(row["reason"]) for row in rows}
