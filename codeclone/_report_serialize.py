"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from ._report_types import GroupItem, GroupMap


def to_json(groups: GroupMap) -> str:
    def _sorted_items(items: list[GroupItem]) -> list[GroupItem]:
        return sorted(
            items,
            key=lambda item: (
                str(item.get("filepath", "")),
                int(item.get("start_line", 0)),
                int(item.get("end_line", 0)),
                str(item.get("qualname", "")),
            ),
        )

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
) -> str:
    def _sorted_items(items: list[GroupItem]) -> list[GroupItem]:
        return sorted(
            items,
            key=lambda item: (
                str(item.get("filepath", "")),
                int(item.get("start_line", 0)),
                int(item.get("end_line", 0)),
                str(item.get("qualname", "")),
            ),
        )

    def _sorted_group_map(groups: GroupMap) -> GroupMap:
        return {
            k: _sorted_items(v)
            for k, v in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        }

    meta_payload = dict(meta or {})
    func_sorted = _sorted_group_map(func_groups)
    block_sorted = _sorted_group_map(block_groups)
    segment_sorted = _sorted_group_map(segment_groups)
    return json.dumps(
        {
            "meta": meta_payload,
            "function_clones": func_sorted,
            "block_clones": block_sorted,
            "segment_clones": segment_sorted,
            # Backward-compatible keys.
            "functions": func_sorted,
            "blocks": block_sorted,
            "segments": segment_sorted,
        },
        ensure_ascii=False,
        indent=2,
    )


def to_text(groups: GroupMap) -> str:
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
                f"loc={item.get('loc', item.get('size'))}"
                for item in items
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _format_meta_text_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "n/a"
    text = str(value).strip()
    return text if text else "n/a"


def to_text_report(
    *,
    meta: Mapping[str, object],
    func_groups: GroupMap,
    block_groups: GroupMap,
    segment_groups: GroupMap,
) -> str:
    lines = [
        "REPORT METADATA",
        f"CodeClone version: {_format_meta_text_value(meta.get('codeclone_version'))}",
        f"Python version: {_format_meta_text_value(meta.get('python_version'))}",
        f"Baseline path: {_format_meta_text_value(meta.get('baseline_path'))}",
        "Baseline fingerprint version: "
        f"{_format_meta_text_value(meta.get('baseline_fingerprint_version'))}",
        "Baseline schema version: "
        f"{_format_meta_text_value(meta.get('baseline_schema_version'))}",
        "Baseline Python tag: "
        f"{_format_meta_text_value(meta.get('baseline_python_tag'))}",
        "Baseline generator version: "
        f"{_format_meta_text_value(meta.get('baseline_generator_version'))}",
        f"Baseline loaded: {_format_meta_text_value(meta.get('baseline_loaded'))}",
        f"Baseline status: {_format_meta_text_value(meta.get('baseline_status'))}",
    ]
    if "cache_path" in meta:
        lines.append(f"Cache path: {_format_meta_text_value(meta.get('cache_path'))}")
    if "cache_used" in meta:
        lines.append(f"Cache used: {_format_meta_text_value(meta.get('cache_used'))}")
    if "files_skipped_source_io" in meta:
        lines.append(
            "Source IO skipped: "
            f"{_format_meta_text_value(meta.get('files_skipped_source_io'))}"
        )

    sections = [
        ("FUNCTION CLONES", func_groups),
        ("BLOCK CLONES", block_groups),
        ("SEGMENT CLONES", segment_groups),
    ]
    for title, groups in sections:
        lines.append("")
        lines.append(title)
        block = to_text(groups).rstrip()
        lines.append(block if block else "(none)")

    return "\n".join(lines).rstrip() + "\n"
