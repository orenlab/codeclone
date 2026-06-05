# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import builtins
from typing import Any
from unittest.mock import patch

import pytest

from codeclone.budget.estimator import estimate_payload


def test_estimate_payload_defaults_to_chars_approx() -> None:
    """Default estimation is cheap and does not import tiktoken."""
    payload = {"key": "value", "number": 42}
    result = estimate_payload(payload)
    assert result.method == "chars_approx"
    assert result.encoding == "chars_approx"
    assert result.tokens == -(-result.characters // 4)


def test_estimate_payload_default_does_not_import_tiktoken() -> None:
    """Long-lived MCP paths must not import tiktoken by default."""
    real_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "tiktoken":
            raise AssertionError("default estimator must not import tiktoken")
        return real_import(name, globals_, locals_, fromlist, level)

    with patch.object(builtins, "__import__", guarded_import):
        result = estimate_payload({"key": "value"})

    assert result.method == "chars_approx"


def test_estimate_payload_with_tiktoken_opt_in() -> None:
    """Exact BPE estimation when explicitly requested and available."""
    payload = {
        "status": "accepted",
        "health": 90,
        "findings": {"total": 5, "new": 2},
        "message": "Patch contract accepted.",
    }
    result = estimate_payload(payload, estimator="tiktoken")
    assert result.method == "tiktoken"
    assert result.encoding == "o200k_base"
    assert result.tokens > 0
    assert result.characters > 0
    assert result.tokens < result.characters


def test_estimate_payload_without_tiktoken() -> None:
    """Explicit tiktoken mode falls back when tiktoken import fails."""
    payload = {"key": "value", "number": 42}
    with patch.dict("sys.modules", {"tiktoken": None}):
        result = estimate_payload(payload, estimator="tiktoken")
    assert result.method == "chars_approx"
    assert result.encoding == "chars_approx"
    assert result.tokens == -(-result.characters // 4)


def test_estimate_payload_canonical_json_determinism() -> None:
    """Same content in different insertion order -> identical estimates."""
    payload_a = {"z_last": 1, "a_first": 2, "m_middle": 3}
    payload_b = {"a_first": 2, "m_middle": 3, "z_last": 1}
    result_a = estimate_payload(payload_a)
    result_b = estimate_payload(payload_b)
    assert result_a.tokens == result_b.tokens
    assert result_a.characters == result_b.characters


def test_estimate_empty_payload() -> None:
    """Empty dict produces minimal token count."""
    result = estimate_payload({})
    assert result.characters == 2  # "{}"
    assert result.tokens >= 1


def test_estimate_payload_custom_encoding() -> None:
    """Custom encoding parameter is passed through."""
    result = estimate_payload(
        {"key": "value"},
        encoding="cl100k_base",
        estimator="tiktoken",
    )
    assert result.encoding == "cl100k_base"
    assert result.method == "tiktoken"
    assert result.tokens > 0


def test_token_estimate_is_frozen() -> None:
    """TokenEstimate is immutable."""
    result = estimate_payload({"x": 1})
    with pytest.raises(AttributeError):
        result.tokens = 999  # type: ignore[misc]


def test_estimate_payload_with_nested_structures() -> None:
    """Complex nested payloads produce reasonable estimates."""
    payload = {
        "scope": {
            "allowed_files": [f"pkg/module_{i}.py" for i in range(20)],
            "forbidden": [".cache/**", "*.baseline.json"],
        },
        "blast_radius": {
            "level": "high",
            "dependents": [
                {"path": f"dep_{i}.py", "reason": "import"} for i in range(5)
            ],
        },
        "gate_preview": {"would_fail": False, "reasons": []},
    }
    result = estimate_payload(payload)
    assert result.tokens > 50
    assert result.characters > 200


def test_estimate_payload_with_unicode() -> None:
    """Unicode content is handled correctly (ensure_ascii=False)."""
    payload = {"message": "Результат: чистый", "emoji": "✅"}
    result = estimate_payload(payload)
    assert result.tokens > 0
    assert result.characters > 0


def test_estimate_payload_rejects_unknown_estimator() -> None:
    with pytest.raises(ValueError, match="token estimator"):
        estimate_payload({"x": 1}, estimator="bad")  # type: ignore[arg-type]
