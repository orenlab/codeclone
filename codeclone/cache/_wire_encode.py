# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from ..models import (
    BlockGroupItem,
    CacheEntryV3,
    CacheFactsDict,
    ClassMetricsDict,
    DigestObject,
    FactRef,
    FunctionContractSummary,
    FunctionGroupItem,
    SegmentGroupItem,
    SemanticEvent,
)
from ._canonicalize import _normalized_optional_string_list


def _encode_source_stats(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    source_stats = entry.get("source_stats")
    if source_stats is not None:
        wire["ss"] = [
            source_stats["lines"],
            source_stats["functions"],
            source_stats["methods"],
            source_stats["classes"],
        ]


def _encode_units(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    units = sorted(
        entry["units"],
        key=lambda unit: (
            unit["qualname"],
            unit["start_line"],
            unit["end_line"],
            unit["fingerprint"],
        ),
    )
    if units:
        wire["u"] = [
            [
                unit["qualname"],
                unit["start_line"],
                unit["end_line"],
                unit["loc"],
                unit["stmt_count"],
                unit["fingerprint"],
                unit["loc_bucket"],
                unit.get("cyclomatic_complexity", 1),
                unit.get("nesting_depth", 0),
                unit.get("risk", "low"),
                unit.get("raw_hash", ""),
                unit.get("entry_guard_count", 0),
                unit.get("entry_guard_terminal_profile", "none"),
                1 if unit.get("entry_guard_has_side_effect_before", False) else 0,
                unit.get("terminal_kind", "fallthrough"),
                unit.get("try_finally_profile", "none"),
                unit.get("side_effect_order_profile", "none"),
            ]
            for unit in units
        ]
        # Own top-level key, never a defaulted field on the positional unit
        # row: the row decodes optionals through ``.get(default)``, so a
        # sequence carried there would read as "no statements" on a stale entry
        # and a warm run would silently report zero near-miss pairs. As its own
        # key its ABSENCE rejects the entry instead, and rejection just means
        # the file is re-analysed (39Y Y8).
        wire["us"] = [
            [
                unit["qualname"],
                unit["start_line"],
                [
                    field
                    for element in unit.get("statement_sequence", ())
                    for field in (element[0], element[1], element[2])
                ],
            ]
            for unit in units
        ]
        # Same own-key/absence-rejects carriage as "us" (Wave C, CACHE_VERSION
        # 3.3): the renamed-structure digest is computed from the AST, which a
        # warm run never re-parses. A stale entry without this key must reject
        # rather than decode into units that merely look digest-free.
        wire["uc"] = [
            [
                unit["qualname"],
                unit["start_line"],
                unit.get("renamed_fingerprint", ""),
            ]
            for unit in units
        ]
        # Same reasoning one lane over (39Y Y9): the CFG is built only on the
        # analysed path, so a warm run cannot recompute reachability. Carried
        # as its own key, an entry written before the fact existed is rejected
        # rather than decoding into units that merely look fully reachable.
        wire["ur"] = [
            [
                unit["qualname"],
                unit["start_line"],
                [
                    field
                    for fact in unit.get("unreachable_statements", ())
                    for field in (
                        fact.reason,
                        fact.start_line,
                        fact.end_line,
                        fact.statement_count,
                    )
                ],
            ]
            for unit in units
        ]


def _encode_blocks(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    blocks = sorted(
        entry["blocks"],
        key=lambda block: (
            block["qualname"],
            block["start_line"],
            block["end_line"],
            block["block_hash"],
        ),
    )
    if blocks:
        wire["b"] = [
            [
                block["qualname"],
                block["start_line"],
                block["end_line"],
                block["size"],
                block["block_hash"],
            ]
            for block in blocks
        ]


def _encode_segments(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    segments = sorted(
        entry["segments"],
        key=lambda segment: (
            segment["qualname"],
            segment["start_line"],
            segment["end_line"],
            segment["segment_hash"],
        ),
    )
    if segments:
        wire["s"] = [
            [
                segment["qualname"],
                segment["start_line"],
                segment["end_line"],
                segment["size"],
                segment["segment_hash"],
                segment["segment_sig"],
            ]
            for segment in segments
        ]


def _append_coupled_classes_row(
    metric: ClassMetricsDict,
    *,
    rows: list[list[object]],
) -> None:
    coupled_classes = _normalized_optional_string_list(
        metric.get("coupled_classes", [])
    )
    if coupled_classes:
        rows.append([metric["qualname"], coupled_classes])


def _append_instantiation_candidates_row(
    metric: ClassMetricsDict,
    *,
    rows: list[list[object]],
) -> None:
    """CACHE_VERSION 3.2: imported call targets awaiting project resolution.

    A class that calls no imported binding is omitted, so trees that never had
    a candidate keep encoding byte-identically.
    """
    candidates = _normalized_optional_string_list(
        metric.get("instantiation_candidates", [])
    )
    if candidates:
        rows.append([metric["qualname"], candidates])


def _append_class_base_row(
    metric: ClassMetricsDict,
    *,
    rows: list[list[object]],
) -> None:
    """CACHE_VERSION 3.2: declared bases and the rule-3 opacity flag.

    A class that declares no base is omitted - it has nothing to resolve, and
    the flag cannot be true without a base - so 3.1-shaped trees keep encoding
    byte-identically.
    """
    base_names = _normalized_optional_string_list(metric.get("base_names", []))
    if base_names:
        rows.append(
            [
                metric["qualname"],
                base_names,
                bool(metric.get("has_unresolved_external_base", False)),
            ]
        )


def _append_decorator_evidence_row(
    metric: ClassMetricsDict,
    *,
    rows: list[list[object]],
) -> None:
    """CACHE_VERSION 3.2: methods of this class with an explicit contract."""
    evidenced = _normalized_optional_string_list(
        metric.get("decorator_evidenced_methods", [])
    )
    if evidenced:
        rows.append([metric["qualname"], evidenced])


def _append_self_dispatch_row(
    metric: ClassMetricsDict,
    *,
    rows: list[list[object]],
) -> None:
    """CACHE_VERSION 3.2: methods of this class called through ``self``."""
    dispatched = _normalized_optional_string_list(
        metric.get("self_dispatched_methods", [])
    )
    if dispatched:
        rows.append([metric["qualname"], dispatched])


def _encode_class_metrics(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    class_metrics = sorted(
        entry["class_metrics"],
        key=lambda metric: (
            metric["start_line"],
            metric["end_line"],
            metric["qualname"],
        ),
    )
    if class_metrics:
        coupled_classes_rows: list[list[object]] = []
        # "bs"/"de"/"sd", not "cb": the top-level wire already spends "cb" on
        # cache_content_binding_version, and a reader should never have to
        # know which dict it is holding to read a key correctly.
        class_base_rows: list[list[object]] = []
        decorator_evidence_rows: list[list[object]] = []
        self_dispatch_rows: list[list[object]] = []
        instantiation_candidate_rows: list[list[object]] = []
        wire["cm"] = [
            [
                metric["qualname"],
                metric["start_line"],
                metric["end_line"],
                metric["cbo"],
                metric["lcom4"],
                metric["method_count"],
                metric["instance_var_count"],
                metric["risk_coupling"],
                metric["risk_cohesion"],
            ]
            for metric in class_metrics
        ]
        for metric in class_metrics:
            _append_coupled_classes_row(metric, rows=coupled_classes_rows)
            _append_class_base_row(metric, rows=class_base_rows)
            _append_decorator_evidence_row(metric, rows=decorator_evidence_rows)
            _append_self_dispatch_row(metric, rows=self_dispatch_rows)
            _append_instantiation_candidates_row(
                metric,
                rows=instantiation_candidate_rows,
            )
        if coupled_classes_rows:
            wire["cc"] = coupled_classes_rows
        if class_base_rows:
            wire["bs"] = class_base_rows
        if decorator_evidence_rows:
            wire["de"] = decorator_evidence_rows
        if self_dispatch_rows:
            wire["sd"] = self_dispatch_rows
        if instantiation_candidate_rows:
            wire["ic"] = instantiation_candidate_rows


def _encode_module_deps(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    module_deps = sorted(
        entry["module_deps"],
        key=lambda dep: (
            dep["source"],
            dep["target"],
            dep["import_type"],
            dep["line"],
            dep.get("resolution", ""),
            dep.get("level", -1),
            dep.get("requested_module") or "",
            tuple(dep.get("requested_names", ())),
            tuple(dep.get("candidate_targets", ())),
            dep.get("inventory_expansion", False),
            dep.get("mechanism", ""),
        ),
    )
    if module_deps:
        rows: list[list[object]] = []
        for dep in module_deps:
            base_row: list[object] = [
                dep["source"],
                dep["target"],
                dep["import_type"],
                dep["line"],
            ]
            try:
                detail_row: tuple[object, ...] = (
                    dep["resolution"],
                    dep["inventory_expansion"],
                    dep["level"],
                    dep["requested_module"],
                    dep["requested_names"],
                    dep["candidate_targets"],
                    dep["mechanism"],
                )
            except KeyError:
                # A pre-revision row is retained only so its neutral lane can
                # survive the dependent-profile miss and be rewritten.
                detail_row = ()
            base_row.extend(detail_row)
            rows.append(base_row)
        wire["md"] = rows


def _encode_dead_candidates(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    dead_candidates = sorted(
        entry["dead_candidates"],
        key=lambda candidate: (
            candidate["start_line"],
            candidate["end_line"],
            candidate["qualname"],
            candidate["local_name"],
            candidate["kind"],
        ),
    )
    if dead_candidates:
        encoded_dead_candidates: list[list[object]] = []
        for candidate in dead_candidates:
            encoded: list[object] = [
                candidate["qualname"],
                candidate["local_name"],
                candidate["start_line"],
                candidate["end_line"],
                candidate["kind"],
            ]
            suppressed_rules = candidate.get("suppressed_rules", [])
            normalized_rules = _normalized_optional_string_list(suppressed_rules)
            live_root_reason = candidate.get("live_root_reason", "")
            # Positional tail. The reason needs slot 5 occupied to stay
            # unambiguous, so an empty rules list is written when a row
            # carries a reason but no suppressions.
            if normalized_rules or live_root_reason:
                encoded.append(normalized_rules)
            if live_root_reason:
                encoded.append(live_root_reason)
            encoded_dead_candidates.append(encoded)
        wire["dc"] = encoded_dead_candidates


def _encode_name_lists(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    if entry["referenced_names"]:
        wire["rn"] = sorted(set(entry["referenced_names"]))
    if entry.get("referenced_qualnames"):
        wire["rq"] = sorted(set(entry["referenced_qualnames"]))
    if entry["import_names"]:
        wire["in"] = sorted(set(entry["import_names"]))
    if entry["class_names"]:
        wire["cn"] = sorted(set(entry["class_names"]))


def _encode_security_surfaces(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    security_surfaces = sorted(
        entry.get("security_surfaces", []),
        key=lambda item: (
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["category"],
            item["capability"],
            item["evidence_symbol"],
        ),
    )
    if security_surfaces:
        wire["sc"] = [
            [
                item["category"],
                item["capability"],
                item["module"],
                item["qualname"],
                item["start_line"],
                item["end_line"],
                item["location_scope"],
                item["classification_mode"],
                item["evidence_kind"],
                item["evidence_symbol"],
            ]
            for item in security_surfaces
        ]


def _encode_runtime_reachability(
    entry: CacheFactsDict,
    wire: dict[str, object],
) -> None:
    runtime_reachability = sorted(
        entry.get("runtime_reachability", []),
        key=lambda item: (
            item["start_line"],
            item["end_line"],
            item["target_qualname"],
            item["framework"],
            item["edge_kind"],
            item["evidence_symbol"],
        ),
    )
    if runtime_reachability:
        wire["rr"] = [
            [
                item["target_qualname"],
                item["start_line"],
                item["end_line"],
                item["target_kind"],
                item["framework"],
                item["edge_kind"],
                item["confidence"],
                item["evidence"],
                item["evidence_symbol"],
                item["source_qualname"],
            ]
            for item in runtime_reachability
        ]


def _encode_function_relationship_facts(
    entry: CacheFactsDict,
    wire: dict[str, object],
) -> None:
    facts_rows = entry.get("function_relationship_facts", [])
    if facts_rows:
        wire["fr"] = [
            [
                facts["source_qualname"],
                [
                    [
                        record["relation_kind"],
                        record["resolution_status"],
                        record["origin_lane"],
                        record["target_qualname"],
                        record["line"],
                        record["expression"],
                        record["resolution_rule"],
                    ]
                    for record in facts["relationships"]
                ],
            ]
            for facts in facts_rows
        ]


def _encode_optional_metrics_sections(
    entry: CacheFactsDict, wire: dict[str, object]
) -> None:
    typing_coverage = entry.get("typing_coverage")
    if typing_coverage is not None:
        wire["tc"] = [
            typing_coverage["module"],
            typing_coverage["callable_count"],
            typing_coverage["params_total"],
            typing_coverage["params_annotated"],
            typing_coverage["returns_total"],
            typing_coverage["returns_annotated"],
            typing_coverage["any_annotation_count"],
        ]
    docstring_coverage = entry.get("docstring_coverage")
    if docstring_coverage is not None:
        wire["dg"] = [
            docstring_coverage["module"],
            docstring_coverage["public_symbol_total"],
            docstring_coverage["public_symbol_documented"],
        ]
    api_surface = entry.get("api_surface")
    if api_surface is not None:
        wire["as"] = [
            api_surface["module"],
            sorted(set(api_surface.get("all_declared", []))),
            [
                [
                    symbol["qualname"],
                    symbol["kind"],
                    symbol["start_line"],
                    symbol["end_line"],
                    symbol.get("exported_via", "name"),
                    symbol.get("returns_hash", ""),
                    [
                        [
                            param["name"],
                            param["kind"],
                            1 if param["has_default"] else 0,
                            param.get("annotation_hash", ""),
                        ]
                        for param in symbol.get("params", [])
                    ],
                ]
                for symbol in api_surface["symbols"]
            ],
        ]


def _encode_structural_findings(entry: CacheFactsDict, wire: dict[str, object]) -> None:
    if "structural_findings" in entry:
        structural_findings = entry.get("structural_findings", [])
        wire["sf"] = [
            [
                group["finding_kind"],
                group["finding_key"],
                sorted(group["signature"].items()),
                [
                    [item["qualname"], item["start"], item["end"]]
                    for item in group["items"]
                ],
            ]
            for group in structural_findings
        ]


def _encode_fact_ref(fact: FactRef) -> list[str]:
    return [fact.kind, fact.ref]


def _encode_semantic_event(event: SemanticEvent) -> list[object]:
    return [
        event.event_id,
        event.kind,
        event.subject,
        [_encode_fact_ref(fact) for fact in event.inputs],
        _encode_fact_ref(event.output) if event.output is not None else None,
        list(event.guards),
        event.location[1],
        event.resolution,
    ]


def _encode_contract_summary(summary: FunctionContractSummary) -> list[object]:
    return [
        summary.function,
        [_encode_semantic_event(event) for event in summary.events],
        [list(flow) for flow in summary.param_flows],
        [_encode_fact_ref(fact) for fact in summary.returns],
        summary.unresolved_flow,
    ]


def _encode_semantic_facts(entry: CacheEntryV3, wire: dict[str, object]) -> None:
    facts = entry.module_neutral.semantic_facts
    wire["se"] = [
        _encode_semantic_event(event)
        for event in sorted(facts.events, key=lambda item: item.event_id)
    ]
    wire["fc"] = [
        _encode_contract_summary(summary)
        for summary in sorted(
            facts.function_contract_summaries,
            key=lambda item: item.function,
        )
    ]


def _neutral_facts(entry: CacheEntryV3) -> CacheFactsDict:
    neutral = entry.module_neutral
    return CacheFactsDict(
        source_stats=neutral.source_stats,
        units=[
            FunctionGroupItem(
                qualname=item.local_name,
                filepath="",
                start_line=item.start_line,
                end_line=item.end_line,
                loc=item.loc,
                stmt_count=item.stmt_count,
                fingerprint=item.fingerprint,
                loc_bucket=item.loc_bucket,
                cyclomatic_complexity=item.cyclomatic_complexity,
                nesting_depth=item.nesting_depth,
                risk=item.risk,
                raw_hash=item.raw_hash,
                entry_guard_count=item.entry_guard_count,
                entry_guard_terminal_profile=item.entry_guard_terminal_profile,
                entry_guard_has_side_effect_before=item.entry_guard_has_side_effect_before,
                terminal_kind=item.terminal_kind,
                try_finally_profile=item.try_finally_profile,
                side_effect_order_profile=item.side_effect_order_profile,
                statement_sequence=item.statement_sequence,
                renamed_fingerprint=item.renamed_fingerprint,
                unreachable_statements=item.unreachable_statements,
            )
            for item in neutral.units
        ],
        blocks=[
            BlockGroupItem(
                qualname=item.local_name,
                filepath="",
                start_line=item.start_line,
                end_line=item.end_line,
                size=item.size,
                block_hash=item.block_hash,
            )
            for item in neutral.blocks
        ],
        segments=[
            SegmentGroupItem(
                qualname=item.local_name,
                filepath="",
                start_line=item.start_line,
                end_line=item.end_line,
                size=item.size,
                segment_hash=item.segment_hash,
                segment_sig=item.segment_sig,
            )
            for item in neutral.segments
        ],
        class_metrics=[],
        module_deps=[],
        dead_candidates=[],
        referenced_names=[],
        referenced_qualnames=[],
        import_names=[],
        class_names=[],
        runtime_reachability=[],
        security_surfaces=[],
        function_relationship_facts=[],
    )


def _dependent_facts(entry: CacheEntryV3) -> CacheFactsDict:
    dependent = entry.module_dependent
    facts = CacheFactsDict(
        source_stats=entry.module_neutral.source_stats,
        units=[],
        blocks=[],
        segments=[],
        class_metrics=list(dependent.class_metrics),
        module_deps=list(dependent.module_deps),
        dead_candidates=list(dependent.dead_candidates),
        referenced_names=list(dependent.referenced_names),
        referenced_qualnames=list(dependent.referenced_qualnames),
        import_names=list(dependent.import_names),
        class_names=list(dependent.class_names),
        runtime_reachability=list(dependent.runtime_reachability),
        security_surfaces=list(dependent.security_surfaces),
        function_relationship_facts=list(dependent.function_relationship_facts),
    )
    if dependent.typing_coverage is not None:
        facts["typing_coverage"] = dependent.typing_coverage
    if dependent.docstring_coverage is not None:
        facts["docstring_coverage"] = dependent.docstring_coverage
    if dependent.api_surface is not None:
        facts["api_surface"] = dependent.api_surface
    if dependent.structural_findings is not None:
        facts["structural_findings"] = list(dependent.structural_findings)
    return facts


def _digest_row(digest: DigestObject) -> list[object]:
    return [digest.domain, digest.algorithm, digest.value]


def _encode_wire_file_entry(entry: CacheEntryV3) -> dict[str, object]:
    source_digest = entry.source_content_digest
    git_blob = entry.git_blob_id_at_write
    neutral_wire: dict[str, object] = {}
    dependent_wire: dict[str, object] = {}
    neutral_facts = _neutral_facts(entry)
    dependent_facts = _dependent_facts(entry)
    _encode_source_stats(neutral_facts, neutral_wire)
    _encode_units(neutral_facts, neutral_wire)
    _encode_blocks(neutral_facts, neutral_wire)
    _encode_segments(neutral_facts, neutral_wire)
    _encode_semantic_facts(entry, neutral_wire)
    _encode_class_metrics(dependent_facts, dependent_wire)
    _encode_module_deps(dependent_facts, dependent_wire)
    _encode_dead_candidates(dependent_facts, dependent_wire)
    _encode_name_lists(dependent_facts, dependent_wire)
    _encode_runtime_reachability(dependent_facts, dependent_wire)
    _encode_function_relationship_facts(dependent_facts, dependent_wire)
    _encode_security_surfaces(dependent_facts, dependent_wire)
    _encode_optional_metrics_sections(dependent_facts, dependent_wire)
    _encode_structural_findings(dependent_facts, dependent_wire)
    wire: dict[str, object] = {
        "cb": entry.cache_content_binding_version,
        "sd": [
            source_digest.domain,
            source_digest.algorithm,
            source_digest.value,
        ],
        "gb": (
            [git_blob.object_format, git_blob.object_id]
            if git_blob is not None
            else None
        ),
        "st": [entry.stat["mtime_ns"], entry.stat["size"]],
        "bc": _digest_row(entry.binding_context_digest),
        "np": _digest_row(entry.module_neutral_profile),
        "dp": _digest_row(entry.module_dependent_profile),
        "n": neutral_wire,
        "d": dependent_wire,
    }
    return wire


__all__ = ["_encode_wire_file_entry"]
