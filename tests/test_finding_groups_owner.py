# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One owner walks the finding-family containers; every consumer asks it.

The defect (wave 5, t4-b): the predicate "walk the finding families of a
report document and collect their groups" was implemented independently in
eleven closed enumerations. Each one spelled the five container keys itself,
each one restated that the clone family holds three sibling lists while the
other four nest under ``groups``, and one of them -- the CLI changed-scope
gate -- had silently lost the ``authority`` family from a total it publishes.
A shape spelled eleven times is eleven chances to disagree, and the project
has already paid for that class once, in a document that stated both
"seventeen suppressed" and "zero".

The pins here are causal, not descriptive. The universe a consumer walks is
read from the owner **at call time**, so redirecting the owner's declared
family tuple must move every consumer at once: a consumer that kept its own
enumeration stays on five families while the owner says one, and reds. That
mutation -- "give one consumer back its own list" -- is the whole proof that
the reduction happened, and it is run against every converted surface below.

The four frozen invariants of t4-a are pinned here too, because this is
exactly the change that could move them by accident:

1. ``family="all"`` stays the five baseline-tracked families;
2. published totals do not move (including the changed-scope subset, which
   stays four families **by declaration** rather than by omission);
3. the advisory tiers are never members of the clone family and never enter a
   total;
4. the tier state witness still reaches the surfaces it reached.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: The container keys the canonical document uses for the baseline-tracked
#: families. Spelled here independently of production so that a production
#: change to the vocabulary has to be argued against this list.
_CONTAINER_KEYS = ("clones", "structural", "dead_code", "design", "authority")

#: The same container keys spelled as the constants production imports.
_CONTAINER_KEY_BY_CONSTANT = {
    "FAMILY_CLONES": "clones",
    "FAMILY_STRUCTURAL": "structural",
    "FAMILY_DEAD_CODE": "dead_code",
    "FAMILY_DESIGN": "design",
    "FAMILY_AUTHORITY": "authority",
}

#: The advisory tiers. Containers, never families, never totals.
_TIER_KEYS = ("near_miss", "renamed_structure")

#: The module that owns the walk.
_OWNER_MODULE = "codeclone.utils.finding_groups"

#: Production modules allowed to spell more than one family container key.
#: The owner holds the law; contracts holds the vocabulary; the producer of
#: the container necessarily writes every key it publishes.
_OWNER_FILES = frozenset(
    {
        "codeclone/utils/finding_groups.py",
        "codeclone/contracts/__init__.py",
        "codeclone/report/document/findings.py",
    }
)


def _owner() -> Any:
    return importlib.import_module(_OWNER_MODULE)


# --------------------------------------------------------------------------
# Fixtures -- one finding in each family, both tiers populated
# --------------------------------------------------------------------------


