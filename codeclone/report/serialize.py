# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from .._coerce import as_int, as_mapping, as_sequence
from ..domain.source_scope import IMPACT_SCOPE_NON_RUNTIME, SOURCE_KIND_OTHER
from ._formatting import format_spread_text

_as_int = as_int
_as_mapping = as_mapping
_as_sequence = as_sequence


def render_json_report_document(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )


def format_meta_text_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "(none)"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        formatted = [format_meta_text_value(item) for item in value]
        return ", ".join(formatted) if formatted else "(none)"
    text = str(value).strip()
    return text if text else "(none)"


def _format_key_values(
    mapping: Mapping[str, object],
    keys: Sequence[str],
    *,
    skip_empty: bool = False,
) -> str:
    parts: list[str] = []
    for key in keys:
        if key not in mapping:
            continue
        formatted = format_meta_text_value(mapping.get(key))
        if skip_empty and formatted == "(none)":
            continue
        parts.append(f"{key}={formatted}")
    return " ".join(parts) if parts else "(none)"


def _spread_text(spread: Mapping[str, object]) -> str:
    return format_spread_text(
        _as_int(spread.get("files")),
        _as_int(spread.get("functions")),
    )


def _scope_text(source_scope: Mapping[str, object]) -> str:
    dominant = str(source_scope.get("dominant_kind", "")).strip() or SOURCE_KIND_OTHER
    impact = (
        str(source_scope.get("impact_scope", "")).strip() or IMPACT_SCOPE_NON_RUNTIME
    )
    return f"{dominant}/{impact}"


def _structural_kind_label(kind: object) -> str:
    kind_text = str(kind).strip()
    match kind_text:
        case "duplicated_branches":
            return "Duplicated branches"
        case "clone_guard_exit_divergence":
            return "Clone guard/exit divergence"
        case "clone_cohort_drift":
            return "Clone cohort drift"
        case _:
            return kind_text or "(none)"


def _location_line(
    item: Mapping[str, object],
    *,
    metric_name: str | None = None,
) -> str:
    metric_suffix = ""
    if metric_name is not None and metric_name in item:
        metric_suffix = (
            f" {metric_name}={format_meta_text_value(item.get(metric_name))}"
        )
    return (
        f"- {format_meta_text_value(item.get('qualname'))} "
        f"{format_meta_text_value(item.get('relative_path'))}:"
        f"{format_meta_text_value(item.get('start_line'))}-"
        f"{format_meta_text_value(item.get('end_line'))}"
        f"{metric_suffix}"
    )


def _append_clone_section(
    lines: list[str],
    *,
    title: str,
    groups: Sequence[object],
    novelty: str,
    metric_name: str,
) -> None:
    section_groups = [
        _as_mapping(group)
        for group in groups
        if str(_as_mapping(group).get("novelty", "")) == novelty
    ]
    lines.append(f"{title} ({novelty.upper()}) (groups={len(section_groups)})")
    if not section_groups:
        lines.append("(none)")
        return
    for idx, group in enumerate(section_groups, start=1):
        lines.append(f"=== Clone group #{idx} ===")
        lines.append(
            "id="
            f"{format_meta_text_value(group.get('id'))} "
            f"clone_type={format_meta_text_value(group.get('clone_type'))} "
            f"severity={format_meta_text_value(group.get('severity'))} "
            f"count={format_meta_text_value(group.get('count'))} "
            f"spread={_spread_text(_as_mapping(group.get('spread')))} "
            f"scope={_scope_text(_as_mapping(group.get('source_scope')))}"
        )
        facts = _as_mapping(group.get("facts"))
        if facts:
            lines.append(
                "facts: "
                + _format_key_values(
                    facts,
                    tuple(sorted(str(key) for key in facts)),
                    skip_empty=True,
                )
            )
        display_facts = _as_mapping(group.get("display_facts"))
        if display_facts:
            lines.append(
                "display_facts: "
                + _format_key_values(
                    display_facts,
                    tuple(sorted(str(key) for key in display_facts)),
                    skip_empty=True,
                )
            )
        lines.extend(
            _location_line(item, metric_name=metric_name)
            for item in map(_as_mapping, _as_sequence(group.get("items")))
        )
        lines.append("")
    if lines[-1] == "":
        lines.pop()


