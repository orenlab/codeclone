# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Standing red set for the per-lane B+ baseline doctrine, on both surfaces.

One untrusted lane must not condemn the whole container. Both surfaces degrade
per lane: a lane no active gate depends on is reported opaque and its novelty
is honestly nulled, while a lane an active gate *does* depend on stays
fail-closed. Degrading is not ignoring.

The CLI half runs as a real subprocess, so the assertions read the true process
exit code rather than an in-process ``SystemExit``.

The MCP half of the same doctrine lives in ``tests/test_mcp_service.py`` and
reuses the fixture helpers below: this module reaches into ``codeclone.baseline``
internals to forge the degraded container, and the architecture ratchet
reclassifies every one of those imports the moment an r4 surface is imported
beside them. The gap that half covers was not academic -- MCP resolved this
container all-or-nothing, so one stale ``api_surface`` lane took the clone
comparison away while leaving the container attached to the report, and the
report's classifier then read the empty difference set as "compared, nothing
new". The fixture below therefore carries a real clone; the original fixture had
none, which is why every test here stayed green while that answer was wrong.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping
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
from codeclone.models import (
    BaselineContainerV3,
    BaselineLaneIndex,
    ContainerReadSuccess,
)

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


def _rewrite_container(
    baseline_path: Path,
    mutate: Callable[[BaselineContainerV3], BaselineContainerV3],
) -> None:
    """Read one container, apply ``mutate``, re-sign the root, write it back.

    Every forged artifact in this module needs the same four steps, and writing
    them out twice made the two forgeries a clone group of their own. The root
    digest is always re-signed last, so whatever ``mutate`` changed, the artifact
    on disk authenticates -- which is the point: these fixtures must be
    root-authentic, or they would be testing the integrity path instead.
    """

    result = read_container_v3(baseline_path, limit_bytes=_LIMIT_BYTES)
    assert isinstance(result, ContainerReadSuccess)
    changed = mutate(result.container)
    changed = replace(
        changed,
        meta=replace(changed.meta, root_digest=compute_root_digest(changed)),
    )
    baseline_path.write_bytes(canonical_container_bytes(changed) + b"\n")


def downgrade_api_surface_lane(baseline_path: Path) -> None:
    """Move only the api_surface lane payload schema 3 -> 2, re-authenticating.

    The container stays root-authentic; exactly one lane becomes semantically
    outdated against the current runtime contract.
    """

    def _mutate(container: BaselineContainerV3) -> BaselineContainerV3:
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
        return replace(
            changed,
            observation_contract=replace(
                changed.observation_contract,
                descriptors=tuple(
                    descriptor if item.name == "api_surface" else item
                    for item in changed.observation_contract.descriptors
                ),
            ),
        )

    _rewrite_container(baseline_path, _mutate)


