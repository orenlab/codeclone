# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Stores whose runs are registered by execution, spelled once for the
registry and retention suites.

Every store lives under the test's own ``tmp_path``; the clock the registry
and the sweep read (``canonical.store._lease_now``) is the one the tests
move, so an age is set, never waited for.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

import pytest

from codeclone.canonical import CanonicalModel
from codeclone.canonical import store as store_module
from codeclone.canonical.store import (
    ExecutionRecord,
    PublishReceipt,
    RegisteredExecution,
    RunStore,
    finalize_execution,
)
from tests.test_canonical_roundtrip import fixture_model

NAMESPACE = "registry-ns"
TARGET = "registry-target"
ROOT = "/checkout/registry"
CONTRACT = "test-overlay:1"


def report_of(label: str) -> str:
    """A report identity of its own per label: 64 lowercase hex."""
    return hashlib.sha256(f"report:{label}".encode()).hexdigest()


def model_for(label: str) -> CanonicalModel:
    """A run of its own: the fixture's objects plus one per label."""
    model = fixture_model()
    coupled = set(model.coupled_sets)
    coupled.add(frozenset({label}))
    return replace(model, coupled_sets=frozenset(coupled))


class Clock:
    """The store's lease clock, moved by the test."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, start: int) -> None:
        self.now = start
        monkeypatch.setattr(store_module, "_lease_now", lambda: self.now)

    def advance(self, seconds: int) -> None:
        self.now += seconds


def publish(
    store: RunStore,
    label: str,
    *,
    target: str = TARGET,
    lease: tuple[str, int] | None = None,
) -> PublishReceipt:
    """Publish ``label``'s run, advancing ``target``'s head."""
    head = store.head(namespace=NAMESPACE, target=target)
    return store.write_full_run(
        model_for(label),
        namespace=NAMESPACE,
        target=target,
        expected_generation=0 if head is None else head.generation,
        in_flight_lease=lease,
    )


@dataclass(frozen=True, slots=True)
class Registered:
    receipt: PublishReceipt
    registered: RegisteredExecution


def record_for(
    receipt: PublishReceipt,
    *,
    execution: str,
    report: str,
    root: str = ROOT,
    overlay: bytes = b"overlay",
) -> ExecutionRecord:
    return ExecutionRecord(
        execution_event_id=execution,
        root=root,
        report_run_identity=report,
        store_run_id=receipt.run_id,
        record_contract=CONTRACT,
        overlay=overlay,
    )


def register(
    store: RunStore,
    label: str,
    *,
    execution: str | None = None,
    report: str | None = None,
    root: str = ROOT,
    target: str = TARGET,
) -> Registered:
    """Publish ``label``'s run under a publisher lease and finalize one
    execution of it, the way a publishing surface does."""
    lease_id = f"publication:test:{label}:{execution or label}"
    receipt = publish(store, label, target=target, lease=(lease_id, 3600))
    registered = finalize_execution(
        store,
        record_for(
            receipt,
            execution=execution or f"exec-{label}",
            report=report or report_of(label),
            root=root,
        ),
        expected_scope_digest=receipt.analysis_scope_digest,
        publisher_lease=lease_id,
    )
    return Registered(receipt=receipt, registered=registered)


__all__ = [
    "CONTRACT",
    "NAMESPACE",
    "ROOT",
    "TARGET",
    "Clock",
    "Registered",
    "model_for",
    "publish",
    "record_for",
    "register",
    "report_of",
]
