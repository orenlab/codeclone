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


def write_tree(
    root: Path,
    tree: dict[str, str],
    *,
    scope_id: str,
    pyproject_lines: tuple[str, ...] = (),
) -> Path:
    """Materialize one generated project, with a stable canonical scope id.

    ``pyproject_lines`` are appended verbatim under ``[tool.codeclone]``: the
    one way a suite can exercise a repository-level policy key through the
    same door a user turns.
    """

    root.mkdir(parents=True, exist_ok=True)
    for name, source in tree.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.lstrip(), encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "".join(
            (
                "[tool.codeclone]\n",
                f'baseline_scope_id = "{scope_id}"\n',
                *(f"{line}\n" for line in pyproject_lines),
            )
        ),
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


def run_cli(
    tmp_path: Path,
    tree: dict[str, str],
    name: str,
    *,
    scope_id: str,
    cli_args: tuple[str, ...] = (),
    pyproject_lines: tuple[str, ...] = (),
    expect_warm_cache: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Spawn one full analysis of a generated tree and return the process.

    The report lands at ``<tmp_path>/<name>-report.json``; callers that need
    the document go through :func:`analysis_report`, which also asserts the
    witness chain. This entry point exists for the runs whose whole point is
    the exit status - a refused flag value has no report to read.
    """

    # Rewriting the tree for a second run is what defeats the cache: the bytes
    # are identical and the run still re-analyzed every file. Measured on the
    # wildcard suite, while a "warm" pin was reading a cold run.
    project_root = (
        tmp_path / name
        if expect_warm_cache
        else write_tree(
            tmp_path / name,
            tree,
            scope_id=scope_id,
            pyproject_lines=pyproject_lines,
        )
    )
    return run_bounded(
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
            str(tmp_path / f"{name}-report.json"),
            "--no-skip-metrics",
            "--no-skip-dead-code",
            "--no-progress",
            *cli_args,
        ],
        name=name,
    )


def analysis_report(
    tmp_path: Path,
    tree: dict[str, str],
    name: str,
    *,
    scope_id: str,
    cli_args: tuple[str, ...] = (),
    pyproject_lines: tuple[str, ...] = (),
    expect_warm_cache: bool = False,
) -> dict[str, object]:
    """The whole report document of one generated tree, behind the witness chain.

    The producer, the mode and the family are asserted before a single row is
    read. ``expect_warm_cache`` additionally proves the run REUSED the cache
    rather than merely opening it.
    """

    completed = run_cli(
        tmp_path,
        tree,
        name,
        scope_id=scope_id,
        cli_args=cli_args,
        pyproject_lines=pyproject_lines,
        expect_warm_cache=expect_warm_cache,
    )
    report_path = tmp_path / f"{name}-report.json"
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
    return payload


def dead_code_family(
    tmp_path: Path,
    tree: dict[str, str],
    name: str,
    *,
    scope_id: str,
    cli_args: tuple[str, ...] = (),
    pyproject_lines: tuple[str, ...] = (),
    expect_warm_cache: bool = False,
) -> dict[str, object]:
    """The dead-code family of one generated tree, behind the witness chain."""

    payload = analysis_report(
        tmp_path,
        tree,
        name,
        scope_id=scope_id,
        cli_args=cli_args,
        pyproject_lines=pyproject_lines,
        expect_warm_cache=expect_warm_cache,
    )
    return dead_code_family_of(payload)


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


def _rows_by_qualname(
    family: dict[str, object],
    lane: str,
) -> dict[str, dict[str, object]]:
    """One lane of the family, keyed by qualname, rows returned whole.

    Whole rows because the ruling fixes each lane's minimal content and a
    projection onto one field would leave the others free to vanish.
    """

    rows = family[lane]
    assert isinstance(rows, list)
    by_qualname: dict[str, dict[str, object]] = {}
    for row in rows:
        assert isinstance(row, dict)
        by_qualname[str(row["qualname"])] = dict(row)
    return by_qualname


def unresolved_by_qualname(family: dict[str, object]) -> dict[str, dict[str, object]]:
    """The reachability abstention: neither dead nor live under this world."""

    return _rows_by_qualname(family, "unresolved")


def metric_family_of(payload: dict[str, object], name: str) -> dict[str, object]:
    """One metric family of an already-witnessed report document."""

    metrics = payload["metrics"]
    assert isinstance(metrics, dict)
    families = metrics["families"]
    assert isinstance(families, dict)
    family = families[name]
    assert isinstance(family, dict)
    return family


def dead_code_family_of(payload: dict[str, object]) -> dict[str, object]:
    """The dead-code family of an already-witnessed report document."""

    return metric_family_of(payload, "dead_code")


def unresolved_override_by_qualname(
    family: dict[str, object],
) -> dict[str, dict[str, object]]:
    """The rule-3 abstention: a method under an opaque external base."""

    return _rows_by_qualname(family, "unresolved_overrides")


def measured_qualnames(payload: dict[str, object]) -> frozenset[str]:
    """Every function the run actually measured, from the complexity family.

    The liveness verdict LIVE is an ABSENCE - the symbol is in none of the
    three lanes - and an absence is what a mistyped qualname, an unanalyzed
    file and a truncated list all look like. This is the presence witness
    that tells them apart, and the truncation flag is asserted because a
    truncated list would restore exactly the hole it closes.
    """

    complexity = metric_family_of(payload, "complexity")
    assert complexity["items_truncated"] is False, complexity["items_truncated"]
    items = complexity["items"]
    assert isinstance(items, list)
    return frozenset(str(item["qualname"]) for item in items)


#: The four verdicts a symbol can carry once a run has seen it.
VERDICT_LIVE = "live"
VERDICT_DEAD = "dead"
VERDICT_UNRESOLVED = "unresolved"
VERDICT_UNRESOLVED_OVERRIDE = "unresolved_override"


def liveness_verdict(payload: dict[str, object], qualname: str) -> str:
    """What the run concluded about ``qualname``, behind the presence witness.

    Raises rather than returning ``live`` when the run never measured the
    symbol: a pin that reads a typo as a passing LIVE assertion is the one
    failure this projection exists to make impossible.
    """

    measured = measured_qualnames(payload)
    if qualname not in measured:
        raise AssertionError(
            f"{qualname!r} was never measured by this run, so it has no "
            f"liveness verdict; measured: {sorted(measured)}"
        )
    family = dead_code_family_of(payload)
    if qualname in dead_qualnames(family):
        return VERDICT_DEAD
    if qualname in unresolved_by_qualname(family):
        return VERDICT_UNRESOLVED
    if qualname in unresolved_override_by_qualname(family):
        return VERDICT_UNRESOLVED_OVERRIDE
    return VERDICT_LIVE
