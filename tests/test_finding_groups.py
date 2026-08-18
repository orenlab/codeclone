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
    projection, the HTML label helper, the Markdown and text renderers. Only
    these can see whether a consumer actually reaches the owner; an owner test
    is green with nothing wired.
``ratchet``
    the guard that keeps the class closed. Wave 6 routed three broken readers
    through the owner and left two correct ones parsing the container
    themselves, because they addressed it with a dotted string constant rather
    than a literal key and a scan for the key could not see them (`I1`). A
    fix without a guard closes the class for today only.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from codeclone.api.finding_groups import (
    SUPPRESSED_KIND_ORDER,
    iter_finding_groups,
    suppressed_clone_groups,
)
from codeclone.contracts import SUPPRESSED_CONTAINER_PATH
from codeclone.report.html.sections import _clones as html_clones_mod
from codeclone.report.html.sections._clones import (
    _flatten_suppressed_clone_groups,
    _suppressed_group_label,
)
from codeclone.report.messages import markdown as md_msgs
from codeclone.report.messages import projections as proj
from codeclone.report.renderers.markdown import render_markdown_report_document
from codeclone.report.renderers.text import render_text_report_document
from codeclone.surfaces.mcp import _implementation_context as impl_context_mod
from codeclone.surfaces.mcp import _review_receipt as receipt_mod
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.utils import suppressed_clone_groups as law_mod

from ._report_fixtures import build_maximal_report_document
from .test_report_document_reads import report_document_reads

# Unpacked from the door's declared order rather than imported one by one:
# that binds every fixture below to the order the HTML panel states to its
# readers, so a change to either has to answer for the other.
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


# --- consumer: the Markdown and text renderers -----------------------------

#: The marker the text renderer prints above each suppressed group. Read out
#: of the rendering rather than out of the owner: a helper that asked the
#: owner what to look for would agree with the owner by construction and could
#: not observe a renderer that printed nothing at all.
_TEXT_SUPPRESSED_GROUP_MARKER = "=== Suppressed clone group #"

#: The Markdown section heading for the whole suppressed lane. Spelled here
#: because the renderer spells it inline and the message catalog carries no
#: entry for it — a labelled value without a catalog entry is a contract gap
#: (`SH1`), reported rather than repaired inside this change.
_MARKDOWN_SUPPRESSED_SECTION_HEADING = "#### Suppressed Golden Fixture Clone Groups"

_TEXT_SUPPRESSED_TITLES = frozenset(
    {
        proj.TEXT_SECTION_SUPPRESSED_FUNCTION_CLONES,
        proj.TEXT_SECTION_SUPPRESSED_BLOCK_CLONES,
        proj.TEXT_SECTION_SUPPRESSED_SEGMENT_CLONES,
    }
)


def _published_kind_order() -> tuple[str, ...]:
    """The kind order the HTML panel publishes to its readers, re-derived.

    The panel prints ``ordering=`` prose beside the suppressed table, so the
    order is a statement made to a user and not an accident of iteration.
    Re-deriving it from that prose pins the rule the constant is supposed to
    obey; asserting the constant equals a tuple written out here again would
    only move the magic value into the test (`H1`).
    """

    return tuple(
        word.strip().removeprefix("then ").removesuffix("s")
        for word in html_clones_mod._SUPPRESSED_GROUP_ORDER.split(",")
    )


def _live_shaped_document_with_a_segment() -> dict[str, object]:
    """The live-shaped document with one group of every suppressed kind."""

    document = _live_shaped_document()
    findings = cast("dict[str, Any]", document["findings"])
    findings["groups"]["clones"]["suppressed"]["segments"] = [
        _suppressed_group(
            kind=CLONE_KIND_SEGMENT,
            group_key="ss1",
            relative_path="tests/fixtures/delta.py",
        )
    ]
    return document


