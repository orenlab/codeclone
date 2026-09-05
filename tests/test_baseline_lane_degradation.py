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
from typing import Any, Literal
from uuid import UUID

import pytest

from codeclone.baseline import Baseline, current_python_tag
from codeclone.baseline._metrics_baseline_payload import snapshot_from_project_metrics
from codeclone.baseline.container import read_container_v3
from codeclone.baseline.container_digest import (
    canonical_container_bytes,
    canonical_value_bytes,
    compute_lane_digest,
    compute_root_digest,
)
from codeclone.baseline.diff import diff_metrics
from codeclone.baseline.lanes import lane_payload_is_opaque
from codeclone.baseline.metrics_baseline import _lane_payload, _snapshot
from codeclone.contracts import HealthPopulation
from codeclone.contracts.errors import BaselineValidationError
from codeclone.models import (
    BaselineContainerV3,
    BaselineLaneIndex,
    CloneObservationPayload,
    ContainerReadSuccess,
    HealthScore,
    MetricsSnapshot,
    ObservationLaneName,
    ProjectMetrics,
)
from codeclone.report.gates.evaluator import HEALTH_INPUT_LANES

_SCOPE_ID = "3f2b8c1e-7a41-4d90-9c62-5b0e8a7d4f13"
#: A different input universe: the half of context compatibility that stays a
#: whole-container verdict.
FOREIGN_SCOPE_ID = "9d41c0a7-2e18-4f6b-8a35-6c7d1e94b028"
_LIMIT_BYTES = 64 * 1024 * 1024
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _foreign_python_tag() -> str:
    """An interpreter tag that is certainly not the one running the suite.

    Derived from the runtime rather than hard-coded, so the fixture stays foreign
    whichever interpreter the suite runs on. A literal would silently become the
    *native* tag on that interpreter, and every assertion about a foreign tag
    would then pass while testing the native case.
    """

    return "cp313" if current_python_tag() != "cp313" else "cp312"


_FOREIGN_TAG = _foreign_python_tag()

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


def downgrade_lane_payload_schema(
    baseline_path: Path,
    *,
    lane_name: ObservationLaneName,
    payload_schema: str,
) -> None:
    """Move one lane's recorded payload schema, re-authenticating the container.

    Generalised from the api_surface case below so that a lane feeding *health*
    can be made opaque by the same technique. Only the schema label moves: the
    payload bytes and the observation digest stay exactly as the publisher wrote
    them, so the reader keeps the bytes authenticated and reports the lane
    opaque rather than failing integrity (`B5`, `B6`).
    """

    def _mutate(container: BaselineContainerV3) -> BaselineContainerV3:
        assert container.lanes[lane_name].descriptor.payload_schema != payload_schema
        descriptor = replace(
            container.lanes[lane_name].descriptor,
            payload_schema=payload_schema,
        )
        lane = replace(container.lanes[lane_name], descriptor=descriptor)
        lane = replace(lane, digest=compute_lane_digest(lane))
        changed = replace(
            container,
            lanes=BaselineLaneIndex(
                rows=tuple(
                    (key, lane if key == lane_name else existing)
                    for key, existing in container.lanes.rows
                )
            ),
        )
        return replace(
            changed,
            observation_contract=replace(
                changed.observation_contract,
                descriptors=tuple(
                    descriptor if item.name == lane_name else item
                    for item in changed.observation_contract.descriptors
                ),
            ),
        )

    _rewrite_container(baseline_path, _mutate)


def downgrade_api_surface_lane(baseline_path: Path) -> None:
    """Move only the api_surface lane payload schema 3 -> 2, re-authenticating.

    The container stays root-authentic; exactly one lane becomes semantically
    outdated against the current runtime contract.
    """

    downgrade_lane_payload_schema(
        baseline_path,
        lane_name="api_surface",
        payload_schema="2",
    )


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


