# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any, cast

from .session import (
    DEFAULT_MCP_HISTORY_LIMIT,
    MCPAnalysisRequest,
    MCPGateRequest,
    MCPSession,
)
from .tools import MCP_TOOLS_BY_NAME
from .tools._base import MCPTool


class CodeCloneMCPService:
    def __init__(self, *, history_limit: int = DEFAULT_MCP_HISTORY_LIMIT) -> None:
        self.session = MCPSession(history_limit=history_limit)
        self._tools: Mapping[str, MCPTool] = MCP_TOOLS_BY_NAME

    def __getattr__(self, name: str) -> Any:
        return getattr(self.session, name)

    def _dispatch(self, name: str, **params: object) -> object:
        return self._tools[name].run(self.session, params)

    def analyze_repository(self, request: MCPAnalysisRequest) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("analyze_repository", request=request),
        )

    def analyze_changed_paths(self, request: MCPAnalysisRequest) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("analyze_changed_paths", request=request),
        )

    def get_run_summary(self, run_id: str | None = None) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("get_run_summary", run_id=run_id),
        )

    def compare_runs(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("compare_runs", **params))

    def evaluate_gates(self, request: MCPGateRequest) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("evaluate_gates", request=request),
        )

    def get_report_section(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("get_report_section", **params))

    def list_findings(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("list_findings", **params))

    def get_finding(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("get_finding", **params))

    def get_remediation(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("get_remediation", **params))

    def list_hotspots(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("list_hotspots", **params))

    def get_production_triage(self, **params: object) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("get_production_triage", **params),
        )

    def get_help(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("help", **params))

    def generate_pr_summary(self, **params: object) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("generate_pr_summary", **params),
        )

    def mark_finding_reviewed(self, **params: object) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("mark_finding_reviewed", **params),
        )

    def list_reviewed_findings(self, **params: object) -> dict[str, object]:
        return cast(
            "dict[str, object]",
            self._dispatch("list_reviewed_findings", **params),
        )

    def clear_session_runs(self) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("clear_session_runs"))

    def check_complexity(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("check_complexity", **params))

    def check_clones(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("check_clones", **params))

    def check_coupling(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("check_coupling", **params))

    def check_cohesion(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("check_cohesion", **params))

    def check_dead_code(self, **params: object) -> dict[str, object]:
        return cast("dict[str, object]", self._dispatch("check_dead_code", **params))

    def read_resource(self, uri: str) -> str:
        return self.session.read_resource(uri)


_EMPTY = inspect.Signature.empty


def _kwonly(
    name: str,
    annotation: str,
    default: object = _EMPTY,
) -> inspect.Parameter:
    return inspect.Parameter(
        name,
        inspect.Parameter.KEYWORD_ONLY,
        default=default,
        annotation=annotation,
    )


