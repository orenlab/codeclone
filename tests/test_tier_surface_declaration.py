# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every surface either names the advisory tiers or declares it does not.

T4-a (maintainer sanction 2026-08-26): *MCP must be able to name the tiers;
HTML must show their state explicitly; md/text/SARIF may stay subset
projections, but must declare that honestly.*

The two advisory detection tiers -- ``near_miss`` and ``renamed_structure`` --
live in ``findings.groups.<tier>`` of the canonical document as containers,
never as baseline-lane findings. Before this contract they were reachable from
no consumer surface at all: MCP's family vocabulary was the five baseline
families, HTML did not draw them anywhere, and markdown/text/SARIF stated
"Total findings" / "FINDINGS SUMMARY" with no word that a whole advisory
channel sits outside those numbers.

Three separable claims are pinned here, each with a mutation that kills it:

1. **MCP names them.** ``family="near_miss"`` returns the container itself and
   carries the T1 execution witness through: ``disabled`` utters no
   measurement at all (no ``count``, no ``total``, no ``items``), while
   ``complete`` is a measurement that happens to be empty. Records keep their
   own keys -- ``pair_key`` / ``group_key`` -- and no addressable ``id`` is
   invented for them, because none exists.
2. **The five-family total is unchanged.** ``family="all"`` remains the
   baseline-tracked universe. Widening it is a separate contract decision, so
   a tier leaking into ``all`` must red here.
3. **The subset projections say so.** markdown, text and SARIF each state, in
   their own artifact's words, that the families they list are the
   baseline-tracked ones and that the advisory tiers are read from
   ``report.json``.

**Where the tier containers come from, and why not from the producer.** This
module tests consumer surfaces, which the boundary ratchet places in ring
``r4``; the tier producers live in ``r2`` and are out of reach by construction
(``test_architecture``). The bridge the project already uses is a frozen
document, so the ``disabled`` and ``complete`` containers here are read
straight from ``tests/fixtures/tier_state`` -- the two distinguishing
documents ``test_tier_container_state`` proves the real pipeline emits.