def rescope_container(baseline_path: Path, *, scope_id: str) -> None:
    """Rewrite ``baseline_scope_id`` and re-authenticate the root digest.

    The deliberate twin of ``retag_container_python``: same forgery technique,
    same re-signing, one different field. It exists so the two halves of the old
    context-incompatibility rule can be mutated independently -- the interpreter
    tag, which stopped being a trust term, and the scope id, which did not. A
    single fixture covering both would let one test stand in for two contract
    states, and then one mutation would red what the contract distinguishes.
    """

    def _mutate(container: BaselineContainerV3) -> BaselineContainerV3:
        assert str(container.baseline_scope_id) != scope_id
        return replace(container, baseline_scope_id=UUID(scope_id))

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
    assert "Baseline lanes opaque for this run" in result.stdout
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
    assert "Baseline lanes opaque for this run" not in result.stdout


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


def _degraded_copy(
    source: Path,
    target: Path,
    *,
    lane_name: ObservationLaneName,
) -> Path:
    target.write_bytes(source.read_bytes())
    downgrade_lane_payload_schema(target, lane_name=lane_name, payload_schema="0")
    return target


@pytest.fixture
def opaque_module_identity_baseline(
    baseline_without_clone: Path, tmp_path: Path
) -> Path:
    """The intact baseline with only ``module_identity`` made stale.

    ``module_identity`` is the lane the baseline's health projection reads its
    file counts from, so this is the shape in which the *producer* of the health
    number has no population to compute it over.
    """

    return _degraded_copy(
        baseline_without_clone,
        tmp_path / "opaque-module-identity.baseline.json",
        lane_name="module_identity",
    )


def _health_summary(document: Mapping[str, object]) -> Mapping[str, object]:
    metrics = document["metrics"]
    assert isinstance(metrics, Mapping)
    summary = metrics["summary"]
    assert isinstance(summary, Mapping)
    health = summary["health"]
    assert isinstance(health, Mapping)
    return health


def test_a_transparent_container_keeps_the_real_health_comparison(
    settlement_tree: Path,
    baseline_without_clone: Path,
    tmp_path: Path,
) -> None:
    """The opposite boundary: no lane is opaque, so the comparison must run.

    Refusing health whenever *any* lane were untrusted, or whenever the tree
    differs from the baseline, would satisfy every assertion in the two tests
    below while destroying the product. This pins the healthy run: the tree
    carries a clone the baseline does not, so a real comparison exists and its
    number must be published as available.
    """

    document = cli_document(
        settlement_tree,
        baseline=baseline_without_clone,
        out=tmp_path / "transparent.json",
    )
    health = _health_summary(document)

    assert health["baseline_diff_available"] is True
    # A real difference, not merely an available flag over a zero.
    assert health["delta"] != 0


@pytest.mark.parametrize(
    "lane_name",
    ["module_identity", "dead_code"],
)
def test_an_opaque_health_input_lane_withholds_the_health_comparison(
    settlement_tree: Path,
    baseline_without_clone: Path,
    tmp_path: Path,
    lane_name: ObservationLaneName,
) -> None:
    """Health is fed by seven lanes, so one lane cannot answer for the set.

    Two lanes, because the same opacity moves the published number in opposite
    directions and a single case would leave half the class unproven.
    ``module_identity`` is where the stored health reads its population, so the
    baseline half of the subtraction collapses to nothing and the run reports a
    large improvement. ``dead_code`` leaves the population intact and empties
    one dimension, so the baseline reads *better* than it was and the run
    reports a regression no code caused. Publishing either announces a
    comparison that never ran (`B8`, `G3`): the report already states which
    lanes health consumes, in ``contracts.evaluation.health_input_lanes``, and
    then contradicted itself by keying availability on ``risk_observations``
    alone.
    """

    degraded = _degraded_copy(
        baseline_without_clone,
        tmp_path / f"opaque-{lane_name}.baseline.json",
        lane_name=lane_name,
    )
    health = _health_summary(
        cli_document(
            settlement_tree,
            baseline=degraded,
            out=tmp_path / f"opaque-{lane_name}.json",
        )
    )

    assert health["baseline_diff_available"] is False, lane_name
    assert health["delta"] == 0, lane_name


