# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One owner for reading the canonical findings-group container.

``findings.groups.clones.suppressed`` is a mapping one level deeper than its
sibling lists, and it was the only clone container read straight out of the raw
document by three consumers, each with its own idea of the shape. The receipt
spelled the bucket keys in the singular and counted zero against a document
that published seventeen; the implementation context ran ``as_sequence`` over a
mapping and silently got ``()``; the HTML panel asked items for ``filepath``
while the document gives them ``relative_path``.

Every fixture here is built to the shape of the **live** document, measured off
a real ``codeclone --json`` run of this repository, never copied from a
neighbouring fixture. That is deliberate: a fixture written in the reader's
dialect makes a wrong reader look right, and it is exactly how this class
survived being declared closed (`H4`).

The tests name the layer they hold:

``owner``
    the R3 door as a pure function over a document mapping.
``consumer``
    a real consumer — the receipt counter, the implementation-context
    projection, the HTML label helper. Only these can see whether a consumer
    actually reaches the owner; an owner test is green with nothing wired.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from codeclone.api.finding_groups import (
    SUPPRESSED_KIND_ORDER,
    iter_finding_groups,
    suppressed_clone_groups,
)
from codeclone.report.html.sections._clones import (
    _flatten_suppressed_clone_groups,
    _suppressed_group_label,
)
from codeclone.surfaces.mcp import _implementation_context as impl_context_mod
from codeclone.surfaces.mcp import _review_receipt as receipt_mod
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord

# Reached through the R3 door rather than imported from ``codeclone.domain``:
# this module's subject ring is r4, and an r4 test reaching r2 directly is a
# boundary violation the Phase 39S ratchet counts. Unpacking also pins the
# order the owner declares, which the HTML panel states to its readers.
CLONE_KIND_FUNCTION, CLONE_KIND_BLOCK, CLONE_KIND_SEGMENT = SUPPRESSED_KIND_ORDER


def _suppressed_group(
    *,
    kind: str,
    group_key: str,
    relative_path: str,
    qualname: str = "",
    count: int = 2,
) -> dict[str, object]:
    """One suppressed clone group in the shape the producer publishes.

    Measured against a live document: a suppressed group carries its own
    ``category`` in the singular, its items carry ``relative_path`` and never
    ``filepath``, and it carries **no** ``novelty`` key at all — a suppressed
    group has no baseline comparison term.
    """

    return {
        "id": f"clone:{kind}:{group_key}",
        "family": "clone",
        "category": kind,
        "kind": "clone_group",
        "severity": "low",
        "confidence": "high",
        "priority": 1,
        "clone_kind": kind,
        "clone_type": "type_1",
        "count": count,
        "source_scope": "tests",
        "spread": {"files": 1, "functions": count},
        "items": [
            {
                "relative_path": relative_path,
                "qualname": qualname,
                "start_line": 10,
                "end_line": 20,
            }
        ],
        "facts": {"group_key": group_key},
        "suppression_rule": "clone",
        "suppression_source": "project_config",
        "matched_patterns": ["tests/fixtures/**"],
    }


def _active_group(
    *,
    family_category: str,
    group_key: str,
    relative_path: str,
    novelty: str = "known",
) -> dict[str, object]:
    """One active finding group, which does carry a novelty term."""

    return {
        "id": f"{family_category}:{group_key}",
        "family": "design",
        "category": family_category,
        "kind": "design_finding",
        "severity": "medium",
        "novelty": novelty,
        "items": [{"relative_path": relative_path}],
    }