The populated container adds one *synthetic* record to that frozen container.
That is deliberate and is the stronger pin for what is actually claimed here:
these surfaces must pass a tier's records through **verbatim**, so a record
whose contents the producer would never emit proves the absence of reshaping
in a way a real record cannot -- a surface that rebuilt records from known
fields would drop the unknown one and red. The producer's own record shape is
pinned one ring down, where it belongs, by the near-miss and
renamed-structure tier tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from codeclone.contracts import TIER_STATE_COMPLETE
from codeclone.report.html import build_html_report
from codeclone.report.html.primitives.escape import _escape_html
from codeclone.report.messages.overview import (
    TIER_COMPLETE_HINT,
    TIER_COUNT_ABSENT,
    TIER_DISABLED_HINT,
    TIER_DISPLAY_ORDER,
    TIER_ROW_COUNT,
    TIER_STATE_LABEL_COMPLETE,
    TIER_STATE_LABEL_DISABLED,
)
from codeclone.report.renderers.markdown import render_markdown_report_document
from codeclone.report.renderers.sarif import render_sarif_report_document
from codeclone.report.renderers.text import render_text_report_document
from codeclone.surfaces.mcp._session_shared import (
    ExecutionEvent,
    build_served_projection,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import (
    MCPAnalysisRequest,
    MCPRunRecord,
    MCPServiceContractError,
)
from tests._report_fixtures import build_test_report_document

_TIER_STATE_FIXTURES = Path(__file__).parent / "fixtures" / "tier_state"

#: The tier names as the canonical document keys them.
_TIERS = ("near_miss", "renamed_structure")

#: The baseline-tracked finding families. ``family="all"`` is exactly this
#: universe, and the advisory tiers are deliberately outside it: their records
#: reach no baseline lane, so they can be neither ``new`` nor ``known``, and a
#: total that mixed them would be a number no baseline could support.
_BASELINE_TRACKED_FAMILIES = ("clone", "structural", "dead_code", "design", "authority")


def _tier_state_document(name: str) -> dict[str, dict[str, object]]:
    """One of the two frozen distinguishing tier documents."""

    payload = json.loads((_TIER_STATE_FIXTURES / name).read_text("utf-8"))
    return {str(tier): dict(payload[tier]) for tier in _TIERS}


#: Where each tier container lists its records, and one synthetic record for
#: each. ``probe`` is a field no producer emits: a surface that rebuilt the
#: record from the fields it recognises would drop it, so its survival is the
#: evidence that records travel verbatim.
_TIER_RECORDS: dict[str, tuple[str, dict[str, object]]] = {
    "near_miss": (
        "pairs",
        {
            "pair_key": "nm-pair-0001",
            "edit_statements": 1,
            "edit_kind": "replace",
            "token_domain": "y8",
            "probe": "verbatim",
            "members": [
                {"relative_path": "pkg/mod.py", "qualname": "pkg.mod:alpha"},
                {"relative_path": "pkg/other.py", "qualname": "pkg.other:beta"},
            ],
        },
    ),
    "renamed_structure": (
        "groups",
        {
            "group_key": "rs-group-0001",
            "member_count": 2,
            "distinct_exact_fingerprints": 2,
            "probe": "verbatim",
            "members": [
                {"relative_path": "pkg/mod.py", "qualname": "pkg.mod:gamma"},
                {"relative_path": "pkg/other.py", "qualname": "pkg.other:delta"},
            ],
        },
    ),
}


#: The record-key each tier gives its own records.
_TIER_RECORD_KEY = {"near_miss": "pair_key", "renamed_structure": "group_key"}

#: A published count deliberately NOT equal to the length of the record list
#: beside it. ``count`` is what the producer measured; the record list is what
#: the document carries. Today's producers make the two agree, which is exactly
#: why a fixture built on their agreement proves nothing: it is satisfied by a
#: renderer that reads the count and equally by one that counts the list, so
#: the law "presentation never recomputes" is asserted in prose and held by no
#: instrument. A ceiling, a page, or a truncation makes the two differ
#: legitimately, and on that day the recomputing renderer reports the smaller
#: number with full confidence. These fixtures make them differ now, so the
#: pins can tell the two renderers apart before that day arrives.
_MEASURED_COUNT = 7
_CARRIED_RECORDS = 2


def _tier_containers(*, state: str) -> dict[str, dict[str, object]]:
    """Both tier containers in the requested execution state.

    ``disabled`` -- the producer never ran; ``complete_empty`` -- it ran and
    measured nothing; ``complete_populated`` -- the frozen complete container
    carrying one synthetic record (see the module docstring);
    ``complete_truncated`` -- a completed measurement of ``_MEASURED_COUNT``
    whose document carries only ``_CARRIED_RECORDS`` of those records.
    """

    if state == "disabled":
        return _tier_state_document("expected_disabled.json")
    containers = _tier_state_document("expected_complete_empty.json")
    if state == "complete_empty":
        return containers
    for tier, (records_key, record) in _TIER_RECORDS.items():
        if state == "complete_truncated":
            key = _TIER_RECORD_KEY[tier]
            containers[tier][records_key] = [
                {**record, key: f"{record[key]}-{index}"}
                for index in range(_CARRIED_RECORDS)
            ]
            containers[tier]["count"] = _MEASURED_COUNT
        else:
            containers[tier][records_key] = [dict(record)]
            containers[tier]["count"] = 1
    return containers


def _document_with_tiers(state: str) -> dict[str, object]:
    """A canonical report document whose tier containers are in ``state``."""

    document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    findings = cast("dict[str, object]", document["findings"])
    groups = cast("dict[str, object]", findings["groups"])
    groups.update(_tier_containers(state=state))
    return document


# --------------------------------------------------------------------------
# Part 1 -- MCP can name the tiers
# --------------------------------------------------------------------------


def _service_with_tiers(tmp_path: Path, state: str) -> CodeCloneMCPService:
    """A service holding one run whose tier containers are in ``state``."""

    service = CodeCloneMCPService(history_limit=4)
    record = MCPRunRecord(
        run_id=f"tier{state}0000000000",
        root=tmp_path,
        request=MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection(
            {
                "findings": {
                    "summary": {"total": 0},
                    "groups": {
                        "clones": {"functions": [], "blocks": [], "segments": []},
                        "structural": {"groups": []},
                        "dead_code": {"groups": []},
                        "design": {"groups": []},
                        "authority": {"groups": []},
                        **_tier_containers(state=state),
                    },
                }
            }
        ),
        summary={"run_id": "tier", "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=tmp_path,
            semantic_report_id=f"tier{state}0000000000",
        ),
    )
    service._runs.register(record)
    return service


@pytest.mark.parametrize("tier", _TIERS)
def test_list_findings_accepts_the_tier_families(tmp_path: Path, tier: str) -> None:
    """The defect, stated plainly: MCP could not name a tier at all."""

    service = _service_with_tiers(tmp_path, "complete_empty")

    payload = service.list_findings(run_id="tier", family=tier)

    assert payload["family"] == tier
    assert payload["tier"] == tier


@pytest.mark.parametrize("tier", _TIERS)
def test_a_disabled_tier_family_utters_no_measurement(
    tmp_path: Path, tier: str
) -> None:
    """T1's witness must survive the trip to the MCP wire.

    A tier that never ran has nothing to count. ``count``, ``total`` and
    ``items`` are omitted entirely -- omission, not 0 and not null -- because
    every one of them would read as a completed empty measurement.
    """

    service = _service_with_tiers(tmp_path, "disabled")

    payload = service.list_findings(run_id="tier", family=tier)

    assert payload["state"] == "disabled"
    for measurement_key in ("count", "total", "items", "returned", "next_offset"):
        assert measurement_key not in payload, (
            f"{tier}: a disabled tier must not utter '{measurement_key}'"
        )
    assert str(payload.get("state_note", "")).strip(), (
        f"{tier}: a disabled tier must explain its own absence of measurement"
    )


@pytest.mark.parametrize("tier", _TIERS)
def test_a_complete_empty_tier_family_is_a_measurement(
    tmp_path: Path, tier: str
) -> None:
    """``count=0`` means a completed measurement with an empty result."""

    service = _service_with_tiers(tmp_path, "complete_empty")

    payload = service.list_findings(run_id="tier", family=tier)

    assert payload["state"] == "complete"
    assert payload["count"] == 0
    assert payload["total"] == 0
    assert payload["items"] == []


def test_the_two_tier_states_are_distinguishable_on_the_mcp_wire(
    tmp_path: Path,
) -> None:
    """The killer for the collapse: the two responses must not be one."""

    disabled = _service_with_tiers(tmp_path / "off", "disabled")
    complete = _service_with_tiers(tmp_path / "on", "complete_empty")

    for tier in _TIERS:
        off = disabled.list_findings(run_id="tier", family=tier)
        on = complete.list_findings(run_id="tier", family=tier)
        assert off["state"] != on["state"], (
            f"{tier}: the disabled and complete-empty MCP responses became "
            "indistinguishable"
        )


@pytest.mark.parametrize(
    ("tier", "record_key"),
    (("near_miss", "pair_key"), ("renamed_structure", "group_key")),
)
def test_tier_records_keep_their_own_key_and_invent_no_id(
    tmp_path: Path, tier: str, record_key: str
) -> None:
    """These records have no addressable finding id, so none is manufactured."""

    service = _service_with_tiers(tmp_path, "complete_populated")

    payload = service.list_findings(run_id="tier", family=tier)

    items = cast("list[dict[str, object]]", payload["items"])
    assert payload["count"] == 1
    assert len(items) == 1
    assert str(items[0][record_key]).strip()
    assert "id" not in items[0], (
        f"{tier}: records carry {record_key}; an addressable id does not exist"
    )


@pytest.mark.parametrize("tier", _TIERS)
def test_mcp_reports_the_measurement_and_the_page_as_separate_facts(
    tmp_path: Path, tier: str
) -> None:
    """``count`` is the producer's measurement; ``total`` is what this page has.

    The same document that catches a recomputing HTML renderer is asked of
    MCP: 7 measured, 2 carried. ``count`` must be the container's number
    verbatim and ``total`` must describe the page, so a reader can see that
    the response is showing fewer records than were measured. Collapsing the
    two into one number -- in either direction -- destroys exactly that
    distinction.
    """

    service = _service_with_tiers(tmp_path, "complete_truncated")

    payload = service.list_findings(run_id="tier", family=tier)
    items = cast("list[dict[str, object]]", payload["items"])

    assert payload["count"] == _MEASURED_COUNT, (
        f"{tier}: count must restate the container's measurement"
    )
    assert payload["total"] == _CARRIED_RECORDS, (
        f"{tier}: total must describe the records this response pages over"
    )
    assert payload["returned"] == _CARRIED_RECORDS
    assert len(items) == _CARRIED_RECORDS
    assert payload["count"] != payload["total"], (
        f"{tier}: the measurement and the page collapsed into one number"
    )


def test_family_all_keeps_the_five_family_baseline_tracked_universe(
    tmp_path: Path,
) -> None:
    """The total pin: widening ``all`` is a separate contract decision.

    ``family="all"`` counts the baseline-tracked families and nothing else.
    The advisory tiers reach no baseline lane, so admitting them would move a
    published total onto evidence the baseline cannot support.
    """

    service = _service_with_tiers(tmp_path, "complete_populated")

    everything = service.list_findings(run_id="tier", family="all")
    families = {
        str(item.get("family", ""))
        for item in cast("list[dict[str, object]]", everything["items"])
    }

    assert not families & set(_TIERS), (
        f"advisory tiers leaked into the family=all universe: {sorted(families)}"
    )
    assert everything["total"] == 0
    for tier in _TIERS:
        scoped = service.list_findings(run_id="tier", family=tier)
        assert scoped["count"] == 1, (
            f"{tier}: the tier itself must still be reachable by explicit family"
        )


def test_an_unknown_family_is_still_rejected(tmp_path: Path) -> None:
    """The vocabulary widened by exactly two names, not into a free-for-all."""

    service = _service_with_tiers(tmp_path, "complete_empty")

    with pytest.raises(MCPServiceContractError):
        service.list_findings(run_id="tier", family="not_a_family")


# --------------------------------------------------------------------------
# Part 2 -- HTML shows the tier state
# --------------------------------------------------------------------------


def _html_for(state: str) -> str:
    return build_html_report(report_document=_document_with_tiers(state))


@pytest.mark.parametrize("state", ("disabled", "complete_empty", "complete_populated"))
def test_html_names_both_tiers(state: str) -> None:
    """The defect: the tiers appeared nowhere in the HTML report at all."""

    html = _html_for(state)

    for label in ("Near-miss", "Renamed structure"):
        assert label in html, f"{state}: HTML never names the {label} tier"


def test_html_distinguishes_a_disabled_tier_from_a_completed_empty_one() -> None:
    """The load-bearing pin of Part 2.

    Two documents that differ only in the tier execution witness must produce
    two different pages. A renderer that drew "0" for both would repeat, in
    the surface a human actually reads, exactly the confusion T1 removed from
    the document.
    """

    disabled = _html_for("disabled")
    complete_empty = _html_for("complete_empty")

    assert disabled != complete_empty, (
        "the disabled and the complete-empty tier documents render the same page"
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    (
        ("disabled", "disabled"),
        ("complete_empty", "complete"),
        ("complete_populated", "complete"),
    ),
)
def test_html_states_each_tier_state_verbatim(state: str, expected: str) -> None:
    """The state is shown as a word, not inferred by the reader from a count.

    Both the machine-readable attribute and the words a human reads are
    pinned. Pinning only the attribute leaves the visible label free to say
    the opposite of it -- one page, two answers -- and a page whose label
    contradicts its own data attribute is worse than one that shows neither.
    """

    html = _html_for(state)
    complete = expected == TIER_STATE_COMPLETE
    shown, absent = (
        (TIER_STATE_LABEL_COMPLETE, TIER_STATE_LABEL_DISABLED)
        if complete
        else (TIER_STATE_LABEL_DISABLED, TIER_STATE_LABEL_COMPLETE)
    )
    hint_shown, hint_absent = (
        (TIER_COMPLETE_HINT, TIER_DISABLED_HINT)
        if complete
        else (TIER_DISABLED_HINT, TIER_COMPLETE_HINT)
    )

    assert html.count(f'data-tier-state="{expected}"') == len(_TIERS), (
        f"{state}: both tier rows must carry the {expected!r} state"
    )
    assert html.count(_escape_html(shown)) == len(_TIERS), (
        f"{state}: the visible label must agree with the state attribute"
    )
    assert _escape_html(absent) not in html
    assert html.count(_escape_html(hint_shown)) == len(_TIERS)
    assert _escape_html(hint_absent) not in html


def test_html_shows_the_count_only_for_a_completed_measurement() -> None:
    """A count is a measurement; a disabled tier has none to draw.

    The absence is pinned in both registers too: no count attribute for a
    machine, and the absence stated in words for a human. A page that
    withheld the attribute but still drew a "0" in the row would show a
    reader a measurement that was never taken.
    """

    populated = _html_for("complete_populated")
    empty = _html_for("complete_empty")
    disabled = _html_for("disabled")

    assert populated.count('data-tier-count="1"') == len(_TIERS)
    assert empty.count('data-tier-count="0"') == len(_TIERS), (
        "a completed empty measurement must draw its 0"
    )
    assert "data-tier-count=" not in disabled, (
        "a disabled tier must not render a count attribute of any value"
    )
    assert disabled.count(_escape_html(TIER_COUNT_ABSENT)) == len(_TIERS), (
        "a disabled tier must state the absence of a measurement in words"
    )
    assert _escape_html(TIER_COUNT_ABSENT) not in empty


def _measured_fact_row(value: int) -> str:
    """The exact ``Measured`` fact row the overview draws for ``value``."""

    return (
        f'<span class="overview-fact-label">{_escape_html(TIER_ROW_COUNT)}</span>'
        f'<span class="overview-fact-value">{value}</span>'
    )


def test_html_draws_the_measured_count_not_the_records_it_was_handed() -> None:
    """The law in the renderer's own comment, finally held by an instrument.

    ``count`` and the record list are two facts, and this document makes them
    disagree: 7 measured, 2 carried. A renderer that reads the container draws
    7. A renderer that counts the list it was handed draws 2 -- and every pin
    built on a self-consistent fixture passes it, because there the two
    renderers are indistinguishable by construction.

    Both registers are checked, because the defect can land in either one
    alone: the number a human reads, and the attribute a machine reads.
    """

    html = _html_for("complete_truncated")

    assert html.count(_measured_fact_row(_MEASURED_COUNT)) == len(_TIERS), (
        "the overview must draw the measured count the container published"
    )
    assert _measured_fact_row(_CARRIED_RECORDS) not in html, (
        "the overview drew the length of the record list instead of the count"
    )
    assert html.count(f'data-tier-count="{_MEASURED_COUNT}"') == len(_TIERS)
    assert f'data-tier-count="{_CARRIED_RECORDS}"' not in html


def test_html_reads_the_state_from_the_document_it_was_given() -> None:
    """Presentation never recomputes: the page restates the container.

    A document whose container says ``disabled`` is drawn as disabled even
    when the tier lists records beside it -- an incoherent document CodeClone
    does not emit, which is the point: the renderer has no opinion of its own
    to fall back on.
    """

    document = _document_with_tiers("complete_populated")
    groups = cast(
        "dict[str, object]",
        cast("dict[str, object]", document["findings"])["groups"],
    )
    for tier in _TIERS:
        container = cast("dict[str, object]", groups[tier])
        container["state"] = "disabled"
        container.pop("count", None)

    html = build_html_report(report_document=document)

    assert html.count('data-tier-state="disabled"') == len(_TIERS)
    assert "data-tier-count=" not in html


def test_html_draws_the_frozen_distinguishing_documents_apart() -> None:
    """The same two documents the pipeline pin froze, drawn by the page."""

    frozen_disabled = build_test_report_document(
        func_groups={}, block_groups={}, segment_groups={}
    )
    frozen_complete = build_test_report_document(
        func_groups={}, block_groups={}, segment_groups={}
    )
    for document, name in (
        (frozen_disabled, "expected_disabled.json"),
        (frozen_complete, "expected_complete_empty.json"),
    ):
        groups = cast(
            "dict[str, object]",
            cast("dict[str, object]", document["findings"])["groups"],
        )
        groups.update(_tier_state_document(name))

    assert build_html_report(report_document=frozen_disabled) != build_html_report(
        report_document=frozen_complete
    )


# --------------------------------------------------------------------------
# Part 3 -- the subset projections declare themselves
# --------------------------------------------------------------------------


@pytest.mark.parametrize("state", ("disabled", "complete_populated"))
def test_markdown_declares_its_baseline_tracked_subset(state: str) -> None:
    """ "Total findings" is a total over the baseline-tracked families only."""

    rendered = render_markdown_report_document(_document_with_tiers(state))

    assert "baseline-tracked" in rendered
    assert "report.json" in rendered
    for tier in _TIERS:
        assert tier in rendered, (
            f"the subset declaration must name {tier} so a reader knows what "
            "was left out"
        )


@pytest.mark.parametrize("state", ("disabled", "complete_populated"))
def test_text_declares_its_baseline_tracked_subset(state: str) -> None:
    """The FINDINGS SUMMARY block says which universe it summarizes."""

    rendered = render_text_report_document(_document_with_tiers(state))

    assert "baseline-tracked" in rendered
    assert "report.json" in rendered
    for tier in _TIERS:
        assert tier in rendered


@pytest.mark.parametrize("state", ("disabled", "complete_populated"))
def test_sarif_declares_its_baseline_tracked_subset(state: str) -> None:
    """The SARIF run states its own result scope in its properties bag."""

    document = _document_with_tiers(state)
    rendered = json.loads(render_sarif_report_document(document))

    properties = rendered["runs"][0]["properties"]
    assert properties["resultScope"] == "baseline_tracked_families"
    assert sorted(properties["advisoryTiersOmitted"]) == sorted(_TIERS)
    assert "report.json" in properties["resultScopeNote"]


def test_the_subset_declaration_is_unconditional() -> None:
    """The declaration is a property of the artifact, not of the run.

    A declaration that appeared only when a tier happened to be populated
    would be silent in exactly the run where a reader most needs it -- the
    one where the tiers are off and the artifact looks complete.
    """

    for state in ("disabled", "complete_empty", "complete_populated"):
        document = _document_with_tiers(state)
        assert "baseline-tracked" in render_markdown_report_document(document)
        assert "baseline-tracked" in render_text_report_document(document)
        sarif = json.loads(render_sarif_report_document(document))
        assert sarif["runs"][0]["properties"]["resultScope"] == (
            "baseline_tracked_families"
        )


def test_the_declared_families_are_the_ones_the_artifacts_list() -> None:
    """The declaration names the same five families the artifacts enumerate."""

    document = _document_with_tiers("complete_empty")
    markdown = render_markdown_report_document(document)

    for family in _BASELINE_TRACKED_FAMILIES:
        # markdown enumerates the clone family under its plural container key.
        name = "clones" if family == "clone" else family
        assert name in markdown


def test_a_document_without_tier_containers_still_declares_the_subset() -> None:
    """Older documents carry no tier keys; the artifact still tells the truth."""

    document = build_test_report_document(
        func_groups={}, block_groups={}, segment_groups={}
    )
    groups = cast(
        "dict[str, object]",
        cast("dict[str, object]", document["findings"])["groups"],
    )
    for tier in _TIERS:
        groups.pop(tier, None)

    assert "baseline-tracked" in render_markdown_report_document(document)
    assert "baseline-tracked" in render_text_report_document(document)
    html = build_html_report(report_document=document)
    # No container means no state to restate; the page must not invent one.
    assert "data-tier-state=" not in html


def test_a_tier_pair_carries_its_token_domain_to_the_mcp_wire(
    tmp_path: Path,
) -> None:
    """Every near-miss pair declares which token space certified it."""

    service = _service_with_tiers(tmp_path, "complete_populated")

    payload = service.list_findings(run_id="tier", family="near_miss")
    items = cast("list[dict[str, object]]", payload["items"])

    assert items[0]["token_domain"] == "y8"
    assert items[0]["edit_kind"] == "replace"


@pytest.mark.parametrize("tier", _TIERS)
def test_tier_records_travel_verbatim(tmp_path: Path, tier: str) -> None:
    """The wire restates the container's records; it does not rebuild them.

    ``probe`` is a field no producer emits. A surface that reassembled each
    record from the fields it knows about would silently drop it, and the
    reader would receive a quietly narrower record than the document holds.
    """

    service = _service_with_tiers(tmp_path, "complete_populated")

    payload = service.list_findings(run_id="tier", family=tier)
    items = cast("list[dict[str, object]]", payload["items"])

    _records_key, expected = _TIER_RECORDS[tier]
    assert items == [expected]


def test_every_tier_the_document_carries_is_drawn_by_the_page() -> None:
    """The page's display list must cover the document's tier containers.

    The presentation ring cannot import the domain vocabulary that names the
    tiers, so this is where the two lists are held together: a tier the
    canonical document grows without a place on the page would red here
    rather than going quietly undrawn.
    """

    frozen = _tier_state_document("expected_complete_empty.json")

    assert set(frozen) <= set(TIER_DISPLAY_ORDER), (
        "the canonical document carries a tier container the overview panel "
        f"has no place for: {sorted(set(frozen) - set(TIER_DISPLAY_ORDER))}"
    )
    html = _html_for("complete_empty")
    for tier in frozen:
        assert f'data-tier="{tier}"' in html