def test_an_empty_health_lane_is_not_an_opaque_one(
    baseline_without_clone: Path,
    tmp_path: Path,
) -> None:
    """Zero observations and unreadable observations are different facts (`G4`).

    The baseline is published from the tree *before* the routine was copied, so
    its ``clones.functions`` lane decodes correctly and legitimately carries zero
    clone groups -- a real, best-possible clones dimension inside the stored
    health number. Making that same lane opaque leaves the reader holding zero
    groups as well, and it must not reach the same conclusion.

    This is the row that catches the tempting cheap fix: refusing when the
    decoded rows are empty, rather than when the lane was never decoded, passes
    every other test in this module and silently withholds health from every
    clean repository.
    """

    intact = read_container_v3(baseline_without_clone, limit_bytes=_LIMIT_BYTES)
    assert isinstance(intact, ContainerReadSuccess)
    payload = _lane_payload(intact.container, "clones.functions")
    assert isinstance(payload, CloneObservationPayload)
    assert payload.items == ()
    assert _snapshot(intact.container).health_score is not None

    target = _degraded_copy(
        baseline_without_clone,
        tmp_path / "opaque-clones.baseline.json",
        lane_name="clones.functions",
    )
    opaque = read_container_v3(target, limit_bytes=_LIMIT_BYTES)
    assert isinstance(opaque, ContainerReadSuccess)
    assert lane_payload_is_opaque(opaque.container.lanes["clones.functions"])
    assert _snapshot(opaque.container).health_score is None


def test_the_baseline_snapshot_carries_the_health_refusal(
    opaque_module_identity_baseline: Path,
) -> None:
    """The producer seam, pinned where the refusal is actually dropped.

    ``compute_health`` already withholds the number honestly and says which
    absence it was in ``population``. The snapshot then read ``health.total``
    through a field typed ``int``, which cannot say "not measured", so the
    refusal arrived downstream as a measured zero and an F grade -- and every
    consumer of ``MetricsDiff.health_delta`` that does not consult lane trust
    (the gate summary, the MCP run summary, the review receipt) saw a fabricated
    improvement. Pinning only the report would leave that half live.
    """

    result = read_container_v3(
        opaque_module_identity_baseline, limit_bytes=_LIMIT_BYTES
    )
    assert isinstance(result, ContainerReadSuccess)
    container = result.container
    assert lane_payload_is_opaque(container.lanes["module_identity"])

    snapshot = _snapshot(container)

    assert snapshot.health_score is None
    assert snapshot.health_grade is None


def test_every_health_input_lane_withholds_the_snapshot_health(
    baseline_without_clone: Path,
    tmp_path: Path,
) -> None:
    """Reachability across the whole declared manifest, not one lucky lane.

    ``HEALTH_INPUT_LANES`` is the versioned statement of what health consumes.
    Each of its members is made opaque in turn and must reach the refusal; a
    guard that only fires for ``module_identity`` would be theater for the other
    six (`H2`). The intact container is checked in the same test so the loop
    cannot pass by refusing unconditionally.
    """

    intact = read_container_v3(baseline_without_clone, limit_bytes=_LIMIT_BYTES)
    assert isinstance(intact, ContainerReadSuccess)
    assert _snapshot(intact.container).health_score is not None

    for index, lane_name in enumerate(HEALTH_INPUT_LANES):
        target = _degraded_copy(
            baseline_without_clone,
            tmp_path / f"opaque-{index}.baseline.json",
            lane_name=lane_name,
        )
        result = read_container_v3(target, limit_bytes=_LIMIT_BYTES)
        assert isinstance(result, ContainerReadSuccess)
        assert lane_payload_is_opaque(result.container.lanes[lane_name])
        assert _snapshot(result.container).health_score is None, lane_name


# ---------------------------------------------------------------------------
# The CURRENT half of the same disease. Wave 7 taught the baseline half above
# to carry the refusal; ``snapshot_from_project_metrics`` builds the other term
# of the same subtraction, and it read ``health.total`` through the same
# ``int`` that cannot say "not measured". An empty or unread CURRENT run
# against a good baseline then published ``health_delta = 0 - good`` -- a
# regression no code caused, the mirror image of the false improvement the
# wave 7 tests pin.
# ---------------------------------------------------------------------------


def _project_metrics_with_health(health: HealthScore) -> ProjectMetrics:
    """The smallest metrics object whose only interesting fact is health."""

    return ProjectMetrics(
        complexity_avg=0.0,
        complexity_max=0,
        high_risk_functions=(),
        coupling_avg=0.0,
        coupling_max=0,
        high_risk_classes=(),
        cohesion_avg=0.0,
        cohesion_max=0,
        low_cohesion_classes=(),
        dependency_modules=0,
        dependency_edges=0,
        dependency_edge_list=(),
        dependency_cycles=(),
        dependency_max_depth=0,
        dependency_longest_chains=(),
        dead_code=(),
        health=health,
    )


