# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import ast
import operator
from typing import Any, cast

import pytest

import codeclone.analysis as analysis_mod
import codeclone.analysis.units as units_mod
import codeclone.config.argparse_builder as argparse_builder_mod
import codeclone.config.spec as spec_mod
import codeclone.report.gates.evaluator as evaluator_mod
import codeclone.surfaces.cli.console as cli_console_mod
import codeclone.surfaces.cli.state as cli_state_mod
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.config.spec import OptionSpec
from codeclone.contracts.errors import ParseError
from codeclone.report.gates.evaluator import MetricGateConfig
from codeclone.utils.git_diff import validate_git_diff_ref


def _report_document() -> dict[str, object]:
    return {
        "findings": {
            "groups": {
                "clones": {
                    "functions": [{"id": "clone:function:new", "novelty": "new"}],
                    "blocks": [],
                }
            }
        },
        "metrics": {
            "families": {
                "complexity": {"summary": {"max": 30}},
                "coupling": {"summary": {"max": 12}},
                "cohesion": {"summary": {"max": 4}},
                "dependencies": {"summary": {"cycles": 0}},
                "dead_code": {"summary": {"high_confidence": 1}},
                "health": {"summary": {"score": 90}},
                "coverage_adoption": {
                    "summary": {
                        "param_permille": 1000,
                        "docstring_permille": 1000,
                        "param_delta": 0,
                        "return_delta": 0,
                        "docstring_delta": 0,
                    }
                },
                "api_surface": {"summary": {"breaking": 0}},
                "coverage_join": {"summary": {"status": "", "coverage_hotspots": 0}},
            }
        },
    }


def test_analysis_module_exports_extract_units_directly() -> None:
    assert (
        analysis_mod.extract_units_and_stats_from_source
        is units_mod.extract_units_and_stats_from_source
    )
    with pytest.raises(AttributeError, match="has no attribute 'missing'"):
        operator.attrgetter("missing")(analysis_mod)


def test_extract_units_rejects_non_module_ast_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(units_mod, "_parse_with_limits", lambda *_args: ast.Pass())
    with pytest.raises(ParseError, match="expected module AST root"):
        units_mod.extract_units_and_stats_from_source(
            source="pass\n",
            filepath="pkg/mod.py",
            module_name="pkg.mod",
            cfg=NormalizationConfig(),
            min_loc=1,
            min_stmt=1,
        )


def test_cli_state_initializes_console_once_and_allows_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr(cli_state_mod, "console", None)
    monkeypatch.setattr(cli_console_mod, "make_plain_console", lambda: sentinel)

    assert cli_state_mod.get_console() is sentinel
    assert cli_state_mod.get_console() is sentinel

    replacement = object()
    cli_state_mod.set_console(replacement)
    assert cli_state_mod.get_console() is replacement


def test_validate_git_diff_ref_rejects_control_whitespace_characters() -> None:
    with pytest.raises(ValueError, match="whitespace and control characters"):
        validate_git_diff_ref("main\tHEAD")


def test_validate_git_diff_ref_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_git_diff_ref("")


def test_add_option_rejects_unsupported_cli_kind() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_argument_group("Example")
    option = OptionSpec(
        dest="broken",
        group="Example",
        cli_kind=cast(Any, "broken-kind"),
        flags=("--broken",),
    )

    with pytest.raises(RuntimeError, match="Unsupported CLI option kind"):
        argparse_builder_mod._add_option(group, option=option, version="2.0.0")


def test_config_spec_option_supports_explicit_pyproject_key_and_conflict_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit = spec_mod._option(
        dest="baseline_path",
        group="Example",
        pyproject_type=str,
        pyproject_key="baseline-file",
    )
    assert explicit.pyproject_key == "baseline-file"

    monkeypatch.setattr(
        spec_mod,
        "OPTIONS",
        (
            spec_mod._option(
                dest="first",
                group="Example",
                pyproject_type=str,
                pyproject_key="shared",
            ),
            spec_mod._option(
                dest="second",
                group="Example",
                pyproject_type=int,
                pyproject_key="shared",
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="Conflicting pyproject spec for shared"):
        spec_mod._build_pyproject_specs()


def test_summarize_metrics_diff_accepts_mapping_payload() -> None:
    summary = evaluator_mod.summarize_metrics_diff(
        {
            "new_high_risk_functions": 2,
            "new_high_coupling_classes": 3,
            "new_cycles": 4,
            "new_dead_code": 5,
            "health_delta": -2,
            "typing_param_permille_delta": -100,
            "typing_return_permille_delta": -200,
            "docstring_permille_delta": -300,
            "new_api_breaking_changes": 7,
        }
    )

    assert summary == {
        "new_high_risk_functions": 2,
        "new_high_coupling_classes": 3,
        "new_cycles": 4,
        "new_dead_code": 5,
        "health_delta": -2,
        "typing_param_permille_delta": -100,
        "typing_return_permille_delta": -200,
        "docstring_permille_delta": -300,
        "new_api_symbols": 0,
        "api_breaking_changes": 7,
    }


def test_metric_gate_reasons_wrapper_uses_report_document_snapshot() -> None:
    reasons = evaluator_mod.metric_gate_reasons(
        report_document=_report_document(),
        config=MetricGateConfig(
            fail_complexity=20,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=True,
            fail_health=-1,
            fail_on_new_metrics=False,
            fail_on_typing_regression=False,
            fail_on_docstring_regression=False,
            fail_on_api_break=False,
            fail_on_untested_hotspots=False,
            min_typing_coverage=-1,
            min_docstring_coverage=-1,
            coverage_min=50,
            fail_on_new=True,
            fail_threshold=0,
        ),
        metrics_diff={"new_dead_code": 1, "health_delta": -1},
    )

    assert "Complexity threshold exceeded: max CC=30, threshold=20." in reasons
    assert "Dead code detected (high confidence): 1 item(s)." in reasons
    assert "New dead code items vs metrics baseline: 1." not in reasons


def test_metric_gate_reasons_for_state_skips_missing_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(
        evaluator_mod._GATE_REASON_BUILDERS,
        "complexity_threshold",
        raising=False,
    )

    reasons = evaluator_mod.metric_gate_reasons_for_state(
        state=evaluator_mod.GateState(complexity_max=10),
        config=MetricGateConfig(
            fail_complexity=5,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
            fail_on_typing_regression=False,
            fail_on_docstring_regression=False,
            fail_on_api_break=False,
            fail_on_untested_hotspots=False,
            min_typing_coverage=-1,
            min_docstring_coverage=-1,
            coverage_min=50,
            fail_on_new=False,
            fail_threshold=-1,
        ),
    )

    assert reasons == ()
