# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import inspect
import random
import textwrap
from math import fsum
from pathlib import Path

import pytest

from codeclone.baseline.trust import MAX_BASELINE_SIZE_BYTES
from codeclone.cache.versioning import MAX_CACHE_SIZE_BYTES
from codeclone.config import spec as spec_mod
from codeclone.config.argparse_builder import build_parser
from codeclone.contracts import (
    DEFAULT_BASELINE_PATH,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_COVERAGE_MIN,
    DEFAULT_MAX_BASELINE_SIZE_MB,
    DEFAULT_MAX_CACHE_SIZE_MB,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_PROCESSES,
    DEFAULT_ROOT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
    HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER,
    HEALTH_DEPENDENCY_DEPTH_P95_MARGIN,
    HEALTH_WEIGHTS,
)
from codeclone.contracts.errors import ContractInvariantError
from codeclone.core._types import DEFAULT_RUNTIME_PROCESSES
from codeclone.metrics import health as health_mod
from codeclone.report.gates.evaluator import MetricGateConfig
from codeclone.report.html.sections import _dependencies as html_dependencies_mod
from codeclone.surfaces.mcp import server as mcp_server
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPGateRequest


def test_config_spec_reexports_shared_runtime_defaults() -> None:
    assert spec_mod.DEFAULT_ROOT == DEFAULT_ROOT
    assert spec_mod.DEFAULT_MIN_LOC == DEFAULT_MIN_LOC
    assert spec_mod.DEFAULT_MIN_STMT == DEFAULT_MIN_STMT
    assert spec_mod.DEFAULT_BLOCK_MIN_LOC == DEFAULT_BLOCK_MIN_LOC
    assert spec_mod.DEFAULT_BLOCK_MIN_STMT == DEFAULT_BLOCK_MIN_STMT
    assert spec_mod.DEFAULT_SEGMENT_MIN_LOC == DEFAULT_SEGMENT_MIN_LOC
    assert spec_mod.DEFAULT_SEGMENT_MIN_STMT == DEFAULT_SEGMENT_MIN_STMT
    assert spec_mod.DEFAULT_PROCESSES == DEFAULT_PROCESSES
    assert spec_mod.DEFAULT_MAX_CACHE_SIZE_MB == DEFAULT_MAX_CACHE_SIZE_MB
    assert spec_mod.DEFAULT_MAX_BASELINE_SIZE_MB == DEFAULT_MAX_BASELINE_SIZE_MB
    assert spec_mod.DEFAULT_BASELINE_PATH == DEFAULT_BASELINE_PATH
    assert spec_mod.DEFAULTS_BY_DEST["coverage_min"] == DEFAULT_COVERAGE_MIN


def test_cli_parser_defaults_follow_contract_defaults() -> None:
    args = build_parser("2.0.0").parse_args([])

    assert args.root == DEFAULT_ROOT
    assert args.min_loc == DEFAULT_MIN_LOC
    assert args.min_stmt == DEFAULT_MIN_STMT
    assert args.block_min_loc == DEFAULT_BLOCK_MIN_LOC
    assert args.block_min_stmt == DEFAULT_BLOCK_MIN_STMT
    assert args.segment_min_loc == DEFAULT_SEGMENT_MIN_LOC
    assert args.segment_min_stmt == DEFAULT_SEGMENT_MIN_STMT
    assert args.processes == DEFAULT_PROCESSES
    assert args.max_cache_size_mb == DEFAULT_MAX_CACHE_SIZE_MB
    assert args.baseline == DEFAULT_BASELINE_PATH
    assert args.max_baseline_size_mb == DEFAULT_MAX_BASELINE_SIZE_MB
    assert args.coverage_min == DEFAULT_COVERAGE_MIN


def test_size_byte_limits_derive_from_contract_megabyte_defaults() -> None:
    assert MAX_CACHE_SIZE_BYTES == DEFAULT_MAX_CACHE_SIZE_MB * 1024 * 1024
    assert MAX_BASELINE_SIZE_BYTES == DEFAULT_MAX_BASELINE_SIZE_MB * 1024 * 1024


def test_cache_cap_default_pins_maintainer_ruling_value() -> None:
    # Maintainer ruling 2026-08-04 (perf-ledger #1, option B): the default
    # cache cap is 256 MB. Drifting back to a smaller cap silently re-opens
    # the over-cap cold-fallback cliff for large repositories; changing this
    # value requires an explicit maintainer decision.
    assert DEFAULT_MAX_CACHE_SIZE_MB == 256


