# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from .._coerce import as_float, as_int, as_mapping, as_sequence
from ..domain.findings import FAMILY_CLONE, FAMILY_DEAD_CODE, FAMILY_STRUCTURAL
from ._formatting import format_spread_text
from .json_contract import build_report_document

if TYPE_CHECKING:
    from ..models import StructuralFindingGroup, Suggestion
    from .types import GroupMapLike

MARKDOWN_SCHEMA_VERSION = "1.0"
_MAX_FINDING_LOCATIONS = 5
_MAX_METRIC_ITEMS = 10

_as_int = as_int
_as_float = as_float
_as_mapping = as_mapping
_as_sequence = as_sequence

_ANCHORS: tuple[tuple[str, str, int], ...] = (
    ("overview", "Overview", 2),
    ("inventory", "Inventory", 2),
    ("findings-summary", "Findings Summary", 2),
    ("top-risks", "Top Risks", 2),
    ("suggestions", "Suggestions", 2),
    ("findings", "Findings", 2),
    ("clone-findings", "Clone Findings", 3),
    ("structural-findings", "Structural Findings", 3),
    ("dead-code-findings", "Dead Code Findings", 3),
    ("design-findings", "Design Findings", 3),
    ("metrics", "Metrics", 2),
    ("health", "Health", 3),
    ("complexity", "Complexity", 3),
    ("coupling", "Coupling", 3),
    ("cohesion", "Cohesion", 3),
    ("overloaded-modules", "Overloaded Modules", 3),
    ("dependencies", "Dependencies", 3),
    ("dead-code-metrics", "Dead Code", 3),
    ("dead-code-suppressed", "Suppressed Dead Code", 3),
    ("integrity", "Integrity", 2),
)
_ANCHOR_MAP: dict[str, tuple[str, str, int]] = {
    anchor[0]: anchor for anchor in _ANCHORS
}


def _text(value: object) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".") or "0"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    return text or "(none)"


def _source_scope_text(scope: Mapping[str, object]) -> str:
    dominant = _text(scope.get("dominant_kind"))
    impact = _text(scope.get("impact_scope"))
    return f"{dominant} / {impact}"


def _spread_text(spread: Mapping[str, object]) -> str:
    return format_spread_text(
        _as_int(spread.get("files")),
        _as_int(spread.get("functions")),
    )


def _location_text(item: Mapping[str, object]) -> str:
    relative_path = _text(item.get("relative_path"))
    start_line = _as_int(item.get("start_line"))
    end_line = _as_int(item.get("end_line"))
    qualname = str(item.get("qualname", "")).strip()
    line_part = ""
    if start_line > 0:
        line_part = f":{start_line}"
        if end_line > 0 and end_line != start_line:
            line_part += f"-{end_line}"
    if qualname:
        return f"`{relative_path}{line_part}` :: `{qualname}`"
    return f"`{relative_path}{line_part}`"


def _append_anchor(lines: list[str], anchor_id: str, title: str, level: int) -> None:
    lines.append(f'<a id="{anchor_id}"></a>')
    lines.append(f"{'#' * level} {title}")
    lines.append("")


def _anchor(anchor_id: str) -> tuple[str, str, int]:
    return _ANCHOR_MAP[anchor_id]


def _append_kv_bullets(
    lines: list[str],
    rows: Sequence[tuple[str, object]],
) -> None:
    for label, value in rows:
        lines.append(f"- {label}: {_text(value)}")
    lines.append("")


def _finding_heading(group: Mapping[str, object]) -> str:
    family = str(group.get("family", "")).strip()
    category = str(group.get("category", "")).strip()
    clone_type = str(group.get("clone_type", "")).strip()
    if family == FAMILY_CLONE:
        suffix = f" ({clone_type})" if clone_type else ""
        return f"{category.title()} clone group{suffix}"
    if family == FAMILY_STRUCTURAL:
        return f"Structural finding: {category}"
    if family == FAMILY_DEAD_CODE:
        return f"Dead code: {category}"
    return f"Design finding: {category}"


def _append_facts_block(
    lines: list[str],
    *,
    title: str,
    facts: Mapping[str, object],
) -> None:
    if not facts:
        return
    lines.append(f"- {title}:")
    lines.extend(f"  - `{key}`: {_text(facts[key])}" for key in sorted(facts))