def _live_shaped_document() -> dict[str, object]:
    """A findings document in the shape the canonical producer publishes.

    ``clones`` holds three sibling **lists** plus a ``suppressed`` **mapping**
    one level deeper, whose bucket keys are plural while the groups inside
    carry their kind in the singular. Non-clone families hold their groups
    under a ``groups`` key, so the container key is never the finding category.
    """

    return {
        "findings": {
            "summary": {
                "clones": {
                    "functions": 1,
                    "blocks": 0,
                    "segments": 0,
                    "suppressed": 3,
                    "suppressed_functions": 2,
                    "suppressed_blocks": 1,
                    "suppressed_segments": 0,
                }
            },
            "groups": {
                "clones": {
                    "functions": [
                        {
                            "id": "clone:function:active",
                            "family": "clone",
                            "category": CLONE_KIND_FUNCTION,
                            "kind": "clone_group",
                            "severity": "high",
                            "novelty": "new",
                            "clone_kind": CLONE_KIND_FUNCTION,
                            "count": 2,
                            "items": [{"relative_path": "pkg/active.py"}],
                        }
                    ],
                    "blocks": [],
                    "segments": [],
                    "suppressed": {
                        "functions": [
                            _suppressed_group(
                                kind=CLONE_KIND_FUNCTION,
                                group_key="sf1",
                                relative_path="tests/fixtures/alpha.py",
                                qualname="alpha:run",
                            ),
                            _suppressed_group(
                                kind=CLONE_KIND_FUNCTION,
                                group_key="sf2",
                                relative_path="tests/fixtures/beta.py",
                            ),
                        ],
                        "blocks": [
                            _suppressed_group(
                                kind=CLONE_KIND_BLOCK,
                                group_key="sb1",
                                relative_path="tests/fixtures/gamma.py",
                            )
                        ],
                        "segments": [],
                    },
                },
                "design": {
                    "groups": [
                        _active_group(
                            family_category="complexity",
                            group_key="c1",
                            relative_path="pkg/deep.py",
                        )
                    ]
                },
                "structural": {"groups": []},
                "dead_code": {"groups": []},
            },
        }
    }


def _document_without_suppressed() -> dict[str, object]:
    """The producer omits ``suppressed`` entirely when no group is suppressed."""

    document = _live_shaped_document()
    findings = cast("dict[str, Any]", document["findings"])
    del findings["groups"]["clones"]["suppressed"]
    return document


def _run_record(root: Path, document: dict[str, object]) -> MCPRunRecord:
    return MCPRunRecord(
        run_id="findinggroups01",
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        report_document=document,
        summary={"run_id": "findinggroups01"},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )


# --- owner -----------------------------------------------------------------


def test_owner_reaches_every_suppressed_group_the_document_publishes() -> None:
    """The owner descends the extra level its sibling lists do not have."""

    suppressed = suppressed_clone_groups(_live_shaped_document())

    assert suppressed.present is True
    assert suppressed.count == 3
    assert [str(group["id"]) for group in suppressed.groups] == [
        "clone:function:sf1",
        "clone:function:sf2",
        "clone:block:sb1",
    ]


def test_owner_keys_buckets_by_the_group_kind_not_the_container_spelling() -> None:
    """A reader asking for a kind cannot mis-spell the producer's bucket key.

    The container spells the buckets in the plural and the groups spell their
    kind in the singular. The owner answers on the group's own term, so the
    two spellings can never disagree in a consumer again.
    """

    by_kind = suppressed_clone_groups(_live_shaped_document()).by_kind

    assert set(by_kind) == {
        CLONE_KIND_FUNCTION,
        CLONE_KIND_BLOCK,
        CLONE_KIND_SEGMENT,
    }
    assert len(by_kind[CLONE_KIND_FUNCTION]) == 2
    assert len(by_kind[CLONE_KIND_BLOCK]) == 1
    assert by_kind[CLONE_KIND_SEGMENT] == ()


def test_owner_distinguishes_an_absent_container_from_an_empty_one() -> None:
    """Absence is not emptiness (`G4`, `RP2`)."""

    absent = suppressed_clone_groups(_document_without_suppressed())
    assert absent.present is False
    assert absent.count == 0

    empty_document = _live_shaped_document()
    findings = cast("dict[str, Any]", empty_document["findings"])
    findings["groups"]["clones"]["suppressed"] = {
        "functions": [],
        "blocks": [],
        "segments": [],
    }
    empty = suppressed_clone_groups(empty_document)
    assert empty.present is True
    assert empty.count == 0


def test_owner_never_reports_an_active_clone_group_as_suppressed() -> None:
    """The reverse boundary: the active lane must not leak into the suppressed one."""

    suppressed = suppressed_clone_groups(_live_shaped_document())
    assert "clone:function:active" not in {
        str(group["id"]) for group in suppressed.groups
    }

    refs = iter_finding_groups(_live_shaped_document())
    active_ids = {str(ref.group["id"]) for ref in refs if not ref.suppressed}
    suppressed_ids = {str(ref.group["id"]) for ref in refs if ref.suppressed}
    assert "clone:function:active" in active_ids
    assert "clone:function:active" not in suppressed_ids
    assert suppressed_ids.isdisjoint(active_ids)


def test_owner_reports_the_group_category_never_the_container_key() -> None:
    """A group carries its own category; the container key is not it."""

    refs = iter_finding_groups(_live_shaped_document())
    design = [ref for ref in refs if ref.family == "design"]
    assert [ref.category for ref in design] == ["complexity"]

    suppressed_refs = [ref for ref in refs if ref.suppressed]
    assert {ref.category for ref in suppressed_refs} == {
        CLONE_KIND_FUNCTION,
        CLONE_KIND_BLOCK,
    }


