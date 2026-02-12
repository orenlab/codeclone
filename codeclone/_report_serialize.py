"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping

from ._report_types import GroupItem, GroupMap
from .contracts import REPORT_SCHEMA_VERSION

FunctionRecord = tuple[int, str, int, int, int, int, str, str]
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


def _item_sort_key(item: GroupItem) -> tuple[str, int, int, str]:
    return (
        str(item.get("filepath", "")),
        int(item.get("start_line", 0)),
        int(item.get("end_line", 0)),
        str(item.get("qualname", "")),
    )


def _collect_files(
    *,
    func_groups: GroupMap,
    block_groups: GroupMap,
    segment_groups: GroupMap,
) -> list[str]:
    files: set[str] = set()
    for groups in (func_groups, block_groups, segment_groups):
        for items in groups.values():
            for item in items:
                files.add(str(item.get("filepath", "")))
    return sorted(files)


def _encode_function_item(item: GroupItem, file_id: int) -> FunctionRecord:
    return (
        file_id,
        str(item.get("qualname", "")),
        int(item.get("start_line", 0)),
        int(item.get("end_line", 0)),
        int(item.get("loc", 0)),
        int(item.get("stmt_count", 0)),
        str(item.get("fingerprint", "")),
        str(item.get("loc_bucket", "")),
    )


def _encode_block_item(item: GroupItem, file_id: int) -> BlockRecord:
    return (
        file_id,
        str(item.get("qualname", "")),
        int(item.get("start_line", 0)),
        int(item.get("end_line", 0)),
        int(item.get("size", 0)),
    )


def _encode_segment_item(item: GroupItem, file_id: int) -> SegmentRecord:
    return (
        file_id,
        str(item.get("qualname", "")),
        int(item.get("start_line", 0)),
        int(item.get("end_line", 0)),
        int(item.get("size", 0)),
        str(item.get("segment_hash", "")),
        str(item.get("segment_sig", "")),
    )


def _function_record_sort_key(record: FunctionRecord) -> tuple[int, str, int, int]:
    return record[0], record[1], record[2], record[3]


def _block_record_sort_key(record: BlockRecord) -> tuple[int, str, int, int]:
    return record[0], record[1], record[2], record[3]


def _segment_record_sort_key(record: SegmentRecord) -> tuple[int, str, int, int]:
    return record[0], record[1], record[2], record[3]


def _resolve_metric_value(item: GroupItem, metric_name: str) -> int:
    raw_value = item.get(metric_name)
    if raw_value is None:
        fallback_metric = "size" if metric_name == "loc" else "loc"
        raw_value = item.get(fallback_metric, 0)
    return int(raw_value)


def _baseline_is_trusted(meta: Mapping[str, object]) -> bool:
    return (
        meta.get("baseline_loaded") is True
        and str(meta.get("baseline_status", "")).strip().lower() == "ok"
    )


