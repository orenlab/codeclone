# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import importlib
import inspect
import random
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass
from math import fsum
from pathlib import Path
from typing import Literal

import pytest

from codeclone import contracts as contracts_mod
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
    storage_paths,
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


# --------------------------------------------------------------------------------------
# The storage-path authority ratchet
#
# Six product default paths each had two or three spellings: a full literal in
# ``contracts``, a composed ``REL_*`` twin in ``paths.workspace``, a segments
# tuple, and hand-written copies in help text. Each spelling is a place the
# value can rot on its own, and one of them already had.
#
# The rule this enforces is about SEMANTIC IDENTITY, not about string counts.
# "The literal occurs once" is the wrong predicate: the same characters may
# legitimately mean something else somewhere. The predicate here is
#
#     a production module may not RECONSTRUCT a storage-path contract's value
#     out of material it declares itself; it must interpolate a name it
#     imported from the owner.
#
# That is what separates a redeclaration from a derivation, and it is computed
# per named contract, so a failure says which of the six broke and where.
# --------------------------------------------------------------------------------------

_PRODUCTION_ROOT = Path(__file__).resolve().parents[1] / "codeclone"

#: The owner module, as the scan addresses modules: repository-relative.
_STORAGE_PATH_OWNER_MODULE = "codeclone/contracts/storage_paths.py"

#: The module that owns the workspace LAYOUT the six paths sit inside.
_WORKSPACE_LAYOUT_MODULE = "codeclone/paths/workspace.py"


@dataclass(frozen=True)
class _DerivedRef:
    """One production name that speaks a storage-path contract's value.

    ``mode`` is how the owner's value has to show up in it: ``equals`` for a
    re-exported or imported constant, ``contains`` for a sentence that embeds
    the path.
    """

    module: str
    attr: str
    mode: Literal["equals", "contains"]


@dataclass(frozen=True)
class _StoragePathContract:
    """One semantic path contract: an identity, an owner, and its readers."""

    contract_id: str
    owner_attr: str
    #: The layout constants this path sits under, named rather than spelled,
    #: and its own tail. Together they are the RULE; the test re-derives the
    #: answer from them every run instead of restating it.
    prefix_constants: tuple[str, ...]
    tail: tuple[str, ...]
    derived: tuple[_DerivedRef, ...]

    @property
    def value(self) -> str:
        owned: str = getattr(storage_paths, self.owner_attr)
        return owned


_HELP = "codeclone.ui_messages.help"
_SPEC = "codeclone.config.spec"
_CONTRACTS = "codeclone.contracts"

