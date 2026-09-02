# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TypedDict

from ..models import (
    BlockUnit,
    CacheNeutralPayload,
    FactRef,
    FunctionContractSummary,
    RehydratedCacheNeutral,
    SegmentGroupItem,
    SegmentUnit,
    SemanticEvent,
    SemanticFileFacts,
    SourceStats,
    Unit,
)
from ..utils.repo_paths import RepoPathPolicy, resolve_under_repo_root
from .integrity import (
    as_int_or_none,
    as_object_list,
    as_str_dict,
    as_str_or_none,
)

SegmentDict = SegmentGroupItem

_LOCAL_SEMANTIC_REF_PREFIX = "cc-local:"


def _localize_semantic_value(value: str, *, module_name: str) -> str:
    module_prefix = f"{module_name}:"
    if value.startswith(module_prefix):
        return f"{_LOCAL_SEMANTIC_REF_PREFIX}{value[len(module_prefix) :]}"
    return value


def _rehydrate_semantic_value(value: str, *, module_name: str) -> str:
    if value.startswith(_LOCAL_SEMANTIC_REF_PREFIX):
        return f"{module_name}:{value[len(_LOCAL_SEMANTIC_REF_PREFIX) :]}"
    return value


def _map_fact_ref(
    fact: FactRef,
    *,
    transform: Callable[[str], str],
) -> FactRef:
    return replace(fact, ref=transform(fact.ref))


def _map_semantic_event(
    event: SemanticEvent,
    *,
    transform: Callable[[str], str],
    filepath: str,
) -> SemanticEvent:
    return replace(
        event,
        event_id=transform(event.event_id),
        subject=transform(event.subject),
        inputs=tuple(_map_fact_ref(fact, transform=transform) for fact in event.inputs),
        output=(
            _map_fact_ref(event.output, transform=transform)
            if event.output is not None
            else None
        ),
        location=(filepath, event.location[1]),
    )


def _map_contract_summary(
    summary: FunctionContractSummary,
    *,
    transform: Callable[[str], str],
    filepath: str,
) -> FunctionContractSummary:
    return replace(
        summary,
        function=transform(summary.function),
        events=tuple(
            _map_semantic_event(event, transform=transform, filepath=filepath)
            for event in summary.events
        ),
        param_flows=tuple(
            (transform(source), transform(target))
            for source, target in summary.param_flows
        ),
        returns=tuple(
            _map_fact_ref(fact, transform=transform) for fact in summary.returns
        ),
    )


def localize_semantic_facts(
    facts: SemanticFileFacts,
    *,
    module_name: str,
) -> SemanticFileFacts:
    transform = lambda value: _localize_semantic_value(  # noqa: E731
        value,
        module_name=module_name,
    )
    return SemanticFileFacts(
        events=tuple(
            _map_semantic_event(event, transform=transform, filepath="")
            for event in facts.events
        ),
        function_contract_summaries=tuple(
            _map_contract_summary(summary, transform=transform, filepath="")
            for summary in facts.function_contract_summaries
        ),
    )


def rehydrate_semantic_facts(
    facts: SemanticFileFacts,
    *,
    module_name: str,
    filepath: str,
) -> SemanticFileFacts:
    transform = lambda value: _rehydrate_semantic_value(  # noqa: E731
        value,
        module_name=module_name,
    )
    return SemanticFileFacts(
        events=tuple(
            _map_semantic_event(event, transform=transform, filepath=filepath)
            for event in facts.events
        ),
        function_contract_summaries=tuple(
            _map_contract_summary(summary, transform=transform, filepath=filepath)
            for summary in facts.function_contract_summaries
        ),
    )