def to_json(groups: GroupMap) -> str:
    def _sorted_items(items: list[GroupItem]) -> list[GroupItem]:
        return sorted(items, key=_item_sort_key)

    return json.dumps(
        {
            "group_count": len(groups),
            "groups": [
                {"key": k, "count": len(v), "items": _sorted_items(v)}
                for k, v in sorted(
                    groups.items(),
                    key=lambda kv: (-len(kv[1]), kv[0]),
                )
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def to_json_report(
    func_groups: GroupMap,
    block_groups: GroupMap,
    segment_groups: GroupMap,
    meta: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
) -> str:
    """
    Serialize report JSON schema v1.1.

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
            function_records, key=_function_record_sort_key
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
            segment_records, key=_segment_record_sort_key
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

    payload: dict[str, object] = {
        "meta": meta_payload,
        "files": files,
        "groups": {
            "functions": function_groups,
            "blocks": block_groups_out,
            "segments": segment_groups_out,
        },
        "groups_split": groups_split,
        "group_item_layout": GROUP_ITEM_LAYOUT,
    }

    if block_facts:
        sorted_block_facts: dict[str, dict[str, str]] = {}
        for group_key in sorted(block_facts):
            sorted_block_facts[group_key] = {
                fact_key: str(block_facts[group_key][fact_key])
                for fact_key in sorted(block_facts[group_key])
            }
        payload["facts"] = {"blocks": sorted_block_facts}

    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )


def to_text(groups: GroupMap, *, metric_name: str = "loc") -> str:
    lines: list[str] = []
    for i, (_, v) in enumerate(
        sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ):
        items = sorted(
            v,
            key=lambda item: (
                str(item.get("filepath", "")),
                int(item.get("start_line", 0)),
                int(item.get("end_line", 0)),
                str(item.get("qualname", "")),
            ),
        )
        lines.append(f"\n=== Clone group #{i + 1} (count={len(v)}) ===")
        lines.extend(
            [
                f"- {item['qualname']} "
                f"{item['filepath']}:{item['start_line']}-{item['end_line']} "
                f"{metric_name}={_resolve_metric_value(item, metric_name)}"
                for item in items
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _format_meta_text_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "(none)"
    text = str(value).strip()
    return text if text else "(none)"


def to_text_report(
    *,
    meta: Mapping[str, object],
    func_groups: GroupMap,
    block_groups: GroupMap,
    segment_groups: GroupMap,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
) -> str:
    """
    Serialize deterministic TXT report.

    NEW/KNOWN split follows the same contract as JSON v1.1.
    """

    baseline_trusted = _baseline_is_trusted(meta)

    def _split_for(
        *,
        groups: GroupMap,
        new_keys: Collection[str] | None,
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
        f"{_format_meta_text_value(meta.get('report_schema_version'))}",
        f"CodeClone version: {_format_meta_text_value(meta.get('codeclone_version'))}",
        f"Python version: {_format_meta_text_value(meta.get('python_version'))}",
        f"Python tag: {_format_meta_text_value(meta.get('python_tag'))}",
        f"Baseline path: {_format_meta_text_value(meta.get('baseline_path'))}",
        "Baseline fingerprint version: "
        f"{_format_meta_text_value(meta.get('baseline_fingerprint_version'))}",
        "Baseline schema version: "
        f"{_format_meta_text_value(meta.get('baseline_schema_version'))}",
        "Baseline Python tag: "
        f"{_format_meta_text_value(meta.get('baseline_python_tag'))}",
        "Baseline generator name: "
        f"{_format_meta_text_value(meta.get('baseline_generator_name'))}",
        "Baseline generator version: "
        f"{_format_meta_text_value(meta.get('baseline_generator_version'))}",
        "Baseline payload sha256: "
        f"{_format_meta_text_value(meta.get('baseline_payload_sha256'))}",
        "Baseline payload verified: "
        f"{_format_meta_text_value(meta.get('baseline_payload_sha256_verified'))}",
        f"Baseline loaded: {_format_meta_text_value(meta.get('baseline_loaded'))}",
        f"Baseline status: {_format_meta_text_value(meta.get('baseline_status'))}",
        f"Cache path: {_format_meta_text_value(meta.get('cache_path'))}",
        "Cache schema version: "
        f"{_format_meta_text_value(meta.get('cache_schema_version'))}",
        f"Cache status: {_format_meta_text_value(meta.get('cache_status'))}",
        f"Cache used: {_format_meta_text_value(meta.get('cache_used'))}",
        "Source IO skipped: "
        f"{_format_meta_text_value(meta.get('files_skipped_source_io'))}",
    ]

    if not baseline_trusted:
        lines.append("Note: baseline is untrusted; all groups are treated as NEW.")

    sections = (
        ("FUNCTION CLONES", "functions", func_groups, "loc"),
        ("BLOCK CLONES", "blocks", block_groups, "size"),
        ("SEGMENT CLONES", "segments", segment_groups, "size"),
    )
    for title, section_key, groups, metric_name in sections:
        split = groups_split[section_key]
        new_groups: GroupMap = {
            group_key: groups[group_key]
            for group_key in split["new"]
            if group_key in groups
        }
        known_groups: GroupMap = {
            group_key: groups[group_key]
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