_STORAGE_PATH_CONTRACTS: tuple[_StoragePathContract, ...] = (
    _StoragePathContract(
        contract_id="report.html",
        owner_attr="DEFAULT_HTML_REPORT_PATH",
        prefix_constants=("WORKSPACE_DIR_NAME",),
        tail=("report.html",),
        derived=(
            _DerivedRef(_CONTRACTS, "DEFAULT_HTML_REPORT_PATH", "equals"),
            _DerivedRef(_SPEC, "DEFAULT_HTML_REPORT_PATH", "equals"),
            _DerivedRef(
                "codeclone.surfaces.cli.execution",
                "DEFAULT_HTML_REPORT_PATH",
                "equals",
            ),
            _DerivedRef(_HELP, "HELP_HTML", "contains"),
            _DerivedRef(_HELP, "HELP_TOUR_STEP_REPORTS_BODY", "contains"),
            _DerivedRef(
                "codeclone.surfaces.cli.ui.help_tour",
                "_DEMO_STATS_SUCCESS",
                "contains",
            ),
            _DerivedRef(
                "codeclone.surfaces.cli.ui.help_tour",
                "_DEMO_STATS_REGRESSION",
                "contains",
            ),
        ),
    ),
    _StoragePathContract(
        contract_id="report.json",
        owner_attr="DEFAULT_JSON_REPORT_PATH",
        prefix_constants=("WORKSPACE_DIR_NAME",),
        tail=("report.json",),
        derived=(
            _DerivedRef(_CONTRACTS, "DEFAULT_JSON_REPORT_PATH", "equals"),
            _DerivedRef(_SPEC, "DEFAULT_JSON_REPORT_PATH", "equals"),
            _DerivedRef(
                "codeclone.surfaces.mcp._session_shared",
                "DEFAULT_JSON_REPORT_PATH",
                "equals",
            ),
            _DerivedRef(
                "codeclone.surfaces.cli.memory_analysis",
                "DEFAULT_JSON_REPORT_PATH",
                "equals",
            ),
            _DerivedRef(
                "codeclone.controller_insights.session_stats",
                "DEFAULT_JSON_REPORT_PATH",
                "equals",
            ),
            _DerivedRef(_HELP, "HELP_JSON", "contains"),
            _DerivedRef(
                "codeclone.surfaces.mcp.messages.tools",
                "GET_REPORT_SECTION",
                "contains",
            ),
            _DerivedRef(
                "codeclone.surfaces.mcp._report_section",
                "_REMOVED_SECTION_NEXT_STEP",
                "contains",
            ),
        ),
    ),
    _StoragePathContract(
        contract_id="report.md",
        owner_attr="DEFAULT_MARKDOWN_REPORT_PATH",
        prefix_constants=("WORKSPACE_DIR_NAME",),
        tail=("report.md",),
        derived=(
            _DerivedRef(_CONTRACTS, "DEFAULT_MARKDOWN_REPORT_PATH", "equals"),
            _DerivedRef(_SPEC, "DEFAULT_MARKDOWN_REPORT_PATH", "equals"),
            _DerivedRef(_HELP, "HELP_MD", "contains"),
        ),
    ),
    _StoragePathContract(
        contract_id="report.sarif",
        owner_attr="DEFAULT_SARIF_REPORT_PATH",
        prefix_constants=("WORKSPACE_DIR_NAME",),
        tail=("report.sarif",),
        derived=(
            _DerivedRef(_CONTRACTS, "DEFAULT_SARIF_REPORT_PATH", "equals"),
            _DerivedRef(_SPEC, "DEFAULT_SARIF_REPORT_PATH", "equals"),
            _DerivedRef(_HELP, "HELP_SARIF", "contains"),
        ),
    ),
    _StoragePathContract(
        contract_id="report.txt",
        owner_attr="DEFAULT_TEXT_REPORT_PATH",
        prefix_constants=("WORKSPACE_DIR_NAME",),
        tail=("report.txt",),
        derived=(
            _DerivedRef(_CONTRACTS, "DEFAULT_TEXT_REPORT_PATH", "equals"),
            _DerivedRef(_SPEC, "DEFAULT_TEXT_REPORT_PATH", "equals"),
            _DerivedRef(_HELP, "HELP_TEXT", "contains"),
        ),
    ),
    _StoragePathContract(
        contract_id="cache",
        owner_attr="DEFAULT_CACHE_PATH",
        prefix_constants=("WORKSPACE_DIR_NAME", "CACHE_DB_DIR_NAME"),
        tail=("cache.sqlite3",),
        derived=(
            _DerivedRef(_CONTRACTS, "DEFAULT_CACHE_PATH", "equals"),
            _DerivedRef(_HELP, "HELP_CACHE_PATH", "contains"),
            _DerivedRef(_HELP, "HELP_TOUR_STEP_CACHE_BODY", "contains"),
        ),
    ),
)

#: The population every scan below must actually reach. Named, because a guard
#: that silently checks nothing passes in silence -- that failure mode was hit
#: in this repository while this very wave was being measured.
_EXPECTED_CONTRACT_COUNT = 6
_MIN_PRODUCTION_MODULES = 400


def _eval_str(node: ast.expr, env: dict[str, str]) -> str | None:
    """The string this expression yields from the module's OWN material.

    ``env`` holds only names the module binds itself. A name it imported is
    absent on purpose: interpolating an imported owner is derivation and must
    stay invisible here, while composing the same characters out of local
    constants is the redeclaration this whole ratchet is about.
    """

    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.FormattedValue):
                if piece.conversion != -1 or piece.format_spec is not None:
                    return None
                resolved = _eval_str(piece.value, env)
            else:
                resolved = _eval_str(piece, env)
            if resolved is None:
                return None
            parts.append(resolved)
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_str(node.left, env)
        right = _eval_str(node.right, env)
        return None if left is None or right is None else left + right
    return None


