# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib.util

from codeclone import baseline as baseline_pkg
from codeclone.analysis import _module_walk as analysis_module_walk
from codeclone.analysis import parser as analysis_parser
from codeclone.analysis import units as analysis_units
from codeclone.analysis.cfg import CFGBuilder
from codeclone.analysis.cfg import CFGBuilder as AnalysisCFGBuilder
from codeclone.analysis.cfg_model import CFG as AnalysisCFG
from codeclone.analysis.cfg_model import Block as AnalysisBlock
from codeclone.analysis.fingerprint import bucket_loc, sha1
from codeclone.analysis.fingerprint import bucket_loc as analysis_bucket_loc
from codeclone.analysis.fingerprint import sha1 as analysis_sha1
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.normalizer import (
    NormalizationConfig as AnalysisNormalizationConfig,
)
from codeclone.baseline.clone_baseline import Baseline
from codeclone.baseline.metrics_baseline import MetricsBaseline
from codeclone.contracts.errors import BaselineValidationError
from codeclone.contracts.schemas import AnalysisProfile, ReportMeta
from codeclone.findings.clones.grouping import build_groups as canonical_build_groups
from codeclone.findings.structural.detectors import (
    scan_function_structure as canonical_scan_function_structure,
)
from codeclone.report.html import build_html_report
from codeclone.surfaces.mcp.server import build_mcp_server
from codeclone.surfaces.mcp.service import CodeCloneMCPService


def test_analysis_canonical_imports_are_stable() -> None:
    assert CFGBuilder is AnalysisCFGBuilder
    assert AnalysisCFG.__module__ == "codeclone.analysis.cfg_model"
    assert AnalysisBlock.__module__ == "codeclone.analysis.cfg_model"
    assert NormalizationConfig is AnalysisNormalizationConfig
    assert sha1 is analysis_sha1
    assert bucket_loc is analysis_bucket_loc


def test_baseline_canonical_imports_match_compat_packages() -> None:
    assert Baseline is baseline_pkg.Baseline
    assert MetricsBaseline.__module__ == "codeclone.baseline.metrics_baseline"


def test_old_analysis_and_findings_paths_are_gone() -> None:
    assert importlib.util.find_spec("codeclone.cli") is None
    assert importlib.util.find_spec("codeclone.cfg") is None
    assert importlib.util.find_spec("codeclone.errors") is None
    assert importlib.util.find_spec("codeclone.extractor") is None
    assert importlib.util.find_spec("codeclone.metrics_baseline") is None
    assert importlib.util.find_spec("codeclone.normalize") is None
    assert importlib.util.find_spec("codeclone.fingerprint") is None
    assert importlib.util.find_spec("codeclone.grouping") is None
    assert importlib.util.find_spec("codeclone.pipeline") is None
    assert importlib.util.find_spec("codeclone.structural_findings") is None
    assert callable(canonical_build_groups)
    assert callable(canonical_scan_function_structure)


def test_extractor_canonical_helpers_live_in_analysis_modules() -> None:
    assert (
        analysis_module_walk._collect_module_walk_data.__module__
        == "codeclone.analysis._module_walk"
    )
    assert (
        analysis_module_walk._resolve_import_target.__module__
        == "codeclone.analysis._module_walk"
    )
    assert (
        analysis_parser._declaration_token_index.__module__
        == "codeclone.analysis.parser"
    )
    assert analysis_units._eligible_unit_shape.__module__ == "codeclone.analysis.units"


def test_html_report_is_canonical_report_subpackage() -> None:
    assert importlib.util.find_spec("codeclone.html_report") is None
    assert importlib.util.find_spec("codeclone._html_report") is None
    assert callable(build_html_report)


def test_mcp_is_canonical_surfaces_subpackage() -> None:
    assert importlib.util.find_spec("codeclone.mcp_service") is None
    assert importlib.util.find_spec("codeclone.mcp_server") is None
    assert callable(build_mcp_server)
    assert CodeCloneMCPService.__module__ == "codeclone.surfaces.mcp.service"


def test_contracts_are_canonical_contracts_package() -> None:
    assert BaselineValidationError.__module__ == "codeclone.contracts.errors"
    assert AnalysisProfile.__module__ == "codeclone.contracts.schemas"
    assert ReportMeta.__module__ == "codeclone.contracts.schemas"
