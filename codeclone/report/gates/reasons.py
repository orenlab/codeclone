# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Protocol

from ..messages import gates as gate_msgs

__all__ = [
    "parse_metric_reason_entry",
    "policy_context",
    "print_gating_failure_block",
]


class _GatingArgs(Protocol):
    ci: bool
    fail_on_new_metrics: bool
    fail_on_typing_regression: bool
    fail_on_docstring_regression: bool
    fail_on_api_break: bool
    fail_on_untested_hotspots: bool
    fail_complexity: int
    fail_coupling: int
    fail_cohesion: int
    fail_cycles: bool
    fail_dead_code: bool
    fail_health: int
    min_typing_coverage: int
    min_docstring_coverage: int
    coverage_min: int
    fail_on_new: bool
    fail_threshold: int


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def _strip_terminal_period(text: str) -> str:
    return text[:-1] if text.endswith(".") else text


def _parse_two_part_metric_detail(
    text: str,
    *,
    prefix: str,
    right_label: str,
) -> str | None:
    if not text.startswith(prefix):
        return None
    left_part, right_part = text[len(prefix) :].split(", ", maxsplit=1)
    return (
        f"{left_part.rsplit('=', maxsplit=1)[1]} "
        f"({right_label}={right_part.rsplit('=', maxsplit=1)[1]})"
    )


def parse_metric_reason_entry(reason: str) -> tuple[str, str]:
    trimmed = _strip_terminal_period(reason)

    def tail(prefix: str) -> str:
        return trimmed[len(prefix) :]

    simple_prefixes: tuple[tuple[str, str], ...] = (
        (gate_msgs.GATE_REASON_NEW_HIGH_RISK_FUNCTIONS, "new_high_risk_functions"),
        (gate_msgs.GATE_REASON_NEW_HIGH_COUPLING, "new_high_coupling_classes"),
        (gate_msgs.GATE_REASON_NEW_CYCLES, "new_dependency_cycles"),
        (gate_msgs.GATE_REASON_NEW_DEAD_CODE, "new_dead_code_items"),
    )
    for prefix, kind in simple_prefixes:
        if trimmed.startswith(prefix):
            return kind, tail(prefix)

    if trimmed.startswith(gate_msgs.GATE_REASON_HEALTH_REGRESSION):
        return "health_delta", trimmed.rsplit("=", maxsplit=1)[1]
    typing_detail = _parse_two_part_metric_detail(
        trimmed,
        prefix=gate_msgs.GATE_REASON_TYPING_REGRESSION,
        right_label="returns_delta",
    )
    if typing_detail is not None:
        return "typing_coverage_delta", typing_detail
    if trimmed.startswith(gate_msgs.GATE_REASON_DOCSTRING_REGRESSION):
        return "docstring_coverage_delta", trimmed.rsplit("=", maxsplit=1)[1]
    if trimmed.startswith(gate_msgs.GATE_REASON_API_BREAKING):
        return "api_breaking_changes", tail(gate_msgs.GATE_REASON_API_BREAKING)
    coverage_detail = _parse_two_part_metric_detail(
        trimmed,
        prefix=gate_msgs.GATE_REASON_COVERAGE_HOTSPOTS,
        right_label="threshold",
    )
    if coverage_detail is not None:
        return "coverage_hotspots", coverage_detail

    if trimmed.startswith(gate_msgs.GATE_REASON_CYCLES_DETECTED):
        return "dependency_cycles", tail(gate_msgs.GATE_REASON_CYCLES_DETECTED).replace(
            gate_msgs.GATE_SUFFIX_CYCLES, ""
        )

    if trimmed.startswith(gate_msgs.GATE_REASON_DEAD_CODE_DETECTED):
        return "dead_code_items", tail(
            gate_msgs.GATE_REASON_DEAD_CODE_DETECTED
        ).replace(gate_msgs.GATE_SUFFIX_ITEMS, "")

    threshold_prefixes: tuple[tuple[str, str], ...] = (
        (gate_msgs.GATE_REASON_COMPLEXITY_THRESHOLD, "complexity_max"),
        (gate_msgs.GATE_REASON_COUPLING_THRESHOLD, "coupling_max"),
        (gate_msgs.GATE_REASON_COHESION_THRESHOLD, "cohesion_max"),
        (gate_msgs.GATE_REASON_HEALTH_THRESHOLD, "health_score"),
        (gate_msgs.GATE_REASON_TYPING_THRESHOLD, "typing_coverage"),
        (gate_msgs.GATE_REASON_DOCSTRING_THRESHOLD, "docstring_coverage"),
    )
    for prefix, kind in threshold_prefixes:
        threshold_detail = _parse_two_part_metric_detail(
            trimmed,
            prefix=prefix,
            right_label="threshold",
        )
        if threshold_detail is not None:
            return kind, threshold_detail

    return "detail", trimmed


