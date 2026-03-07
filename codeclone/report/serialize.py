"""Report serialization for JSON and text outputs."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping

from ..contracts import REPORT_SCHEMA_VERSION
from ..models import Suggestion
from .suggestions import classify_clone_type
from .types import GroupItemLike, GroupMap, GroupMapLike

FunctionRecord = tuple[int, str, int, int, int, int, str, str, int, int, str, str]
BlockRecord = tuple[int, str, int, int, int]
SegmentRecord = tuple[int, str, int, int, int, str, str]
SplitLists = dict[str, list[str]]
GroupsSplit = dict[str, SplitLists]

GROUP_ITEM_LAYOUT: dict[str, list[str]] = {
    "functions": [
        "file_i",
        "qualname",
        "start",
        "end",
        "loc",
        "stmt_count",
        "fingerprint",
        "loc_bucket",
        "cyclomatic_complexity",
        "nesting_depth",
        "risk",
        "raw_hash",
    ],
    "blocks": ["file_i", "qualname", "start", "end", "size"],
    "segments": [
        "file_i",
        "qualname",
        "start",
        "end",
        "size",
        "segment_hash",
        "segment_sig",
    ],
}


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


def _collect_files(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
) -> list[str]:
    files: set[str] = set()
    for groups in (func_groups, block_groups, segment_groups):
        for items in groups.values():
            for item in items:
                files.add(str(item.get("filepath", "")))
    return sorted(files)


def _encode_function_item(item: GroupItemLike, file_id: int) -> FunctionRecord:
    return (
        file_id,
        str(item.get("qualname", "")),
        _as_int(item.get("start_line", 0)),
        _as_int(item.get("end_line", 0)),
        _as_int(item.get("loc", 0)),
        _as_int(item.get("stmt_count", 0)),
        str(item.get("fingerprint", "")),
        str(item.get("loc_bucket", "")),
        _as_int(item.get("cyclomatic_complexity", 1)),
        _as_int(item.get("nesting_depth", 0)),
        str(item.get("risk", "low")),
        str(item.get("raw_hash", "")),
    )


def _encode_block_item(item: GroupItemLike, file_id: int) -> BlockRecord:
    return (
        file_id,
        str(item.get("qualname", "")),
        _as_int(item.get("start_line", 0)),
        _as_int(item.get("end_line", 0)),
        _as_int(item.get("size", 0)),
    )


def _encode_segment_item(item: GroupItemLike, file_id: int) -> SegmentRecord:
    return (
        file_id,
        str(item.get("qualname", "")),
        _as_int(item.get("start_line", 0)),
        _as_int(item.get("end_line", 0)),
        _as_int(item.get("size", 0)),
        str(item.get("segment_hash", "")),
        str(item.get("segment_sig", "")),
    )


def _function_record_sort_key(record: FunctionRecord) -> tuple[int, str, int, int]:
    return record[0], record[1], record[2], record[3]


def _block_record_sort_key(record: BlockRecord) -> tuple[int, str, int, int]:
    return record[0], record[1], record[2], record[3]


def _segment_record_sort_key(record: SegmentRecord) -> tuple[int, str, int, int]:
    return record[0], record[1], record[2], record[3]


def _resolve_metric_value(item: GroupItemLike, metric_name: str) -> int:
    raw_value = item.get(metric_name)
    if raw_value is None:
        fallback_metric = "size" if metric_name == "loc" else "loc"
        raw_value = item.get(fallback_metric, 0)
    if isinstance(raw_value, bool):
        return int(raw_value)
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str):
        return _as_int(raw_value)
    return 0


def _baseline_is_trusted(meta: Mapping[str, object]) -> bool:
    return (
        meta.get("baseline_loaded") is True
        and str(meta.get("baseline_status", "")).strip().lower() == "ok"
    )


def to_json_report(
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    meta: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Collection[Suggestion] | None = None,
) -> str:
    """
    Serialize report JSON schema v2.0.

    NEW/KNOWN split contract:
    - if baseline is not trusted, all groups are NEW and KNOWN is empty
    - if baseline is trusted, callers must pass `new_*_group_keys` computed by
      the core baseline diff pipeline; keys absent from `new_*` are treated as KNOWN
    """
    meta_payload = dict(meta or {})
    meta_payload["report_schema_version"] = REPORT_SCHEMA_VERSION

    files = _collect_files(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
    )
    file_ids = {filepath: idx for idx, filepath in enumerate(files)}

    function_groups: dict[str, list[FunctionRecord]] = {}
    for group_key in sorted(func_groups):
        function_records = [
            _encode_function_item(item, file_ids[str(item.get("filepath", ""))])
            for item in func_groups[group_key]
        ]
        function_groups[group_key] = sorted(
            function_records,
            key=_function_record_sort_key,
        )

    block_groups_out: dict[str, list[BlockRecord]] = {}
    for group_key in sorted(block_groups):
        block_records = [
            _encode_block_item(item, file_ids[str(item.get("filepath", ""))])
            for item in block_groups[group_key]
        ]
        block_groups_out[group_key] = sorted(block_records, key=_block_record_sort_key)

    segment_groups_out: dict[str, list[SegmentRecord]] = {}
    for group_key in sorted(segment_groups):
        segment_records = [
            _encode_segment_item(item, file_ids[str(item.get("filepath", ""))])
            for item in segment_groups[group_key]
        ]
        segment_groups_out[group_key] = sorted(
            segment_records,
            key=_segment_record_sort_key,
        )

    baseline_trusted = _baseline_is_trusted(meta_payload)

    def _split_for(
        *,
        keys: Collection[str],
        new_keys: Collection[str] | None,
    ) -> SplitLists:
        sorted_keys = sorted(keys)
        if not baseline_trusted:
            return {"new": sorted_keys, "known": []}
        if new_keys is None:
            return {"new": sorted_keys, "known": []}
        new_key_set = set(new_keys)
        new_list = [group_key for group_key in sorted_keys if group_key in new_key_set]
        known_list = [
            group_key for group_key in sorted_keys if group_key not in new_key_set
        ]
        return {"new": new_list, "known": known_list}

    groups_split: GroupsSplit = {
        "functions": _split_for(
            keys=function_groups.keys(),
            new_keys=new_function_group_keys,
        ),
        "blocks": _split_for(
            keys=block_groups_out.keys(),
            new_keys=new_block_group_keys,
        ),
        "segments": _split_for(
            keys=segment_groups_out.keys(),
            new_keys=new_segment_group_keys,
        ),
    }
    meta_payload["groups_counts"] = {
        section_name: {
            "total": len(section_split["new"]) + len(section_split["known"]),
            "new": len(section_split["new"]),
            "known": len(section_split["known"]),
        }
        for section_name, section_split in groups_split.items()
    }

    clone_types = {
        "functions": {
            group_key: classify_clone_type(
                items=func_groups[group_key],
                kind="function",
            )
            for group_key in sorted(func_groups)
        },
        "blocks": {
            group_key: classify_clone_type(
                items=block_groups[group_key],
                kind="block",
            )
            for group_key in sorted(block_groups)
        },
        "segments": {
            group_key: classify_clone_type(
                items=segment_groups[group_key],
                kind="segment",
            )
            for group_key in sorted(segment_groups)
        },
    }

    payload: dict[str, object] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "meta": meta_payload,
        "files": files,
        "groups": {
            "functions": function_groups,
            "blocks": block_groups_out,
            "segments": segment_groups_out,
        },
        "groups_split": groups_split,
        "group_item_layout": GROUP_ITEM_LAYOUT,
        "clones": {
            "functions": {
                "groups": function_groups,
                "split": groups_split["functions"],
                "count": len(function_groups),
            },
            "blocks": {
                "groups": block_groups_out,
                "split": groups_split["blocks"],
                "count": len(block_groups_out),
            },
            "segments": {
                "groups": segment_groups_out,
                "split": groups_split["segments"],
                "count": len(segment_groups_out),
            },
            "clone_types": clone_types,
        },
        "clone_types": clone_types,
    }

    if block_facts:
        sorted_block_facts: dict[str, dict[str, str]] = {}
        for group_key in sorted(block_facts):
            sorted_block_facts[group_key] = {
                fact_key: str(block_facts[group_key][fact_key])
                for fact_key in sorted(block_facts[group_key])
            }
        payload["facts"] = {"blocks": sorted_block_facts}

    if metrics is not None:
        payload["metrics"] = dict(metrics)

    if suggestions is not None:
        payload["suggestions"] = [
            {
                "severity": suggestion.severity,
                "category": suggestion.category,
                "title": suggestion.title,
                "location": suggestion.location,
                "steps": list(suggestion.steps),
                "effort": suggestion.effort,
                "priority": suggestion.priority,
            }
            for suggestion in suggestions
        ]

    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )


def to_text(groups: GroupMapLike, *, metric_name: str = "loc") -> str:
    lines: list[str] = []
    for i, (_, items_unsorted) in enumerate(
        sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ):
        items = sorted(
            items_unsorted,
            key=lambda item: (
                str(item.get("filepath", "")),
                _as_int(item.get("start_line", 0)),
                _as_int(item.get("end_line", 0)),
                str(item.get("qualname", "")),
            ),
        )
        lines.append(f"\n=== Clone group #{i + 1} (count={len(items_unsorted)}) ===")
        lines.extend(
            [
                f"- {item['qualname']} "
                f"{item['filepath']}:{item['start_line']}-{item['end_line']} "
                f"{metric_name}={_resolve_metric_value(item, metric_name)}"
                for item in items
            ]
        )
    return "\n".join(lines).strip() + "\n"


def format_meta_text_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "(none)"
    text = str(value).strip()
    return text if text else "(none)"


def to_text_report(
    *,
    meta: Mapping[str, object],
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Collection[Suggestion] | None = None,
) -> str:
    """
    Serialize deterministic TXT report.

    NEW/KNOWN split follows the same contract as JSON report output.
    """

    baseline_trusted = _baseline_is_trusted(meta)

    def _split_for(
        *, groups: GroupMapLike, new_keys: Collection[str] | None
    ) -> SplitLists:
        sorted_keys = sorted(groups.keys())
        if not baseline_trusted:
            return {"new": sorted_keys, "known": []}
        if new_keys is None:
            return {"new": sorted_keys, "known": []}
        new_key_set = set(new_keys)
        new_list = [group_key for group_key in sorted_keys if group_key in new_key_set]
        known_list = [
            group_key for group_key in sorted_keys if group_key not in new_key_set
        ]
        return {"new": new_list, "known": known_list}

    groups_split: GroupsSplit = {
        "functions": _split_for(groups=func_groups, new_keys=new_function_group_keys),
        "blocks": _split_for(groups=block_groups, new_keys=new_block_group_keys),
        "segments": _split_for(groups=segment_groups, new_keys=new_segment_group_keys),
    }

    lines = [
        "REPORT METADATA",
        "Report schema version: "
        f"{format_meta_text_value(meta.get('report_schema_version'))}",
        f"CodeClone version: {format_meta_text_value(meta.get('codeclone_version'))}",
        f"Project name: {format_meta_text_value(meta.get('project_name'))}",
        f"Scan root: {format_meta_text_value(meta.get('scan_root'))}",
        f"Python version: {format_meta_text_value(meta.get('python_version'))}",
        f"Python tag: {format_meta_text_value(meta.get('python_tag'))}",
        f"Baseline path: {format_meta_text_value(meta.get('baseline_path'))}",
        "Baseline fingerprint version: "
        f"{format_meta_text_value(meta.get('baseline_fingerprint_version'))}",
        "Baseline schema version: "
        f"{format_meta_text_value(meta.get('baseline_schema_version'))}",
        "Baseline Python tag: "
        f"{format_meta_text_value(meta.get('baseline_python_tag'))}",
        "Baseline generator name: "
        f"{format_meta_text_value(meta.get('baseline_generator_name'))}",
        "Baseline generator version: "
        f"{format_meta_text_value(meta.get('baseline_generator_version'))}",
        "Baseline payload sha256: "
        f"{format_meta_text_value(meta.get('baseline_payload_sha256'))}",
        "Baseline payload verified: "
        f"{format_meta_text_value(meta.get('baseline_payload_sha256_verified'))}",
        f"Baseline loaded: {format_meta_text_value(meta.get('baseline_loaded'))}",
        f"Baseline status: {format_meta_text_value(meta.get('baseline_status'))}",
        f"Cache path: {format_meta_text_value(meta.get('cache_path'))}",
        "Cache schema version: "
        f"{format_meta_text_value(meta.get('cache_schema_version'))}",
        f"Cache status: {format_meta_text_value(meta.get('cache_status'))}",
        f"Cache used: {format_meta_text_value(meta.get('cache_used'))}",
        "Source IO skipped: "
        f"{format_meta_text_value(meta.get('files_skipped_source_io'))}",
        "Metrics baseline path: "
        f"{format_meta_text_value(meta.get('metrics_baseline_path'))}",
        "Metrics baseline loaded: "
        f"{format_meta_text_value(meta.get('metrics_baseline_loaded'))}",
        "Metrics baseline status: "
        f"{format_meta_text_value(meta.get('metrics_baseline_status'))}",
        "Metrics baseline schema version: "
        f"{format_meta_text_value(meta.get('metrics_baseline_schema_version'))}",
        "Metrics baseline payload sha256: "
        f"{format_meta_text_value(meta.get('metrics_baseline_payload_sha256'))}",
        "Metrics baseline payload verified: "
        f"{format_meta_text_value(meta.get('metrics_baseline_payload_sha256_verified'))}",
        f"Analysis mode: {format_meta_text_value(meta.get('analysis_mode'))}",
        f"Metrics computed: {format_meta_text_value(meta.get('metrics_computed'))}",
        f"Health score: {format_meta_text_value(meta.get('health_score'))}",
        f"Health grade: {format_meta_text_value(meta.get('health_grade'))}",
    ]

    if not baseline_trusted:
        lines.append("Note: baseline is untrusted; all groups are treated as NEW.")

    if metrics:
        lines.extend(
            [
                "",
                "METRICS",
                json.dumps(dict(metrics), ensure_ascii=False, sort_keys=True),
            ]
        )
    if suggestions is not None:
        lines.extend(
            [
                "",
                "SUGGESTIONS",
                json.dumps(
                    [
                        {
                            "severity": suggestion.severity,
                            "category": suggestion.category,
                            "title": suggestion.title,
                            "location": suggestion.location,
                            "effort": suggestion.effort,
                            "priority": suggestion.priority,
                        }
                        for suggestion in suggestions
                    ],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ]
        )

    sections = (
        ("FUNCTION CLONES", "functions", func_groups, "loc"),
        ("BLOCK CLONES", "blocks", block_groups, "size"),
        ("SEGMENT CLONES", "segments", segment_groups, "size"),
    )
    for title, section_key, groups, metric_name in sections:
        split = groups_split[section_key]
        new_groups: GroupMap = {
            group_key: [dict(item) for item in groups[group_key]]
            for group_key in split["new"]
            if group_key in groups
        }
        known_groups: GroupMap = {
            group_key: [dict(item) for item in groups[group_key]]
            for group_key in split["known"]
            if group_key in groups
        }

        lines.append("")
        lines.append(f"{title} (NEW) (groups={len(split['new'])})")
        new_block = to_text(new_groups, metric_name=metric_name).rstrip()
        lines.append(new_block if new_block else "(none)")

        lines.append("")
        lines.append(f"{title} (KNOWN) (groups={len(split['known'])})")
        known_block = to_text(known_groups, metric_name=metric_name).rstrip()
        lines.append(known_block if known_block else "(none)")

    return "\n".join(lines).rstrip() + "\n"
