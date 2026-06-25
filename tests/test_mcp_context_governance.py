# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
import re
from typing import cast

import orjson

import codeclone.surfaces.mcp._context_governance as governance_mod
from codeclone.surfaces.mcp._context_governance import (
    CONTEXT_GOVERNANCE_CONTRACT_VERSION,
    CONTEXT_GOVERNANCE_DIGEST_VERSION,
    CONTEXT_GOVERNANCE_ESTIMATOR,
    DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
    FINISH_RESPONSE_PROJECTION_KIND,
    START_RESPONSE_PROJECTION_KIND,
    attach_finish_context_governance,
    attach_implementation_context_governance,
    attach_memory_retrieval_context_governance,
    attach_passive_context_governance,
    attach_start_context_governance,
    context_governance_digest,
    estimate_response_context_units,
)


def test_context_governance_estimator_is_key_order_stable() -> None:
    left = {"b": 2, "a": {"z": ["тест", "alpha"]}}
    right = {"a": {"z": ["тест", "alpha"]}, "b": 2}

    assert estimate_response_context_units(left) == estimate_response_context_units(
        right
    )


def test_context_governance_estimate_normalizes_own_estimated_field() -> None:
    payload = attach_passive_context_governance({"status": "accepted"})
    envelope = cast("dict[str, object]", payload["context_governance"])
    with_large_estimate = {
        **payload,
        "context_governance": {
            **envelope,
            "estimated": 999_999,
        },
    }

    assert estimate_response_context_units(payload) == estimate_response_context_units(
        with_large_estimate
    )


def test_context_governance_units_use_utf8_bytes_div_four() -> None:
    payload = {"message": "Привет", "path": "docs/пример.md"}
    expected = (len(orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)) + 3) // 4

    assert estimate_response_context_units(payload) == expected


def test_context_governance_digest_shape_and_sensitivity() -> None:
    digest = context_governance_digest("response_projection_v1", {"a": 1})

    assert digest["kind"] == "response_projection_v1"
    assert digest["algorithm"] == "sha256"
    assert digest["digest_version"] == CONTEXT_GOVERNANCE_DIGEST_VERSION
    assert re.fullmatch(r"[0-9a-f]{64}", digest["value"])
    assert digest != context_governance_digest("response_projection_v1", {"a": 2})


def test_passive_context_governance_envelope_is_observe_only() -> None:
    payload = attach_passive_context_governance({"status": "accepted"})
    envelope = cast("dict[str, object]", payload["context_governance"])

    assert {
        "contract_version": envelope["contract_version"],
        "estimator": envelope["estimator"],
        "limit": envelope["limit"],
        "mode": envelope["mode"],
        "truncated": envelope["truncated"],
        "mandatory_overflow": envelope["mandatory_overflow"],
    } == {
        "contract_version": CONTEXT_GOVERNANCE_CONTRACT_VERSION,
        "estimator": CONTEXT_GOVERNANCE_ESTIMATOR,
        "limit": DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
        "mode": "observe",
        "truncated": False,
        "mandatory_overflow": False,
    }
    assert envelope["enforcement"] == {
        "response_budget": False,
        "nested_budget": False,
        "omission": False,
    }
    blocked = cast("dict[str, list[str]]", envelope["enforcement_blocked"])
    assert blocked == {
        "response_budget": [],
        "nested_budget": [],
        "omission": [],
    }
    # Exact drill-down and continuation routes exist; enforcement still stays
    # observe-only until a packing policy actually omits evidence.
    assert "receipt_retrieval_unavailable" not in blocked["response_budget"]
    assert "durable_receipt_lookup" not in blocked["response_budget"]
    assert "post_clear_receipt_lookup" not in blocked["omission"]
    assert "durable_patch_trail_lookup" not in blocked["response_budget"]
    assert "immutable_blast_artifact" not in blocked["response_budget"]
    assert "memory_tail_continuation" not in blocked["nested_budget"]
    assert "implementation_context_artifact_pages" not in blocked["nested_budget"]
    capabilities = cast("dict[str, object]", envelope["capabilities"])
    assert capabilities["typed_receipt_alias"] is True
    assert capabilities["durable_receipt_lookup"] is True
    assert capabilities["durable_patch_trail_lookup"] is True
    assert capabilities["immutable_blast_artifact"] is True
    assert capabilities["memory_tail_continuation"] is True
    assert capabilities["implementation_context_artifact_pages"] is True
    assert capabilities["omitted_evidence_continuation"] is True
    assert isinstance(envelope["estimated"], int)
    assert envelope["estimated"] == estimate_response_context_units(payload)


