# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import Protocol

__all__ = [
    "parse_metric_reason_entry",
    "policy_context",
    "print_gating_failure_block",
]


class _GatingArgs(Protocol):
    ci: bool
    fail_on_new_metrics: bool
    fail_complexity: int
    fail_coupling: int
    fail_cohesion: int
    fail_cycles: bool
    fail_dead_code: bool
    fail_health: int
    fail_on_new: bool
    fail_threshold: int


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def _strip_terminal_period(text: str) -> str:
    return text[:-1] if text.endswith(".") else text


def parse_metric_reason_entry(reason: str) -> tuple[str, str]:
    trimmed = _strip_terminal_period(reason)

    def tail(prefix: str) -> str:
        return trimmed[len(prefix) :]

    simple_prefixes: tuple[tuple[str, str], ...] = (
        ("New high-risk functions vs metrics baseline: ", "new_high_risk_functions"),
        (
            "New high-coupling classes vs metrics baseline: ",
            "new_high_coupling_classes",
        ),
        ("New dependency cycles vs metrics baseline: ", "new_dependency_cycles"),
        ("New dead code items vs metrics baseline: ", "new_dead_code_items"),
    )
    for prefix, kind in simple_prefixes:
        if trimmed.startswith(prefix):
            return kind, tail(prefix)

    if trimmed.startswith("Health score regressed vs metrics baseline: delta="):
        return "health_delta", trimmed.rsplit("=", maxsplit=1)[1]

    if trimmed.startswith("Dependency cycles detected: "):
        return "dependency_cycles", tail("Dependency cycles detected: ").replace(
            " cycle(s)", ""
        )

    if trimmed.startswith("Dead code detected (high confidence): "):
        return "dead_code_items", tail(
            "Dead code detected (high confidence): "
        ).replace(" item(s)", "")

    threshold_prefixes: tuple[tuple[str, str], ...] = (
        ("Complexity threshold exceeded: ", "complexity_max"),
        ("Coupling threshold exceeded: ", "coupling_max"),
        ("Cohesion threshold exceeded: ", "cohesion_max"),
        ("Health score below threshold: ", "health_score"),
    )
    for prefix, kind in threshold_prefixes:
        if trimmed.startswith(prefix):
            left_part, threshold_part = tail(prefix).split(", ")
            return (
                kind,
                f"{left_part.rsplit('=', maxsplit=1)[1]} "
                f"(threshold={threshold_part.rsplit('=', maxsplit=1)[1]})",
            )

    return "detail", trimmed


def policy_context(*, args: _GatingArgs, gate_kind: str) -> str:
    if args.ci:
        return "ci"

    parts: tuple[str | None, ...]
    match gate_kind:
        case "metrics":
            parts = (
                "fail-on-new-metrics" if args.fail_on_new_metrics else None,
                f"fail-complexity={args.fail_complexity}"
                if args.fail_complexity >= 0
                else None,
                f"fail-coupling={args.fail_coupling}"
                if args.fail_coupling >= 0
                else None,
                f"fail-cohesion={args.fail_cohesion}"
                if args.fail_cohesion >= 0
                else None,
                "fail-cycles" if args.fail_cycles else None,
                "fail-dead-code" if args.fail_dead_code else None,
                f"fail-health={args.fail_health}" if args.fail_health >= 0 else None,
            )
        case "new-clones":
            parts = ("fail-on-new" if args.fail_on_new else None,)
        case "threshold":
            parts = (
                f"fail-threshold={args.fail_threshold}"
                if args.fail_threshold >= 0
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
    console.print(f"\n\u2717 GATING FAILURE [{code}]", style="bold red", markup=False)
    normalized_entries = [("policy", policy_context(args=args, gate_kind=code))]
    normalized_entries.extend((key, str(value)) for key, value in entries)
    width = max(len(key) for key, _ in normalized_entries)
    console.print()
    for key, value in normalized_entries:
        console.print(f"  {key:<{width}}: {value}")
