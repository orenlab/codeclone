# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..contracts import DOCS_URL, REPOSITORY_URL
from .json_contract import build_report_document

if TYPE_CHECKING:
    from ..models import StructuralFindingGroup, Suggestion
    from .types import GroupMapLike

SARIF_VERSION = "2.1.0"
SARIF_PROFILE_VERSION = "1.0"
SARIF_SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"


@dataclass(frozen=True, slots=True)
class _RuleSpec:
    rule_id: str
    short_description: str
    full_description: str
    default_level: str
    category: str
    kind: str
    precision: str


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _severity_to_level(severity: str) -> str:
    if severity == "critical":
        return "error"
    if severity == "warning":
        return "warning"
    return "note"


def _flatten_findings(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    findings = _as_mapping(payload.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clones = _as_mapping(groups.get("clones"))
    structural = _as_mapping(groups.get("structural"))
    dead_code = _as_mapping(groups.get("dead_code"))
    design = _as_mapping(groups.get("design"))
    return [
        *map(_as_mapping, _as_sequence(clones.get("functions"))),
        *map(_as_mapping, _as_sequence(clones.get("blocks"))),
        *map(_as_mapping, _as_sequence(clones.get("segments"))),
        *map(_as_mapping, _as_sequence(structural.get("groups"))),
        *map(_as_mapping, _as_sequence(dead_code.get("groups"))),
        *map(_as_mapping, _as_sequence(design.get("groups"))),
    ]


def _rule_spec(group: Mapping[str, object]) -> _RuleSpec:
    family = _text(group.get("family"))
    category = _text(group.get("category"))
    kind = _text(group.get("kind"))
    if family == "clone":
        if category == "function":
            return _RuleSpec(
                "CCLONE001",
                "Function clone group",
                "Multiple functions share the same normalized function body.",
                "warning",
                "clone",
                "clone_group",
                "high",
            )
        if category == "block":
            return _RuleSpec(
                "CCLONE002",
                "Block clone group",
                (
                    "Repeated normalized statement blocks were detected "
                    "across occurrences."
                ),
                "warning",
                "clone",
                "clone_group",
                "high",
            )
        return _RuleSpec(
            "CCLONE003",
            "Segment clone group",
            "Repeated normalized statement segments were detected across occurrences.",
            "note",
            "clone",
            "clone_group",
            "medium",
        )
    if family == "structural":
        if kind == "clone_guard_exit_divergence":
            return _RuleSpec(
                "CSTRUCT002",
                "Clone guard/exit divergence",
                (
                    "Members of the same function-clone cohort diverged in "
                    "entry guards or early-exit behavior."
                ),
                "warning",
                "structural",
                "clone_guard_exit_divergence",
                "high",
            )
        if kind == "clone_cohort_drift":
            return _RuleSpec(
                "CSTRUCT003",
                "Clone cohort drift",
                (
                    "Members of the same function-clone cohort drifted from "
                    "the majority terminal/guard/try profile."
                ),
                "warning",
                "structural",
                "clone_cohort_drift",
                "high",
            )
        return _RuleSpec(
            "CSTRUCT001",
            "Duplicated branches",
            (
                "Repeated branch families with matching structural signatures "
                "were detected."
            ),
            "warning",
            "structural",
            kind or "duplicated_branches",
            "medium",
        )
    if family == "dead_code":
        if category == "function":
            return _RuleSpec(
                "CDEAD001",
                "Unused function",
                "Function appears to be unused with high confidence.",
                "warning",
                "dead_code",
                "unused_symbol",
                "high",
            )
        if category == "class":
            return _RuleSpec(
                "CDEAD002",
                "Unused class",
                "Class appears to be unused with high confidence.",
                "warning",
                "dead_code",
                "unused_symbol",
                "high",
            )
        if category == "method":
            return _RuleSpec(
                "CDEAD003",
                "Unused method",
                "Method appears to be unused with high confidence.",
                "warning",
                "dead_code",
                "unused_symbol",
                "high",
            )
        return _RuleSpec(
            "CDEAD004",
            "Unused symbol",
            "Symbol appears to be unused with reported confidence.",
            "warning",
            "dead_code",
            "unused_symbol",
            "medium",
        )
    if category == "cohesion":
        return _RuleSpec(
            "CDESIGN001",
            "Low cohesion class",
            "Class cohesion is low according to LCOM4 hotspot thresholds.",
            "warning",
            "design",
            kind or "class_hotspot",
            "high",
        )
    if category == "complexity":
        return _RuleSpec(
            "CDESIGN002",
            "Complexity hotspot",
            "Function exceeds the project complexity hotspot threshold.",
            "warning",
            "design",
            kind or "function_hotspot",
            "high",
        )
    if category == "coupling":
        return _RuleSpec(
            "CDESIGN003",
            "Coupling hotspot",
            "Class exceeds the project coupling hotspot threshold.",
            "warning",
            "design",
            kind or "class_hotspot",
            "high",
        )
    return _RuleSpec(
        "CDESIGN004",
        "Dependency cycle",
        "A dependency cycle was detected between project modules.",
        "error",
        "design",
        kind or "cycle",
        "high",
    )


def _result_message(group: Mapping[str, object]) -> str:
    family = _text(group.get("family"))
    category = _text(group.get("category"))
    count = _as_int(group.get("count"))
    spread = _as_mapping(group.get("spread"))
    items = [_as_mapping(item) for item in _as_sequence(group.get("items"))]
    first_item = items[0] if items else {}
    qualname = _text(first_item.get("qualname"))
    if family == "clone":
        clone_type = _text(group.get("clone_type"))
        return (
            f"{category.title()} clone group ({clone_type}), {count} occurrences "
            f"across {_as_int(spread.get('files'))} files."
        )
    if family == "structural":
        signature = _as_mapping(_as_mapping(group.get("signature")).get("stable"))
        signature_family = _text(signature.get("family"))
        if signature_family == "clone_guard_exit_divergence":
            cohort_id = _text(signature.get("cohort_id"))
            return (
                "Clone guard/exit divergence"
                f" ({count} divergent members) in cohort {cohort_id or 'unknown'}."
            )
        if signature_family == "clone_cohort_drift":
            drift_fields = _as_sequence(signature.get("drift_fields"))
            drift_label = ",".join(_text(item) for item in drift_fields) or "profile"
            cohort_id = _text(signature.get("cohort_id"))
            return (
                f"Clone cohort drift ({drift_label}), {count} divergent members in "
                f"cohort {cohort_id or 'unknown'}."
            )
        stmt_shape = _text(signature.get("stmt_shape"))
        if qualname:
            return (
                f"Repeated branch family ({stmt_shape}), {count} occurrences in "
                f"{qualname}."
            )
        return f"Repeated branch family ({stmt_shape}), {count} occurrences."
    if family == "dead_code":
        confidence = _text(group.get("confidence")) or "reported"
        target = qualname or _text(first_item.get("relative_path"))
        return f"Unused {category} with {confidence} confidence: {target}"
    if category == "cohesion":
        lcom4 = _as_int(_as_mapping(group.get("facts")).get("lcom4"))
        return f"Low cohesion class (LCOM4={lcom4}): {qualname}"
    if category == "complexity":
        cc = _as_int(_as_mapping(group.get("facts")).get("cyclomatic_complexity"))
        return f"High complexity function (CC={cc}): {qualname}"
    if category == "coupling":
        cbo = _as_int(_as_mapping(group.get("facts")).get("cbo"))
        return f"High coupling class (CBO={cbo}): {qualname}"
    modules = [_text(item.get("module")) for item in items if _text(item.get("module"))]
    return f"Dependency cycle ({len(modules)} modules): {' -> '.join(modules)}"


def _logical_locations(item: Mapping[str, object]) -> list[dict[str, object]]:
    qualname = _text(item.get("qualname"))
    if qualname:
        return [{"fullyQualifiedName": qualname}]
    module = _text(item.get("module"))
    if module:
        return [{"fullyQualifiedName": module}]
    return []


def _location_entry(
    item: Mapping[str, object],
    *,
    related_id: int | None = None,
) -> dict[str, object]:
    relative_path = _text(item.get("relative_path"))
    physical_location: dict[str, object] = {
        "artifactLocation": {
            "uri": relative_path,
        }
    }
    start_line = _as_int(item.get("start_line"))
    end_line = _as_int(item.get("end_line"))
    if start_line > 0:
        region: dict[str, object] = {"startLine": start_line}
        if end_line > 0:
            region["endLine"] = end_line
        physical_location["region"] = region
    location: dict[str, object] = {
        "physicalLocation": physical_location,
    }
    logical_locations = _logical_locations(item)
    if logical_locations:
        location["logicalLocations"] = logical_locations
    if related_id is not None:
        location["id"] = related_id
    return location


def _generic_properties(group: Mapping[str, object]) -> dict[str, object]:
    source_scope = _as_mapping(group.get("source_scope"))
    spread = _as_mapping(group.get("spread"))
    properties: dict[str, object] = {
        "findingId": _text(group.get("id")),
        "family": _text(group.get("family")),
        "category": _text(group.get("category")),
        "kind": _text(group.get("kind")),
        "confidence": _text(group.get("confidence")),
        "priority": round(_as_float(group.get("priority")), 2),
        "impactScope": _text(source_scope.get("impact_scope")),
        "sourceKind": _text(source_scope.get("dominant_kind")),
        "spreadFiles": _as_int(spread.get("files")),
        "spreadFunctions": _as_int(spread.get("functions")),
        "helpUri": DOCS_URL,
    }
    return properties


def _result_properties(group: Mapping[str, object]) -> dict[str, object]:
    props = _generic_properties(group)
    family = _text(group.get("family"))
    facts = _as_mapping(group.get("facts"))
    if family == "clone":
        props.update(
            {
                "novelty": _text(group.get("novelty")),
                "cloneKind": _text(group.get("clone_kind")),
                "cloneType": _text(group.get("clone_type")),
                "groupArity": _as_int(group.get("count")),
            }
        )
    elif family == "structural":
        signature = _as_mapping(_as_mapping(group.get("signature")).get("stable"))
        signature_family = _text(signature.get("family"))
        props["occurrenceCount"] = _as_int(group.get("count"))
        if signature_family == "clone_guard_exit_divergence":
            props.update(
                {
                    "cohortId": _text(signature.get("cohort_id")),
                    "majorityGuardCount": _as_int(
                        signature.get("majority_guard_count"),
                    ),
                    "majorityTerminalKind": _text(
                        signature.get("majority_terminal_kind"),
                    ),
                }
            )
        elif signature_family == "clone_cohort_drift":
            props.update(
                {
                    "cohortId": _text(signature.get("cohort_id")),
                    "driftFields": [
                        _text(field)
                        for field in _as_sequence(signature.get("drift_fields"))
                    ],
                }
            )
        else:
            props.update(
                {
                    "statementShape": _text(signature.get("stmt_shape")),
                    "terminalKind": _text(signature.get("terminal_kind")),
                }
            )
    elif family == "design":
        for key in (
            "lcom4",
            "method_count",
            "instance_var_count",
            "cbo",
            "cyclomatic_complexity",
            "nesting_depth",
            "cycle_length",
        ):
            if key in facts:
                props[key] = facts[key]
    elif family == "dead_code":
        props["confidence"] = _text(group.get("confidence"))
    return props


def _partial_fingerprints(
    *,
    rule_id: str,
    group: Mapping[str, object],
    primary_item: Mapping[str, object],
) -> dict[str, str]:
    fingerprints = {
        "rule": rule_id,
        "path": _text(primary_item.get("relative_path")),
    }
    qualname = _text(primary_item.get("qualname"))
    if qualname:
        fingerprints["qualname"] = qualname
    start_line = _as_int(primary_item.get("start_line"))
    end_line = _as_int(primary_item.get("end_line"))
    if start_line > 0:
        fingerprints["region"] = f"{start_line}-{end_line or start_line}"
    fingerprints["finding"] = _text(group.get("id"))
    return fingerprints


def _result_entry(
    *,
    group: Mapping[str, object],
    rule_id: str,
    rule_index: int,
) -> dict[str, object]:
    items = [_as_mapping(item) for item in _as_sequence(group.get("items"))]
    primary_item = items[0] if items else {}
    result: dict[str, object] = {
        "ruleId": rule_id,
        "ruleIndex": rule_index,
        "level": _severity_to_level(_text(group.get("severity"))),
        "message": {
            "text": _result_message(group),
        },
        "locations": [_location_entry(primary_item)] if primary_item else [],
        "fingerprints": {
            "codecloneFindingId": _text(group.get("id")),
        },
        "partialFingerprints": _partial_fingerprints(
            rule_id=rule_id,
            group=group,
            primary_item=primary_item,
        ),
        "properties": _result_properties(group),
    }
    related_items = items[1:]
    if related_items:
        result["relatedLocations"] = [
            _location_entry(item, related_id=index)
            for index, item in enumerate(related_items, start=1)
        ]
    return result


def render_sarif_report_document(payload: Mapping[str, object]) -> str:
    meta = _as_mapping(payload.get("meta"))
    runtime = _as_mapping(meta.get("runtime"))
    generated_at = _text(runtime.get("report_generated_at_utc"))
    analysis_mode = _text(meta.get("analysis_mode")) or "full"
    findings = sorted(
        _flatten_findings(payload),
        key=lambda group: (
            _rule_spec(group).rule_id,
            _text(group.get("id")),
        ),
    )
    used_rule_specs = {
        spec.rule_id: spec for spec in (_rule_spec(group) for group in findings)
    }
    ordered_rule_specs = [used_rule_specs[key] for key in sorted(used_rule_specs)]
    rule_index_map = {
        spec.rule_id: index for index, spec in enumerate(ordered_rule_specs)
    }
    results = [
        _result_entry(
            group=group,
            rule_id=rule.rule_id,
            rule_index=rule_index_map[rule.rule_id],
        )
        for group in findings
        for rule in (_rule_spec(group),)
    ]
    run: dict[str, object] = {
        "tool": {
            "driver": {
                "name": "codeclone",
                "version": _text(meta.get("codeclone_version")),
                "semanticVersion": _text(meta.get("codeclone_version")),
                "informationUri": REPOSITORY_URL,
                "rules": [
                    {
                        "id": spec.rule_id,
                        "shortDescription": {"text": spec.short_description},
                        "fullDescription": {"text": spec.full_description},
                        "defaultConfiguration": {"level": spec.default_level},
                        "helpUri": DOCS_URL,
                        "properties": {
                            "category": spec.category,
                            "kind": spec.kind,
                            "precision": spec.precision,
                        },
                    }
                    for spec in ordered_rule_specs
                ],
            }
        },
        "automationDetails": {
            "id": f"codeclone/{analysis_mode}",
        },
        "artifacts": [],
        "results": results,
        "invocations": [
            {
                "executionSuccessful": True,
                **({"endTimeUtc": generated_at} if generated_at else {}),
            }
        ],
        "properties": {
            "profileVersion": SARIF_PROFILE_VERSION,
            "reportSchemaVersion": _text(payload.get("report_schema_version")),
            "analysisMode": analysis_mode,
            "reportMode": _text(meta.get("report_mode")),
            "canonicalDigestSha256": _text(
                _as_mapping(_as_mapping(payload.get("integrity")).get("digest")).get(
                    "value"
                )
            ),
            **({"reportGeneratedAtUtc": generated_at} if generated_at else {}),
        },
    }
    return json.dumps(
        {
            "$schema": SARIF_SCHEMA_URL,
            "version": SARIF_VERSION,
            "runs": [run],
        },
        ensure_ascii=False,
        indent=2,
    )


def to_sarif_report(
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
    return render_sarif_report_document(payload)