def _document_with_singular_bucket_keys() -> dict[str, object]:
    """The same suppressed groups, in buckets the producer does not spell.

    Bucket keys are not a name the owner honours: it reads every list inside
    the container, so which key holds a group is not load-bearing (`G2`). The
    wave 6 receipt spelled these keys in the singular and counted zero against
    a document publishing seventeen, which is the failure this shape
    reproduces. Rendering it is how a renderer proves it asked the owner
    rather than guessing the producer's spelling: a renderer that spells
    bucket keys reports none of these groups, and the owner reports all of
    them.
    """

    document = _live_shaped_document_with_a_segment()
    findings = cast("dict[str, Any]", document["findings"])
    buckets = cast("dict[str, Any]", findings["groups"]["clones"]["suppressed"])
    findings["groups"]["clones"]["suppressed"] = {
        key.removesuffix("s"): groups for key, groups in buckets.items()
    }
    return document


def _document_with_an_empty_suppressed_container() -> dict[str, object]:
    """The container is published and holds nothing — not the same as absent."""

    document = _live_shaped_document()
    findings = cast("dict[str, Any]", document["findings"])
    findings["groups"]["clones"]["suppressed"] = {
        "functions": [],
        "blocks": [],
        "segments": [],
    }
    return document


def _markdown_suppressed_ids(rendered: str) -> list[str]:
    """Every finding id Markdown printed inside a suppressed clone block."""

    lines = rendered.splitlines()
    heading = f"#### {md_msgs.MD_SUPPRESSED_CLONE_GROUP}"
    ids: list[str] = []
    for index, line in enumerate(lines):
        if line != heading:
            continue
        for follower in lines[index + 1 : index + 4]:
            match = re.search(r"`([^`]+)`", follower)
            if match:
                ids.append(match.group(1))
                break
    return ids


def _text_suppressed_ids(rendered: str) -> list[str]:
    """Every finding id the text renderer printed in a suppressed block."""

    lines = rendered.splitlines()
    return [
        lines[index + 1].split(" ", 1)[0].removeprefix("id=")
        for index, line in enumerate(lines)
        if line.startswith(_TEXT_SUPPRESSED_GROUP_MARKER)
    ]


def _text_suppressed_section_kinds(rendered: str) -> list[str]:
    """The clone kind of each suppressed section the text renderer printed."""

    return [
        title.split()[1].lower()
        for line in rendered.splitlines()
        if (title := line.split(" (groups=")[0]) in _TEXT_SUPPRESSED_TITLES
    ]


def test_consumer_markdown_prints_every_group_the_owner_reaches() -> None:
    """Markdown must not lose a group to the producer's bucket spelling.

    The renderer addressed the container by dotted path and then asked it for
    three bucket keys of its own choosing, so it agreed with the producer only
    for as long as both spelled the buckets the same way. The owner answers on
    the group's own terms, and the renderer prints what the owner reaches.
    """

    document = _document_with_singular_bucket_keys()
    expected = [str(group["id"]) for group in suppressed_clone_groups(document).groups]

    assert expected == [
        "clone:function:sf1",
        "clone:function:sf2",
        "clone:block:sb1",
        "clone:segment:ss1",
    ]
    assert _markdown_suppressed_ids(render_markdown_report_document(document)) == (
        expected
    )


def test_consumer_text_prints_every_group_the_owner_reaches() -> None:
    """The text renderer carried the same second spelling of the container."""

    document = _document_with_singular_bucket_keys()
    expected = [str(group["id"]) for group in suppressed_clone_groups(document).groups]

    assert _text_suppressed_ids(render_text_report_document(document)) == expected


def test_consumer_markdown_and_text_print_the_same_suppressed_groups() -> None:
    """One document, two projections, one answer.

    Stated without an owner term on purpose. Wave 6 routed three consumers
    through the owner and left two behind, and the survivors stayed green
    because every test asked one renderer at a time. This is the pin that
    fails when a fix reaches one renderer and not the other.
    """

    document = _document_with_singular_bucket_keys()

    assert _markdown_suppressed_ids(render_markdown_report_document(document)) == (
        _text_suppressed_ids(render_text_report_document(document))
    )


