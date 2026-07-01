#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Standalone benchmark for MCP payload token budget estimation.

Requires the ``codeclone[token-bench]`` extra (``tiktoken``).

Usage::

    uv run python benchmarks/mcp_token_budget.py
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        from codeclone.budget.estimator import estimate_payload
    except ImportError:
        print(
            "ERROR: tiktoken not installed. "
            "Install with: uv pip install 'codeclone[token-bench]'",
            file=sys.stderr,
        )
        sys.exit(1)

    scenarios: dict[str, dict[str, object]] = {
        "analyze_repository_small": _analyze_repository_small(),
        "get_blast_radius_bounded": _blast_radius_bounded(),
        "get_blast_radius_large_truncated": _blast_radius_large(),
        "check_patch_contract_verify": _patch_contract_verify(),
        "create_review_receipt_markdown": _review_receipt(),
        "manage_change_intent_declare": _change_intent_declare(),
    }

    results: dict[str, dict[str, int]] = {}
    total_chars = 0
    total_tokens = 0

    for name, payload in scenarios.items():
        estimate = estimate_payload(payload)
        results[name] = {
            "chars": estimate.characters,
            "tokens": estimate.tokens,
        }
        total_chars += estimate.characters
        total_tokens += estimate.tokens

    results["full_workflow_all_calls"] = {
        "chars": total_chars,
        "tokens": total_tokens,
    }

    output = {
        "encoder": "o200k_base",
        "scenarios": results,
    }

    print(json.dumps(output, indent=2))


def _analyze_repository_small() -> dict[str, object]:
    return {
        "run_id": "abc12345",
        "focus": "repository",
        "version": "2.1.0a1",
        "schema": "2.12",
        "mode": "full",
        "baseline": {
            "loaded": True,
            "status": "ok",
            "trusted": True,
        },
        "inventory": {"files": 120, "lines": 45000, "functions": 800, "classes": 90},
        "health": {
            "score": 92,
            "grade": "A",
            "dimensions": {
                "clones": 100,
                "complexity": 75,
                "coupling": 80,
                "cohesion": 95,
                "dead_code": 100,
                "coverage": 85,
                "dependencies": 90,
            },
        },
        "findings": {
            "total": 3,
            "new": 1,
            "known": 2,
            "by_family": {"clones": 2, "dead_code": 1},
        },
        "warnings": [],
        "failures": [],
    }


def _blast_radius_bounded() -> dict[str, object]:
    return {
        "radius_level": "medium",
        "direct_dependents": [
            {
                "path": f"pkg/module_{i}.py",
                "reason": "imports target",
                "edge_type": "import",
            }
            for i in range(8)
        ],
        "clone_cohort_members": [
            {
                "path": f"pkg/clone_{i}.py",
                "finding_id": f"CCLONE00{i}",
                "clone_type": "Type-2",
            }
            for i in range(3)
        ],
        "do_not_touch": [
            {"path": ".codeclone/**", "reason": "generated state"},
            {"path": "codeclone.baseline.json", "reason": "baseline file"},
        ],
        "review_context": [
            {
                "path": f"pkg/context_{i}.py",
                "reason": "report-only signal",
                "category": "security_boundary",
            }
            for i in range(5)
        ],
        "structural_risk": {
            "hub_dependents": 8,
            "cohort_spread": 3,
        },
    }


def _blast_radius_large() -> dict[str, object]:
    base = _blast_radius_bounded()
    base["direct_dependents"] = [
        {
            "path": f"pkg/deep/sub/module_{i}.py",
            "reason": "transitive import chain via pkg.core",
            "edge_type": "import",
        }
        for i in range(50)
    ]
    base["review_context"] = [
        {
            "path": f"pkg/large_context_{i}.py",
            "reason": f"overloaded module candidate (score={0.7 + i * 0.01:.2f})",
            "category": "overloaded_module",
        }
        for i in range(30)
    ]
    return base


def _patch_contract_verify() -> dict[str, object]:
    return {
        "mode": "verify",
        "status": "accepted",
        "before": {"run_id": "before12", "health": 90},
        "after": {"run_id": "after123", "health": 90},
        "strictness": "ci",
        "structural_delta": {
            "regressions": [],
            "improvements": [
                {"id": "CCLONE001", "kind": "clone_group", "severity": "medium"}
            ],
            "health_delta": 0,
            "verdict": "stable",
        },
        "worsened": [],
        "scope_check": {
            "status": "clean",
            "declared_scope": ["pkg/a.py", "pkg/b.py"],
            "actual_changed_files": ["pkg/a.py"],
            "unexpected_files": [],
            "forbidden_touched": [],
        },
        "gate_preview": {"would_fail": False, "exit_code": 0, "reasons": []},
        "baseline_abuse": {"detected": False, "triggers": []},
        "contract_violations": [],
        "blocking_violations": [],
        "message": "Patch contract accepted.",
    }


def _review_receipt() -> dict[str, object]:
    return {
        "format": "markdown",
        "receipt": {
            "verdict": "clean",
            "provenance": {
                "digest": "a" * 64,
                "schema_version": "2.12",
                "baseline_trust": "ok",
                "run_id": "abc12345",
                "root": "/repo",
            },
            "scope": {
                "intent_id": "intent-abc-001",
                "declared_files": ["pkg/a.py", "pkg/b.py"],
                "changed_files": ["pkg/a.py"],
                "unexpected_files": [],
            },
            "blast_radius_summary": {
                "level": "low",
                "direct_dependents": 2,
                "clone_cohorts": 0,
                "do_not_touch": 3,
            },
            "reviewed_findings": [
                {
                    "finding_id": "CCLONE001",
                    "reviewed": True,
                    "note": "Accepted: intentional parallel implementation",
                }
            ],
            "patch_contract": {
                "status": "accepted",
                "violations": [],
            },
            "human_decision_points": [
                "Clone divergence in pkg/a.py:func_a acknowledged",
            ],
            "claims_not_made": [
                "Security Surfaces are boundary inventory, not vulnerability claims",
                "Report-only signals are not CI gates",
            ],
        },
    }


def _change_intent_declare() -> dict[str, object]:
    return {
        "intent_id": "intent-abc-001",
        "run_id": "abc12345",
        "status": "active",
        "scope": {
            "allowed_files": ["pkg/a.py", "pkg/b.py", "tests/test_a.py"],
            "allowed_related": ["pkg/utils.py"],
            "forbidden": [".cache/**", "codeclone.baseline.json"],
        },
        "intent": "Refactor module A and B to reduce coupling",
        "guards": [
            "scope_expansion_requires_explanation",
            "baseline_update_forbidden",
            "new_structural_regression_forbidden",
        ],
        "blast_radius_summary": {
            "radius_level": "medium",
            "direct_dependents_count": 5,
            "clone_cohort_members_count": 1,
            "do_not_touch_count": 3,
        },
        "concurrent_intents": [],
        "workspace_registered": True,
        "ttl_seconds": 3600,
    }


if __name__ == "__main__":
    main()