def _eval_path_parts(node: ast.expr, env: dict[str, str]) -> str | None:
    """A path spelled as segments, joined back into the path it means.

    ``REPORT_JSON_PARTS = (WORKSPACE_DIR_NAME, "report.json")`` was the third
    spelling of the JSON report contract and no scan over string literals could
    see it. A segments tuple is the same semantic identity written sideways.
    """

    if not isinstance(node, ast.Tuple | ast.List):
        return None
    segments = [_eval_str(element, env) for element in node.elts]
    if not segments or any(segment is None for segment in segments):
        return None
    return "/".join(str(segment) for segment in segments)


def _eval_any(node: ast.expr, env: dict[str, str]) -> str | None:
    return _eval_str(node, env) or _eval_path_parts(node, env)


def _module_level_assignments(
    tree: ast.Module,
) -> Iterator[tuple[list[ast.expr], ast.expr]]:
    """Every module-level assignment, in either spelling, targets first."""

    for node in tree.body:
        if isinstance(node, ast.Assign):
            yield list(node.targets), node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            yield [node.target], node.value


def _module_level_bindings(tree: ast.Module) -> list[tuple[str, str]]:
    """Module-level ``NAME = <statically resolvable path>`` bindings, in order."""

    bindings: list[tuple[str, str]] = []
    env: dict[str, str] = {}
    for targets, value in _module_level_assignments(tree):
        resolved = _eval_any(value, env)
        if resolved is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                bindings.append((target.id, resolved))
                # Only a plain string may serve later interpolations; a joined
                # segments tuple is not the object the module would splice in.
                if _eval_str(value, env) is not None:
                    env[target.id] = resolved
    return bindings


def _self_composed_strings(tree: ast.Module) -> frozenset[str]:
    """Every string this module can build from what it declares itself."""

    env = dict(_module_level_bindings(tree))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.expr):
            continue
        resolved = _eval_any(node, env)
        if resolved:
            found.add(resolved)
    return frozenset(found)


def _production_modules() -> list[tuple[str, ast.Module]]:
    root = _PRODUCTION_ROOT.parent
    return [
        (
            path.relative_to(root).as_posix(),
            ast.parse(path.read_text("utf-8"), filename=str(path)),
        )
        for path in sorted(_PRODUCTION_ROOT.rglob("*.py"))
    ]


def _workspace_layout_constants() -> dict[str, str]:
    """``paths.workspace``'s layout constants, read as source, not imported.

    The boundary ratchet freezes which test modules may import r2 production
    packages, and this file is not one of them for ``codeclone.paths``.
    Reading is also the more honest instrument: the question is whether the
    owner still equals what the layout module DECLARES, which is a fact about
    that module's source, and it reuses the same evaluator the scans use.
    """

    path = _PRODUCTION_ROOT.parent / _WORKSPACE_LAYOUT_MODULE
    return dict(_module_level_bindings(ast.parse(path.read_text("utf-8"))))


def test_every_storage_path_contract_rederives_from_the_workspace_layout() -> None:
    """The owner's value is the layout rule applied, not a remembered string.

    Pinning ``== ".codeclone/report.html"`` would move the magic constant into
    the test and leave the stated basis unexecuted. This recomputes each value
    from the layout constants ``paths.workspace`` declares plus the contract's
    own tail, so renaming the workspace without moving these paths goes red.
    """

    layout = _workspace_layout_constants()
    assert {"WORKSPACE_DIR_NAME", "CACHE_DB_DIR_NAME"} <= layout.keys(), (
        f"the layout module no longer declares the constants this rule reads: "
        f"{sorted(layout)}"
    )

    checked = 0
    for contract in _STORAGE_PATH_CONTRACTS:
        expected = "/".join(
            (
                *(layout[name] for name in contract.prefix_constants),
                *contract.tail,
            )
        )
        assert contract.value == expected, (
            f"{contract.contract_id}: owner value {contract.value!r} is no longer "
            f"the workspace layout applied ({expected!r})"
        )
        checked += 1

    assert checked == _EXPECTED_CONTRACT_COUNT