def test_consumer_renderers_never_print_an_active_clone_group_as_suppressed() -> None:
    """The reverse boundary: the active lane must not leak into either output.

    Active clone groups live in flat sibling lists and suppressed ones in a
    mapping one level deeper. A reader that stopped distinguishing them would
    print a finding that is being gated as one that is being excluded, which
    is the more damaging of the two errors.
    """

    document = _live_shaped_document_with_a_segment()
    active_id = "clone:function:active"

    assert active_id in render_markdown_report_document(document)
    assert active_id not in _markdown_suppressed_ids(
        render_markdown_report_document(document)
    )
    assert active_id not in _text_suppressed_ids(render_text_report_document(document))


def test_the_owner_kind_order_is_the_order_the_html_panel_publishes() -> None:
    """The order is a claim made to a reader, so it is pinned to that claim."""

    published = _published_kind_order()

    assert published == SUPPRESSED_KIND_ORDER


def test_consumer_renderers_print_the_kinds_in_the_published_order() -> None:
    """Both renderers take their order from the owner, not from the container.

    Markdown prints one flat list, the text renderer prints one section per
    kind, and the two orders are the same fact. A mutation of the owner's
    order has to move both, or the order is not owned in one place.
    """

    published = list(_published_kind_order())
    document = _live_shaped_document_with_a_segment()

    markdown_kinds = [
        finding_id.split(":")[1]
        for finding_id in _markdown_suppressed_ids(
            render_markdown_report_document(document)
        )
    ]
    deduped = [
        kind
        for index, kind in enumerate(markdown_kinds)
        if index == 0 or markdown_kinds[index - 1] != kind
    ]

    assert deduped == published
    assert _text_suppressed_section_kinds(render_text_report_document(document)) == (
        published
    )


def test_consumer_renderers_distinguish_an_absent_container_from_an_empty_one() -> None:
    """A lane that did not run must not read as a lane that found nothing.

    The producer omits the container entirely when nothing was suppressed, so
    the two states are different documents and the renderers must not collapse
    them (`G4`, `RP2`). Markdown drops its heading for one and prints it with
    ``_None._`` for the other; the text renderer drops its three sections for
    one and prints them with ``groups=0`` for the other.
    """

    absent = render_markdown_report_document(_document_without_suppressed())
    empty = render_markdown_report_document(
        _document_with_an_empty_suppressed_container()
    )

    assert _MARKDOWN_SUPPRESSED_SECTION_HEADING not in absent
    assert _MARKDOWN_SUPPRESSED_SECTION_HEADING in empty
    assert md_msgs.MD_NONE in empty
    assert _markdown_suppressed_ids(empty) == []

    assert (
        _text_suppressed_section_kinds(
            render_text_report_document(_document_without_suppressed())
        )
        == []
    )
    assert _text_suppressed_section_kinds(
        render_text_report_document(_document_with_an_empty_suppressed_container())
    ) == list(_published_kind_order())


# --------------------------------------------------------------------------------------
# The suppressed-container ratchet
#
# The predicate: the shape of ``findings.groups.clones.suppressed`` is known
# to the owner and to nobody else. Wave 6 built the owner and routed three
# consumers through it; two more kept parsing the container themselves and
# were not found, because a scan for the literal key ``"suppressed"`` cannot
# see a module that addresses the container with a dotted string constant
# handed to an accessor (`I1`).
#
# So the guard is not a text scan. It reuses the reconstruction the withdrawn-
# key pin already owns: ``report_document_reads`` resolves a literal ``.get()``
# chain, a dotted accessor path, and either of those reached through a local
# alias or a module-local helper's return, into one dotted path. A consumer is
# an offender exactly when one of its reconstructed reads addresses the
# container the owner declares -- whichever way it spelled the read.
#
# The address is taken from the owner (`SUPPRESSED_CONTAINER_PATH`) and never
# restated here: a literal copy stays green while the owner is renamed out from
# under it, which is the pattern that let five spellings of one shape survive.
# --------------------------------------------------------------------------------------