def test_finish_context_governance_marks_whole_response_projection() -> None:
    payload = attach_finish_context_governance(
        {"intent_id": "intent-1", "status": "accepted"}
    )
    envelope = cast("dict[str, object]", payload["context_governance"])
    response = cast("dict[str, object]", envelope["response"])
    digest = cast("dict[str, object]", response["projection_digest"])
    blocked = cast("dict[str, list[str]]", envelope["enforcement_blocked"])

    assert {
        "tool": response["tool"],
        "budget_scope": response["budget_scope"],
        "policy": response["evidence_policy"],
        "receipt_content": response["receipt_content"],
        "digest_kind": digest["kind"],
        "receipt_retrieval_blocked": "receipt_retrieval_unavailable"
        in blocked["response_budget"],
    } == {
        "tool": "finish_controlled_change",
        "budget_scope": "whole_response",
        "policy": "observe_only_no_omission",
        "receipt_content": "markdown_inlined_typed_via_lookup",
        "digest_kind": FINISH_RESPONSE_PROJECTION_KIND,
        "receipt_retrieval_blocked": False,
    }


def test_start_context_governance_marks_whole_response_projection() -> None:
    payload = attach_start_context_governance(
        {"intent_id": "intent-1", "status": "active"}
    )
    envelope = cast("dict[str, object]", payload["context_governance"])
    response = cast("dict[str, object]", envelope["response"])
    digest = cast("dict[str, object]", response["projection_digest"])

    assert {
        "tool": response["tool"],
        "budget_scope": response["budget_scope"],
        "policy": response["evidence_policy"],
        "blast_radius_content": response["blast_radius_content"],
        "digest_kind": digest["kind"],
        "mode": envelope["mode"],
    } == {
        "tool": "start_controlled_change",
        "budget_scope": "whole_response",
        "policy": "observe_only_no_omission",
        "blast_radius_content": "summary_with_immutable_artifact_lookup",
        "digest_kind": START_RESPONSE_PROJECTION_KIND,
        "mode": "observe",
    }


def test_memory_retrieval_context_governance_enforces_compact_budget() -> None:
    payload = attach_memory_retrieval_context_governance(
        {"records": [], "trajectories": [], "experiences": []},
        detail_level="compact",
        max_records=20,
        evidence_omitted={
            "records": {
                "evaluation": "complete",
                "total": 3,
                "shown": 1,
                "omitted": 2,
                "reason": "response_budget",
            }
        },
    )
    envelope = cast("dict[str, object]", payload["context_governance"])
    response = cast("dict[str, object]", envelope["response"])
    omitted = cast("dict[str, object]", envelope["omitted"])

    assert {
        "mode": envelope["mode"],
        "response_budget": cast("dict[str, bool]", envelope["enforcement"])[
            "response_budget"
        ],
        "omission": cast("dict[str, bool]", envelope["enforcement"])["omission"],
        "policy": response["evidence_policy"],
        "tool": response["tool"],
        "record_reason": cast("dict[str, object]", omitted["records"])["reason"],
    } == {
        "mode": "partial_enforce",
        "response_budget": True,
        "omission": True,
        "policy": "response_budget_with_exact_continuation",
        "tool": "get_relevant_memory",
        "record_reason": "response_budget",
    }


