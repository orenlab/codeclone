# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
from pathlib import Path

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
    HEALTH_DEPENDENCY_MAX_DEPTH_SAFE_ZONE,
)
from codeclone.core._types import DEFAULT_RUNTIME_PROCESSES
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
    assert args.metrics_baseline == DEFAULT_BASELINE_PATH
    assert args.coverage_min == DEFAULT_COVERAGE_MIN


def test_size_byte_limits_derive_from_contract_megabyte_defaults() -> None:
    assert MAX_CACHE_SIZE_BYTES == DEFAULT_MAX_CACHE_SIZE_MB * 1024 * 1024
    assert MAX_BASELINE_SIZE_BYTES == DEFAULT_MAX_BASELINE_SIZE_MB * 1024 * 1024


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
    assert args.metrics_baseline == DEFAULT_BASELINE_PATH
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


def test_dependency_depth_safe_zone_stays_shared_between_contract_and_html() -> None:
    source = inspect.getsource(html_dependencies_mod.render_dependencies_panel)
    assert "HEALTH_DEPENDENCY_MAX_DEPTH_SAFE_ZONE" in source
    assert HEALTH_DEPENDENCY_MAX_DEPTH_SAFE_ZONE == 8