#: The one module allowed to address the container, named rather than left to
#: be the only match. The name is checked against the module that actually
#: navigates the path, so the exemption cannot outlive its subject.
_SUPPRESSED_CONTAINER_OWNER = "codeclone/utils/suppressed_clone_groups.py"

#: Sites that address the container and cannot be routed through the owner,
#: with the reason each one is blocked. Two-sided on purpose: a new offender
#: fails as growth, and a repaired one fails as a stale entry, so the register
#: is a work queue with a deadline and not a permit.
#:
#: Emptied by the authority relocation: ``codeclone/analysis/blast_radius.py``
#: was registered here because it read the container itself -- hedging the
#: singular *and* the plural bucket spelling -- and could not be routed through
#: an r3 door from r2. The register said "the owner would have to move", and it
#: did: the container address and the normalization law now live in the rings
#: r2 and r4 can both reach, so the consumer holds no shape knowledge left to
#: register. Add an entry only for a reader another live branch already owns,
#: and delete it the moment that branch lands.
_CONTAINER_READERS_BLOCKED_BY_A_RING: dict[str, str] = {}

#: Trees scanned for consumers. ``tests/`` is deliberately outside: a test that
#: describes the container is the pin, not a second reader. Measured on this
#: tree at the time of writing: no Python outside ``codeclone/`` reads a report
#: document at all -- ``extensions/`` ships no Python, ``plugins/`` ships hooks
#: and launchers, and the one benchmark that mentions ``findings`` builds a
#: payload instead of reading one. They are scanned anyway, because "there is
#: no consumer there today" is a measurement with a shelf life.
_SCANNED_TREES = ("codeclone", "extensions", "plugins", "scripts", "benchmarks")

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _owned_container_path() -> str:
    return ".".join(SUPPRESSED_CONTAINER_PATH)


def _modules_addressing_the_suppressed_container() -> dict[str, tuple[str, ...]]:
    """Every scanned module whose report-document reads reach the container."""

    owned = _owned_container_path()
    found: dict[str, set[str]] = {}
    for relative in _tracked_python_sources():
        module = _REPO_ROOT / relative
        try:
            reads = report_document_reads(module.read_text("utf-8"))
        except SyntaxError:
            # A source this scanner cannot parse is an unresolved site, not a
            # reason to answer nothing about every other file. Dying here made
            # the whole ratchet silent: one vendored Python 2 helper under a
            # build directory, and the guard reported on none of the sources it
            # exists to watch.
            _UNPARSABLE_SOURCES.add(relative)
            continue
        for _line, path in reads:
            if path == owned or path.startswith(f"{owned}."):
                found.setdefault(relative, set()).add(path)
    return {module: tuple(sorted(paths)) for module, paths in sorted(found.items())}


#: Sources the scanner could not parse on the last pass. Named rather than
#: dropped: an inventory that silently skips what it cannot read reports a
#: coverage it does not have (`I5`).
_UNPARSABLE_SOURCES: set[str] = set()


