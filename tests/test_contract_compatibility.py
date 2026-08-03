# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from codeclone.contracts.compatibility import (
    LEGACY_COMPATIBILITY_OWNERS,
    CompatibilityPolicy,
    check_contract_compatibility,
)
from codeclone.models import CompatibilityVerdict, ObservabilityConfig
from codeclone.observability import bootstrap, operation, shutdown, span


@pytest.mark.parametrize(
    ("policy", "required", "actual", "status", "compatible"),
    [
        (CompatibilityPolicy("exact"), "2", "2", "compatible", True),
        (CompatibilityPolicy("exact"), "2", "1", "incompatible", False),
        (
            CompatibilityPolicy("supported_versions", frozenset({"2.0", "2.1"})),
            "2.1",
            "2.0",
            "compatible",
            True,
        ),
        (
            CompatibilityPolicy("supported_versions", frozenset({"2.0", "2.1"})),
            "2.1",
            "3.0",
            "incompatible",
            False,
        ),
        (
            CompatibilityPolicy("ordered_migration", frozenset({"1.6", "1.7"})),
            "1.8",
            "1.7",
            "migration_required",
            False,
        ),
        (
            CompatibilityPolicy("ordered_migration", frozenset({"1.6", "1.7"})),
            "1.8",
            "1.8",
            "compatible",
            True,
        ),
        (
            CompatibilityPolicy("ordered_migration", frozenset({"1.6", "1.7"})),
            "1.8",
            "1.5",
            "incompatible",
            False,
        ),
    ],
)
def test_contract_policy_table(
    policy: CompatibilityPolicy,
    required: str,
    actual: str,
    status: str,
    compatible: bool,
) -> None:
    verdict = check_contract_compatibility(
        {"contract": required},
        {"contract": actual},
        {"contract": policy},
    )

    assert verdict.status == status
    assert verdict.compatible is compatible
    assert verdict.per_contract[0].status == status


def test_unknown_required_contract_fails_closed() -> None:
    verdict = check_contract_compatibility(
        {"future": "1"},
        {"future": "1"},
        {},
    )

    assert verdict.status == "unknown_contract"
    assert verdict.compatible is False
    assert verdict.per_contract[0].contract == "future"


def test_contract_verdict_order_is_insertion_independent() -> None:
    policies = {
        "a": CompatibilityPolicy("exact"),
        "b": CompatibilityPolicy("supported_versions", frozenset({"1"})),
    }
    forward = check_contract_compatibility(
        {"a": "2", "b": "1"},
        {"a": "2", "b": "1"},
        policies,
    )
    reverse = check_contract_compatibility(
        {"b": "1", "a": "2"},
        {"b": "1", "a": "2"},
        {"b": policies["b"], "a": policies["a"]},
    )

    assert forward == reverse
    assert tuple(item.contract for item in forward.per_contract) == ("a", "b")


def test_missing_actual_contract_is_incompatible() -> None:
    verdict = check_contract_compatibility(
        {"fingerprint": "2"},
        {},
        {"fingerprint": CompatibilityPolicy("exact")},
    )

    assert verdict.status == "incompatible"
    assert verdict.per_contract[0].actual is None


def _observed_check() -> CompatibilityVerdict:
    with span(name="compatibility.check") as check_span:
        verdict = check_contract_compatibility(
            {"future": "1"},
            {"future": "1"},
            {},
        )
        check_span.set_counter("contract_count", len(verdict.per_contract))
        check_span.add_counter(f"compatibility_status_{verdict.status}")
        return verdict


def test_observer_is_passive_and_consumer_owns_one_span(tmp_path: Path) -> None:
    expected = _observed_check()
    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="test.compatibility", surface="test"):
            observed = _observed_check()
    finally:
        shutdown()

    assert observed == expected


def test_legacy_compatibility_inventory_names_each_consuming_cutover() -> None:
    assert LEGACY_COMPATIBILITY_OWNERS == (
        ("codeclone.cache.store.Cache._load_and_validate", "39J"),
        (
            "codeclone.baseline.clone_baseline.CloneBaseline.verify_compatibility",
            "39M",
        ),
        (
            "codeclone.baseline.metrics_baseline.MetricsBaseline.verify_compatibility",
            "39O",
        ),
        (
            "codeclone.memory.schema.ensure_schema/validate_schema_readonly",
            "39Q",
        ),
    )


def test_compatibility_owner_has_no_persistence_or_surface_imports() -> None:
    source = Path("codeclone/contracts/compatibility.py").read_text("utf-8")
    tree = ast.parse(source)
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        forbidden in module
        for module in imported
        for forbidden in ("baseline", "cache", "memory", "surfaces")
    )
    assert "observability" not in source
    assert "span(" not in source


def test_contract_and_config_authorities_are_not_redeclared() -> None:
    definitions: dict[str, list[str]] = {
        "CompatibilityPolicy": [],
        "CompatibilityVerdict": [],
        "ContractVerdict": [],
        "check_contract_compatibility": [],
        "normalize_source_roots": [],
    }
    canonical_messages: dict[str, list[str]] = {
        "baseline_scope_id must be a canonical UUID": [],
        "source_roots must contain repo-relative POSIX paths": [],
    }
    for path in sorted(Path("codeclone").rglob("*.py")):
        source = path.read_text("utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.ClassDef, ast.FunctionDef))
                and node.name in definitions
            ):
                definitions[node.name].append(path.as_posix())
        for message in canonical_messages:
            if message in source:
                canonical_messages[message].append(path.as_posix())

    assert definitions == {
        "CompatibilityPolicy": ["codeclone/models.py"],
        "CompatibilityVerdict": ["codeclone/models.py"],
        "ContractVerdict": ["codeclone/models.py"],
        "check_contract_compatibility": ["codeclone/contracts/compatibility.py"],
        "normalize_source_roots": ["codeclone/config/resolver.py"],
    }
    assert canonical_messages == {
        "baseline_scope_id must be a canonical UUID": ["codeclone/models.py"],
        "source_roots must contain repo-relative POSIX paths": [
            "codeclone/config/resolver.py"
        ],
    }


def test_every_public_contract_constant_is_exported() -> None:
    """``__all__`` is the contract surface of ``codeclone.contracts``.

    A public constant missing from it is a version or digest domain that
    consumers cannot import by contract, only by reaching into the module.
    """
    import codeclone.contracts as contracts_pkg

    tree = ast.parse(Path(contracts_pkg.__file__).read_text(encoding="utf-8"))

    defined: set[str] = set()
    exported: set[str] = set()
    for node in tree.body:
        targets: list[str] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets = [
                target.id for target in node.targets if isinstance(target, ast.Name)
            ]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
            value = node.value
        if targets == ["__all__"] and isinstance(value, (ast.List, ast.Tuple)):
            exported = {
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
        defined.update(
            name for name in targets if name.isupper() and not name.startswith("_")
        )

    unexported = sorted(defined - exported)
    assert unexported == [], f"public contract constants not in __all__: {unexported}"

    # The other direction: __all__ must not promise a symbol that is not there.
    dangling = sorted(name for name in exported if not hasattr(contracts_pkg, name))
    assert dangling == [], f"__all__ names undefined symbols: {dangling}"
