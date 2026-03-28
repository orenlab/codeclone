# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .. import _coerce
from ..contracts import DOCS_URL, REPOSITORY_URL
from ..domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    CATEGORY_DEPENDENCY,
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    FAMILY_CLONE,
    FAMILY_CLONES,
    FAMILY_DEAD_CODE,
    FAMILY_DESIGN,
    FAMILY_STRUCTURAL,
    FINDING_KIND_CLASS_HOTSPOT,
    FINDING_KIND_CLONE_GROUP,
    FINDING_KIND_CYCLE,
    FINDING_KIND_FUNCTION_HOTSPOT,
    FINDING_KIND_UNUSED_SYMBOL,
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
    STRUCTURAL_KIND_DUPLICATED_BRANCHES,
    SYMBOL_KIND_CLASS,
    SYMBOL_KIND_FUNCTION,
    SYMBOL_KIND_METHOD,
)
from ..domain.quality import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
)
from .json_contract import build_report_document

if TYPE_CHECKING:
    from ..models import StructuralFindingGroup, Suggestion
    from .types import GroupMapLike

SARIF_VERSION = "2.1.0"
SARIF_PROFILE_VERSION = "1.0"
SARIF_SCHEMA_URL = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_SRCROOT_BASE_ID = "%SRCROOT%"


@dataclass(frozen=True, slots=True)
class _RuleSpec:
    rule_id: str
    short_description: str
    full_description: str
    default_level: str
    category: str
    kind: str
    precision: str


_as_int = _coerce.as_int
_as_float = _coerce.as_float
_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _severity_to_level(severity: str) -> str:
    if severity == SEVERITY_CRITICAL:
        return "error"
    if severity == SEVERITY_WARNING:
        return "warning"
    return "note"


def _rule_name(spec: _RuleSpec) -> str:
    return f"codeclone.{spec.rule_id}"


def _rule_remediation(spec: _RuleSpec) -> str:
    rule_id = spec.rule_id
    if rule_id.startswith("CCLONE"):
        return (
            "Review the representative occurrence and related occurrences, "
            "then extract shared behavior or keep accepted debt in the baseline."
        )
    if rule_id == "CSTRUCT001":
        return (
            "Collapse repeated branch shapes into a shared helper, validator, "
            "or control-flow abstraction where the behavior is intentionally shared."
        )
    if rule_id == "CSTRUCT002":
        return (
            "Review the clone cohort and reconcile guard or early-exit behavior "
            "if those members are expected to stay aligned."
        )
    if rule_id == "CSTRUCT003":
        return (
            "Review the clone cohort and reconcile terminal, guard, or try/finally "
            "profiles if the drift is not intentional."
        )
    if rule_id.startswith("CDEAD"):
        return (
            "Remove the unused symbol or keep it explicitly documented/suppressed "
            "when runtime dynamics call it intentionally."
        )
    if rule_id == "CDESIGN001":
        return (
            "Split the class or regroup behavior so responsibilities become cohesive."
        )
    if rule_id == "CDESIGN002":
        return "Split the function or simplify control flow to reduce complexity."
    if rule_id == "CDESIGN003":
        return "Reduce dependencies or split responsibilities to lower coupling."
    return (
        "Break the cycle or invert dependencies so modules no longer depend "
        "on each other circularly."
    )


def _rule_help(spec: _RuleSpec) -> dict[str, str]:
    remediation = _rule_remediation(spec)
    return {
        "text": f"{spec.full_description} {remediation}",
        "markdown": (
            f"{spec.full_description}\n\n"
            f"{remediation}\n\n"
            f"See [CodeClone docs]({DOCS_URL})."
        ),
    }


def _scan_root_uri(payload: Mapping[str, object]) -> str:
    meta = _as_mapping(payload.get("meta"))
    runtime = _as_mapping(meta.get("runtime"))
    scan_root_absolute = _text(runtime.get("scan_root_absolute"))
    if not scan_root_absolute:
        return ""
    scan_root_path = Path(scan_root_absolute)
    if not scan_root_path.is_absolute():
        return ""
    try:
        uri = scan_root_path.as_uri()
    except ValueError:
        return ""
    return uri if uri.endswith("/") else f"{uri}/"