def _append_structural_findings(lines: list[str], groups: Sequence[object]) -> None:
    structural_groups = [_as_mapping(group) for group in groups]
    lines.append(f"STRUCTURAL FINDINGS (groups={len(structural_groups)})")
    if not structural_groups:
        lines.append("(none)")
        return
    for idx, group in enumerate(structural_groups, start=1):
        lines.append(f"=== Structural finding #{idx} ===")
        signature = _as_mapping(group.get("signature"))
        stable = _as_mapping(signature.get("stable"))
        control_flow = _as_mapping(stable.get("control_flow"))
        lines.append(
            "id="
            f"{format_meta_text_value(group.get('id'))} "
            f"kind={format_meta_text_value(group.get('kind'))} "
            f"label={_structural_kind_label(group.get('kind'))} "
            f"severity={format_meta_text_value(group.get('severity'))} "
            f"confidence={format_meta_text_value(group.get('confidence'))} "
            f"count={format_meta_text_value(group.get('count'))} "
            f"spread={_spread_text(_as_mapping(group.get('spread')))} "
            f"scope={_scope_text(_as_mapping(group.get('source_scope')))}"
        )
        stable_family = str(stable.get("family", "")).strip()
        match stable_family:
            case "clone_guard_exit_divergence":
                lines.append(
                    "signature: "
                    f"cohort_id={format_meta_text_value(stable.get('cohort_id'))} "
                    f"majority_guard_count="
                    f"{format_meta_text_value(stable.get('majority_guard_count'))} "
                    f"majority_terminal_kind="
                    f"{format_meta_text_value(stable.get('majority_terminal_kind'))}"
                )
            case "clone_cohort_drift":
                majority_profile = _as_mapping(stable.get("majority_profile"))
                lines.append(
                    "signature: "
                    f"cohort_id={format_meta_text_value(stable.get('cohort_id'))} "
                    f"drift_fields="
                    f"{format_meta_text_value(stable.get('drift_fields'))} "
                    f"majority_terminal_kind="
                    f"{format_meta_text_value(majority_profile.get('terminal_kind'))}"
                )
            case _:
                lines.append(
                    "signature: "
                    f"stmt_shape={format_meta_text_value(stable.get('stmt_shape'))} "
                    f"terminal_kind="
                    f"{format_meta_text_value(stable.get('terminal_kind'))} "
                    f"has_loop={format_meta_text_value(control_flow.get('has_loop'))} "
                    f"has_try={format_meta_text_value(control_flow.get('has_try'))} "
                    f"nested_if={format_meta_text_value(control_flow.get('nested_if'))}"
                )
        facts = _as_mapping(group.get("facts"))
        if facts:
            lines.append(
                "facts: "
                + _format_key_values(
                    facts,
                    tuple(sorted(str(key) for key in facts)),
                    skip_empty=True,
                )
            )
        items = list(map(_as_mapping, _as_sequence(group.get("items"))))
        visible_items = items[:3]
        lines.extend(_location_line(item) for item in visible_items)
        if len(items) > len(visible_items):
            lines.append(f"... and {len(items) - len(visible_items)} more occurrences")
        lines.append("")
    if lines[-1] == "":
        lines.pop()


def _append_single_item_findings(
    lines: list[str],
    *,
    title: str,
    groups: Sequence[object],
    fact_keys: Sequence[str],
) -> None:
    finding_groups = [_as_mapping(group) for group in groups]
    lines.append(f"{title} (groups={len(finding_groups)})")
    if not finding_groups:
        lines.append("(none)")
        return
    for idx, group in enumerate(finding_groups, start=1):
        lines.append(f"=== Finding #{idx} ===")
        lines.append(
            "id="
            f"{format_meta_text_value(group.get('id'))} "
            f"category={format_meta_text_value(group.get('category'))} "
            f"kind={format_meta_text_value(group.get('kind'))} "
            f"severity={format_meta_text_value(group.get('severity'))} "
            f"confidence={format_meta_text_value(group.get('confidence'))} "
            f"scope={_scope_text(_as_mapping(group.get('source_scope')))}"
        )
        facts = _as_mapping(group.get("facts"))
        if facts:
            lines.append(
                f"facts: {_format_key_values(facts, fact_keys, skip_empty=True)}"
            )
        lines.extend(
            _location_line(item)
            for item in map(_as_mapping, _as_sequence(group.get("items")))
        )
        lines.append("")
    if lines[-1] == "":
        lines.pop()