def test_each_storage_path_contract_has_exactly_one_value_owner() -> None:
    """One normative declaration per contract, anywhere in production.

    A declaration is a module-level binding whose value the module itself can
    produce -- a full literal, an f-string over its own constants, or a
    segments tuple. All three shipped at once for these six paths.
    """

    modules = _production_modules()
    assert len(modules) >= _MIN_PRODUCTION_MODULES, (
        f"the declaration scan reached only {len(modules)} production modules"
    )

    bindings_by_module = {
        relative: _module_level_bindings(tree) for relative, tree in modules
    }

    checked = 0
    for contract in _STORAGE_PATH_CONTRACTS:
        sites = sorted(
            f"{relative}::{name}"
            for relative, bindings in bindings_by_module.items()
            for name, value in bindings
            if value == contract.value
        )
        assert sites == [f"{_STORAGE_PATH_OWNER_MODULE}::{contract.owner_attr}"], (
            f"{contract.contract_id} is declared in more than one place, or not "
            f"by its owner: {sites}"
        )
        checked += 1

    assert checked == _EXPECTED_CONTRACT_COUNT


def test_no_production_module_respells_a_storage_path_contract() -> None:
    """Outside the owner, the value may only arrive by import.

    This is the half that catches a derived reference being turned back into a
    hand-written literal -- including inside a help sentence, where the copy
    that went stale actually lived.
    """

    modules = _production_modules()
    assert len(modules) >= _MIN_PRODUCTION_MODULES, (
        f"the respell scan reached only {len(modules)} production modules"
    )

    composed_by_module = {
        relative: _self_composed_strings(tree)
        for relative, tree in modules
        if relative != _STORAGE_PATH_OWNER_MODULE
    }

    offenders: list[str] = []
    for contract in _STORAGE_PATH_CONTRACTS:
        offenders.extend(
            f"{contract.contract_id} respelled in {relative}"
            for relative, composed in sorted(composed_by_module.items())
            if any(contract.value in candidate for candidate in composed)
        )

    assert offenders == [], (
        "these production modules build a storage-path contract out of their own "
        f"material instead of importing it from the owner: {offenders}"
    )


def test_the_respell_scan_can_see_a_composed_respelling() -> None:
    """The detector is reachable: the historical shapes still trip it.

    A scan whose evaluator quietly failed on f-strings would report an empty
    offender list forever and read as success. These are the two shapes this
    wave actually removed, fed to the evaluator directly.
    """

    composed = _self_composed_strings(
        ast.parse(
            "WORKSPACE_DIR_NAME = '.codeclone'\n"
            "CACHE_DB_DIR_NAME = 'db'\n"
            "REL_REPORT_JSON_PATH = f'{WORKSPACE_DIR_NAME}/report.json'\n"
            "REPORT_JSON_PARTS = (WORKSPACE_DIR_NAME, 'report.json')\n"
            "REL_CACHE_PATH = "
            "f'{WORKSPACE_DIR_NAME}/{CACHE_DB_DIR_NAME}/cache.sqlite3'\n"
        )
    )

    assert storage_paths.DEFAULT_JSON_REPORT_PATH in composed
    assert storage_paths.DEFAULT_CACHE_PATH in composed

    derived_only = _self_composed_strings(
        ast.parse(
            "from codeclone.contracts import DEFAULT_JSON_REPORT_PATH\n"
            "HELP = f'writes to {DEFAULT_JSON_REPORT_PATH}.'\n"
        )
    )
    assert not any(
        storage_paths.DEFAULT_JSON_REPORT_PATH in candidate
        for candidate in derived_only
    ), "interpolating an imported owner must not read as a respelling"


def _normalized(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, tuple | list):
        return "\n".join(str(item) for item in value)
    raise AssertionError(f"unsupported derived reference shape: {type(value)!r}")