def _current_half_snapshot(
    health_score: int | None,
    health_grade: Literal["A", "B", "C", "D", "F"] | None,
) -> MetricsSnapshot:
    """A hand-built snapshot for exercising one health term of the diff."""

    return MetricsSnapshot(
        max_complexity=0,
        high_risk_functions=(),
        max_coupling=0,
        high_coupling_classes=(),
        max_cohesion=0,
        low_cohesion_classes=(),
        dependency_cycles=(),
        dependency_max_depth=0,
        dead_code_items=(),
        health_score=health_score,
        health_grade=health_grade,
    )


@pytest.mark.parametrize("population", ["unmeasured", "complete_empty"])
def test_the_current_snapshot_carries_the_health_refusal(
    population: HealthPopulation,
) -> None:
    """The producer seam of the current half, pinned where the refusal drops.

    ``compute_health`` refuses both non-carrying populations honestly and its
    zero total is a placeholder, not a measurement. Converting it with
    ``int()`` re-manufactures the measured zero wave 7 removed from the other
    half, and every consumer of ``MetricsDiff.health_delta`` that does not
    consult the current run's population -- the gate summary, the MCP run
    summary, the review receipt -- then sees the whole baseline score as a
    regression. Both refusing states must reach the refusal: a guard that
    fired for one absence would be theater for the other (`H2`).
    """

    snapshot = snapshot_from_project_metrics(
        _project_metrics_with_health(
            HealthScore(total=0, grade="F", dimensions={}, population=population)
        )
    )

    assert snapshot.health_score is None, population
    assert snapshot.health_grade is None, population


@pytest.mark.parametrize("population", ["complete_nonempty", "partial"])
def test_a_measured_population_keeps_the_current_snapshot_health(
    population: HealthPopulation,
) -> None:
    """The opposite boundary: a population that carries a score keeps it.

    ``partial`` is deliberately here and not above: a truncated run measured
    something, and naming the truncation is a different job from withholding
    the number (`population_carries_score`). Refusing it -- or refusing
    unconditionally -- would satisfy the refusal tests while withholding
    health from every legitimately measured run.
    """

    snapshot = snapshot_from_project_metrics(
        _project_metrics_with_health(
            HealthScore(
                total=87,
                grade="B",
                dimensions={"clones": 100},
                population=population,
            )
        )
    )

    assert snapshot.health_score == 87, population
    assert snapshot.health_grade == "B", population


def test_diff_metrics_does_not_subtract_against_an_absent_current_health() -> None:
    """The comparison seam: no current term, no health movement.

    Wave 7 wrote ``_health_delta`` to refuse on either absent side, but until
    the current snapshot could actually carry ``None`` this branch was
    unreachable from production inputs. Both directions are pinned in one
    place so the guard cannot rot back into a one-sided check: an absent
    current term reports no movement, and two present terms still subtract.
    """

    withheld = diff_metrics(
        baseline_snapshot=_current_half_snapshot(96, "A"),
        current_snapshot=_current_half_snapshot(None, None),
        baseline_api_surface=None,
        current_api_surface=None,
    )
    assert withheld.health_delta == 0

    measured = diff_metrics(
        baseline_snapshot=_current_half_snapshot(96, "A"),
        current_snapshot=_current_half_snapshot(90, "A"),
        baseline_api_surface=None,
        current_api_surface=None,
    )
    assert measured.health_delta == -6


def test_an_empty_current_scope_withholds_the_health_comparison(
    baseline_without_clone: Path,
    tmp_path: Path,
) -> None:
    """End to end: an emptied CURRENT tree against a good baseline.

    The same input universe -- the scope id matches -- with no source file
    left in it. The run's own health is withheld honestly (``score: null``,
    ``population: complete_empty``); the comparison must not then subtract a
    number the run never measured and publish the whole baseline score as a
    regression beside ``baseline_diff_available: true``, which is the exact
    shape wave 7 removed from the opaque-lane direction (`B8`, `G4`).
    """

    root = tmp_path / "settlement-emptied"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        "utf-8",
    )

    health = _health_summary(
        cli_document(
            root,
            baseline=baseline_without_clone,
            out=tmp_path / "emptied.json",
        )
    )

    assert health["score"] is None
    assert health["population"] == "complete_empty"
    assert health["delta"] == 0
    assert health["baseline_diff_available"] is False