def _append_findings_section(
    lines: list[str],
    *,
    groups: Sequence[object],
) -> None:
    finding_rows = [_as_mapping(group) for group in groups]
    if not finding_rows:
        lines.append("_None._")
        lines.append("")
        return
    for group in finding_rows:
        lines.append(f"#### {_finding_heading(group)}")
        lines.append("")
        _append_kv_bullets(
            lines,
            (
                ("Finding ID", f"`{_text(group.get('id'))}`"),
                ("Family", group.get("family")),
                ("Category", group.get("category")),
                ("Kind", group.get("kind")),
                ("Severity", group.get("severity")),
                ("Confidence", group.get("confidence")),
                ("Priority", _as_float(group.get("priority"))),
                ("Scope", _source_scope_text(_as_mapping(group.get("source_scope")))),
                ("Spread", _spread_text(_as_mapping(group.get("spread")))),
                ("Occurrences", group.get("count")),
            ),
        )
        facts = _as_mapping(group.get("facts"))
        display_facts = _as_mapping(group.get("display_facts"))
        if facts or display_facts:
            _append_facts_block(lines, title="Facts", facts=facts)
            _append_facts_block(lines, title="Presentation facts", facts=display_facts)
            lines.append("")
        items = list(map(_as_mapping, _as_sequence(group.get("items"))))
        lines.append("- Locations:")
        visible_items = items[:_MAX_FINDING_LOCATIONS]
        lines.extend(f"  - {_location_text(item)}" for item in visible_items)
        if len(items) > len(visible_items):
            lines.append(
                f"  - ... and {len(items) - len(visible_items)} more occurrence(s)"
            )
        lines.append("")


def _append_metric_items(
    lines: list[str],
    *,
    items: Sequence[object],
    key_order: Sequence[str],
) -> None:
    metric_rows = [_as_mapping(item) for item in items[:_MAX_METRIC_ITEMS]]
    if not metric_rows:
        lines.append("_No detailed items._")
        lines.append("")
        return
    for item in metric_rows:
        parts = [f"{key}={_text(item[key])}" for key in key_order if key in item]
        if "relative_path" in item:
            parts.append(_location_text(item))
        lines.append(f"- {'; '.join(parts)}")
    if len(items) > len(metric_rows):
        lines.append(f"- ... and {len(items) - len(metric_rows)} more item(s)")
    lines.append("")


