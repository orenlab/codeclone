# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The refusals frozen model types owe their callers.

Every row below is a contract a ``__post_init__`` enforces, and each is
asserted from both sides: the value the type must refuse, and the smallest
neighbouring value it must accept. One side alone is not a pin — a guard
deleted passes the accept half, and a guard widened to reject everything
passes the refuse half. Only the pair distinguishes them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.models import (
    RUN_SNAPSHOT_LINK_LINKED,
    RUN_SNAPSHOT_LINK_UNEVALUATED,
    RUN_SNAPSHOT_LINK_UNPUBLISHED,
    RUN_SNAPSHOT_PUBLICATION_DISABLED,
    RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
    RUN_SNAPSHOT_RESOLUTION_RESOLVED,
    DependencyCycleDetail,
    DependencyCycleKindChange,
    FileIdentity,
    ResolvedSourceIdentity,
    RiskObservation,
    RunSnapshotLink,
    RunSnapshotPublication,
    RunSnapshotResolution,
    RunStoreConfig,
)

_SOURCE = ResolvedSourceIdentity(file=FileIdentity(path="pkg/a.py"), python_module=None)
_DIGEST = "b" * 64
_RUN = "a" * 64


def _link(**overrides: object) -> Callable[[], RunSnapshotLink]:
    fields: dict[str, object] = {
        "state": RUN_SNAPSHOT_LINK_UNPUBLISHED,
        "outcome": RUN_SNAPSHOT_PUBLICATION_DISABLED,
    }
    fields.update(overrides)
    return lambda: RunSnapshotLink(**fields)  # type: ignore[arg-type]


def _resolution(**overrides: object) -> Callable[[], RunSnapshotResolution]:
    fields: dict[str, object] = {
        "state": "unlinked",
        "lane": "stored",
        "report_run_identity": "r",
        "analysis_scope_digest": _DIGEST,
    }
    fields.update(overrides)
    return lambda: RunSnapshotResolution(**fields)  # type: ignore[arg-type]


def _publication(**overrides: object) -> Callable[[], RunSnapshotPublication]:
    fields: dict[str, object] = {
        "outcome": RUN_SNAPSHOT_PUBLICATION_PUBLISHED,
        "admissible": True,
        "target": "canonical",
        "run_id": _RUN,
        "generation": 1,
        "analysis_scope_digest": _DIGEST,
    }
    fields.update(overrides)
    return lambda: RunSnapshotPublication(**fields)  # type: ignore[arg-type]


def _risk(**overrides: object) -> Callable[[], RiskObservation]:
    fields: dict[str, object] = {
        "source": _SOURCE,
        "qualname": "f",
        "dimension": "complexity",
        "numerator": 1,
        "start_line": 1,
    }
    fields.update(overrides)
    return lambda: RiskObservation(**fields)  # type: ignore[arg-type]


_MODEL_CONTRACTS: tuple[
    tuple[str, Callable[[], object], Callable[[], object], str], ...
] = (
    (
        "run_store_enabled_without_a_path",
        lambda: RunStoreConfig(enabled=True, path=None),
        lambda: RunStoreConfig(enabled=True, path=Path("runs.sqlite3")),
        "must carry its database path",
    ),
    (
        "run_store_disabled_with_a_path",
        lambda: RunStoreConfig(enabled=False, path=Path("runs.sqlite3")),
        lambda: RunStoreConfig(enabled=False, path=None),
        "must not carry a database path",
    ),
    (
        "publication_outcome_outside_the_vocabulary",
        _publication(outcome="mystery"),
        _publication(),
        "unknown run snapshot publication outcome",
    ),
    (
        "stored_publication_without_its_addresses",
        _publication(target="", run_id=""),
        _publication(),
        "must carry its target and run id",
    ),
    (
        "unreasoned_publication_carrying_a_reason",
        _publication(reason="boom"),
        _publication(),
        "each carry their reason",
    ),
    (
        "link_state_outside_the_vocabulary",
        _link(state="mystery"),
        _link(),
        "unknown run snapshot link state",
    ),
    (
        "unpublished_link_carrying_a_store_address",
        _link(store_run_id=_RUN),
        _link(),
        "carries no store address",
    ),
    (
        "unevaluated_link_carrying_a_report_address",
        _link(state=RUN_SNAPSHOT_LINK_UNEVALUATED, report_run_identity="r"),
        _link(state=RUN_SNAPSHOT_LINK_UNEVALUATED),
        "carries no report address",
    ),
    (
        "store_address_without_its_scope_receipt",
        _link(
            state=RUN_SNAPSHOT_LINK_LINKED,
            store_run_id=_RUN,
            report_run_identity="r",
            analysis_scope_digest="",
        ),
        _link(
            state=RUN_SNAPSHOT_LINK_LINKED,
            store_run_id=_RUN,
            report_run_identity="r",
            analysis_scope_digest=_DIGEST,
        ),
        "travel together",
    ),
    (
        "resolution_state_outside_the_vocabulary",
        _resolution(state="mystery"),
        _resolution(),
        "unknown run snapshot resolution state",
    ),
    (
        "resolution_lane_outside_the_vocabulary",
        _resolution(lane="mystery"),
        _resolution(),
        "unknown run snapshot resolution lane",
    ),
    (
        "resolution_without_the_address_it_answered",
        _resolution(report_run_identity=""),
        _resolution(),
        "carries the report address it answered",
    ),
    (
        "unresolved_answer_naming_a_run",
        _resolution(store_run_id=_RUN),
        _resolution(state=RUN_SNAPSHOT_RESOLUTION_RESOLVED, store_run_id=_RUN),
        "names a run and nothing else does",
    ),
    (
        "cycle_member_paths_shorter_than_its_modules",
        lambda: DependencyCycleDetail(
            modules=("pkg.a", "pkg.b"), kind="import_cycle", member_paths=("pkg/a.py",)
        ),
        lambda: DependencyCycleDetail(
            modules=("pkg.a", "pkg.b"),
            kind="import_cycle",
            member_paths=("pkg/a.py", "pkg/b.py"),
        ),
        "must align with modules",
    ),
    (
        "cycle_kind_change_that_changes_nothing",
        lambda: DependencyCycleKindChange(
            modules=("pkg.a",),
            previous_kind="import_cycle",
            current_kind="import_cycle",
        ),
        lambda: DependencyCycleKindChange(
            modules=("pkg.a",),
            previous_kind="import_cycle",
            current_kind="deferred_cycle",
        ),
        "must change the kind",
    ),
    (
        "risk_observation_without_a_qualname",
        _risk(qualname=""),
        _risk(),
        "qualnames must be non-empty",
    ),
)


@pytest.mark.parametrize(
    ("contract", "refused", "accepted", "fragment"),
    _MODEL_CONTRACTS,
    ids=[row[0] for row in _MODEL_CONTRACTS],
)
def test_model_contract_refuses_only_what_it_names(
    contract: str,
    refused: Callable[[], object],
    accepted: Callable[[], object],
    fragment: str,
) -> None:
    with pytest.raises(ValueError) as raised:
        refused()
    assert fragment in str(raised.value), f"{contract}: refusal did not name the rule"
    accepted()