@pytest.fixture
def foreign_interpreter_without_clone(
    baseline_without_clone: Path, tmp_path: Path
) -> Path:
    """The same intact baseline, restamped with another interpreter's tag.

    Root-authentic: ``retag_container_python`` re-signs the root digest, so this
    artifact really carries a foreign tag and really authenticates. Nothing else
    about it moves -- every lane digest and every lane payload is the byte the
    publisher wrote.
    """

    target = tmp_path / "foreign-interpreter.baseline.json"
    target.write_bytes(baseline_without_clone.read_bytes())
    retag_container_python(target, python_tag=_FOREIGN_TAG)
    return target


def test_a_foreign_interpreter_tag_changes_no_finding(
    settlement_tree: Path,
    baseline_without_clone: Path,
    foreign_interpreter_without_clone: Path,
    tmp_path: Path,
) -> None:
    """An authentic baseline from another interpreter must answer identically.

    The interpreter tag was the last remaining reason to refuse a comparison the
    data supports. Measured across CPython 3.10-3.14: all ten lane digests and
    all ten lane payloads byte-identical, and 3 of 163179 container leaf fields
    differing -- ``created_at``, ``python_tag``, and the root digest the tag
    feeds. So a foreign tag may change the provenance and *nothing else*.

    Pinned as an equality between two runs rather than against stored expected
    values: a literal would be a magic number that gets refreshed the first time
    it moves (`H1`, `P5`). The intact baseline and the retagged one differ in
    exactly one string, so any reintroduction of a tag term anywhere in the trust
    projection, in either baseline half, or in the context-incompatibility set
    breaks this equality.

    Before the fix this run printed ``Invalid baseline file.``, reported every
    lane unavailable on ``python_tag``, and turned all 7 recognitions in this
    fixture into ``unavailable`` while exiting 2 (`B4`, `B5`).
    """

    intact = cli_document(
        settlement_tree,
        baseline=baseline_without_clone,
        out=tmp_path / "cli-intact-tag.json",
    )
    foreign = cli_document(
        settlement_tree,
        baseline=foreign_interpreter_without_clone,
        out=tmp_path / "cli-foreign-tag.json",
    )

    def _canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    assert _canonical(intact["findings"]) == _canonical(foreign["findings"])
    assert _canonical(intact["derived"]) == _canonical(foreign["derived"])
    # And the answer itself, so the equality above cannot be satisfied by two
    # matching wrong words: the clone is in the tree and not in the baseline, so
    # a comparison that actually ran must call it new -- never "unavailable".
    assert _sole_function_clone(foreign)["novelty"] == "new"


def test_a_foreign_interpreter_tag_is_reported_as_origin_not_as_distrust(
    settlement_tree: Path,
    foreign_interpreter_without_clone: Path,
    tmp_path: Path,
) -> None:
    """The run proceeds, and it says where the reference came from (`G4`).

    Two separate obligations, both checked here because dropping either one
    reintroduces a defect this wave exists to remove. The container must stop
    being called invalid -- admissibility and context compatibility are
    different levels and the message must not conflate them (`B4`). And the
    difference must not become silence: we hold the fact, so withholding it
    trades a false refusal for an unreported one.
    """

    result = _run_cli(
        str(settlement_tree),
        "--baseline",
        str(foreign_interpreter_without_clone),
        "--api-surface",
        "--json",
        str(tmp_path / "cli-foreign-note.json"),
        "--ci",
        "--fail-on-new",
        "--no-progress",
    )

    # The gate verdict on new clones, reached because the comparison ran at all.
    assert result.returncode == 3, result.stdout + result.stderr
    assert "Invalid baseline file" not in result.stdout
    assert "python_tag" not in result.stdout
    assert f"Baseline was taken on {_FOREIGN_TAG}" in result.stdout
    assert f"this run is {current_python_tag()}" in result.stdout