def _tracked_python_sources() -> tuple[str, ...]:
    """Every tracked ``.py`` under the scanned trees, in path order.

    The universe is what git tracks, not what the working tree happens to hold.
    A checkout also carries build output, IDE sandboxes and vendored third-party
    code -- measured here, 2979 ``.py`` files on disk against 567 tracked -- and
    none of it is source this ratchet governs. Reading it invites both a crash
    on code written for another Python and a false offender from a vendored file
    that happens to spell the same attribute chain.
    """

    completed = subprocess.run(
        # Directory pathspecs, not globs: ``tree/**/*.py`` silently drops the
        # files directly under each tree -- measured at 545 against 548 for
        # ``codeclone`` alone, ``__init__.py`` among the three it lost.
        ["git", "ls-files", "-z", "--", *_SCANNED_TREES],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return tuple(
        sorted(
            item
            for item in completed.stdout.split("\0")
            if item and item.endswith(".py")
        )
    )


def _access_form_sources() -> dict[str, str]:
    """One source per shape a consumer can address the container in.

    Every source is assembled from the owner's declared path, so the probe
    follows a rename instead of pinning yesterday's spelling.
    """

    *ancestors, container_key = SUPPRESSED_CONTAINER_PATH
    chain = "document"
    for segment in SUPPRESSED_CONTAINER_PATH:
        chain = f"as_mapping({chain}.get({segment!r}))"
    parent_chain = "report_document"
    for segment in ancestors:
        parent_chain = f"as_mapping({parent_chain}.get({segment!r}))"
    return {
        "literal key": f"def reader(document):\n    return {chain}\n",
        "dotted string constant": (
            "def reader(payload):\n"
            f"    (container,) = sections(payload, {_owned_container_path()!r})\n"
            "    return container\n"
        ),
        "alias through a helper": (
            "def _clone_groups(report_document):\n"
            f"    return {parent_chain}\n"
            "def reader(report_document):\n"
            "    clones = _clone_groups(report_document)\n"
            f"    return clones.get({container_key!r})\n"
        ),
    }


def test_the_ratchet_resolves_every_form_the_container_can_be_addressed_in() -> None:
    """Reachability: the guard's detector fires on all three access shapes.

    A guard nothing can be shown to reach is theater (`H2`), and the shape
    that hid two correct consumers through wave 6 is the middle one -- the
    dotted string constant, which a scan for the literal key cannot see.
    """

    owned = _owned_container_path()
    unseen = sorted(
        form
        for form, source in _access_form_sources().items()
        if owned not in {path for _line, path in report_document_reads(source)}
    )

    assert unseen == [], (
        f"the ratchet cannot see {owned} addressed in these forms, so a "
        f"consumer writing one of them would never be reported: {unseen}"
    )


def test_the_ratchet_takes_its_address_from_the_owner_not_from_a_literal() -> None:
    """The guard's vocabulary is the owner's, and the owner's is the producer's.

    Binding the three together is what stops the guard from rotting. Restated
    as a literal it would keep scanning yesterday's address after the owner
    moved, and report a closed class over a path nothing publishes; taken from
    the owner and resolved against the document the product's own builder
    emits, a rename that the producer did not follow fails here by name.
    """

    owner_module = Path(str(law_mod.__file__)).resolve()
    assert owner_module.relative_to(_REPO_ROOT).as_posix() == (
        _SUPPRESSED_CONTAINER_OWNER
    )

    carried: object = build_maximal_report_document()
    for segment in SUPPRESSED_CONTAINER_PATH:
        assert isinstance(carried, dict), (
            f"the owner declares {_owned_container_path()}, and the document "
            f"the builder emits does not carry {segment!r} as a mapping step"
        )
        assert segment in carried, (
            f"the owner declares {_owned_container_path()}, which the document "
            f"the builder emits does not carry: {segment!r} is missing"
        )
        carried = carried[segment]

    assert carried, "the maximal document must publish a suppressed container"


def test_only_the_owner_addresses_the_suppressed_clone_container() -> None:
    """The ratchet: nobody but the owner navigates to the container.

    A consumer that reaches the container itself has to know that it is a
    mapping one level deeper than its sibling lists and that its bucket keys
    are plural while the groups inside are singular. That is five facts about
    one shape, re-derived per consumer, and it produced one document stating
    both "seventeen suppressed" and "zero". The owner answers on terms a
    consumer cannot mis-spell, so reaching past it is the defect, not the
    spelling that follows.
    """

    readers = _modules_addressing_the_suppressed_container()
    offenders = {
        module: paths
        for module, paths in readers.items()
        if module != _SUPPRESSED_CONTAINER_OWNER
        and module not in _CONTAINER_READERS_BLOCKED_BY_A_RING
    }
    stale = sorted(set(_CONTAINER_READERS_BLOCKED_BY_A_RING) - set(readers))

    assert offenders == {}, (
        "these modules address the suppressed clone container themselves "
        "instead of reading it through "
        f"{_SUPPRESSED_CONTAINER_OWNER}: {offenders}"
    )
    assert stale == [], (
        "these registered readers no longer address the container; shrink "
        f"_CONTAINER_READERS_BLOCKED_BY_A_RING: {stale}"
    )


# --------------------------------------------------------------------------------------
# The authority ratchet
#
# The ratchet above asks who *navigates* to the container. This one asks who
# *declares* the vocabulary the container is spelled in, and it is the guard
# the relocation earns: moving a constant leaves every byte of output where it
# was, so a suite that only compares values stays green whether the vocabulary
# has one owner or three. Restating one of these names anywhere else would be
# invisible to every behavioural test in this file and would hand the next
# reader a second place to spell it -- which is how one document came to state
# both "seventeen suppressed" and "zero".
#
# The scan is over module-level *declarations*, resolved from the AST, not over
# occurrences of the text: an import of the owner's name is a consumer and must
# stay legal, while an assignment of the same name is a second authority. A
# text scan cannot tell those apart (`I1`).
# --------------------------------------------------------------------------------------

#: The ring the vocabulary had to reach: the producer of the document is r2 and
#: the renderers are r4, and the only rings both may import are r0 and r1. The
#: names below are wire facts -- what the document says -- so they belong to
#: the contracts module rather than to any layer that reads or writes them.
_CLONE_VOCABULARY_OWNER = "codeclone/contracts/__init__.py"

_CLONE_VOCABULARY = frozenset(
    {
        "CLONE_KIND_BLOCK",
        "CLONE_KIND_FUNCTION",
        "CLONE_KIND_SEGMENT",
        "FAMILY_CLONES",
        "SUPPRESSED_CONTAINER_KEY",
        "SUPPRESSED_CONTAINER_PATH",
    }
)

#: The presentation order is not a wire fact. The HTML panel states it to its
#: readers in prose, so it is a contract of the surface that publishes it, and
#: it stays with that surface: pushed down beside the vocabulary it would hand
#: the analysis layer a dependency on a display policy it has no use for.
_PRESENTATION_ORDER_OWNER = "codeclone/api/finding_groups.py"

#: The baseline's lane names are a different contract with a different owner.
#: ``clones.functions`` and ``clones.blocks`` are lane identities that feed the
#: container digest; they are spelled similarly to the findings vocabulary and
#: mean something else. Deriving one from the other would put two contracts
#: under one value, and a bump meant for one would silently move the other.
_BASELINE_LANE_OWNER = "codeclone/baseline/lanes.py"


def _module_level_declarations(names: frozenset[str]) -> dict[str, tuple[str, ...]]:
    """Every module under ``codeclone/`` that assigns one of ``names``."""

    found: dict[str, set[str]] = {}
    for module in sorted((_REPO_ROOT / "codeclone").rglob("*.py")):
        relative = module.relative_to(_REPO_ROOT).as_posix()
        tree = ast.parse(module.read_text("utf-8"))
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in names:
                    found.setdefault(relative, set()).add(target.id)
    return {module: tuple(sorted(hit)) for module, hit in sorted(found.items())}


def _names_borrowed_by(module_path: str, names: frozenset[str]) -> tuple[str, ...]:
    """The names of ``names`` that ``module_path`` imports or reads by attribute."""

    tree = ast.parse((_REPO_ROOT / module_path).read_text("utf-8"))
    borrowed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            borrowed.update(alias.name for alias in node.names if alias.name in names)
        elif isinstance(node, ast.Attribute) and node.attr in names:
            borrowed.add(node.attr)
    return tuple(sorted(borrowed))


def test_the_clone_vocabulary_is_declared_in_exactly_one_place() -> None:
    """One vocabulary, one declaring module, reachable from every real reader.

    A second declaration is byte-identical at runtime while it agrees, which
    is precisely why no output test can see it. It becomes visible only when
    the two spellings drift -- by which time both are load-bearing.
    """

    declarers = _module_level_declarations(_CLONE_VOCABULARY)

    assert _CLONE_VOCABULARY_OWNER in declarers, (
        f"{_CLONE_VOCABULARY_OWNER} declares none of the clone vocabulary, so "
        f"the name this guard protects has moved or gone: {sorted(declarers)}"
    )
    assert sorted(declarers) == [_CLONE_VOCABULARY_OWNER], (
        "the clone vocabulary is declared outside its owner "
        f"{_CLONE_VOCABULARY_OWNER}; a consumer imports these names, it does "
        f"not restate them: {declarers}"
    )
    owned = set(declarers[_CLONE_VOCABULARY_OWNER])
    assert owned == set(_CLONE_VOCABULARY), (
        "the owner no longer declares the whole vocabulary this guard names; "
        f"missing: {sorted(_CLONE_VOCABULARY - owned)}"
    )


def test_the_presentation_order_stays_with_the_surface_that_publishes_it() -> None:
    """The display order is the door's contract, not a wire fact.

    Pushed down into the contracts module it would be reachable -- and then
    depended on -- by the analysis layer, which renders nothing and has no
    order to honour. That is the reverse boundary of the relocation: the test
    that the substrate stayed minimal.
    """

    declarers = _module_level_declarations(frozenset({"SUPPRESSED_KIND_ORDER"}))

    assert sorted(declarers) == [_PRESENTATION_ORDER_OWNER], (
        "the suppressed-kind presentation order must be declared by "
        f"{_PRESENTATION_ORDER_OWNER} and nowhere else: {declarers}"
    )


def test_the_baseline_lane_names_are_not_bound_to_the_findings_vocabulary() -> None:
    """Two contracts that look alike must not become one value.

    ``clones.functions`` is a baseline lane identity that enters the container
    digest; ``FAMILY_CLONES`` is what the report document calls a family. They
    are spelled alike and versioned apart, and binding the first to the second
    would make a findings-vocabulary edit move a digest nobody meant to move.
    """

    borrowed = _names_borrowed_by(_BASELINE_LANE_OWNER, _CLONE_VOCABULARY)

    assert borrowed == (), (
        f"{_BASELINE_LANE_OWNER} takes its lane names from the findings "
        f"vocabulary, which puts two contracts under one value: {borrowed}"
    )


def test_the_scan_names_a_source_it_cannot_parse_instead_of_skipping_it() -> None:
    """An unreadable source is an unresolved site, not an absence of one.

    The scan used to die on the first file it could not parse, so one vendored
    Python 2 helper made the ratchet silent about every source it guards. Not
    dying is half the fix; the other half is that a file the scanner could not
    read must be *named*, because an inventory that quietly drops what it cannot
    parse reports a coverage it does not have (`I5`).
    """

    unreadable = _REPO_ROOT / "codeclone" / "_unparsable_probe.py"
    unreadable.write_text("idents = [`ident` for ident in x]\n", encoding="utf-8")
    subprocess.run(["git", "add", "-N", str(unreadable)], cwd=_REPO_ROOT, check=True)
    try:
        _UNPARSABLE_SOURCES.clear()
        _modules_addressing_the_suppressed_container()

        assert "codeclone/_unparsable_probe.py" in _UNPARSABLE_SOURCES
    finally:
        subprocess.run(
            ["git", "rm", "--cached", "--quiet", str(unreadable)],
            cwd=_REPO_ROOT,
            check=False,
        )
        unreadable.unlink()
        _UNPARSABLE_SOURCES.clear()


def test_the_scan_universe_is_what_git_tracks_not_what_the_tree_holds() -> None:
    """An untracked source is not source this ratchet governs.

    A checkout carries build output, IDE sandboxes and vendored third-party
    code: measured here, 2979 ``.py`` files on disk against 567 tracked. Reading
    them invites a false offender from a vendored file that happens to spell the
    same attribute chain, and it made the scan die on Python 2 helpers under a
    build directory.

    Tolerating an unparsable file hides that defect rather than fixing it -- the
    scan stops crashing and quietly reads five times what it governs -- so the
    universe needs a pin of its own.
    """

    untracked = _REPO_ROOT / "codeclone" / "_untracked_probe.py"
    untracked.write_text("value = 1\n", encoding="utf-8")
    try:
        assert "codeclone/_untracked_probe.py" not in _tracked_python_sources()
    finally:
        untracked.unlink()