def test_implementation_context_governance_enforces_compact_budget() -> None:
    payload = attach_implementation_context_governance(
        {"status": "ok", "analysis": {"context_projection_digest": "a" * 64}},
        detail_level="compact",
        budget=50,
        evidence_omitted={
            "structural_context.public_surface": {
                "evaluation": "complete",
                "total": 4,
                "shown": 1,
                "omitted": 3,
                "reason": "response_budget",
            }
        },
    )
    envelope = cast("dict[str, object]", payload["context_governance"])
    response = cast("dict[str, object]", envelope["response"])
    omitted = cast("dict[str, object]", envelope["omitted"])

    assert {
        "mode": envelope["mode"],
        "response_budget": cast("dict[str, bool]", envelope["enforcement"])[
            "response_budget"
        ],
        "nested_budget": cast("dict[str, bool]", envelope["enforcement"])[
            "nested_budget"
        ],
        "omission": cast("dict[str, bool]", envelope["enforcement"])["omission"],
        "policy": response["evidence_policy"],
        "tool": response["tool"],
        "reason": cast(
            "dict[str, object]",
            omitted["structural_context.public_surface"],
        )["reason"],
    } == {
        "mode": "partial_enforce",
        "response_budget": True,
        "nested_budget": True,
        "omission": True,
        "policy": "response_budget_with_exact_facet_pages",
        "tool": "get_implementation_context",
        "reason": "response_budget",
    }


def test_context_governance_declares_drill_down_reachability() -> None:
    payload = attach_passive_context_governance({"status": "accepted"})
    envelope = cast("dict[str, object]", payload["context_governance"])
    drill_down = cast("dict[str, dict[str, object]]", envelope["drill_down"])

    assert {
        "memory_record_lookup": drill_down["memory_record"]["object_lookup"],
        "memory_record_route": drill_down["memory_record"]["route"],
        "memory_tail_continuation": drill_down["memory_record"]["continuation"],
        "memory_tail_route": drill_down["memory_record"]["continuation_route"],
        "trajectory_lookup": drill_down["trajectory"]["object_lookup"],
        "trajectory_tail_continuation": drill_down["trajectory"]["continuation"],
        "receipt_current_path": drill_down["structured_receipt"][
            "current_complete_path"
        ],
        "receipt_lookup": drill_down["structured_receipt"]["object_lookup"],
        "patch_trail_lookup": drill_down["patch_trail"]["object_lookup"],
        "patch_trail_route": drill_down["patch_trail"]["route"],
        "blast_lookup": drill_down["blast_artifact"]["object_lookup"],
        "blast_route": drill_down["blast_artifact"]["route"],
        "experience_lookup": drill_down["experience"]["object_lookup"],
        "experience_route": drill_down["experience"]["route"],
        "experience_tail_continuation": drill_down["experience"]["continuation"],
        "context_facet_lookup": drill_down["implementation_context_facet"][
            "object_lookup"
        ],
        "context_facet_route": drill_down["implementation_context_facet"]["route"],
        "context_facet_continuation": drill_down["implementation_context_facet"][
            "continuation"
        ],
    } == {
        "memory_record_lookup": "available",
        "memory_record_route": "query_engineering_memory(mode='get', record_id=...)",
        "memory_tail_continuation": "available",
        "memory_tail_route": "get_memory_projection_page(cursor=...)",
        "trajectory_lookup": "available",
        "trajectory_tail_continuation": "available",
        "receipt_current_path": "receipt.receipt",
        "receipt_lookup": "available",
        "patch_trail_lookup": "available",
        "patch_trail_route": "get_patch_trail(run_id=..., patch_trail_digest=...)",
        "blast_lookup": "available",
        "blast_route": "get_blast_artifact(run_id=..., blast_artifact_id=...)",
        "experience_lookup": "available",
        "experience_route": (
            "query_engineering_memory(mode='experience_get', record_id=...)"
        ),
        "experience_tail_continuation": "available",
        "context_facet_lookup": "available",
        "context_facet_route": (
            "get_implementation_context_page(context_projection_digest=..., facet=...)"
        ),
        "context_facet_continuation": "available",
    }


def test_context_governance_has_no_tokenizer_dependency() -> None:
    source = inspect.getsource(governance_mod)

    assert "tiktoken" not in source
    assert "tokenizer" not in source.lower()