def test_a_matching_interpreter_tag_says_nothing_about_provenance(
    settlement_tree: Path,
    baseline_without_clone: Path,
    tmp_path: Path,
) -> None:
    """The note is about a difference, so no difference means no note.

    The opposite direction of the case above. Without it, a formatter that
    printed the origin unconditionally would satisfy the provenance obligation
    while adding a line to every ordinary run.
    """

    result = _run_cli(
        str(settlement_tree),
        "--baseline",
        str(baseline_without_clone),
        "--api-surface",
        "--json",
        str(tmp_path / "cli-native-note.json"),
        "--no-progress",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Baseline was taken on" not in result.stdout


def test_a_foreign_scope_id_still_condemns_the_whole_container(
    settlement_tree: Path,
    baseline_without_clone: Path,
    tmp_path: Path,
) -> None:
    """The half that was never under question, pinned on its own witness.

    Scope and interpreter were once one rule, and only one half of it was wrong.
    The scope id says which input universe the artifact describes; a container
    describing a different one describes nothing about this run, so no lane of it
    is comparable and degrading it per lane would publish a trusted baseline for
    a run the artifact is not about (`B4`, `G3`).

    Kept in its own test, with its own forgery and its own witness, so that
    removing the surviving half cannot be mistaken for passing: this test and
    ``test_a_foreign_interpreter_tag_changes_no_finding`` must fail on opposite
    mutations, and one test covering both would hide exactly that.
    """

    target = tmp_path / "foreign-scope.baseline.json"
    target.write_bytes(baseline_without_clone.read_bytes())
    rescope_container(target, scope_id=FOREIGN_SCOPE_ID)

    result = _run_cli(
        str(settlement_tree),
        "--baseline",
        str(target),
        "--api-surface",
        "--ci",
        "--fail-on-new",
        "--no-progress",
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Invalid baseline file" in result.stdout
    assert "baseline_scope_id" in result.stdout

    baseline = Baseline(target)
    baseline.load(max_size_bytes=_LIMIT_BYTES)
    unavailable = baseline.unavailable_lanes(
        current_python_tag=current_python_tag(),
        baseline_scope_id=UUID(_SCOPE_ID),
    )
    assert unavailable, "a foreign-scope container must report no comparable lane"
    assert {item.reason for item in unavailable} == {"baseline_scope_id"}


def test_python_tag_stays_a_root_digest_input(
    baseline_without_clone: Path,
) -> None:
    """The tag left the trust decision; it must not leave the signature (`G5`).

    Provenance that no digest covers is provenance an editor can rewrite without
    detection, and the artifact would then authenticate while lying about where
    it came from. The point of this wave is that the tag is honest metadata --
    which is only true while it is signed.

    Pinned as the derivation, by recomputing the product's own root digest over a
    container that differs in the tag alone, rather than by asserting a stored
    hex string (`H1`).
    """

    result = read_container_v3(baseline_without_clone, limit_bytes=_LIMIT_BYTES)
    assert isinstance(result, ContainerReadSuccess)
    container = result.container
    assert container.meta.python_tag != _FOREIGN_TAG

    retagged = replace(
        container,
        meta=replace(container.meta, python_tag=_FOREIGN_TAG),
    )

    assert compute_root_digest(retagged) != compute_root_digest(container)


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


# ---------------------------------------------------------------------------
# F1 lane-contract migration: a pre-migration (schema "4") risk lane reads
# unavailable — not a crash, not a wrong number, not a silent comparison.
# ---------------------------------------------------------------------------

#: 24 sequential decisions — decision-count cyclomatic complexity 25, above
#: DEFAULT_COMPLEXITY_THRESHOLD (20), so the report carries a complexity
#: finding whose novelty this pin can read.
_COMPLEX_MODULE_SOURCE = _MODULE_SOURCE + (
    "\n\ndef triage(v: int) -> str:\n"
    '    """Deliberately over the complexity threshold."""\n'
    + "".join(
        f'    if v == {index}:\n        return "x{index}"\n' for index in range(1, 25)
    )
    + '    return "z"\n'
)


def _write_complex_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "mod.py").write_text(_COMPLEX_MODULE_SOURCE, "utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        "utf-8",
    )
    return root


def downgrade_lane_to_its_pre_migration_shape(
    baseline_path: Path,
    *,
    lane_name: ObservationLaneName,
    published_schema: str,
    stored_schema: str,
    dropped_column: str,
) -> None:
    """Rewrite one lane into the authentic shape it had before a migration.

    Not only the label: the KEY column the migration added is removed too,
    so the artifact on disk is exactly what a pre-migration publisher
    wrote — re-authenticated at lane and root so the reader answers the
    contract question, not integrity.

    One helper for both migrations on purpose. Writing the four steps out
    per lane made the F1 and F6 forgeries a clone group of their own, and
    a second spelling of one forgery is the thing this suite exists to
    refuse elsewhere.
    """

    def _mutate(container: BaselineContainerV3) -> BaselineContainerV3:
        lane = container.lanes[lane_name]
        assert lane.descriptor.payload_schema == published_schema
        descriptor = replace(lane.descriptor, payload_schema=stored_schema)
        old_shape = json.loads(canonical_value_bytes(lane.payload))
        old_shape.pop(dropped_column)
        lane = replace(lane, descriptor=descriptor, payload=old_shape)
        lane = replace(lane, digest=compute_lane_digest(lane))
        changed = replace(
            container,
            lanes=BaselineLaneIndex(
                rows=tuple(
                    (key, lane if key == lane_name else existing)
                    for key, existing in container.lanes.rows
                )
            ),
        )
        return replace(
            changed,
            observation_contract=replace(
                changed.observation_contract,
                descriptors=tuple(
                    descriptor if item.name == lane_name else item
                    for item in changed.observation_contract.descriptors
                ),
            ),
        )

    _rewrite_container(baseline_path, _mutate)


def _publish_baseline(root: Path, baseline_path: Path) -> BaselineContainerV3:
    """Publish a baseline for ``root`` and hand back the artifact on disk."""

    published = _run_cli(
        str(root),
        "--baseline",
        str(baseline_path),
        "--update-baseline",
        "--no-progress",
    )
    assert published.returncode == 0, published.stdout + published.stderr
    read_back = read_container_v3(
        baseline_path, limit_bytes=baseline_path.stat().st_size
    )
    assert isinstance(read_back, ContainerReadSuccess)
    return read_back.container


def assert_pre_migration_lane_is_a_typed_absence(
    tmp_path: Path,
    *,
    root: Path,
    lane_name: ObservationLaneName,
    published_schema: str,
    stored_schema: str,
    dropped_column: str,
    withheld_families: tuple[str, ...],
    compared_families: tuple[str, ...],
) -> Mapping[str, Any]:
    """The three verdicts every lane migration owes, checked in one place.

    Publish, forge the authentic pre-migration lane, re-run, and assert:
    the run completes (no crash), the opaque lane is named exactly once,
    and the families that read it lose their baseline comparison instead
    of comparing against a wire that cannot answer the identity question.
    Returns the report so a caller can add the assertions only its own
    lane can make.

    One body for both migrations deliberately: spelled out per lane, the
    F1 and F6 pins were a measured clone group, and the second spelling
    would have had to be kept in step by hand.
    """

    baseline_path = tmp_path / "codeclone.baseline.json"
    container = _publish_baseline(root, baseline_path)
    # The red-first anchor: the current publisher writes the migrated wire.
    assert container.lanes[lane_name].descriptor.payload_schema == published_schema

    downgrade_lane_to_its_pre_migration_shape(
        baseline_path,
        lane_name=lane_name,
        published_schema=published_schema,
        stored_schema=stored_schema,
        dropped_column=dropped_column,
    )

    report_path = tmp_path / "report.json"
    result = _run_cli(
        str(root),
        "--baseline",
        str(baseline_path),
        "--json",
        str(report_path),
        "--no-progress",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Baseline lanes opaque for this run" in result.stdout
    assert result.stdout.count(f"{lane_name}:payload_schema_outdated") == 1

    document: Mapping[str, Any] = json.loads(report_path.read_text("utf-8"))
    summary = document["metrics"]["summary"]
    for family in withheld_families:
        assert summary[family]["baseline_diff_available"] is False, family
    for family in compared_families:
        assert summary[family]["baseline_diff_available"] is True, family
    return document


def test_schema4_risk_lane_degrades_to_unavailable_with_novelty_reason(
    tmp_path: Path,
) -> None:
    """F1 K1 pin: the stored schema-4 risk lane is a typed absence.

    Four verdicts in one artifact run: the run completes (no crash), the
    opaque lane is named once (payload_schema_outdated), the complexity
    family loses its baseline comparison honestly (no silent comparison),
    and the complexity finding says ``unavailable`` with the
    ``lane_unavailable`` reason instead of guessing ``known`` or ``new``.
    """

    # The risk lane feeds health, so the stored score is withheld too.
    document = assert_pre_migration_lane_is_a_typed_absence(
        tmp_path,
        root=_write_complex_repo(tmp_path),
        lane_name="risk_observations",
        published_schema="5",
        stored_schema="4",
        dropped_column="start_line",
        withheld_families=("complexity", "health"),
        compared_families=("coupling", "dependencies", "dead_code"),
    )

    design_groups = document["findings"]["groups"]["design"]["groups"]
    complexity_findings = [
        group for group in design_groups if group["category"] == "complexity"
    ]
    assert complexity_findings, "the fixture repo must carry a complexity finding"
    for group in complexity_findings:
        assert group["novelty"] == "unavailable"
        assert group["novelty_reason"] == "lane_unavailable"


_IMPORT_MODULE_SOURCE = '''"""A module that defers one import at two different sites."""

from __future__ import annotations


def first(name: str) -> str:
    """Return a greeting from the first site."""
    from helper import greet

    return greet(name)


def second(name: str) -> str:
    """Return the same greeting from a second site."""
    from helper import greet

    return greet(name)
'''

_HELPER_MODULE_SOURCE = '''"""The helper both sites import."""


def greet(name: str) -> str:
    """Return a greeting."""
    return f"hello {name}"
'''


def _write_two_occurrence_repo(tmp_path: Path) -> Path:
    """A repository whose dependency lane needs the occurrence site.

    ``mod.py`` defers ``from helper import greet`` inside two function
    bodies. Every dependency field except the site is equal between the
    two imports, so this fixture is the end-to-end half of the F6
    distinguishing corpus: if the site is not on the wire, the published
    lane cannot tell a reader that this repository imports ``helper``
    twice.
    """

    root = tmp_path / "repo"
    root.mkdir()
    (root / "mod.py").write_text(_IMPORT_MODULE_SOURCE, "utf-8")
    (root / "helper.py").write_text(_HELPER_MODULE_SOURCE, "utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        "utf-8",
    )
    return root


def test_the_published_dependency_lane_names_both_import_occurrences(
    tmp_path: Path,
) -> None:
    """F6 red-first, end to end: the site reaches the published artifact.

    The projection is where ``ModuleDep.line`` used to be dropped, so this
    asserts on what a reader actually receives — the lane inside a real
    published baseline — rather than on an in-memory row the wire may
    still flatten.
    """

    root = _write_two_occurrence_repo(tmp_path)
    baseline_path = tmp_path / "codeclone.baseline.json"
    lane = _publish_baseline(root, baseline_path).lanes["dependencies"]
    assert lane.descriptor.payload_schema == "8"
    payload = json.loads(canonical_value_bytes(lane.payload))
    sites = [
        payload["line"][row]
        for row, target in enumerate(payload["resolved_target"])
        if target is not None and payload["modules"][target] == "helper"
    ]
    assert len(sites) == 2
    assert len(set(sites)) == 2


def test_schema7_dependency_lane_degrades_to_unavailable_not_silently(
    tmp_path: Path,
) -> None:
    """F6 K1 pin: a stored schema-7 dependency lane is a typed absence.

    Three verdicts in one artifact run: the run completes (no crash), the
    opaque lane is named exactly once (payload_schema_outdated), and the
    families that read this lane lose their baseline comparison honestly
    instead of comparing today's rows against a wire that cannot answer
    the identity question.
    """

    # The dependency lane is a health input, so the stored score goes too.
    assert_pre_migration_lane_is_a_typed_absence(
        tmp_path,
        root=_write_two_occurrence_repo(tmp_path),
        lane_name="dependencies",
        published_schema="8",
        stored_schema="7",
        dropped_column="line",
        withheld_families=("dependencies", "health"),
        compared_families=("complexity", "coupling", "dead_code"),
    )