def rehydrate_cache_neutral(
    payload: CacheNeutralPayload,
    *,
    module_name: str,
    filepath: str,
    analysed_filepath: str,
) -> RehydratedCacheNeutral:
    """Serve one cached file's neutral families, each in ITS OWN domain.

    ``filepath`` is the runtime path, and it is what a family stamped by a
    module pass wants back: ``Unit``, ``BlockUnit`` and ``SegmentUnit`` all
    carry it, and the report layer relativises them against the scan root.
    ``analysed_filepath`` is the analysed spelling -- the repository-relative
    path the identity index, the module registry and the wire key all use --
    and the semantic facts are the family that wants THAT one.

    The split is not stylistic.  Measured 2026-09-02: a warm run stamped
    ``SemanticEvent.location[0]`` with the runtime path while a parsed run
    stamped ``ResolvedSourceIdentity.file.path``, so the authority result's
    violation locations changed spelling with cache warmth alone -- and
    ``source_facts`` is the preimage of the ``analysis_facts`` integrity
    tier, so the run identity changed with it.  The parameter is required
    rather than defaulted for the same reason ``_decode_wire_file_entry``
    takes two: a single path made the choice invisible, and the family that
    got it wrong was found only after it had shipped.
    """

    def qualify(local_name: str) -> str:
        return f"{module_name}:{local_name}"

    return RehydratedCacheNeutral(
        source_stats=SourceStats(**payload.source_stats),
        units=tuple(
            Unit(
                qualname=qualify(item.local_name),
                filepath=filepath,
                start_line=item.start_line,
                end_line=item.end_line,
                loc=item.loc,
                stmt_count=item.stmt_count,
                fingerprint=item.fingerprint,
                loc_bucket=item.loc_bucket,
                cyclomatic_complexity=item.cyclomatic_complexity,
                cfg_cyclomatic_complexity=item.cfg_cyclomatic_complexity,
                nesting_depth=item.nesting_depth,
                risk=item.risk,
                raw_hash=item.raw_hash,
                entry_guard_count=item.entry_guard_count,
                entry_guard_terminal_profile=item.entry_guard_terminal_profile,
                entry_guard_has_side_effect_before=(
                    item.entry_guard_has_side_effect_before
                ),
                terminal_kind=item.terminal_kind,
                try_finally_profile=item.try_finally_profile,
                side_effect_order_profile=item.side_effect_order_profile,
                statement_sequence=item.statement_sequence,
                renamed_fingerprint=item.renamed_fingerprint,
                renamed_statement_sequence=item.renamed_statement_sequence,
                unreachable_statements=item.unreachable_statements,
            )
            for item in payload.units
        ),
        blocks=tuple(
            BlockUnit(
                qualname=qualify(item.local_name),
                filepath=filepath,
                start_line=item.start_line,
                end_line=item.end_line,
                size=item.size,
                block_hash=item.block_hash,
            )
            for item in payload.blocks
        ),
        segments=tuple(
            SegmentUnit(
                qualname=qualify(item.local_name),
                filepath=filepath,
                start_line=item.start_line,
                end_line=item.end_line,
                size=item.size,
                segment_hash=item.segment_hash,
                segment_sig=item.segment_sig,
            )
            for item in payload.segments
        ),
        semantic_facts=rehydrate_semantic_facts(
            payload.semantic_facts,
            module_name=module_name,
            filepath=analysed_filepath,
        ),
    )


def wire_filepath_from_runtime(
    runtime_filepath: str,
    *,
    root: Path | None,
) -> str:
    runtime_path = Path(runtime_filepath)
    if root is None:
        return runtime_path.as_posix()

    try:
        relative = runtime_path.relative_to(root)
        return relative.as_posix()
    except ValueError:
        pass

    try:
        relative = runtime_path.resolve().relative_to(root.resolve())
        return relative.as_posix()
    except OSError:
        return runtime_path.as_posix()
    except ValueError:
        return runtime_path.as_posix()


def runtime_filepath_from_wire(
    wire_filepath: str,
    *,
    root: Path | None,
) -> str:
    wire_path = Path(wire_filepath)
    if root is None:
        return str(wire_path)

    return str(
        resolve_under_repo_root(
            root,
            wire_path,
            policy=RepoPathPolicy(allow_absolute=True),
        )
    )


class SegmentReportProjection(TypedDict):
    digest: str
    suppressed: int
    groups: dict[str, list[SegmentDict]]


