# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from codeclone.config.observability import ObservabilityConfig
from codeclone.observability import query as query_mod
from codeclone.observability.models import OperationRecord, ProfileSample, SpanRecord
from codeclone.observability.query import query_platform_observability
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import write_operation


def _rows(value: object) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", value)


def _texts(value: object) -> list[str]:
    return cast("list[str]", value)


def _seed(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="F",
                correlation_id="A",
                surface="mcp",
                name="mcp.finish_controlled_change",
                started_at_utc="2026-06-12T00:00:00Z",
                duration_ms=975.0,
                status="ok",
                response_bytes=8800,
                response_tokens=2200,
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="S",
                correlation_id="A",
                surface="memory",
                name="memory.projection.spawn",
                parent_operation_id="F",
                started_at_utc="2026-06-12T00:00:00Z",
                duration_ms=3.0,
                status="ok",
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="J",
                correlation_id="A",
                surface="memory",
                name="memory.projection.job",
                parent_operation_id="S",
                started_at_utc="2026-06-12T00:00:01Z",
                duration_ms=2170.0,
                status="ok",
                spans=(
                    SpanRecord(
                        span_id="r",
                        operation_id="J",
                        name="memory.semantic.reindex",
                        started_at_utc="2026-06-12T00:00:01Z",
                        duration_ms=2120.0,
                        status="ok",
                        counters={"db_queries": 1370, "embedded": 0},
                        profile=ProfileSample(rss_delta_mb=440.0),
                    ),
                    SpanRecord(
                        span_id="d",
                        operation_id="J",
                        name="memory.experience.distill",
                        started_at_utc="2026-06-12T00:00:03Z",
                        duration_ms=33.0,
                        status="ok",
                        counters={
                            "db_queries": 1892,
                            "db_writes": 773,
                            "experiences_distilled": 47,
                        },
                    ),
                ),
            ),
        )
        write_operation(
            conn,
            OperationRecord(
                operation_id="G",
                correlation_id="B",
                surface="mcp",
                name="mcp.get_relevant_memory",
                started_at_utc="2026-06-12T00:00:05Z",
                duration_ms=277.0,
                status="ok",
                response_bytes=18900,
                response_tokens=8900,
                request_tokens=356,
            ),
        )
    finally:
        conn.close()


def test_summary_returns_envelope_diagnostics_and_routing(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(root=tmp_path, section="summary")
    assert out["surface"] == "platform_observability"
    assert out["user_facing"] is False
    assert out["operations"] == 4
    assert out["costly_noops"] == 1
    kinds = {d["kind"] for d in _rows(out["top_diagnostics"])}
    assert {"memory", "db", "context"} <= kinds
    routed = {r["section"] for r in _rows(out["recommended_next_sections"])}
    assert {"db_cost", "agent_context", "costly_noops"} <= routed


def test_summary_does_not_embed_raw_trace(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(root=tmp_path, section="summary")
    for forbidden in (
        "operation_tree",
        "spans",
        "rows",
        "trace",
        "correlated_operations",
    ):
        assert forbidden not in out


def test_full_downgrades_to_normal_with_warning(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(
        root=tmp_path, section="db_cost", detail_level="full"
    )
    assert out["detail_level"] == "normal"
    assert out["requested_detail_level"] == "full"
    assert any("downgraded to normal" in w for w in _texts(out["warnings"]))


def test_detail_selectors_ignored_and_echoed(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(
        root=tmp_path, section="db_cost", operation_id="F", span_id="r"
    )
    assert out["ignored_parameters"] == ["operation_id", "span_id"]


def test_absent_store_is_inert_not_error(tmp_path: Path) -> None:
    out = query_platform_observability(root=tmp_path, section="summary")
    assert out["status"] in {"disabled", "no_store"}
    assert out["rows"] == []
    assert out["user_facing"] is False


def test_disabled_vs_no_store_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        query_mod, "resolve_observability_config", lambda: ObservabilityConfig(True)
    )
    assert (
        query_platform_observability(root=tmp_path, section="db_cost")["status"]
        == "no_store"
    )
    monkeypatch.setattr(
        query_mod, "resolve_observability_config", lambda: ObservabilityConfig(False)
    )
    assert (
        query_platform_observability(root=tmp_path, section="db_cost")["status"]
        == "disabled"
    )


def test_limit_is_clamped_and_floored(tmp_path: Path) -> None:
    _seed(tmp_path)
    big = query_platform_observability(
        root=tmp_path, section="db_cost", detail_level="normal", limit=10000
    )
    assert any("clamped to 50" in w for w in _texts(big["warnings"]))
    bad = query_platform_observability(root=tmp_path, section="db_cost", limit=0)
    assert any("invalid" in w for w in _texts(bad["warnings"]))


def test_aggregate_section_is_projection_without_raw_trace(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(
        root=tmp_path, section="db_cost", detail_level="normal"
    )
    forbidden = {"operation_tree", "spans", "trace", "fingerprint", "sql", "payload"}
    assert not (forbidden & set(out))
    for row in _rows(out["rows"]):
        assert not (forbidden & set(row))
        assert isinstance(row["queries"], int)
    distill = next(
        r for r in _rows(out["rows"]) if r["span"] == "memory.experience.distill"
    )
    assert distill["queries_per_call"] == 1892
    assert distill["verdict"] == "query_chatty"


def test_unknown_section_returns_validation_envelope(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(root=tmp_path, section="bogus")
    assert out["status"] == "invalid_section"
    assert out["section"] == "bogus"
    assert "summary" in _texts(out["available_sections"])
    assert out["rows"] == []


def test_correlated_chains_flattens_root_and_children(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(root=tmp_path, section="correlated_chains")
    chain = next(
        r for r in _rows(out["rows"]) if r["root"] == "mcp.finish_controlled_change"
    )
    assert "memory.projection.job" in _texts(chain["children"])
    assert "memory.semantic.reindex" in _texts(chain["children"])
    assert chain["peak_rss_delta_mb"] == 440.0


def test_agent_context_ranks_token_consumers(tmp_path: Path) -> None:
    _seed(tmp_path)
    out = query_platform_observability(
        root=tmp_path, section="agent_context", detail_level="normal"
    )
    assert out["total_response_tokens"] == 11100
    top = _rows(out["rows"])[0]
    assert top["tool"] == "mcp.get_relevant_memory"
    assert top["verdict"] == "context_heavy"