def test_runtime_and_gate_defaults_follow_contract_defaults(tmp_path: Path) -> None:
    service = CodeCloneMCPService()
    args = service._build_args(
        root_path=tmp_path,
        request=MCPAnalysisRequest(respect_pyproject=False),
    )

    assert DEFAULT_RUNTIME_PROCESSES == DEFAULT_PROCESSES
    assert args.min_loc == DEFAULT_MIN_LOC
    assert args.min_stmt == DEFAULT_MIN_STMT
    assert args.block_min_loc == DEFAULT_BLOCK_MIN_LOC
    assert args.block_min_stmt == DEFAULT_BLOCK_MIN_STMT
    assert args.segment_min_loc == DEFAULT_SEGMENT_MIN_LOC
    assert args.segment_min_stmt == DEFAULT_SEGMENT_MIN_STMT
    assert args.max_cache_size_mb == DEFAULT_MAX_CACHE_SIZE_MB
    assert args.max_baseline_size_mb == DEFAULT_MAX_BASELINE_SIZE_MB
    assert args.baseline == DEFAULT_BASELINE_PATH
    # 2.1.0a2 unified the clone and metrics lanes into one baseline container:
    # there is no separate metrics baseline path left to default.
    assert not hasattr(args, "metrics_baseline")
    assert args.coverage_min == DEFAULT_COVERAGE_MIN
    assert MCPGateRequest().coverage_min == DEFAULT_COVERAGE_MIN
    assert (
        MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
        ).coverage_min
        == DEFAULT_COVERAGE_MIN
    )


def test_mcp_parser_and_builder_defaults_stay_in_sync() -> None:
    args = mcp_server.build_parser().parse_args([])
    signature = inspect.signature(mcp_server.build_mcp_server)

    assert signature.parameters["history_limit"].default == args.history_limit
    assert signature.parameters["host"].default == args.host
    assert signature.parameters["port"].default == args.port
    assert signature.parameters["json_response"].default == args.json_response
    assert signature.parameters["stateless_http"].default == args.stateless_http
    assert signature.parameters["debug"].default == args.debug
    assert signature.parameters["log_level"].default == args.log_level


def test_dependency_depth_profile_contract_stays_shared_between_health_and_html() -> (
    None
):
    health_source = inspect.getsource(health_mod._dependency_expected_tail)
    html_source = inspect.getsource(html_dependencies_mod.render_dependencies_panel)

    assert "HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER" in health_source
    assert "HEALTH_DEPENDENCY_DEPTH_P95_MARGIN" in health_source
    assert HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER == 2.0
    assert HEALTH_DEPENDENCY_DEPTH_P95_MARGIN == 1
    assert "avg depth" in html_source
    assert "p95 depth" in html_source
    assert "HEALTH_DEPENDENCY_MAX_DEPTH_SAFE_ZONE" not in html_source


def _measured_health_inputs() -> health_mod.HealthInputs:
    """Health inputs with a real population and mixed, non-uniform dimensions.

    The weighting only shows through when the dimensions disagree: a vector of
    identical dimension scores comes back unchanged under any weight vector
    that sums to one, so a uniform fixture cannot see the aggregate at all.
    """

    return health_mod.HealthInputs(
        files_found=200,
        files_analyzed_or_cached=200,
        function_clone_groups=4,
        block_clone_groups=2,
        complexity_avg=6.5,
        complexity_max=44,
        high_risk_functions=9,
        elevated_complexity_functions=31,
        complexity_function_population=1200,
        coupling_avg=4.0,
        coupling_max=22,
        high_risk_classes=3,
        elevated_coupling_classes=14,
        coupling_class_population=300,
        cohesion_avg=1.4,
        low_cohesion_classes=12,
        import_dependency_cycles=1,
        deferred_dependency_cycles=2,
        dependency_max_depth=7,
        dependency_avg_depth=3.2,
        dependency_p95_depth=6,
        dead_code_items=5,
    )


def test_health_aggregate_consumes_the_contract_weight_vector() -> None:
    """The aggregate must weight with the contract's vector, not a local copy.

    Pins the edge, not the spelling: whatever ``compute_health`` multiplies by
    has to be the object ``codeclone.contracts`` publishes. A second vector
    bound in ``health`` would make every guard below validate one mapping while
    the score was formed from another.
    """

    assert vars(health_mod)["HEALTH_WEIGHTS"] is HEALTH_WEIGHTS


def test_health_weights_sum_to_one() -> None:
    """The published weights sum to exactly one.

    Pinned on the sum itself. An assertion shaped like the aggregate --
    ``sum(dimensions[n] * weights[n] ...)`` -- re-runs the formula and stays
    green for *any* vector, a vector summing to 1.5 included, which is how the
    precondition survived this long with a test file named after it.
    """

    weights = vars(health_mod)["HEALTH_WEIGHTS"]
    total = fsum(weights[name] for name in sorted(weights))

    assert abs(total - 1.0) <= health_mod._weight_sum_slack(len(weights))


