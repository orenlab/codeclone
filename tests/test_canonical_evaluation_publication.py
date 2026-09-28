# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E3 (2026-09-27): an MCP-published run carries its
evaluation facts as store rows.

The pin reads the published store the way the E2 publication pin does — the
distinct families of the run's membership — so it is spelled without any
name the wave introduces and runs unchanged on a tree that has none of it.
The expected names are an INDEPENDENT literal: asking the store which
families it declares would prove only that the table was read twice.

The serving corpus runs without a baseline and without a gate: the run is
still evaluated — under the request it was analysed with (every gate off),
with a health verdict, a band per measured unit, a verdict per finding and
the document's selections — and none of that may be silence.

The producer edge reads that evaluation off the SAME body, gate result and
trust vector the document is sealed from: ``core.reporting.report`` builds
each of them at most once, through ``_once``, and only when a reader needs
it — the comparison inputs included, which read the one trust vector rather
than resolving their own.  Those properties are pinned last, on the real
pipeline.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import TypeVar

import pytest

from codeclone.canonical.store import FAMILY_GATE_OUTCOME, RunStore
from codeclone.core import reporting
from codeclone.core.reporting import _once
from codeclone.models import RUN_SNAPSHOT_PUBLICATION_PUBLISHED
from tests._served_run import ServedRunStoreProjection
from tests.test_run_store_identity_bridge import _report_case

_T = TypeVar("_T")

#: The evaluation families a baseline-less, gate-less MCP run must publish.
_PUBLISHED_WITHOUT_A_GATE = frozenset(
    {
        "evaluation_contract",
        "evaluation_request",
        "finding_evaluation",
        "gate_outcome",
        "health_result",
        "hotlist_selection",
        "unit_risk_result",
    }
)


def _published_families(served: ServedRunStoreProjection) -> set[str]:
    uri = f"file:{served.store_path}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT f.family FROM run_members m "
                "JOIN objects o ON o.object_pk = m.object_pk "
                "JOIN families f ON f.family_pk = o.family_pk "
                "JOIN runs r ON r.run_pk = m.run_pk WHERE r.run_id = ?",
                (served.store_run_id,),
            )
        }


def test_the_evaluation_families_are_published_as_store_rows(
    served_run_store_projection: ServedRunStoreProjection,
) -> None:
    families = _published_families(served_run_store_projection)
    # The instrument is on: the run's analysis and comparison families are there.
    assert {"clone_group", "run_scalar", "baseline_witness"} <= families
    missing = sorted(_PUBLISHED_WITHOUT_A_GATE - families)
    assert not missing, f"evaluation families absent from the published run: {missing}"


# ---------------------------------------------------------------------------
# One build of each evaluation input per run (``core.reporting._once``).
# ---------------------------------------------------------------------------


def test_once_builds_on_first_need_and_shares_the_value() -> None:
    built: list[object] = []

    def build() -> object:
        built.append(object())
        return built[-1]

    shared = _once(build)
    assert built == []
    assert shared() is shared() is built[0]
    assert len(built) == 1


def test_once_does_not_remember_a_failed_build() -> None:
    """The next caller meets the same failure: the build runs again, and
    no placeholder stands in for the value it never produced."""
    attempts: list[int] = []

    def build() -> object:
        attempts.append(len(attempts))
        raise RuntimeError("build failed")

    shared = _once(build)
    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="build failed"):
            shared()
    assert attempts == [0, 1]


def _counted(
    counts: Counter[str], name: str, build: Callable[..., _T]
) -> Callable[..., _T]:
    def counted(*args: object, **kwargs: object) -> _T:
        counts[name] += 1
        return build(*args, **kwargs)

    return counted


def _count_builds(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    """Count every build ``report`` shares through ``_once`` — the body, the
    gate pair, the trust vector — every call of the trust owner behind that
    vector, and every build of the comparison inputs.  The owner is counted
    beside the vector so that a comparison which resolved its trust through
    the owner directly is seen as well as one which went through the vector."""
    counts: Counter[str] = Counter()
    for name in (
        "_report_body",
        "_report_gate",
        "_resolved_baseline_trust",
        "resolve_report_baseline_trust",
    ):
        monkeypatch.setattr(
            reporting, name, _counted(counts, name, getattr(reporting, name))
        )
    factory = reporting._comparison_inputs_factory

    def comparison_factory(**kwargs: object) -> object:
        return _counted(counts, "comparison", factory(**kwargs))  # type: ignore[arg-type]

    monkeypatch.setattr(reporting, "_comparison_inputs_factory", comparison_factory)
    return counts


def _rollout(monkeypatch: pytest.MonkeyPatch, store: Path | None) -> None:
    monkeypatch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_ENABLED", "0" if store is None else "1")
    monkeypatch.setenv("CODECLONE_RUN_STORE_PATH", str(store or ""))


def test_the_store_and_the_document_share_one_build_of_each_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both readers are live — the store published the run's evaluation and
    its comparison, the document was sealed — and each shared input was
    built once.  The trust vector is resolved exactly once: the comparison
    inputs read the vector the document is sealed with instead of resolving
    their own (until 2026-09-28 they did, and the count was two)."""
    store = tmp_path / "runs.sqlite3"
    _rollout(monkeypatch, store)
    counts = _count_builds(monkeypatch)
    artifacts = _report_case(
        tmp_path / "tree", json_out=tmp_path / "out.json", store=store
    )
    link = artifacts.run_snapshot_link
    assert link is not None and link.outcome == RUN_SNAPSHOT_PUBLICATION_PUBLISHED
    assert artifacts.report_document is not None
    with RunStore(store) as opened:
        assert opened.read_family(link.store_run_id, FAMILY_GATE_OUTCOME)
    assert counts == {
        "_report_body": 1,
        "_report_gate": 1,
        "_resolved_baseline_trust": 1,
        "resolve_report_baseline_trust": 1,
        "comparison": 1,
    }


def test_a_run_nobody_reads_builds_none_of_the_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default gate-only run: the rollout is off and no document is
    asked for, so nothing reads the body, the gate pair or the trust vector
    — and none of them is built."""
    _rollout(monkeypatch, None)
    counts = _count_builds(monkeypatch)
    artifacts = _report_case(tmp_path / "tree", json_out=None, store=None)
    assert artifacts.report_document is None
    assert counts == {}


def test_a_failed_body_build_is_met_again_by_the_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The publication contains the failure of its body build; the document
    builds the body again and meets the same failure, which is the one
    ``report`` raises — never a remembered placeholder sealed as a body."""
    store = tmp_path / "runs.sqlite3"
    _rollout(monkeypatch, store)
    counts = _count_builds(monkeypatch)

    def broken(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("body build failed")

    monkeypatch.setattr(reporting, "build_report_body_for_analysis", broken)
    with pytest.raises(RuntimeError, match="body build failed"):
        _report_case(tmp_path / "tree", json_out=tmp_path / "out.json", store=store)
    assert counts["_report_body"] == 2