def _apply_public_method_signatures() -> None:
    signature_specs: dict[str, tuple[inspect.Parameter, ...]] = {
        "check_clones": (
            _kwonly("run_id", "str | None", None),
            _kwonly("root", "str | None", None),
            _kwonly("path", "str | None", None),
            _kwonly("clone_type", "str | None", None),
            _kwonly("source_kind", "str | None", None),
            _kwonly("max_results", "int", 10),
            _kwonly("detail_level", "DetailLevel", "summary"),
        ),
        "check_cohesion": (
            _kwonly("run_id", "str | None", None),
            _kwonly("root", "str | None", None),
            _kwonly("path", "str | None", None),
            _kwonly("max_results", "int", 10),
            _kwonly("detail_level", "DetailLevel", "summary"),
        ),
        "check_complexity": (
            _kwonly("run_id", "str | None", None),
            _kwonly("root", "str | None", None),
            _kwonly("path", "str | None", None),
            _kwonly("min_complexity", "int | None", None),
            _kwonly("max_results", "int", 10),
            _kwonly("detail_level", "DetailLevel", "summary"),
        ),
        "check_coupling": (
            _kwonly("run_id", "str | None", None),
            _kwonly("root", "str | None", None),
            _kwonly("path", "str | None", None),
            _kwonly("max_results", "int", 10),
            _kwonly("detail_level", "DetailLevel", "summary"),
        ),
        "check_dead_code": (
            _kwonly("run_id", "str | None", None),
            _kwonly("root", "str | None", None),
            _kwonly("path", "str | None", None),
            _kwonly("min_severity", "str | None", None),
            _kwonly("max_results", "int", 10),
            _kwonly("detail_level", "DetailLevel", "summary"),
        ),
        "compare_runs": (
            _kwonly("run_id_before", "str"),
            _kwonly("run_id_after", "str | None", None),
            _kwonly("focus", "ComparisonFocus", "all"),
        ),
        "generate_pr_summary": (
            _kwonly("run_id", "str | None", None),
            _kwonly("changed_paths", "Sequence[str]", ()),
            _kwonly("git_diff_ref", "str | None", None),
            _kwonly("format", "PRSummaryFormat", "markdown"),
        ),
        "get_finding": (
            _kwonly("finding_id", "str"),
            _kwonly("run_id", "str | None", None),
            _kwonly("detail_level", "DetailLevel", "normal"),
        ),
        "get_help": (
            _kwonly("topic", "HelpTopic"),
            _kwonly("detail", "HelpDetail", "compact"),
        ),
        "get_production_triage": (
            _kwonly("run_id", "str | None", None),
            _kwonly("max_hotspots", "int", 3),
            _kwonly("max_suggestions", "int", 3),
        ),
        "get_remediation": (
            _kwonly("finding_id", "str"),
            _kwonly("run_id", "str | None", None),
            _kwonly("detail_level", "DetailLevel", "normal"),
        ),
        "get_report_section": (
            _kwonly("run_id", "str | None", None),
            _kwonly("section", "ReportSection", "all"),
            _kwonly("family", "MetricsDetailFamily | None", None),
            _kwonly("path", "str | None", None),
            _kwonly("offset", "int", 0),
            _kwonly("limit", "int", 50),
        ),
        "list_findings": (
            _kwonly("run_id", "str | None", None),
            _kwonly("family", "FindingFamilyFilter", "all"),
            _kwonly("category", "str | None", None),
            _kwonly("severity", "str | None", None),
            _kwonly("source_kind", "str | None", None),
            _kwonly("novelty", "FindingNoveltyFilter", "all"),
            _kwonly("sort_by", "FindingSort", "default"),
            _kwonly("detail_level", "DetailLevel", "summary"),
            _kwonly("changed_paths", "Sequence[str]", ()),
            _kwonly("git_diff_ref", "str | None", None),
            _kwonly("exclude_reviewed", "bool", False),
            _kwonly("offset", "int", 0),
            _kwonly("limit", "int", 50),
            _kwonly("max_results", "int | None", None),
        ),
        "list_hotspots": (
            _kwonly("kind", "HotlistKind"),
            _kwonly("run_id", "str | None", None),
            _kwonly("detail_level", "DetailLevel", "summary"),
            _kwonly("changed_paths", "Sequence[str]", ()),
            _kwonly("git_diff_ref", "str | None", None),
            _kwonly("exclude_reviewed", "bool", False),
            _kwonly("limit", "int", 10),
            _kwonly("max_results", "int | None", None),
        ),
        "list_reviewed_findings": (_kwonly("run_id", "str | None", None),),
        "mark_finding_reviewed": (
            _kwonly("finding_id", "str"),
            _kwonly("run_id", "str | None", None),
            _kwonly("note", "str | None", None),
        ),
    }
    self_param = inspect.Parameter("self", inspect.Parameter.POSITIONAL_OR_KEYWORD)
    for name, params in signature_specs.items():
        method = getattr(CodeCloneMCPService, name)
        method.__signature__ = inspect.Signature(
            parameters=(self_param, *params),
            return_annotation="dict[str, object]",
        )


_apply_public_method_signatures()