def render_markdown_report_document(payload: Mapping[str, object]) -> str:
    meta = _as_mapping(payload.get("meta"))
    inventory = _as_mapping(payload.get("inventory"))
    findings = _as_mapping(payload.get("findings"))
    metrics = _as_mapping(payload.get("metrics"))
    derived = _as_mapping(payload.get("derived"))
    integrity = _as_mapping(payload.get("integrity"))
    runtime = _as_mapping(meta.get("runtime"))
    findings_summary = _as_mapping(findings.get("summary"))
    findings_groups = _as_mapping(findings.get("groups"))
    clone_groups = _as_mapping(findings_groups.get("clones"))
    overview = _as_mapping(derived.get("overview"))
    hotlists = _as_mapping(derived.get("hotlists"))
    suggestions = _as_sequence(derived.get("suggestions"))
    metrics_families = _as_mapping(metrics.get("families"))
    health_snapshot = _as_mapping(overview.get("health_snapshot"))
    inventory_files = _as_mapping(inventory.get("files"))
    inventory_code = _as_mapping(inventory.get("code"))
    digest = _as_mapping(integrity.get("digest"))
    canonicalization = _as_mapping(integrity.get("canonicalization"))
    family_summary = _as_mapping(findings_summary.get("families"))
    severity_summary = _as_mapping(findings_summary.get("severity"))
    impact_summary = _as_mapping(findings_summary.get("impact_scope"))
    source_breakdown = _as_mapping(overview.get("source_scope_breakdown"))

    lines = [
        "# CodeClone Report",
        "",
        f"- Markdown schema: {MARKDOWN_SCHEMA_VERSION}",
        f"- Source report schema: {_text(payload.get('report_schema_version'))}",
        f"- Project: {_text(meta.get('project_name'))}",
        f"- Analysis mode: {_text(meta.get('analysis_mode'))}",
        f"- Report mode: {_text(meta.get('report_mode'))}",
        f"- Generated by: codeclone {_text(meta.get('codeclone_version'))}",
        f"- Python: {_text(meta.get('python_tag'))}",
        f"- Report generated (UTC): {_text(runtime.get('report_generated_at_utc'))}",
        "",
    ]

    _append_anchor(lines, *_anchor("overview"))
    _append_kv_bullets(
        lines,
        (
            ("Project", meta.get("project_name")),
            (
                "Health",
                (
                    f"{_text(health_snapshot.get('score'))} "
                    f"({_text(health_snapshot.get('grade'))})"
                ),
            ),
            ("Total findings", findings_summary.get("total")),
            (
                "Families",
                ", ".join(
                    f"{name}={_text(family_summary.get(name))}"
                    for name in ("clones", "structural", "dead_code", "design")
                ),
            ),
            ("Strongest dimension", health_snapshot.get("strongest_dimension")),
            ("Weakest dimension", health_snapshot.get("weakest_dimension")),
        ),
    )

    _append_anchor(lines, *_anchor("inventory"))
    _append_kv_bullets(
        lines,
        (
            (
                "Files",
                ", ".join(
                    f"{name}={_text(inventory_files.get(name))}"
                    for name in (
                        "total_found",
                        "analyzed",
                        "cached",
                        "skipped",
                        "source_io_skipped",
                    )
                ),
            ),
            (
                "Code",
                ", ".join(
                    f"{name}={_text(inventory_code.get(name))}"
                    for name in (
                        "parsed_lines",
                        "functions",
                        "methods",
                        "classes",
                    )
                ),
            ),
        ),
    )

    _append_anchor(lines, *_anchor("findings-summary"))
    _append_kv_bullets(
        lines,
        (
            ("Total", findings_summary.get("total")),
            (
                "By family",
                ", ".join(
                    f"{name}={_text(family_summary.get(name))}"
                    for name in ("clones", "structural", "dead_code", "design")
                ),
            ),
            (
                "By severity",
                ", ".join(
                    f"{name}={_text(severity_summary.get(name))}"
                    for name in ("critical", "warning", "info")
                ),
            ),
            (
                "By impact scope",
                ", ".join(
                    f"{name}={_text(impact_summary.get(name))}"
                    for name in ("runtime", "non_runtime", "mixed")
                ),
            ),
            (
                "Source scope breakdown",
                ", ".join(
                    f"{name}={_text(source_breakdown.get(name))}"
                    for name in ("production", "tests", "fixtures", "other")
                    if name in source_breakdown
                )
                or "(none)",
            ),
        ),
    )

    _append_anchor(lines, *_anchor("top-risks"))
    top_risks = [_as_mapping(item) for item in _as_sequence(overview.get("top_risks"))]
    if top_risks:
        for idx, risk in enumerate(top_risks[:10], start=1):
            lines.append(
                f"{idx}. {_text(risk.get('label'))} "
                f"(family={_text(risk.get('family'))}, "
                f"scope={_text(risk.get('scope'))}, "
                f"count={_text(risk.get('count'))})"
            )
    else:
        lines.append("_None._")
    lines.append("")

    if suggestions:
        _append_anchor(lines, *_anchor("suggestions"))
        for suggestion in map(_as_mapping, suggestions):
            action = _as_mapping(suggestion.get("action"))
            lines.append(f"### {_text(suggestion.get('title'))}")
            lines.append("")
            _append_kv_bullets(
                lines,
                (
                    ("Finding", f"`{_text(suggestion.get('finding_id'))}`"),
                    ("Summary", suggestion.get("summary")),
                    ("Location", suggestion.get("location_label")),
                    ("Effort", action.get("effort")),
                ),
            )
            representative = [
                _as_mapping(item)
                for item in _as_sequence(suggestion.get("representative_locations"))
            ]
            if representative:
                lines.append(f"- Example: {_location_text(representative[0])}")
            steps = [str(step).strip() for step in _as_sequence(action.get("steps"))]
            if steps:
                lines.append("- Steps:")
                for idx, step in enumerate(steps, start=1):
                    lines.append(f"  {idx}. {step}")
            lines.append("")

    _append_anchor(lines, *_anchor("findings"))
    _append_anchor(lines, *_anchor("clone-findings"))
    _append_findings_section(
        lines,
        groups=[
            *_as_sequence(clone_groups.get("functions")),
            *_as_sequence(clone_groups.get("blocks")),
            *_as_sequence(clone_groups.get("segments")),
        ],
    )

    _append_anchor(lines, *_anchor("structural-findings"))
    _append_findings_section(
        lines,
        groups=_as_sequence(
            _as_mapping(findings_groups.get("structural")).get("groups")
        ),
    )

    _append_anchor(lines, *_anchor("dead-code-findings"))
    _append_findings_section(
        lines,
        groups=_as_sequence(
            _as_mapping(findings_groups.get("dead_code")).get("groups")
        ),
    )

    _append_anchor(lines, *_anchor("design-findings"))
    _append_findings_section(
        lines,
        groups=_as_sequence(_as_mapping(findings_groups.get("design")).get("groups")),
    )

    _append_anchor(lines, *_anchor("metrics"))
    for anchor_id, title, summary_keys, item_keys in (
        ("health", "Health", ("score", "grade"), ()),
        (
            "complexity",
            "Complexity",
            ("total", "average", "max", "high_risk"),
            ("cyclomatic_complexity", "nesting_depth", "risk"),
        ),
        (
            "coupling",
            "Coupling",
            ("total", "average", "max", "high_risk"),
            ("cbo", "risk"),
        ),
        (
            "cohesion",
            "Cohesion",
            ("total", "average", "max", "low_cohesion"),
            ("lcom4", "method_count", "instance_var_count", "risk"),
        ),
        (
            "overloaded-modules",
            "Overloaded Modules",
            (
                "total",
                "candidates",
                "population_status",
                "top_score",
                "average_score",
            ),
            (
                "source_kind",
                "score",
                "candidate_status",
                "loc",
                "fan_in",
                "fan_out",
                "complexity_total",
            ),
        ),
        (
            "dependencies",
            "Dependencies",
            ("modules", "edges", "cycles", "max_depth"),
            ("source", "target", "import_type", "line"),
        ),
        (
            "dead-code-metrics",
            "Dead Code",
            ("total", "high_confidence", "suppressed"),
            ("kind", "confidence"),
        ),
    ):
        family_key = (
            "dead_code"
            if anchor_id == "dead-code-metrics"
            else (
                "overloaded_modules" if anchor_id == "overloaded-modules" else anchor_id
            )
        )
        family_payload = _as_mapping(metrics_families.get(family_key))
        if not family_payload and family_key == "overloaded_modules":
            family_payload = _as_mapping(metrics_families.get("god_modules"))
        family_summary_map = _as_mapping(family_payload.get("summary"))
        _append_anchor(lines, anchor_id, title, 3)
        _append_kv_bullets(
            lines,
            tuple((key, family_summary_map.get(key)) for key in summary_keys),
        )
        _append_metric_items(
            lines,
            items=_as_sequence(family_payload.get("items")),
            key_order=item_keys,
        )

    dead_code_family_payload = _as_mapping(metrics_families.get("dead_code"))
    _append_anchor(lines, *_anchor("dead-code-suppressed"))
    _append_metric_items(
        lines,
        items=_as_sequence(dead_code_family_payload.get("suppressed_items")),
        key_order=("kind", "confidence", "suppression_rule", "suppression_source"),
    )

    _append_anchor(lines, *_anchor("integrity"))
    _append_kv_bullets(
        lines,
        (
            ("Canonicalization version", canonicalization.get("version")),
            ("Canonicalization scope", canonicalization.get("scope")),
            (
                "Canonical sections",
                ", ".join(
                    str(item) for item in _as_sequence(canonicalization.get("sections"))
                ),
            ),
            ("Digest algorithm", digest.get("algorithm")),
            ("Digest verified", digest.get("verified")),
            ("Digest value", digest.get("value")),
            (
                "Hotlists",
                ", ".join(
                    f"{name}={len(_as_sequence(hotlists.get(name)))}"
                    for name in (
                        "most_actionable_ids",
                        "highest_spread_ids",
                        "production_hotspot_ids",
                        "test_fixture_hotspot_ids",
                    )
                ),
            ),
        ),
    )

    return "\n".join(lines).rstrip() + "\n"


def to_markdown_report(
    *,
    report_document: Mapping[str, object] | None = None,
    meta: Mapping[str, object],
    inventory: Mapping[str, object] | None = None,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Collection[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
) -> str:
    payload = report_document or build_report_document(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta=meta,
        inventory=inventory,
        block_facts=block_facts or {},
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        metrics=metrics,
        suggestions=tuple(suggestions or ()),
        structural_findings=tuple(structural_findings or ()),
    )
    return render_markdown_report_document(payload)