def _suppression_bindings_text(item: Mapping[str, object]) -> str:
    bindings = [
        _as_mapping(binding)
        for binding in _as_sequence(item.get("suppressed_by"))
        if isinstance(binding, Mapping)
    ]
    if bindings:
        parts = []
        for binding in bindings:
            rule = str(binding.get("rule", "")).strip() or "unknown"
            source = str(binding.get("source", "")).strip() or "unknown"
            parts.append(f"{rule}@{source}")
        return ",".join(parts)
    rule = str(item.get("suppression_rule", "")).strip()
    source = str(item.get("suppression_source", "")).strip()
    if rule or source:
        return f"{rule or 'unknown'}@{source or 'unknown'}"
    return "(none)"


def _append_suppressed_dead_code_items(
    lines: list[str],
    *,
    items: Sequence[object],
) -> None:
    suppressed_items = [_as_mapping(item) for item in items]
    lines.append(f"SUPPRESSED DEAD CODE (items={len(suppressed_items)})")
    if not suppressed_items:
        lines.append("(none)")
        return
    for idx, item in enumerate(suppressed_items, start=1):
        lines.append(f"=== Suppressed dead-code item #{idx} ===")
        lines.append(
            "kind="
            f"{format_meta_text_value(item.get('kind'))} "
            f"confidence={format_meta_text_value(item.get('confidence'))} "
            f"suppressed_by={_suppression_bindings_text(item)}"
        )
        lines.append(_location_line(item))
        lines.append("")
    if lines[-1] == "":
        lines.pop()


def _flatten_findings(findings: Mapping[str, object]) -> list[Mapping[str, object]]:
    groups = _as_mapping(findings.get("groups"))
    clone_groups = _as_mapping(groups.get("clones"))
    flat_groups = [
        *map(_as_mapping, _as_sequence(clone_groups.get("functions"))),
        *map(_as_mapping, _as_sequence(clone_groups.get("blocks"))),
        *map(_as_mapping, _as_sequence(clone_groups.get("segments"))),
        *map(
            _as_mapping,
            _as_sequence(_as_mapping(groups.get("structural")).get("groups")),
        ),
        *map(
            _as_mapping,
            _as_sequence(_as_mapping(groups.get("dead_code")).get("groups")),
        ),
        *map(
            _as_mapping,
            _as_sequence(_as_mapping(groups.get("design")).get("groups")),
        ),
    ]
    return flat_groups


def _append_suggestions(
    lines: list[str],
    *,
    suggestions: Sequence[object],
    findings: Mapping[str, object],
) -> None:
    suggestion_rows = [_as_mapping(item) for item in suggestions]
    finding_index = {
        str(group.get("id")): group for group in _flatten_findings(findings)
    }
    lines.append(f"SUGGESTIONS (count={len(suggestion_rows)})")
    if not suggestion_rows:
        lines.append("(none)")
        return
    for idx, suggestion in enumerate(suggestion_rows, start=1):
        finding = finding_index.get(str(suggestion.get("finding_id")), {})
        lines.append(
            f"{idx}. "
            f"[{format_meta_text_value(finding.get('severity'))}] "
            f"{format_meta_text_value(suggestion.get('title'))}"
        )
        lines.append(
            "   "
            f"finding_id={format_meta_text_value(suggestion.get('finding_id'))} "
            f"effort={format_meta_text_value(_as_mapping(suggestion.get('action')).get('effort'))}"
        )
        summary = str(suggestion.get("summary", "")).strip()
        if summary:
            lines.append(f"   summary: {summary}")
        lines.append(
            f"   location: {format_meta_text_value(suggestion.get('location_label'))}"
        )
        representative = list(
            map(_as_mapping, _as_sequence(suggestion.get("representative_locations")))
        )
        if representative:
            lines.append(f"   example: {_location_line(representative[0])[2:]}")
        steps = [
            str(step).strip()
            for step in _as_sequence(_as_mapping(suggestion.get("action")).get("steps"))
            if str(step).strip()
        ]
        lines.extend(f"   - {step}" for step in steps[:2])