def retag_container_python(baseline_path: Path, *, python_tag: str) -> None:
    """Rewrite ``meta.python_tag`` and re-authenticate the root digest.

    A container written by another interpreter, produced the way the product
    would produce it rather than by patching the writer mid-test: the artifact on
    disk really carries a foreign tag and really authenticates. Lane digests do
    not cover container meta, so only the root digest is re-signed.
    """

    def _mutate(container: BaselineContainerV3) -> BaselineContainerV3:
        assert container.meta.python_tag != python_tag
        return replace(container, meta=replace(container.meta, python_tag=python_tag))

    _rewrite_container(baseline_path, _mutate)


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
    downgrade_api_surface_lane(baseline_path)
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
    """``verify_compatibility`` stays all-or-nothing, and that is the point.

    The CLI asks ``unavailable_lanes`` first and only delegates here when an
    active gate reads an opaque lane. MCP still calls this method directly, so
    on this container it loses every comparison over one stale lane. The earlier
    note here said MCP "catches this and degrades on its own terms"; a run
    through the real surface refuted that, and the difference is measured in
    ``tests/test_mcp_service.py``.
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


# ---------------------------------------------------------------------------
# The clone-bearing repository: two modules where the second copies the first's
# settlement routine verbatim. The baseline is published from the stage without
# the copy, so the tree and the baseline differ by exactly one clone group and
# by nothing else -- not by the set of files, which would change the input
# universe instead of the finding.
# ---------------------------------------------------------------------------

_SETTLEMENT_ROUTINE = '''

def {name}(rows: list[dict[str, float]], rate: float) -> dict[str, float]:
    """Settle rows against one conversion rate."""
    settled: dict[str, float] = {{}}
    total = 0.0
    skipped = 0
    for row in rows:
        account = str(row.get("account", ""))
        amount = float(row.get("amount", 0.0))
        if not account:
            skipped += 1
            continue
        converted = amount * rate
        settled[account] = settled.get(account, 0.0) + converted
        total += converted
    settled["__total__"] = total
    settled["__skipped__"] = float(skipped)
    return settled
'''

_LEDGER_SOURCE = (
    '"""Ledger settlement: the module owning the original routine."""\n'
    "\nfrom __future__ import annotations\n"
    + _SETTLEMENT_ROUTINE.format(name="settle_ledger_rows")
    + '''

class LedgerBook:
    """Public surface, so the api_surface lane has something to record."""

    def __init__(self, rate: float) -> None:
        self.rate = rate

    def settle(self, rows: list[dict[str, float]]) -> dict[str, float]:
        """Settle rows with the book rate."""
        return settle_ledger_rows(rows, self.rate)
'''
)

#: Stage one: no copy of the routine, so the published baseline holds no clone.
_INVOICES_WITHOUT_CLONE = '''"""Invoice rendering: no copy of the settlement routine."""

from __future__ import annotations


def render_invoice_lines(names: tuple[str, ...]) -> str:
    """Render one invoice line per name."""
    return "\\n".join(f"* {name.strip().title()}" for name in names if name.strip())


class InvoiceSheet:
    """Public surface, so the api_surface lane has something to record."""

    def __init__(self, names: tuple[str, ...]) -> None:
        self.names = names

    def render(self) -> str:
        """Render the sheet."""
        return render_invoice_lines(self.names)
'''

#: Stage two: the routine copied in verbatim, so the tree holds one clone group
#: the stage-one baseline never saw.
_INVOICES_WITH_CLONE = (
    '"""Invoice rendering: the settlement routine copied in verbatim."""\n'
    "\nfrom __future__ import annotations\n"
    + _SETTLEMENT_ROUTINE.format(name="settle_invoice_rows")
    + '''

class InvoiceSheet:
    """Public surface, so the api_surface lane has something to record."""

    def __init__(self, rate: float) -> None:
        self.rate = rate

    def settle(self, rows: list[dict[str, float]]) -> dict[str, float]:
        """Settle rows with the sheet rate."""
        return settle_invoice_rows(rows, self.rate)
'''
)


def settlement_repository(tmp_path: Path, *, with_clone: bool, name: str) -> Path:
    """Write the two-module repository under its own directory.

    ``name`` keeps the tree under test and the staging tree the baseline is
    published from in separate directories. Sharing one directory silently
    overwrote the clone before the analysis ran, and every assertion about the
    clone then failed on an empty group list -- a fixture defect, not a finding.
    """

    root = tmp_path / name
    root.mkdir(exist_ok=True)
    (root / "ledger.py").write_text(_LEDGER_SOURCE, "utf-8")
    (root / "invoices.py").write_text(
        _INVOICES_WITH_CLONE if with_clone else _INVOICES_WITHOUT_CLONE,
        "utf-8",
    )
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        "utf-8",
    )
    return root


def publish_baseline(root: Path, target: Path) -> None:
    published = _run_cli(
        str(root),
        "--baseline",
        str(target),
        "--api-surface",
        "--update-baseline",
        "--no-progress",
    )
    assert published.returncode == 0, published.stdout + published.stderr


def cli_document(root: Path, *, baseline: Path, out: Path) -> dict[str, object]:
    result = _run_cli(
        str(root),
        "--baseline",
        str(baseline),
        "--api-surface",
        "--json",
        str(out),
        "--no-progress",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(out.read_text("utf-8"))
    assert isinstance(document, dict)
    return document


def _function_clone_rows(document: Mapping[str, object]) -> list[dict[str, object]]:
    findings = document["findings"]
    assert isinstance(findings, Mapping)
    groups = findings["groups"]
    assert isinstance(groups, Mapping)
    clones = groups["clones"]
    assert isinstance(clones, Mapping)
    rows = clones["functions"]
    assert isinstance(rows, list)
    return rows


def _sole_function_clone(document: Mapping[str, object]) -> dict[str, object]:
    rows = _function_clone_rows(document)
    assert len(rows) == 1, rows
    return rows[0]


@pytest.fixture
def settlement_tree(tmp_path: Path) -> Path:
    """The tree with the clone; the baselines below all describe the same files."""

    return settlement_repository(tmp_path, with_clone=True, name="settlement")


@pytest.fixture
def baseline_without_clone(tmp_path: Path) -> Path:
    """An intact baseline published before the routine was copied."""

    staging = settlement_repository(
        tmp_path,
        with_clone=False,
        name="settlement-before-the-copy",
    )
    target = tmp_path / "without-clone.baseline.json"
    publish_baseline(staging, target)
    return target


@pytest.fixture
def degraded_without_clone(baseline_without_clone: Path, tmp_path: Path) -> Path:
    """The same intact baseline with only its ``api_surface`` lane made stale.

    Every condition of the discriminating case holds at once: the clone is in
    the tree and not in the baseline, the degraded lane is *not* a clone lane,
    the clone lanes stay per-lane compatible, and the container stays
    root-authentic. That is the shape in which ``verify_compatibility`` raises
    while the container remains attached to the report.
    """

    target = tmp_path / "degraded.baseline.json"
    target.write_bytes(baseline_without_clone.read_bytes())
    downgrade_api_surface_lane(target)
    return target


def test_cli_findings_are_untouched_by_an_opaque_non_clone_lane(
    settlement_tree: Path,
    baseline_without_clone: Path,
    degraded_without_clone: Path,
    tmp_path: Path,
) -> None:
    """The reference surface's answer, pinned on its own terms.

    The CLI is the surface that was right, so it must not move: this compares
    its canonical ``findings`` subtree byte for byte between the intact baseline
    and the same baseline with only ``api_surface`` made stale. One opaque lane
    that no finding family reads may change the baseline trust projection and
    that lane's own metric family -- and not one byte of the findings (`B5`).

    Pinned as a derivation rather than as a stored digest: a literal would be a
    magic number in the test and would be refreshed the first time it moved,
    which is the failure mode goldens exist to prevent (`H1`, `P5`). Any change
    to the shared novelty classifier that reaches the CLI breaks this equality,
    which is what makes the CLI's immobility checkable instead of promised.
    """

    intact = cli_document(
        settlement_tree,
        baseline=baseline_without_clone,
        out=tmp_path / "cli-intact.json",
    )
    degraded = cli_document(
        settlement_tree,
        baseline=degraded_without_clone,
        out=tmp_path / "cli-degraded-pin.json",
    )

    def _canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    assert _canonical(intact["findings"]) == _canonical(degraded["findings"])
    assert _canonical(intact["derived"]) == _canonical(degraded["derived"])
    # And the answer itself, so the equality above cannot be satisfied by two
    # matching wrong words.
    assert _sole_function_clone(degraded)["novelty"] == "new"
    assert _sole_function_clone(degraded)["novelty_reason"] is None