def test_every_declared_derived_reference_reads_the_owner() -> None:
    """Each declared reader actually carries the owner's value at runtime."""

    checked = 0
    per_contract: dict[str, int] = {}
    for contract in _STORAGE_PATH_CONTRACTS:
        for ref in contract.derived:
            module = importlib.import_module(ref.module)
            actual = _normalized(getattr(module, ref.attr))
            if ref.mode == "equals":
                assert actual == contract.value, (
                    f"{ref.module}.{ref.attr} no longer equals the "
                    f"{contract.contract_id} owner"
                )
            else:
                assert contract.value in actual, (
                    f"{ref.module}.{ref.attr} no longer speaks the "
                    f"{contract.contract_id} owner"
                )
            checked += 1
        per_contract[contract.contract_id] = len(contract.derived)

    assert len(per_contract) == _EXPECTED_CONTRACT_COUNT
    assert min(per_contract.values()) >= 1, per_contract
    assert checked == sum(per_contract.values())
    assert checked == 27, f"derived-reference population moved: {per_contract}"


def test_the_six_storage_path_contracts_stay_six_distinct_identities() -> None:
    """Six contracts, six owners, six values -- never one blob.

    The temptation this closes is collapsing the six into a single mapping or a
    shared prefix constant. That would make one owner move all six, which the
    negative control below is written to catch and this makes structurally
    impossible to reach by accident.
    """

    ids = [contract.contract_id for contract in _STORAGE_PATH_CONTRACTS]
    owners = [contract.owner_attr for contract in _STORAGE_PATH_CONTRACTS]
    values = [contract.value for contract in _STORAGE_PATH_CONTRACTS]

    assert len(ids) == _EXPECTED_CONTRACT_COUNT
    assert len(set(ids)) == _EXPECTED_CONTRACT_COUNT
    assert len(set(owners)) == _EXPECTED_CONTRACT_COUNT
    assert len(set(values)) == _EXPECTED_CONTRACT_COUNT
    # Derived from the owner, never maintained beside it: a hand-kept count
    # follows a silent registry shrink, so the population is taken from what
    # the owner publishes. Dropping a contract from this ratchet while the
    # owner still exports it goes red here.
    assert set(owners) == set(storage_paths.__all__)
    assert len(_STORAGE_PATH_CONTRACTS) == len(storage_paths.__all__)


def _help_surface_attrs(contract: _StoragePathContract) -> tuple[str, ...]:
    return tuple(sorted(ref.attr for ref in contract.derived if ref.module == _HELP))


def test_moving_one_storage_path_owner_moves_only_its_own_help_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: each owner drives its own surfaces and no others.

    Causal, not structural: the owner is re-pointed and the help module is
    re-executed against it, which is what a real edit to the constant does one
    commit later. Both halves are asserted -- the contract's own help lines
    MUST move, and the other five contracts' help lines MUST NOT.
    """

    help_module = importlib.import_module(_HELP)
    watched = sorted(
        {
            attr
            for contract in _STORAGE_PATH_CONTRACTS
            for attr in _help_surface_attrs(contract)
        }
    )
    assert len(watched) >= _EXPECTED_CONTRACT_COUNT, watched

    for contract in _STORAGE_PATH_CONTRACTS:
        before = {attr: getattr(help_module, attr) for attr in watched}
        monkeypatch.setattr(contracts_mod, contract.owner_attr, "MUTANT/SENTINEL.PATH")
        try:
            importlib.reload(help_module)
            moved = frozenset(
                attr for attr in watched if getattr(help_module, attr) != before[attr]
            )
        finally:
            monkeypatch.undo()
            importlib.reload(help_module)

        own = frozenset(_help_surface_attrs(contract))
        assert moved == own, (
            f"re-pointing the {contract.contract_id} owner moved {sorted(moved)}; "
            f"its own help surfaces are {sorted(own)}"
        )
        assert {attr: getattr(help_module, attr) for attr in watched} == before, (
            "the negative control failed to restore the help surface"
        )