def _group(*, family: str, category: str, gid: str) -> dict[str, object]:
    return {
        "id": gid,
        "family": family,
        "category": category,
        "severity": "info",
        "novelty": "known",
        "count": 1,
        "clone_kind": category if family == "clone" else "",
        "source_scope": {
            "impact_scope": "non_runtime",
            "dominant_kind": "production",
        },
        "facts": {"contract_id": "c-1"},
        "items": [
            {
                "relative_path": "pkg/mod.py",
                "qualname": "pkg.mod:fn",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
    }


_ONE_PER_FAMILY: dict[str, dict[str, object]] = {
    "clones": {
        "functions": [_group(family="clone", category="function", gid="cl-1")],
        "blocks": [],
        "segments": [],
    },
    "structural": {
        "groups": [
            _group(family="structural", category="duplicated_branches", gid="st-1")
        ]
    },
    "dead_code": {
        "groups": [_group(family="dead_code", category="function", gid="dc-1")]
    },
    "design": {
        "groups": [
            _group(
                family="design",
                category="instance_independent_method",
                gid="ds-1",
            )
        ]
    },
    "authority": {
        "groups": [
            _group(family="authority", category="authority_violation", gid="au-1")
        ]
    },
}

_TIER_CONTAINERS: dict[str, dict[str, object]] = {
    "near_miss": {
        "state": "complete",
        "algorithm_revision": "1",
        "gate_relevant": False,
        "novelty": "untracked",
        "count": 1,
        "max_edit_statements": 1,
        "pairs": [
            {
                "pair_key": "nm-1",
                "edit_statements": 1,
                "members": [{"relative_path": "pkg/mod.py"}],
            }
        ],
    },
    "renamed_structure": {
        "state": "complete",
        "algorithm_revision": "1",
        "gate_relevant": False,
        "novelty": "untracked",
        "count": 1,
        "groups": [
            {
                "group_key": "rs-1",
                "member_count": 2,
                "members": [{"relative_path": "pkg/mod.py"}],
            }
        ],
    },
}


def _findings_payload() -> dict[str, object]:
    return {
        "summary": {"total": 5, "families": {}},
        "groups": {
            **{key: dict(value) for key, value in _ONE_PER_FAMILY.items()},
            **{key: dict(value) for key, value in _TIER_CONTAINERS.items()},
        },
    }


def _document() -> dict[str, object]:
    return {"findings": _findings_payload()}


def _full_document() -> dict[str, object]:
    """A producer-built document whose family containers carry one group each."""

    from tests._report_fixtures import build_test_report_document

    document = build_test_report_document(
        func_groups={}, block_groups={}, segment_groups={}
    )
    findings = cast("dict[str, object]", document["findings"])
    groups = cast("dict[str, object]", findings["groups"])
    for key, payload in _ONE_PER_FAMILY.items():
        existing = cast("dict[str, object]", groups.setdefault(key, {}))
        existing.update({k: list(cast("list[object]", v)) for k, v in payload.items()})
    groups.update({key: dict(value) for key, value in _TIER_CONTAINERS.items()})
    return document


def _ids(groups: Sequence[Mapping[str, object]]) -> set[str]:
    return {str(group.get("id", "")) for group in groups if group.get("id")}


# --------------------------------------------------------------------------
# The owner exists, and it declares the five-family universe
# --------------------------------------------------------------------------


def test_the_universe_is_the_five_baseline_tracked_container_keys() -> None:
    """Invariant 1: the declared universe is five families, tiers excluded."""

    owner = _owner()
    assert tuple(owner.BASELINE_TRACKED_GROUP_KEYS) == _CONTAINER_KEYS
    for tier in _TIER_KEYS:
        assert tier not in owner.BASELINE_TRACKED_GROUP_KEYS


def _domain_baseline_tracked_families() -> tuple[str, ...]:
    """``domain.findings.BASELINE_TRACKED_FAMILIES``, read from its source.

    Read rather than imported on purpose: ``codeclone.domain`` is ring ``r2``
    and this module is ``r4``, an edge the boundary ratchet is closing and
    whose allowlist is shrink-only. Parsing the declaration also pins what is
    actually written there, which is what a drift check wants.
    """

    module = ast.parse(
        (_REPO_ROOT / "codeclone" / "domain" / "findings.py").read_text("utf-8")
    )
    constants: dict[str, str] = {}
    families: tuple[str, ...] = ()
    for statement in module.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(
            statement.target, ast.Name
        ):
            continue
        name = statement.target.id
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            constants[name] = value.value
        elif name == "BASELINE_TRACKED_FAMILIES" and isinstance(value, ast.Tuple):
            families = tuple(
                constants[element.id]
                for element in value.elts
                if isinstance(element, ast.Name)
            )
    assert families, "BASELINE_TRACKED_FAMILIES was not found in its own module"
    return families


def test_the_container_keys_track_the_domain_family_vocabulary() -> None:
    """The container spelling is derived from the family vocabulary, not guessed.

    The two live in different rings and are two different vocabularies -- a
    finding says ``clone``, its container is keyed ``clones``. Pinning the
    relation is what stops them drifting apart silently; mutating either side
    reds here.
    """

    owner = _owner()
    expected = tuple(
        "clones" if family == "clone" else family
        for family in _domain_baseline_tracked_families()
    )
    assert tuple(owner.BASELINE_TRACKED_GROUP_KEYS) == expected


def test_the_owner_walk_excludes_the_tier_containers() -> None:
    """Invariant 3: a tier record never arrives as a clone-family member."""

    owner = _owner()
    root = owner.groups_root_of_document(_document())
    flat = owner.flatten_finding_groups(root)
    assert _ids(flat) == {"cl-1", "st-1", "dc-1", "ds-1", "au-1"}
    assert not any("pair_key" in group or "group_key" in group for group in flat)


# --------------------------------------------------------------------------
# The causal pin: every consumer asks the owner
# --------------------------------------------------------------------------


def _clone_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the owner's declared universe to the clone family alone."""

    monkeypatch.setattr(_owner(), "BASELINE_TRACKED_GROUP_KEYS", ("clones",))


def test_flat_list_consumers_follow_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: give either of these back its own enumeration and it reds."""

    from codeclone.report.renderers.sarif import _flatten_findings as sarif_flatten
    from codeclone.report.renderers.text import _flatten_findings as text_flatten

    findings = _findings_payload()
    document = _document()

    consumers: dict[str, Callable[[], Sequence[Mapping[str, object]]]] = {
        "renderers.text": lambda: text_flatten(findings),
        "renderers.sarif": lambda: sarif_flatten(document),
    }
    for name, call in consumers.items():
        assert _ids(call()) == {"cl-1", "st-1", "dc-1", "ds-1", "au-1"}, name

    _clone_only(monkeypatch)
    for name, call in consumers.items():
        assert _ids(call()) == {"cl-1"}, (
            f"{name} did not follow the owner: it kept its own family enumeration"
        )


def _producer_document() -> dict[str, object]:
    """A document the real producer built, carrying two finding families.

    The producer is asked for the document rather than the walk: the derived
    overview lives in ``codeclone.report.overview`` and the review queue in
    ``codeclone.report.document.derived``, both ring ``r2``, and this module is
    ``r4`` on an edge whose allowlist is shrink-only. Two families is all the
    pin needs -- the universe is redirected below, and a consumer that kept its
    own enumeration cannot follow.
    """

    from tests._report_fixtures import (
        build_test_report_document,
        health_family_for_population,
    )

    return build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={
            "dead_code": {
                "summary": {},
                "items": [
                    {
                        "qualname": "pkg.mod:dead",
                        "relative_path": "pkg/mod.py",
                        "kind": "function",
                        "confidence": "high",
                        "start_line": 10,
                        "end_line": 12,
                    }
                ],
            },
            "health": health_family_for_population(found=10, analyzed=10),
            "semantic_authority": {
                "summary": {},
                "items": [
                    {
                        "item_kind": "violation",
                        "contract_id": "c-1",
                        "relative_path": "pkg/mod.py",
                        "qualname": "pkg.mod:Thing",
                        "violation_kind": "duplicate_owner",
                        "canonical_owner": "pkg.mod",
                        "authority_status": "contested",
                        "resolution_state": "open",
                        "start_line": 3,
                        "end_line": 5,
                    }
                ],
            },
        },
    )


def _derived_populations() -> tuple[int, int]:
    """(overview source-scope population, review-queue population)."""

    document = _producer_document()
    derived = cast("dict[str, object]", document["derived"])
    overview = cast("dict[str, object]", derived["overview"])
    breakdown = cast("dict[str, int]", overview["source_scope_breakdown"])
    review_queue = cast("dict[str, object]", derived["review_queue"])
    summary = cast("dict[str, object]", review_queue["summary"])
    return sum(breakdown.values()), int(cast("int", summary["total"]))


def test_the_derived_document_consumers_follow_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two ``r2`` walkers, reached through the document they help build.

    Both directions are mutated: narrowing the universe to a family the
    document carries must drop the other, and narrowing it to a family the
    document does not carry must empty both populations. A consumer holding a
    private five-family list answers the same number every time and reds on the
    first assertion.
    """

    assert _derived_populations() == (2, 2)

    monkeypatch.setattr(_owner(), "BASELINE_TRACKED_GROUP_KEYS", ("dead_code",))
    assert _derived_populations() == (1, 1), (
        "the derived overview or the review queue kept its own family enumeration"
    )

    monkeypatch.setattr(_owner(), "BASELINE_TRACKED_GROUP_KEYS", ("clones",))
    assert _derived_populations() == (0, 0), (
        "the derived overview or the review queue kept its own family enumeration"
    )


def test_the_mcp_finding_universe_follows_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.mcp.service import CodeCloneMCPService
    from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPRunRecord

    service = CodeCloneMCPService(history_limit=4)
    record = MCPRunRecord(
        run_id="ownercheck00000000",
        root=Path("."),
        request=MCPAnalysisRequest(root=".", respect_pyproject=False),
        comparison_settings=(),
        report_document=_document(),
        summary={"run_id": "owner", "health": {"score": 0, "grade": "N/A"}},
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
    service._runs.register(record)

    assert _ids(service._base_findings(record)) == {
        "cl-1",
        "st-1",
        "dc-1",
        "ds-1",
        "au-1",
    }
    _clone_only(monkeypatch)
    assert _ids(service._base_findings(record)) == {"cl-1"}


def test_the_mcp_report_section_family_vocabulary_follows_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.mcp import _report_section
    from codeclone.surfaces.mcp._session_shared import MCPServiceContractError

    findings = _findings_payload()
    payload = _report_section.findings_section_payload(
        findings, family="structural", offset=0, limit=50
    )
    assert _ids(cast("list[Mapping[str, object]]", payload["items"])) == {"st-1"}

    _clone_only(monkeypatch)
    with pytest.raises(MCPServiceContractError):
        _report_section.findings_section_payload(
            findings, family="structural", offset=0, limit=50
        )


def test_the_changed_scope_gate_follows_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.surfaces.cli.changed_scope import _flatten_report_findings

    document = _document()
    assert _ids(_flatten_report_findings(document)) == {
        "cl-1",
        "st-1",
        "dc-1",
        "ds-1",
    }
    _clone_only(monkeypatch)
    assert _ids(_flatten_report_findings(document)) == {"cl-1"}


def test_the_section_renderers_follow_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """markdown and text draw one section per family the owner names."""

    from codeclone.report.renderers.markdown import render_markdown_report_document
    from codeclone.report.renderers.text import render_text_report_document

    document = _full_document()
    markdown = render_markdown_report_document(document)
    text = render_text_report_document(document)
    for gid in ("st-1", "dc-1", "ds-1", "au-1"):
        assert gid in markdown, gid
        assert gid in text, gid

    _clone_only(monkeypatch)
    markdown = render_markdown_report_document(document)
    text = render_text_report_document(document)
    for gid in ("st-1", "dc-1", "ds-1", "au-1"):
        assert gid not in markdown, f"markdown kept its own section list ({gid})"
        assert gid not in text, f"text kept its own section list ({gid})"


# --------------------------------------------------------------------------
# The text artifact's two family-summary lines
# --------------------------------------------------------------------------
#
# The section walk above was converted; the two *summary* lines were not.
# They enumerate the families over ``findings.summary.families`` -- a mapping,
# not the group container -- so the mechanical ratchet at the bottom of this
# module cannot see them by construction, and they kept a private four-family
# list while the total printed beside them counted five. On this repository
# the ``authority`` family is empty, so the breakdown and the total agree for
# the wrong reason; the fixtures below carry a non-empty one.


#: A key no family and no tier will ever use. It answers in the probe mapping
#: below so that a renderer which widened its universe to *anything* shows it.
_DECOY_FAMILY_KEY = "not_a_family"


def _text_family_lines(rendered: str) -> tuple[tuple[tuple[str, str], ...], ...]:
    """Every ``Families:`` line of the text artifact, as key/value pairs.

    Two lines carry this label -- the FINDINGS SUMMARY breakdown and the
    DERIVED OVERVIEW one -- and they are read together on purpose: they render
    the same mapping through two call sites, which is how one of them could
    have been converted and the other left behind.
    """

    lines: list[tuple[tuple[str, str], ...]] = []
    for line in rendered.splitlines():
        if not line.startswith("Families:"):
            continue
        body = line.split(":", 1)[1].strip()
        lines.append(
            tuple(
                (token.split("=", 1)[0], token.split("=", 1)[1])
                for token in body.split(" ")
                if "=" in token
            )
        )
    return tuple(lines)


def _rendered_text(document: Mapping[str, object]) -> str:
    from codeclone.report.renderers.text import render_text_report_document

    return render_text_report_document(dict(document))


def _findings_summary(document: Mapping[str, object]) -> Mapping[str, object]:
    findings = cast("dict[str, object]", dict(document)["findings"])
    return cast("dict[str, object]", findings["summary"])


def test_the_text_family_breakdown_accounts_for_the_total_beside_it() -> None:
    """The published breakdown and the published total are one artifact.

    ``_producer_document`` is the distinguishing fixture: its two findings sit
    in *different* families and one of them is ``authority``. A document whose
    ``authority`` family is empty -- every document this repository produces
    for itself -- makes both numbers agree whether or not the family is named,
    which is precisely why a four-family enumeration survived here.
    """

    document = _producer_document()
    summary = _findings_summary(document)
    families = cast("dict[str, object]", summary["families"])
    assert int(cast("int", summary["total"])) == 2
    assert int(cast("int", families["authority"])) == 1, (
        "the fixture stopped distinguishing: the pin needs a non-empty "
        "authority family, or it passes for the wrong reason"
    )

    breakdowns = _text_family_lines(_rendered_text(document))
    assert len(breakdowns) == 2, "the text artifact publishes two Families lines"
    for pairs in breakdowns:
        assert sum(int(value) for _key, value in pairs) == 2, (
            "a Families line published a breakdown that does not add up to the "
            f"total printed beside it: {pairs}"
        )


def _document_answering_every_family_key() -> dict[str, object]:
    """A document whose family summary answers *any* key a renderer asks for.

    The text renderer prints a key only when the mapping carries it, so
    against a document that answers the five real families a renderer which
    had widened its universe to an advisory tier renders identically -- the
    widening is unobservable, and a pin that never sees it is theatre. This
    document therefore answers every family, both tiers and a decoy, so the
    rendered line *is* the set of keys the renderer asked for.

    The producer never writes a tier key into ``findings.summary.families``.
    This is an instrument for reading a renderer's universe, not a claim about
    the document the producer emits.
    """

    document = _producer_document()
    answers: dict[str, object] = {
        **dict.fromkeys(_CONTAINER_KEYS, 0),
        **dict.fromkeys(_TIER_KEYS, 0),
        _DECOY_FAMILY_KEY: 0,
    }
    summary = cast("dict[str, object]", _findings_summary(document))
    summary["families"] = dict(answers)
    derived = cast("dict[str, object]", document["derived"])
    overview = cast("dict[str, object]", derived["overview"])
    overview["families"] = dict(answers)
    return document


def test_the_text_family_lines_name_the_declared_universe_and_nothing_else() -> None:
    """Both lines list the owner's families, in the owner's order.

    Mutated in both directions against the probe document: dropping a family
    shortens the line, and admitting a tier -- or the decoy -- lengthens it.
    Invariant 3 is the half that a normal document cannot show.
    """

    owner = _owner()
    expected = tuple(owner.BASELINE_TRACKED_GROUP_KEYS)
    lines = _text_family_lines(_rendered_text(_document_answering_every_family_key()))

    assert len(lines) == 2
    for pairs in lines:
        assert tuple(key for key, _value in pairs) == expected, (
            "a Families line does not publish the declared family universe"
        )
        for tier in _TIER_KEYS:
            assert tier not in dict(pairs), (
                f"an advisory tier reached a published family breakdown: {tier}"
            )
        assert _DECOY_FAMILY_KEY not in dict(pairs)


def test_the_text_family_lines_follow_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation: give either line back its own list and it reds.

    The redirected universe is reordered as well as narrowed, so a consumer
    that kept a private tuple cannot match by accident even if the tuple
    happened to hold the same names.
    """

    document = _document_answering_every_family_key()
    monkeypatch.setattr(
        _owner(), "BASELINE_TRACKED_GROUP_KEYS", ("dead_code", "clones")
    )

    lines = _text_family_lines(_rendered_text(document))
    assert len(lines) == 2
    for pairs in lines:
        assert tuple(key for key, _value in pairs) == ("dead_code", "clones"), (
            "a Families line kept its own family enumeration"
        )


# --------------------------------------------------------------------------
# Invariant 2 -- published totals do not move
# --------------------------------------------------------------------------


def test_the_changed_scope_universe_is_a_declared_subset_not_an_omission() -> None:
    """``findings_total`` on ``--changed-only`` stays four families.

    The CLI gate never counted the ``authority`` family. That total reaches
    the user, so widening it is a contract decision and not a side effect of
    removing a copy. The subset is therefore named and derived from the
    owner's tuple, so the omission is a declaration a reader can see.
    """

    from codeclone.surfaces.cli import changed_scope

    owner = _owner()
    assert changed_scope.changed_scope_group_keys() == tuple(
        key for key in owner.BASELINE_TRACKED_GROUP_KEYS if key != "authority"
    )
    gate = changed_scope._changed_clone_gate_from_report(
        _document(), changed_paths=("pkg/mod.py",)
    )
    assert gate.findings_total == 4


def test_the_producer_total_stays_five_family() -> None:
    """The document's own ``findings.summary`` universe is unchanged."""

    document = _full_document()
    summary = cast(
        "dict[str, object]",
        cast("dict[str, object]", document["findings"])["summary"],
    )
    families = cast("dict[str, object]", summary["families"])
    assert set(families) == {
        "clones",
        "structural",
        "dead_code",
        "design",
        "authority",
    }
    assert summary["total"] == sum(int(cast("int", v)) for v in families.values())


# --------------------------------------------------------------------------
# The two universal walkers keep their universe
# --------------------------------------------------------------------------


def test_the_universal_walkers_still_reach_every_published_container() -> None:
    """They read one structural law, and it is wider than the five families."""

    owner = _owner()
    published = owner.iter_published_group_lists(_document())
    seen = {(family, container_key) for family, container_key, _entries in published}
    assert ("near_miss", "pairs") in seen
    assert ("renamed_structure", "groups") in seen
    assert ("clones", "functions") in seen


def test_the_universal_walkers_still_drop_the_tiers_on_novelty() -> None:
    """Tier records reach the walkers and are declined on a stated predicate."""

    from codeclone.api.finding_groups import iter_finding_groups

    refs = iter_finding_groups(_document())
    tier_refs = [ref for ref in refs if ref.family in _TIER_KEYS]
    assert tier_refs, "the universal walker stopped reaching the tier containers"
    assert all(
        str(ref.group.get("novelty", "")) not in {"new", "known"} for ref in tier_refs
    )


# --------------------------------------------------------------------------
# The mechanical inventory ratchet
# --------------------------------------------------------------------------


#: Parameter names through which a unit receives the findings-group container.
_ROOT_PARAM_NAMES = frozenset({"groups", "groups_root", "findings_groups"})


def _is_findings_mapping(expr: ast.expr) -> bool:
    """True when ``expr`` yields the document's ``findings`` section."""

    if isinstance(expr, ast.Name):
        return "findings" in expr.id or expr.id in {"document", "report_document"}
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and expr.args:
            argument = expr.args[0]
            return isinstance(argument, ast.Constant) and argument.value == "findings"
        return len(expr.args) == 1 and _is_findings_mapping(expr.args[0])
    return False


def _is_groups_navigation(expr: ast.expr, roots: frozenset[str]) -> bool:
    """True when ``expr`` itself yields the ``findings.groups`` container.

    The spine is followed rather than the whole subtree: a name that merely
    appears somewhere inside a larger expression is not that expression's
    value. And ``groups`` is a key at two depths -- the container under
    ``findings``, and the list inside each non-clone family -- so the receiver
    has to be the findings section, or every ``family.get("groups")`` read
    would register as a second container.
    """

    if isinstance(expr, ast.Name):
        return expr.id in roots
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and expr.args:
            argument = expr.args[0]
            return (
                isinstance(argument, ast.Constant)
                and argument.value == "groups"
                and _is_findings_mapping(func.value)
            )
        # A coercion wrapper: ``_as_mapping(findings.get("groups"))``.
        return len(expr.args) == 1 and _is_groups_navigation(expr.args[0], roots)
    return False


def _sections_root_targets(statement: ast.Assign) -> set[str]:
    """Names bound to ``findings.groups`` by a positional ``sections(...)`` call.

    ``findings_summary, groups, clones = sections(document, "findings.summary",
    "findings.groups", "findings.groups.clones")`` binds one name to the
    container and two names to other sections; only the matching position is
    the container.
    """

    value = statement.value
    if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name):
        return set()
    if value.func.id != "sections" or len(statement.targets) != 1:
        return set()
    target = statement.targets[0]
    if not isinstance(target, ast.Tuple):
        return set()
    paths = value.args[1:]
    if len(paths) != len(target.elts):
        return set()
    return {
        element.id
        for element, path in zip(target.elts, paths, strict=True)
        if isinstance(element, ast.Name)
        and isinstance(path, ast.Constant)
        and path.value == "findings.groups"
    }


def _groups_root_names(node: ast.AST) -> frozenset[str]:
    """Names inside one unit that hold the findings-group container."""

    roots: set[str] = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = node.args
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            if argument.arg in _ROOT_PARAM_NAMES:
                roots.add(argument.arg)
    changed = True
    while changed:
        changed = False
        for statement in ast.walk(node):
            if not isinstance(statement, ast.Assign):
                continue
            bound = _sections_root_targets(statement)
            if _is_groups_navigation(statement.value, frozenset(roots)):
                bound.update(
                    target.id
                    for target in statement.targets
                    if isinstance(target, ast.Name)
                )
            for name in bound - roots:
                roots.add(name)
                changed = True
    return frozenset(roots)


class _ContainerKeyReads(ast.NodeVisitor):
    """Collect family container keys a unit reads out of the groups container.

    Only reads whose receiver is the container itself count. A metrics family
    named ``dead_code`` and a finding-family value named ``structural`` are the
    same strings in other places, so a ratchet that matched on the string alone
    would flag units that never touch this container -- and an allowlist for
    those would be the very thing this reduction exists to avoid.
    """

    def __init__(self, roots: frozenset[str]) -> None:
        self.keys: set[str] = set()
        self._roots = roots

    def _record(self, node: ast.expr) -> None:
        if isinstance(node, ast.Constant) and node.value in _CONTAINER_KEYS:
            self.keys.add(str(node.value))
            return
        # The same key spelled through its constant. A ratchet that only saw
        # string literals would be satisfied by a copy that imported the
        # vocabulary and re-enumerated it, which is the same second walk.
        name = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else ""
        )
        key = _CONTAINER_KEY_BY_CONSTANT.get(name)
        if key is not None:
            self.keys.add(key)

    def _receiver_is_root(self, expr: ast.expr) -> bool:
        return isinstance(expr, ast.Name) and expr.id in self._roots

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and node.args
            and self._receiver_is_root(func.value)
        ):
            self._record(node.args[0])
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._receiver_is_root(node.value):
            self._record(node.slice)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        # ``for family in ("structural", "dead_code", ...)`` is the same walk
        # written as a loop; the keys never reach a ``.get`` call site as
        # literals, so the read rule alone would let this spelling through.
        if self._roots and isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            for element in node.iter.elts:
                self._record(element)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        if self._roots and isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            for element in node.iter.elts:
                self._record(element)
        self.generic_visit(node)


def _family_enumeration_sites() -> list[str]:
    sites: list[str] = []
    for path in sorted((_REPO_ROOT / "codeclone").rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative in _OWNER_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            roots = _groups_root_names(node)
            if not roots:
                continue
            visitor = _ContainerKeyReads(roots)
            visitor.visit(node)
            if len(visitor.keys) >= 2:
                sites.append(
                    f"{relative}:{node.lineno} {node.name} {sorted(visitor.keys)}"
                )
    return sites


def test_no_consumer_spells_the_family_container_keys_itself() -> None:
    """The mechanical ratchet: one owner, and it is the only enumeration.

    Grep is blind to this class by construction -- the keys are ordinary
    strings that also appear as finding-family values in severity tables and
    message maps. The predicate here is structural: reading two or more family
    container keys **out of a mapping** in one function is a second walk, and
    there is exactly one place entitled to do it.
    """

    sites = _family_enumeration_sites()
    assert sites == [], (
        "finding-family container enumeration outside the owner:\n" + "\n".join(sites)
    )