def _flatten_findings(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    findings = _as_mapping(payload.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    clones = _as_mapping(groups.get(FAMILY_CLONES))
    structural = _as_mapping(groups.get(FAMILY_STRUCTURAL))
    dead_code = _as_mapping(groups.get(FAMILY_DEAD_CODE))
    design = _as_mapping(groups.get(FAMILY_DESIGN))
    return [
        *map(_as_mapping, _as_sequence(clones.get("functions"))),
        *map(_as_mapping, _as_sequence(clones.get("blocks"))),
        *map(_as_mapping, _as_sequence(clones.get("segments"))),
        *map(_as_mapping, _as_sequence(structural.get("groups"))),
        *map(_as_mapping, _as_sequence(dead_code.get("groups"))),
        *map(_as_mapping, _as_sequence(design.get("groups"))),
    ]


def _artifact_catalog(
    findings: Sequence[Mapping[str, object]],
    *,
    use_uri_base_id: bool,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    artifact_paths = sorted(
        {
            relative_path
            for group in findings
            for item in map(_as_mapping, _as_sequence(group.get("items")))
            for relative_path in (_text(item.get("relative_path")),)
            if relative_path
        }
    )
    artifact_index_map = {path: index for index, path in enumerate(artifact_paths)}
    artifacts = [
        {
            "location": {
                "uri": path,
                **({"uriBaseId": SARIF_SRCROOT_BASE_ID} if use_uri_base_id else {}),
            }
        }
        for path in artifact_paths
    ]
    return cast(list[dict[str, object]], artifacts), artifact_index_map


def _clone_rule_spec(category: str) -> _RuleSpec:
    if category == CLONE_KIND_FUNCTION:
        return _RuleSpec(
            "CCLONE001",
            "Function clone group",
            "Multiple functions share the same normalized function body.",
            SEVERITY_WARNING,
            FAMILY_CLONE,
            FINDING_KIND_CLONE_GROUP,
            CONFIDENCE_HIGH,
        )
    if category == CLONE_KIND_BLOCK:
        return _RuleSpec(
            "CCLONE002",
            "Block clone group",
            "Repeated normalized statement blocks were detected across occurrences.",
            SEVERITY_WARNING,
            FAMILY_CLONE,
            FINDING_KIND_CLONE_GROUP,
            CONFIDENCE_HIGH,
        )
    return _RuleSpec(
        "CCLONE003",
        "Segment clone group",
        "Repeated normalized statement segments were detected across occurrences.",
        "note",
        FAMILY_CLONE,
        FINDING_KIND_CLONE_GROUP,
        CONFIDENCE_MEDIUM,
    )


def _structural_rule_spec(kind: str) -> _RuleSpec:
    if kind == STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE:
        return _RuleSpec(
            "CSTRUCT002",
            "Clone guard/exit divergence",
            (
                "Members of the same function-clone cohort diverged in "
                "entry guards or early-exit behavior."
            ),
            SEVERITY_WARNING,
            FAMILY_STRUCTURAL,
            STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
            CONFIDENCE_HIGH,
        )
    if kind == STRUCTURAL_KIND_CLONE_COHORT_DRIFT:
        return _RuleSpec(
            "CSTRUCT003",
            "Clone cohort drift",
            (
                "Members of the same function-clone cohort drifted from "
                "the majority terminal/guard/try profile."
            ),
            SEVERITY_WARNING,
            FAMILY_STRUCTURAL,
            STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
            CONFIDENCE_HIGH,
        )
    return _RuleSpec(
        "CSTRUCT001",
        "Duplicated branches",
        "Repeated branch families with matching structural signatures were detected.",
        SEVERITY_WARNING,
        FAMILY_STRUCTURAL,
        kind or STRUCTURAL_KIND_DUPLICATED_BRANCHES,
        CONFIDENCE_MEDIUM,
    )


def _dead_code_rule_spec(category: str) -> _RuleSpec:
    if category == SYMBOL_KIND_FUNCTION:
        return _RuleSpec(
            "CDEAD001",
            "Unused function",
            "Function appears to be unused with high confidence.",
            SEVERITY_WARNING,
            FAMILY_DEAD_CODE,
            FINDING_KIND_UNUSED_SYMBOL,
            CONFIDENCE_HIGH,
        )
    if category == SYMBOL_KIND_CLASS:
        return _RuleSpec(
            "CDEAD002",
            "Unused class",
            "Class appears to be unused with high confidence.",
            SEVERITY_WARNING,
            FAMILY_DEAD_CODE,
            FINDING_KIND_UNUSED_SYMBOL,
            CONFIDENCE_HIGH,
        )
    if category == SYMBOL_KIND_METHOD:
        return _RuleSpec(
            "CDEAD003",
            "Unused method",
            "Method appears to be unused with high confidence.",
            SEVERITY_WARNING,
            FAMILY_DEAD_CODE,
            FINDING_KIND_UNUSED_SYMBOL,
            CONFIDENCE_HIGH,
        )
    return _RuleSpec(
        "CDEAD004",
        "Unused symbol",
        "Symbol appears to be unused with reported confidence.",
        SEVERITY_WARNING,
        FAMILY_DEAD_CODE,
        FINDING_KIND_UNUSED_SYMBOL,
        CONFIDENCE_MEDIUM,
    )


def _design_rule_spec(category: str, kind: str) -> _RuleSpec:
    if category == CATEGORY_COHESION:
        return _RuleSpec(
            "CDESIGN001",
            "Low cohesion class",
            "Class cohesion is low according to LCOM4 hotspot thresholds.",
            SEVERITY_WARNING,
            FAMILY_DESIGN,
            kind or FINDING_KIND_CLASS_HOTSPOT,
            CONFIDENCE_HIGH,
        )
    if category == CATEGORY_COMPLEXITY:
        return _RuleSpec(
            "CDESIGN002",
            "Complexity hotspot",
            "Function exceeds the project complexity hotspot threshold.",
            SEVERITY_WARNING,
            FAMILY_DESIGN,
            kind or FINDING_KIND_FUNCTION_HOTSPOT,
            CONFIDENCE_HIGH,
        )
    if category == CATEGORY_COUPLING:
        return _RuleSpec(
            "CDESIGN003",
            "Coupling hotspot",
            "Class exceeds the project coupling hotspot threshold.",
            SEVERITY_WARNING,
            FAMILY_DESIGN,
            kind or FINDING_KIND_CLASS_HOTSPOT,
            CONFIDENCE_HIGH,
        )
    return _RuleSpec(
        "CDESIGN004",
        "Dependency cycle",
        "A dependency cycle was detected between project modules.",
        "error",
        FAMILY_DESIGN,
        kind or FINDING_KIND_CYCLE,
        CONFIDENCE_HIGH,
    )


def _rule_spec(group: Mapping[str, object]) -> _RuleSpec:
    family = _text(group.get("family"))
    category = _text(group.get("category"))
    kind = _text(group.get("kind"))
    if family == FAMILY_CLONE:
        return _clone_rule_spec(category)
    if family == FAMILY_STRUCTURAL:
        return _structural_rule_spec(kind)
    if family == FAMILY_DEAD_CODE:
        return _dead_code_rule_spec(category)
    return _design_rule_spec(category, kind)


def _structural_signature(group: Mapping[str, object]) -> Mapping[str, object]:
    return _as_mapping(_as_mapping(group.get("signature")).get("stable"))


def _clone_result_message(
    group: Mapping[str, object],
    *,
    category: str,
    count: int,
    spread: Mapping[str, object],
) -> str:
    clone_type = _text(group.get("clone_type"))
    return (
        f"{category.title()} clone group ({clone_type}), {count} occurrences "
        f"across {_as_int(spread.get('files'))} files."
    )


def _structural_result_message(
    group: Mapping[str, object],
    *,
    count: int,
    qualname: str,
) -> str:
    signature = _structural_signature(group)
    signature_family = _text(signature.get("family"))
    if signature_family == STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE:
        cohort_id = _text(signature.get("cohort_id"))
        return (
            "Clone guard/exit divergence"
            f" ({count} divergent members) in cohort "
            f"{cohort_id or 'unknown'}."
        )
    if signature_family == STRUCTURAL_KIND_CLONE_COHORT_DRIFT:
        drift_fields = _as_sequence(signature.get("drift_fields"))
        drift_label = ", ".join(_text(item) for item in drift_fields) or "profile"
        cohort_id = _text(signature.get("cohort_id"))
        return (
            f"Clone cohort drift ({drift_label}), "
            f"{count} divergent members in cohort {cohort_id or 'unknown'}."
        )
    stmt_shape = _text(signature.get("stmt_shape"))
    if qualname:
        return (
            f"Repeated branch family ({stmt_shape}), {count} occurrences in {qualname}."
        )
    return f"Repeated branch family ({stmt_shape}), {count} occurrences."


def _dead_code_result_message(
    group: Mapping[str, object],
    *,
    category: str,
    qualname: str,
    relative_path: str,
) -> str:
    confidence = _text(group.get("confidence")) or "reported"
    target = qualname or relative_path
    return f"Unused {category} with {confidence} confidence: {target}."


def _design_result_message(
    *,
    category: str,
    facts: Mapping[str, object],
    qualname: str,
    items: Sequence[Mapping[str, object]],
) -> str:
    if category == CATEGORY_COHESION:
        lcom4 = _as_int(facts.get("lcom4"))
        return f"Low cohesion class (LCOM4={lcom4}): {qualname}."
    if category == CATEGORY_COMPLEXITY:
        cc = _as_int(facts.get("cyclomatic_complexity"))
        return f"High complexity function (CC={cc}): {qualname}."
    if category == CATEGORY_COUPLING:
        cbo = _as_int(facts.get("cbo"))
        return f"High coupling class (CBO={cbo}): {qualname}."
    modules = [_text(item.get("module")) for item in items if _text(item.get("module"))]
    return f"Dependency cycle ({len(modules)} modules): {' -> '.join(modules)}."


def _result_message(group: Mapping[str, object]) -> str:
    family = _text(group.get("family"))
    category = _text(group.get("category"))
    count = _as_int(group.get("count"))
    spread = _as_mapping(group.get("spread"))
    items = [_as_mapping(item) for item in _as_sequence(group.get("items"))]
    first_item = items[0] if items else {}
    qualname = _text(first_item.get("qualname"))
    if family == FAMILY_CLONE:
        return _clone_result_message(
            group,
            category=category,
            count=count,
            spread=spread,
        )
    if family == FAMILY_STRUCTURAL:
        return _structural_result_message(
            group,
            count=count,
            qualname=qualname,
        )
    if family == FAMILY_DEAD_CODE:
        return _dead_code_result_message(
            group,
            category=category,
            qualname=qualname,
            relative_path=_text(first_item.get("relative_path")),
        )
    return _design_result_message(
        category=category,
        facts=_as_mapping(group.get("facts")),
        qualname=qualname,
        items=items,
    )


def _logical_locations(item: Mapping[str, object]) -> list[dict[str, object]]:
    qualname = _text(item.get("qualname"))
    if qualname:
        return [{"fullyQualifiedName": qualname}]
    module = _text(item.get("module"))
    if module:
        return [{"fullyQualifiedName": module}]
    return []


def _location_message(
    group: Mapping[str, object],
    *,
    related_id: int | None = None,
) -> str:
    family = _text(group.get("family"))
    category = _text(group.get("category"))
    if family in {FAMILY_CLONE, FAMILY_STRUCTURAL}:
        return (
            "Representative occurrence"
            if related_id is None
            else f"Related occurrence #{related_id}"
        )
    if family == FAMILY_DEAD_CODE:
        return (
            "Unused symbol declaration"
            if related_id is None
            else f"Related declaration #{related_id}"
        )
    if category == CATEGORY_DEPENDENCY:
        return (
            "Cycle member"
            if related_id is None
            else f"Related cycle member #{related_id}"
        )
    return (
        "Primary location" if related_id is None else f"Related location #{related_id}"
    )


def _location_entry(
    item: Mapping[str, object],
    *,
    related_id: int | None = None,
    artifact_index_map: Mapping[str, int] | None = None,
    use_uri_base_id: bool = False,
    message_text: str = "",
) -> dict[str, object]:
    relative_path = _text(item.get("relative_path"))
    location: dict[str, object] = {}
    if relative_path:
        artifact_location: dict[str, object] = {
            "uri": relative_path,
        }
        if use_uri_base_id:
            artifact_location["uriBaseId"] = SARIF_SRCROOT_BASE_ID
        if artifact_index_map and relative_path in artifact_index_map:
            artifact_location["index"] = artifact_index_map[relative_path]
        physical_location: dict[str, object] = {
            "artifactLocation": artifact_location,
        }
    else:
        physical_location = {}
    start_line = _as_int(item.get("start_line"))
    end_line = _as_int(item.get("end_line"))
    if physical_location and start_line > 0:
        region: dict[str, object] = {"startLine": start_line}
        if end_line > 0:
            region["endLine"] = end_line
        physical_location["region"] = region
    if physical_location:
        location["physicalLocation"] = physical_location
    logical_locations = _logical_locations(item)
    if logical_locations:
        location["logicalLocations"] = logical_locations
    if message_text:
        location["message"] = {"text": message_text}
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


def _clone_result_properties(
    props: dict[str, object],
    group: Mapping[str, object],
) -> dict[str, object]:
    props.update(
        {
            "novelty": _text(group.get("novelty")),
            "cloneKind": _text(group.get("clone_kind")),
            "cloneType": _text(group.get("clone_type")),
            "groupArity": _as_int(group.get("count")),
        }
    )
    return props


def _structural_signature_properties(
    signature: Mapping[str, object],
) -> dict[str, object]:
    signature_family = _text(signature.get("family"))
    if signature_family == STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE:
        return {
            "cohortId": _text(signature.get("cohort_id")),
            "majorityGuardCount": _as_int(
                signature.get("majority_guard_count"),
            ),
            "majorityTerminalKind": _text(
                signature.get("majority_terminal_kind"),
            ),
        }
    if signature_family == STRUCTURAL_KIND_CLONE_COHORT_DRIFT:
        return {
            "cohortId": _text(signature.get("cohort_id")),
            "driftFields": [
                _text(field) for field in _as_sequence(signature.get("drift_fields"))
            ],
        }
    return {
        "statementShape": _text(signature.get("stmt_shape")),
        "terminalKind": _text(signature.get("terminal_kind")),
    }


def _structural_result_properties(
    props: dict[str, object],
    group: Mapping[str, object],
) -> dict[str, object]:
    signature = _structural_signature(group)
    props["occurrenceCount"] = _as_int(group.get("count"))
    props.update(_structural_signature_properties(signature))
    return props


def _design_result_properties(
    props: dict[str, object],
    *,
    facts: Mapping[str, object],
) -> dict[str, object]:
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
    return props


def _result_properties(group: Mapping[str, object]) -> dict[str, object]:
    props = _generic_properties(group)
    family = _text(group.get("family"))
    if family == FAMILY_CLONE:
        return _clone_result_properties(props, group)
    if family == FAMILY_STRUCTURAL:
        return _structural_result_properties(props, group)
    if family == FAMILY_DESIGN:
        return _design_result_properties(
            props,
            facts=_as_mapping(group.get("facts")),
        )
    return props


def _partial_fingerprints(
    *,
    rule_id: str,
    group: Mapping[str, object],
    primary_item: Mapping[str, object],
) -> dict[str, str]:
    finding_id = _text(group.get("id"))
    path = _text(primary_item.get("relative_path"))
    qualname = _text(primary_item.get("qualname"))
    start_line = _as_int(primary_item.get("start_line"))
    if path and start_line > 0:
        fingerprint_material = "\0".join(
            (
                rule_id,
                finding_id,
                path,
                qualname,
            )
        )
        return {
            "primaryLocationLineHash": (
                f"{hashlib.sha256(fingerprint_material.encode('utf-8')).hexdigest()[:16]}"
                f":{start_line}"
            )
        }
    return {}


def _primary_location_properties(
    primary_item: Mapping[str, object],
) -> dict[str, object]:
    path = _text(primary_item.get("relative_path"))
    qualname = _text(primary_item.get("qualname"))
    start_line = _as_int(primary_item.get("start_line"))
    end_line = _as_int(primary_item.get("end_line"))
    props: dict[str, object] = {}
    if path:
        props["primaryPath"] = path
    if qualname:
        props["primaryQualname"] = qualname
    if start_line > 0:
        props["primaryRegion"] = f"{start_line}-{end_line or start_line}"
    return props


def _baseline_state(group: Mapping[str, object]) -> str:
    novelty = _text(group.get("novelty"))
    if novelty == "new":
        return "new"
    if novelty == "known":
        return "unchanged"
    return ""


def _result_entry(
    *,
    group: Mapping[str, object],
    rule_id: str,
    rule_index: int,
    artifact_index_map: Mapping[str, int],
    use_uri_base_id: bool,
) -> dict[str, object]:
    items = [_as_mapping(item) for item in _as_sequence(group.get("items"))]
    primary_item = items[0] if items else {}
    primary_location = (
        _location_entry(
            primary_item,
            artifact_index_map=artifact_index_map,
            use_uri_base_id=use_uri_base_id,
            message_text=_location_message(group),
        )
        if primary_item
        else {}
    )
    result: dict[str, object] = {
        "ruleId": rule_id,
        "ruleIndex": rule_index,
        "kind": "fail",
        "level": _severity_to_level(_text(group.get("severity"))),
        "message": {
            "text": _result_message(group),
        },
        "locations": [primary_location] if primary_location else [],
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
    if primary_item:
        properties = cast(dict[str, object], result["properties"])
        properties.update(_primary_location_properties(primary_item))
    baseline_state = _baseline_state(group)
    if baseline_state:
        result["baselineState"] = baseline_state
    related_items = items[1:]
    if related_items:
        related_locations = [
            _location_entry(
                item,
                related_id=index,
                artifact_index_map=artifact_index_map,
                use_uri_base_id=use_uri_base_id,
                message_text=_location_message(group, related_id=index),
            )
            for index, item in enumerate(related_items, start=1)
        ]
        result["relatedLocations"] = [
            location for location in related_locations if location
        ]
    return result


def render_sarif_report_document(payload: Mapping[str, object]) -> str:
    meta = _as_mapping(payload.get("meta"))
    runtime = _as_mapping(meta.get("runtime"))
    analysis_started_at = _text(runtime.get("analysis_started_at_utc"))
    generated_at = _text(runtime.get("report_generated_at_utc"))
    analysis_mode = _text(meta.get("analysis_mode")) or "full"
    findings = sorted(
        _flatten_findings(payload),
        key=lambda group: (
            _rule_spec(group).rule_id,
            _text(group.get("id")),
        ),
    )
    scan_root_uri = _scan_root_uri(payload)
    use_uri_base_id = bool(scan_root_uri)
    artifacts, artifact_index_map = _artifact_catalog(
        findings,
        use_uri_base_id=use_uri_base_id,
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
            artifact_index_map=artifact_index_map,
            use_uri_base_id=use_uri_base_id,
        )
        for group in findings
        for rule in (_rule_spec(group),)
    ]
    invocation: dict[str, object] = {
        "executionSuccessful": True,
        **({"startTimeUtc": analysis_started_at} if analysis_started_at else {}),
        **({"endTimeUtc": generated_at} if generated_at else {}),
    }
    if scan_root_uri:
        invocation["workingDirectory"] = {"uri": scan_root_uri}
    run: dict[str, object] = {
        "tool": {
            "driver": {
                "name": "codeclone",
                "version": _text(meta.get("codeclone_version")),
                "informationUri": REPOSITORY_URL,
                "rules": [
                    {
                        "id": spec.rule_id,
                        "name": _rule_name(spec),
                        "shortDescription": {"text": spec.short_description},
                        "fullDescription": {"text": spec.full_description},
                        "help": _rule_help(spec),
                        "defaultConfiguration": {"level": spec.default_level},
                        "helpUri": DOCS_URL,
                        "properties": {
                            "category": spec.category,
                            "kind": spec.kind,
                            "precision": spec.precision,
                            "tags": [spec.category, spec.kind, spec.precision],
                        },
                    }
                    for spec in ordered_rule_specs
                ],
            }
        },
        "automationDetails": {
            "id": "/".join(
                part
                for part in (
                    "codeclone",
                    analysis_mode,
                    generated_at
                    or _text(
                        _as_mapping(
                            _as_mapping(payload.get("integrity")).get("digest")
                        ).get("value")
                    )[:12],
                )
                if part
            ),
        },
        **(
            {
                "originalUriBaseIds": {
                    SARIF_SRCROOT_BASE_ID: {
                        "uri": scan_root_uri,
                        "description": {"text": "The root of the scanned source tree."},
                    }
                }
            }
            if scan_root_uri
            else {}
        ),
        "artifacts": artifacts,
        "results": results,
        "invocations": [invocation],
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