# --- consumer: review receipt ----------------------------------------------


def test_consumer_receipt_counts_every_group_the_document_calls_suppressed() -> None:
    """The receipt and the document must not state two different numbers."""

    document = _live_shaped_document()
    published = cast("dict[str, Any]", document["findings"])["summary"]["clones"][
        "suppressed"
    ]

    assert receipt_mod._suppressed_clone_count(document) == published == 3


def test_consumer_receipt_declines_the_suppressed_clone_regression_claim() -> None:
    """A document with suppressed groups must carry the not-claimed marker."""

    claims = receipt_mod.derive_claims_not_made(_live_shaped_document())
    assert "suppressed_clone_regression" in {
        str(claim["claim_type"]) for claim in claims
    }

    without = receipt_mod.derive_claims_not_made(_document_without_suppressed())
    assert "suppressed_clone_regression" not in {
        str(claim["claim_type"]) for claim in without
    }


# --- consumer: implementation context --------------------------------------


def test_consumer_implementation_context_reports_the_group_category(
    tmp_path: Path,
) -> None:
    """The projection must report the finding's category, not the JSON key.

    Every non-clone family nests its groups under ``groups``, so a projection
    taking the category from the container key labels every design and
    structural finding ``groups``.
    """

    record = _run_record(tmp_path, _live_shaped_document())
    rows = impl_context_mod._baseline_sensitive_findings(
        record,
        relevant_paths=frozenset({"pkg/deep.py"}),
    )

    assert [row["category"] for row in rows] == ["complexity"]
    assert [row["family"] for row in rows] == ["design"]


def test_consumer_implementation_context_reaches_suppressed_clone_groups(
    tmp_path: Path,
) -> None:
    """A suppressed group is declined on its novelty, never missed on its shape.

    Reachability and emission are different questions. The owner reaches every
    suppressed group (pinned above); this projection then declines them because
    a suppressed group carries no novelty term and so is not baseline-sensitive
    (`B9`). The distinction matters: the old walk ran ``as_sequence`` over a
    mapping and could not have declined what it never reached, and the two
    states are indistinguishable from the empty result alone.
    """

    document = _live_shaped_document()
    reachable = {str(group["id"]) for group in suppressed_clone_groups(document).groups}
    assert reachable == {
        "clone:function:sf1",
        "clone:function:sf2",
        "clone:block:sb1",
    }
    assert all(
        "novelty" not in group for group in suppressed_clone_groups(document).groups
    )

    record = _run_record(tmp_path, document)
    rows = impl_context_mod._baseline_sensitive_findings(
        record,
        relevant_paths=frozenset({"tests/fixtures/alpha.py"}),
    )
    assert rows == ()


# --- consumer: HTML suppressed panel ---------------------------------------


def test_consumer_html_shows_the_path_the_document_carries(tmp_path: Path) -> None:
    """The File column must show the item's path, not an absent key.

    Suppressed items carry ``relative_path``; the active clone projection turns
    that into a presentation ``filepath``. The suppressed panel bypassed that
    projection and asked for ``filepath`` directly, so the column was empty for
    every row of every report.
    """

    ctx = cast(
        Any,
        SimpleNamespace(
            report_document=_live_shaped_document(),
            scan_root=str(tmp_path),
        ),
    )

    groups = _flatten_suppressed_clone_groups(ctx)
    assert len(groups) == 3

    labels = [_suppressed_group_label(group, ctx) for group in groups]
    assert all(filepath for _label, filepath in labels)
    assert labels[0] == (
        "alpha:run",
        str(tmp_path / "tests/fixtures/alpha.py"),
    )
    assert labels[1] == (
        "tests/fixtures/beta.py",
        str(tmp_path / "tests/fixtures/beta.py"),
    )


def test_consumer_html_orders_suppressed_rows_functions_blocks_segments(
    tmp_path: Path,
) -> None:
    """The panel declares its own order in prose; the owner must honour it."""

    ctx = cast(
        Any,
        SimpleNamespace(
            report_document=_live_shaped_document(),
            scan_root=str(tmp_path),
        ),
    )

    kinds = [
        str(group.get("clone_kind")) for group in _flatten_suppressed_clone_groups(ctx)
    ]
    assert kinds == [
        CLONE_KIND_FUNCTION,
        CLONE_KIND_FUNCTION,
        CLONE_KIND_BLOCK,
    ]