def build_segment_report_projection(
    *,
    digest: str,
    suppressed: int,
    groups: Mapping[str, Sequence[Mapping[str, object]]],
) -> SegmentReportProjection:
    normalized_groups: dict[str, list[SegmentDict]] = {}
    for group_key in sorted(groups):
        normalized_items: list[SegmentDict] = []
        for raw_item in sorted(
            groups[group_key],
            key=lambda item: (
                str(item.get("filepath", "")),
                str(item.get("qualname", "")),
                as_int_or_none(item.get("start_line")) or 0,
                as_int_or_none(item.get("end_line")) or 0,
            ),
        ):
            segment_hash = as_str_or_none(raw_item.get("segment_hash"))
            segment_sig = as_str_or_none(raw_item.get("segment_sig"))
            filepath = as_str_or_none(raw_item.get("filepath"))
            qualname = as_str_or_none(raw_item.get("qualname"))
            start_line = as_int_or_none(raw_item.get("start_line"))
            end_line = as_int_or_none(raw_item.get("end_line"))
            size = as_int_or_none(raw_item.get("size"))
            if (
                segment_hash is None
                or segment_sig is None
                or filepath is None
                or qualname is None
                or start_line is None
                or end_line is None
                or size is None
            ):
                continue
            normalized_items.append(
                SegmentGroupItem(
                    segment_hash=segment_hash,
                    segment_sig=segment_sig,
                    filepath=filepath,
                    qualname=qualname,
                    start_line=start_line,
                    end_line=end_line,
                    size=size,
                )
            )
        if normalized_items:
            normalized_groups[group_key] = normalized_items
    return {
        "digest": digest,
        "suppressed": max(0, int(suppressed)),
        "groups": normalized_groups,
    }


def decode_segment_report_projection(
    value: object,
    *,
    root: Path | None,
) -> SegmentReportProjection | None:
    obj = as_str_dict(value)
    if obj is None:
        return None
    digest = as_str_or_none(obj.get("d"))
    suppressed = as_int_or_none(obj.get("s"))
    groups_raw = as_object_list(obj.get("g"))
    if digest is None or suppressed is None or groups_raw is None:
        return None
    groups: dict[str, list[SegmentDict]] = {}
    for group_row in groups_raw:
        group_list = as_object_list(group_row)
        if group_list is None or len(group_list) != 2:
            return None
        group_key = as_str_or_none(group_list[0])
        items_raw = as_object_list(group_list[1])
        if group_key is None or items_raw is None:
            return None
        items: list[SegmentDict] = []
        for item_raw in items_raw:
            item_list = as_object_list(item_raw)
            if item_list is None or len(item_list) != 7:
                return None
            wire_filepath = as_str_or_none(item_list[0])
            qualname = as_str_or_none(item_list[1])
            start_line = as_int_or_none(item_list[2])
            end_line = as_int_or_none(item_list[3])
            size = as_int_or_none(item_list[4])
            segment_hash = as_str_or_none(item_list[5])
            segment_sig = as_str_or_none(item_list[6])
            if (
                wire_filepath is None
                or qualname is None
                or start_line is None
                or end_line is None
                or size is None
                or segment_hash is None
                or segment_sig is None
            ):
                return None
            items.append(
                SegmentGroupItem(
                    segment_hash=segment_hash,
                    segment_sig=segment_sig,
                    filepath=runtime_filepath_from_wire(wire_filepath, root=root),
                    qualname=qualname,
                    start_line=start_line,
                    end_line=end_line,
                    size=size,
                )
            )
        groups[group_key] = items
    return {
        "digest": digest,
        "suppressed": max(0, suppressed),
        "groups": groups,
    }


def encode_segment_report_projection(
    projection: SegmentReportProjection | None,
    *,
    root: Path | None,
) -> dict[str, object] | None:
    if projection is None:
        return None
    groups_rows: list[list[object]] = []
    for group_key in sorted(projection["groups"]):
        items = sorted(
            projection["groups"][group_key],
            key=lambda item: (
                item["filepath"],
                item["qualname"],
                item["start_line"],
                item["end_line"],
            ),
        )
        encoded_items = [
            [
                wire_filepath_from_runtime(item["filepath"], root=root),
                item["qualname"],
                item["start_line"],
                item["end_line"],
                item["size"],
                item["segment_hash"],
                item["segment_sig"],
            ]
            for item in items
        ]
        groups_rows.append([group_key, encoded_items])
    return {
        "d": projection["digest"],
        "s": max(0, int(projection["suppressed"])),
        "g": groups_rows,
    }


__all__ = [
    "SegmentDict",
    "SegmentReportProjection",
    "build_segment_report_projection",
    "decode_segment_report_projection",
    "encode_segment_report_projection",
    "localize_semantic_facts",
    "rehydrate_cache_neutral",
    "rehydrate_semantic_facts",
    "runtime_filepath_from_wire",
    "wire_filepath_from_runtime",
]