def test_health_weights_are_never_negative() -> None:
    """No weight is negative, which the sum alone does not imply.

    ``{"a": 2.0, "b": -1.0}`` sums to one and still drives the weighted total
    to 200 on ``a = 100, b = 0``. Summing to one is half of the convexity the
    aggregate needs; this is the other half.
    """

    weights = vars(health_mod)["HEALTH_WEIGHTS"]

    assert sorted(name for name, weight in weights.items() if weight < 0.0) == []


def test_weight_sum_slack_admits_every_exactly_unit_vector() -> None:
    """The slack must not reject a vector whose true sum is one.

    Re-measures the rule against its stated basis -- decimal weights stored as
    the nearest double, summed once by ``fsum`` -- rather than restating the
    number. A slack narrowed below the representation drift refuses honest
    recalibrations, so this is the lower boundary of the constant.
    """

    rng = random.Random(20260831)
    worst = 0.0
    for _ in range(2000):
        count = rng.randint(2, 12)
        cuts = sorted(rng.sample(range(1, 1000), count - 1))
        parts = [b - a for a, b in zip([0, *cuts], [*cuts, 1000], strict=True)]
        drift = abs(fsum(part / 1000 for part in parts) - 1.0)
        assert drift <= health_mod._weight_sum_slack(count)
        worst = max(worst, drift)
    for count in range(2, 33):
        drift = abs(fsum([1 / count] * count) - 1.0)
        assert drift <= health_mod._weight_sum_slack(count)
        worst = max(worst, drift)

    assert worst > 0.0


def test_weight_sum_slack_rejects_an_authoring_slip() -> None:
    """The slack must stay far below any weight a human could mistype.

    The upper boundary of the same constant. The internal contract note used
    to claim +/-0.001 "floating-point tolerance"; a slack that wide accepts a
    vector summing to 1.0009 -- a single weight typed as 0.1009 -- which is
    exactly the bias the check exists to refuse.
    """

    assert health_mod._weight_sum_slack(len(HEALTH_WEIGHTS)) < 1e-9


def test_health_aggregate_refuses_weights_that_do_not_sum_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-unit vector must stop the score, not bias it.

    Reachable input for the guard: the aggregate reads this binding, so a
    vector summing to 1.25 arrives at the same read the weighted sum uses.
    Before the guard the run reported a plausible number -- ``_clamp_score``
    folded every inflated total back onto 100.
    """

    monkeypatch.setattr(
        health_mod,
        "HEALTH_WEIGHTS",
        {**HEALTH_WEIGHTS, "dead_code": 0.35},
    )

    with pytest.raises(ContractInvariantError, match=r"sum to 1\.0"):
        health_mod.compute_health(_measured_health_inputs())


def test_health_aggregate_refuses_a_negative_weight_that_sums_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A weight below zero must stop the score even when the total is one.

    The opposite error from the test above, and it has to red under its own
    name: a sum-only guard passes this vector and the aggregate then leaves
    [0, 100] on the strength of a single negative term.
    """

    monkeypatch.setattr(
        health_mod,
        "HEALTH_WEIGHTS",
        {**HEALTH_WEIGHTS, "coupling": -0.10, "dead_code": 0.30},
    )

    with pytest.raises(ContractInvariantError, match="never be negative"):
        health_mod.compute_health(_measured_health_inputs())


def test_health_aggregate_accepts_a_recalibrated_unit_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legal recalibration must pass the guard untouched.

    The guard defends the contract, not the shipped numbers: moving mass
    between dimensions while the total stays one is exactly what a sanctioned
    recalibration does, and it must not have to negotiate with this check.
    """

    monkeypatch.setattr(
        health_mod,
        "HEALTH_WEIGHTS",
        {**HEALTH_WEIGHTS, "clones": 0.30, "complexity": 0.15},
    )

    score = health_mod.compute_health(_measured_health_inputs())

    assert 0 <= score.total <= 100


def test_the_weight_sum_pin_reads_the_weights_alone() -> None:
    """The sum pin must not drift back into a re-run of the aggregate.

    A pin shaped like ``sum(dimensions[n] * weights[n] ...)`` is green for
    every weight vector, a vector summing to 1.5 included, so substituting one
    for the other would quietly restore the state this contract removed. The
    pin's own source is therefore part of the contract: it may name the
    weights, never the dimensions or the aggregate that consumes them.
    """

    tree = ast.parse(textwrap.dedent(inspect.getsource(test_health_weights_sum_to_one)))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    body = function.body[1:] if ast.get_docstring(function) else function.body
    statements = "\n".join(ast.unparse(node) for node in body)

    assert "dimensions" not in statements
    assert "compute_health" not in statements