def _append_overview(
    lines: list[str],
    overview: Mapping[str, object],
    hotlists: Mapping[str, object],
) -> None:
    lines.append("DERIVED OVERVIEW")
    families = _as_mapping(overview.get("families"))
    lines.append(
        "Families: "
        + _format_key_values(
            families,
            ("clones", "structural", "dead_code", "design"),
        )
    )
    source_breakdown = _as_mapping(overview.get("source_scope_breakdown"))
    lines.append(
        "Source scope breakdown: "
        + _format_key_values(
            source_breakdown,
            ("production", "tests", "fixtures", "other"),
        )
    )
    health_snapshot = _as_mapping(overview.get("health_snapshot"))
    lines.append(
        "Health snapshot: "
        + _format_key_values(
            health_snapshot,
            ("score", "grade", "strongest_dimension", "weakest_dimension"),
        )
    )
    hotlist_counts = {
        "most_actionable": len(_as_sequence(hotlists.get("most_actionable_ids"))),
        "highest_spread": len(_as_sequence(hotlists.get("highest_spread_ids"))),
        "production_hotspots": len(
            _as_sequence(hotlists.get("production_hotspot_ids"))
        ),
        "test_fixture_hotspots": len(
            _as_sequence(hotlists.get("test_fixture_hotspot_ids"))
        ),
    }
    lines.append(
        "Hotlists: "
        + _format_key_values(
            hotlist_counts,
            (
                "most_actionable",
                "highest_spread",
                "production_hotspots",
                "test_fixture_hotspots",
            ),
        )
    )
    top_risks = list(map(_as_mapping, _as_sequence(overview.get("top_risks"))))
    if not top_risks:
        lines.append("Top risks: (none)")
        return
    lines.append("Top risks:")
    lines.extend(
        (
            "- "
            f"{format_meta_text_value(risk.get('family'))} "
            f"count={format_meta_text_value(risk.get('count'))} "
            f"scope={format_meta_text_value(risk.get('scope'))} "
            f"label={format_meta_text_value(risk.get('label'))}"
        )
        for risk in top_risks
    )