def policy_context(*, args: _GatingArgs, gate_kind: str) -> str:
    if args.ci:
        return "ci"

    parts: tuple[str | None, ...]
    match gate_kind:
        case "metrics":
            parts = (
                "fail-on-new-metrics"
                if bool(getattr(args, "fail_on_new_metrics", False))
                else None,
                f"fail-complexity={getattr(args, 'fail_complexity', -1)}"
                if int(getattr(args, "fail_complexity", -1)) >= 0
                else None,
                f"fail-coupling={getattr(args, 'fail_coupling', -1)}"
                if int(getattr(args, "fail_coupling", -1)) >= 0
                else None,
                f"fail-cohesion={getattr(args, 'fail_cohesion', -1)}"
                if int(getattr(args, "fail_cohesion", -1)) >= 0
                else None,
                "fail-cycles" if bool(getattr(args, "fail_cycles", False)) else None,
                "fail-dead-code"
                if bool(getattr(args, "fail_dead_code", False))
                else None,
                f"fail-health={getattr(args, 'fail_health', -1)}"
                if int(getattr(args, "fail_health", -1)) >= 0
                else None,
                "fail-on-typing-regression"
                if bool(getattr(args, "fail_on_typing_regression", False))
                else None,
                "fail-on-docstring-regression"
                if bool(getattr(args, "fail_on_docstring_regression", False))
                else None,
                "fail-on-api-break"
                if bool(getattr(args, "fail_on_api_break", False))
                else None,
                "fail-on-untested-hotspots"
                if bool(getattr(args, "fail_on_untested_hotspots", False))
                else None,
                f"min-typing-coverage={getattr(args, 'min_typing_coverage', -1)}"
                if int(getattr(args, "min_typing_coverage", -1)) >= 0
                else None,
                f"min-docstring-coverage={getattr(args, 'min_docstring_coverage', -1)}"
                if int(getattr(args, "min_docstring_coverage", -1)) >= 0
                else None,
                f"coverage-min={getattr(args, 'coverage_min', -1)}"
                if bool(getattr(args, "fail_on_untested_hotspots", False))
                else None,
            )
        case "new-clones":
            parts = (
                "fail-on-new" if bool(getattr(args, "fail_on_new", False)) else None,
            )
        case "threshold":
            parts = (
                f"fail-threshold={getattr(args, 'fail_threshold', -1)}"
                if int(getattr(args, "fail_threshold", -1)) >= 0
                else None,
            )
        case _:
            parts = ()

    enabled_parts = tuple(part for part in parts if part is not None)
    return ", ".join(enabled_parts) if enabled_parts else "custom"


def print_gating_failure_block(
    *,
    console: _PrinterLike,
    code: str,
    entries: tuple[tuple[str, object], ...] | list[tuple[str, object]],
    args: _GatingArgs,
) -> None:
    console.print(
        f"\n\u2717 {gate_msgs.GATE_FAILURE_HEADER.format(code=code)}",
        style="bold red",
        markup=False,
    )
    normalized_entries = [("policy", policy_context(args=args, gate_kind=code))]
    normalized_entries.extend((key, str(value)) for key, value in entries)
    width = max(len(key) for key, _ in normalized_entries)
    console.print()
    for key, value in normalized_entries:
        console.print(f"  {key:<{width}}: {value}")
