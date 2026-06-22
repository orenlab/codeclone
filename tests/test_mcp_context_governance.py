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
    attach_passive_context_governance,
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
    assert {
        "response": "durable_receipt_lookup" in blocked["response_budget"],
        "nested": "implementation_context_artifact_pages" in blocked["nested_budget"],
        "omission": "exact_continuation_for_omitted_tails" in blocked["omission"],
    } == {
        "response": True,
        "nested": True,
        "omission": True,
    }
    capabilities = cast("dict[str, object]", envelope["capabilities"])
    assert capabilities["typed_receipt_alias"] is True
    assert isinstance(envelope["estimated"], int)
    assert envelope["estimated"] == estimate_response_context_units(payload)


def test_context_governance_declares_drill_down_reachability() -> None:
    payload = attach_passive_context_governance({"status": "accepted"})
    envelope = cast("dict[str, object]", payload["context_governance"])
    drill_down = cast("dict[str, dict[str, object]]", envelope["drill_down"])

    assert {
        "memory_record_lookup": drill_down["memory_record"]["object_lookup"],
        "memory_record_route": drill_down["memory_record"]["route"],
        "memory_tail_continuation": drill_down["memory_record"]["continuation"],
        "trajectory_lookup": drill_down["trajectory"]["object_lookup"],
        "receipt_current_path": drill_down["structured_receipt"][
            "current_complete_path"
        ],
        "receipt_lookup": drill_down["structured_receipt"]["object_lookup"],
        "blast_route": drill_down["blast_artifact"]["current_route_is_recomputation"],
        "experience_lookup": drill_down["experience"]["object_lookup"],
    } == {
        "memory_record_lookup": "available",
        "memory_record_route": "query_engineering_memory(mode='get', record_id=...)",
        "memory_tail_continuation": "blocked",
        "trajectory_lookup": "available",
        "receipt_current_path": "receipt.receipt",
        "receipt_lookup": "blocked",
        "blast_route": "get_blast_radius",
        "experience_lookup": "blocked",
    }


def test_context_governance_has_no_tokenizer_dependency() -> None:
    source = inspect.getsource(governance_mod)

    assert "tiktoken" not in source
    assert "tokenizer" not in source.lower()