def render_text_report_document(payload: Mapping[str, object]) -> str:
    meta_payload = _as_mapping(payload.get("meta"))
    baseline = _as_mapping(meta_payload.get("baseline"))
    cache = _as_mapping(meta_payload.get("cache"))
    metrics_baseline = _as_mapping(meta_payload.get("metrics_baseline"))
    inventory_payload = _as_mapping(payload.get("inventory"))
    inventory_files = _as_mapping(inventory_payload.get("files"))
    inventory_code = _as_mapping(inventory_payload.get("code"))
    file_registry = _as_mapping(inventory_payload.get("file_registry"))
    findings = _as_mapping(payload.get("findings"))
    findings_summary = _as_mapping(findings.get("summary"))
    findings_families = _as_mapping(findings_summary.get("families"))
    findings_severity = _as_mapping(findings_summary.get("severity"))
    findings_impact_scope = _as_mapping(findings_summary.get("impact_scope"))
    findings_clones = _as_mapping(findings_summary.get("clones"))
    findings_suppressed = _as_mapping(findings_summary.get("suppressed"))
    metrics_payload = _as_mapping(payload.get("metrics"))
    metrics_summary = _as_mapping(metrics_payload.get("summary"))
    metrics_families = _as_mapping(metrics_payload.get("families"))
    derived = _as_mapping(payload.get("derived"))
    overview = _as_mapping(derived.get("overview"))
    hotlists = _as_mapping(derived.get("hotlists"))
    suggestions_payload = _as_sequence(derived.get("suggestions"))
    integrity = _as_mapping(payload.get("integrity"))
    canonicalization = _as_mapping(integrity.get("canonicalization"))
    digest = _as_mapping(integrity.get("digest"))
    findings_groups = _as_mapping(findings.get("groups"))
    clone_groups = _as_mapping(findings_groups.get("clones"))
    runtime_meta = _as_mapping(meta_payload.get("runtime"))

    lines = [
        "REPORT METADATA",
        "Report schema version: "
        f"{format_meta_text_value(payload.get('report_schema_version'))}",
        "CodeClone version: "
        f"{format_meta_text_value(meta_payload.get('codeclone_version'))}",
        f"Project name: {format_meta_text_value(meta_payload.get('project_name'))}",
        f"Scan root: {format_meta_text_value(meta_payload.get('scan_root'))}",
        f"Python version: {format_meta_text_value(meta_payload.get('python_version'))}",
        f"Python tag: {format_meta_text_value(meta_payload.get('python_tag'))}",
        f"Analysis mode: {format_meta_text_value(meta_payload.get('analysis_mode'))}",
        f"Report mode: {format_meta_text_value(meta_payload.get('report_mode'))}",
        "Report generated (UTC): "
        f"{format_meta_text_value(runtime_meta.get('report_generated_at_utc'))}",
        "Computed metric families: "
        f"{format_meta_text_value(meta_payload.get('computed_metric_families'))}",
        f"Baseline path: {format_meta_text_value(baseline.get('path'))}",
        "Baseline fingerprint version: "
        f"{format_meta_text_value(baseline.get('fingerprint_version'))}",
        "Baseline schema version: "
        f"{format_meta_text_value(baseline.get('schema_version'))}",
        f"Baseline Python tag: {format_meta_text_value(baseline.get('python_tag'))}",
        "Baseline generator name: "
        f"{format_meta_text_value(baseline.get('generator_name'))}",
        "Baseline generator version: "
        f"{format_meta_text_value(baseline.get('generator_version'))}",
        "Baseline payload sha256: "
        f"{format_meta_text_value(baseline.get('payload_sha256'))}",
        "Baseline payload verified: "
        f"{format_meta_text_value(baseline.get('payload_sha256_verified'))}",
        f"Baseline loaded: {format_meta_text_value(baseline.get('loaded'))}",
        f"Baseline status: {format_meta_text_value(baseline.get('status'))}",
        f"Cache path: {format_meta_text_value(cache.get('path'))}",
        f"Cache schema version: {format_meta_text_value(cache.get('schema_version'))}",
        f"Cache status: {format_meta_text_value(cache.get('status'))}",
        f"Cache used: {format_meta_text_value(cache.get('used'))}",
        "Metrics baseline path: "
        f"{format_meta_text_value(metrics_baseline.get('path'))}",
        "Metrics baseline loaded: "
        f"{format_meta_text_value(metrics_baseline.get('loaded'))}",
        "Metrics baseline status: "
        f"{format_meta_text_value(metrics_baseline.get('status'))}",
        "Metrics baseline schema version: "
        f"{format_meta_text_value(metrics_baseline.get('schema_version'))}",
        "Metrics baseline payload sha256: "
        f"{format_meta_text_value(metrics_baseline.get('payload_sha256'))}",
        "Metrics baseline payload verified: "
        f"{format_meta_text_value(metrics_baseline.get('payload_sha256_verified'))}",
    ]

    if (
        baseline.get("loaded") is not True
        or str(baseline.get("status", "")).strip().lower() != "ok"
    ):
        lines.append("Note: baseline is untrusted; all groups are treated as NEW.")

    lines.extend(
        [
            "",
            "INVENTORY",
            "Files: "
            + _format_key_values(
                inventory_files,
                (
                    "total_found",
                    "analyzed",
                    "cached",
                    "skipped",
                    "source_io_skipped",
                ),
            ),
            "Code: "
            + _format_key_values(
                inventory_code,
                ("scope", "parsed_lines", "functions", "methods", "classes"),
            ),
            "File registry: "
            f"encoding={format_meta_text_value(file_registry.get('encoding'))} "
            f"count={len(_as_sequence(file_registry.get('items')))}",
            "",
            "FINDINGS SUMMARY",
            f"Total groups: {format_meta_text_value(findings_summary.get('total'))}",
            "Families: "
            + _format_key_values(
                findings_families,
                ("clones", "structural", "dead_code", "design"),
            ),
            "Severity: "
            + _format_key_values(
                findings_severity,
                ("critical", "warning", "info"),
            ),
            "Impact scope: "
            + _format_key_values(
                findings_impact_scope,
                ("runtime", "non_runtime", "mixed"),
            ),
            "Clones: "
            + _format_key_values(
                findings_clones,
                ("functions", "blocks", "segments", "new", "known"),
            ),
            "Suppressed: "
            + _format_key_values(
                findings_suppressed,
                ("dead_code",),
            ),
            "",
            "METRICS SUMMARY",
        ]
    )
    for family_name in (
        "complexity",
        "coupling",
        "cohesion",
        "overloaded_modules",
        "dependencies",
        "dead_code",
        "health",
    ):
        family_summary = _as_mapping(metrics_summary.get(family_name))
        keys: Sequence[str]
        match family_name:
            case "complexity" | "coupling":
                keys = ("total", "average", "max", "high_risk")
            case "cohesion":
                keys = ("total", "average", "max", "low_cohesion")
            case "dependencies":
                keys = ("modules", "edges", "cycles", "max_depth")
            case "overloaded_modules":
                keys = (
                    "total",
                    "candidates",
                    "population_status",
                    "top_score",
                    "average_score",
                )
            case "dead_code":
                keys = ("total", "high_confidence", "suppressed")
            case _:
                keys = ("score", "grade")
        lines.append(f"{family_name}: {_format_key_values(family_summary, keys)}")

    overloaded_modules_family = _as_mapping(metrics_families.get("overloaded_modules"))
    if not overloaded_modules_family:
        overloaded_modules_family = _as_mapping(metrics_families.get("god_modules"))
    overloaded_module_items = _as_sequence(overloaded_modules_family.get("items"))
    lines.extend(
        [
            "",
            "OVERLOADED MODULES (top 10)",
        ]
    )
    if not overloaded_module_items:
        lines.append("(none)")
    else:
        lines.extend(
            "- "
            + _format_key_values(
                item,
                (
                    "module",
                    "relative_path",
                    "source_kind",
                    "score",
                    "candidate_status",
                    "loc",
                    "fan_in",
                    "fan_out",
                    "complexity_total",
                ),
            )
            for item in map(_as_mapping, overloaded_module_items[:10])
        )

    lines.append("")
    _append_overview(lines, overview, hotlists)

    lines.append("")
    _append_suggestions(lines, suggestions=suggestions_payload, findings=findings)

    lines.append("")
    _append_clone_section(
        lines,
        title="FUNCTION CLONES",
        groups=_as_sequence(clone_groups.get("functions")),
        novelty="new",
        metric_name="loc",
    )
    lines.append("")
    _append_clone_section(
        lines,
        title="FUNCTION CLONES",
        groups=_as_sequence(clone_groups.get("functions")),
        novelty="known",
        metric_name="loc",
    )
    lines.append("")
    _append_clone_section(
        lines,
        title="BLOCK CLONES",
        groups=_as_sequence(clone_groups.get("blocks")),
        novelty="new",
        metric_name="size",
    )
    lines.append("")
    _append_clone_section(
        lines,
        title="BLOCK CLONES",
        groups=_as_sequence(clone_groups.get("blocks")),
        novelty="known",
        metric_name="size",
    )
    lines.append("")
    _append_clone_section(
        lines,
        title="SEGMENT CLONES",
        groups=_as_sequence(clone_groups.get("segments")),
        novelty="new",
        metric_name="size",
    )
    lines.append("")
    _append_clone_section(
        lines,
        title="SEGMENT CLONES",
        groups=_as_sequence(clone_groups.get("segments")),
        novelty="known",
        metric_name="size",
    )
    lines.append("")
    _append_structural_findings(
        lines,
        _as_sequence(_as_mapping(findings_groups.get("structural")).get("groups")),
    )
    lines.append("")
    _append_single_item_findings(
        lines,
        title="DEAD CODE FINDINGS",
        groups=_as_sequence(
            _as_mapping(findings_groups.get("dead_code")).get("groups")
        ),
        fact_keys=("kind", "confidence"),
    )
    lines.append("")
    dead_code_family = _as_mapping(metrics_families.get("dead_code"))
    _append_suppressed_dead_code_items(
        lines,
        items=_as_sequence(dead_code_family.get("suppressed_items")),
    )
    lines.append("")
    _append_single_item_findings(
        lines,
        title="DESIGN FINDINGS",
        groups=_as_sequence(_as_mapping(findings_groups.get("design")).get("groups")),
        fact_keys=("lcom4", "method_count", "instance_var_count", "fan_out", "risk"),
    )
    lines.extend(
        [
            "",
            "INTEGRITY",
            "Canonicalization: "
            + _format_key_values(
                canonicalization,
                ("version", "scope", "sections"),
            ),
            "Digest: "
            + _format_key_values(
                digest,
                ("algorithm", "verified", "value"),
            ),
        ]
    )

    return "\n".join(lines).rstrip() + "\n"
