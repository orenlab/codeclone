# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The two producer shapes the canonical wire refuses, pinned on data.

Measured 2026-09-05 against 21 frozen external repositories (their SHAs are
recorded in the columnar benchmark's ``PREREGISTRATION.json``):
``canonical_model_from_legacy_document`` refused 18 of the 21 documents,
every one of them produced by this project's own CLI.  Two shapes account
for all 18, and neither existed in any fixture in this suite -- which is
precisely why the wire froze without either being seen:

* **A clone group of one item.**  378 singleton ``segments`` groups across
  17 of the 21 members (143 in sympy, 42 in networkx, 37 in kivy, 5 in
  click); ``functions`` and ``blocks`` carried none anywhere.
* **A dependency endpoint outside the identity index.**  ``packaging`` in
  kivy and ``pyglet.experimental`` in pyglet -- both namespace packages.

These pins state what the producer emits and what the oracle answers TODAY.
They do not choose a resolution: whether a group of one is a legitimate
statement, and whether a namespace-package endpoint is the producer's defect
or the grammar's, are contract decisions for the maintainer.  What the pins
guarantee is that neither shape can go back to being invisible, and that
whichever resolution lands must be taken deliberately -- every assertion
here fails loudly the day the behaviour moves.

This module's subject is ``codeclone.canonical`` (ring r2), per the Phase
39S test-import law.
"""

from __future__ import annotations

from typing import Any

import pytest

from codeclone.canonical import (
    CanonicalModelError,
    SemanticGrammarError,
    canonical_model_from_legacy_document,
)

#: The refusal ``CloneGroupRow.__post_init__`` raises, verbatim.
_GROUP_OF_ONE_REFUSAL = (
    "a clone group names at least two items (a group of one is not a "
    "grouping the producer makes)"
)

#: The refusal ``parse_endpoint`` raises for the F7-namespace stage,
#: verbatim.  The corpus members spell ``packaging`` and
#: ``pyglet.experimental`` where this stage spells ``nsp``.
_ENDPOINT_REFUSAL = (
    "dependencies.target: endpoint 'nsp' is neither a registry module nor "
    "an analyzed path"
)


def _section(document: dict[str, object], *path: str) -> Any:
    node: Any = document
    for key in path:
        assert isinstance(node, dict), f"{key}: not a mapping"
        assert key in node, f"{key}: absent"
        node = node[key]
    return node


def _segment_groups(document: dict[str, object]) -> list[dict[str, Any]]:
    groups = _section(document, "findings", "groups", "clones", "segments")
    assert isinstance(groups, list)
    return groups


# ---------------------------------------------------------------------------
# Shape 1: a clone group of one item
# ---------------------------------------------------------------------------


def test_f8_singleton_stage_emits_segment_groups_of_exactly_one_item(
    corpus_f8_singleton_report: dict[str, object],
) -> None:
    """The distinguishing case EXISTS in a fixture, through both branches.

    Probe Validity: a stage that emitted no singleton group would let every
    other pin in this module pass vacuously, so the population is counted
    before anything is concluded from it.  Two groups, one per host, because
    ``merge_overlapping_items`` folds overlapping and adjacent windows
    through different comparisons -- a stage carrying one branch would leave
    the other unproven, which is how the shape stayed invisible until now.
    """
    groups = _segment_groups(corpus_f8_singleton_report)
    assert len(groups) == 2
    assert sorted(group["items"][0]["qualname"] for group in groups) == [
        "pkg.adjacent_host:adjacent_host",
        "pkg.overlap_host:overlap_host",
    ]
    for group in groups:
        assert len(group["items"]) == 1
        assert group["count"] == 1
        assert group["facts"]["group_arity"] == 1
        assert group["spread"] == {"files": 1, "functions": 1}
    # No other clone kind carries the shape -- the same asymmetry the 21
    # frozen repositories show, where functions and blocks were clean
    # everywhere and only segments ever produced a group of one.
    for kind in ("functions", "blocks"):
        other = _section(corpus_f8_singleton_report, "findings", "groups", "clones")[
            kind
        ]
        assert all(len(group["items"]) > 1 for group in other)


def test_f8_singleton_groups_reach_the_user_as_clone_findings(
    corpus_f8_singleton_report: dict[str, object],
) -> None:
    """A group of one is not an internal residue: it is served as a finding.

    Measured on this document -- the two singleton groups are the whole
    ``clones`` family and the whole finding total, each carries a stable
    ``id``, and the summary counts them as segment clones and as clone
    instances.  This is the user-visible number a resolution that drops
    them would move, so it is stated here rather than assumed.
    """
    summary = _section(corpus_f8_singleton_report, "findings", "summary")
    assert summary["total"] == 2
    assert summary["families"]["clones"] == 2
    assert summary["severity"]["info"] == 2
    # Exhaustive rather than key-by-key: the clone counters are one shape,
    # and naming every key means a counter added or renamed here fails loudly
    # instead of silently escaping the pin.
    assert summary["clones"] == {
        "functions": 0,
        "blocks": 0,
        "segments": 2,
        "instances": 2,
        "new": 0,
        "known": 0,
        "unavailable": 2,
    }
    groups = _segment_groups(corpus_f8_singleton_report)
    assert len(groups) == 2
    for group in groups:
        assert group["family"] == "clone"
        assert group["kind"] == "clone_group"
        assert group["severity"] == "info"
        assert str(group["id"]).startswith("clone:segment:")


def test_f8_singleton_group_keeps_no_trace_of_the_merge_that_made_it(
    corpus_f8_singleton_report: dict[str, object],
) -> None:
    """The wire cannot tell one occurrence from several folded into one.

    The group reached the document because at least two raw windows carried
    one segment hash inside one function; the merge coalesced their spans
    and every surviving counter reads 1.  Nothing in the emitted row records
    the pre-merge arity, so a reader -- the canonical model included -- has
    no field that would let it distinguish the two situations.  This bears
    directly on the contract decision and is therefore measured, not
    described in a comment.
    """
    groups = _segment_groups(corpus_f8_singleton_report)
    # An empty population would let every clause below pass without ever
    # being evaluated; the count is the licence to read the loop's result.
    assert len(groups) == 2
    for group in groups:
        assert group["count"] == len(group["items"]) == 1
        assert group["facts"]["group_arity"] == 1
        item = group["items"][0]
        # The merged span is the ONLY surviving evidence of the fold, and it
        # is not labelled as merged: it is spelled exactly like a lone
        # window's span.
        assert set(item) == {
            "relative_path",
            "qualname",
            "start_line",
            "end_line",
            "size",
            "segment_hash",
            "segment_sig",
        }
        assert item["size"] == item["end_line"] - item["start_line"] + 1


def test_f8_singleton_document_is_refused_by_the_canonical_oracle(
    corpus_f8_singleton_report: dict[str, object],
) -> None:
    """The control beside the strict xfail below.

    A strict xfail that fails for the wrong reason keeps passing long after
    its defect is gone.  This pins the exact type and message, so the xfail
    is known to be xfailing for the measured refusal and not for a typo, an
    import error, or a second unrelated defect further along the ingest.
    """
    with pytest.raises(CanonicalModelError) as excinfo:
        canonical_model_from_legacy_document(corpus_f8_singleton_report)
    assert str(excinfo.value) == _GROUP_OF_ONE_REFUSAL


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CloneGroupRow refuses a group of one; the segment lane emits them. "
        "Measured 2026-09-05: 378 such groups across 17 of 21 frozen "
        "repositories, 16 of which the oracle could not ingest for this "
        "reason alone. Awaiting the maintainer's contract decision -- either "
        "the producer stops emitting them (a user-visible clone count that "
        "falls) or the model admits them (and the report must say what a "
        "group of one means)."
    ),
)
def test_f8_singleton_document_ingests_whole(
    corpus_f8_singleton_report: dict[str, object],
) -> None:
    """The wire-freeze end state: a document this CLI produced ingests."""
    canonical_model_from_legacy_document(corpus_f8_singleton_report)


# ---------------------------------------------------------------------------
# Shape 2: a dependency endpoint outside the identity index
# ---------------------------------------------------------------------------


def test_f7_namespace_stage_emits_an_endpoint_no_registry_entry_names(
    corpus_f7_namespace_report: dict[str, object],
) -> None:
    """The full accounting for the endpoint, from the document itself.

    Every clause is measured, because the refusal only means what this test
    says it means if all four hold at once: the edge is emitted, its target
    is a namespace package the registry itself lists, and that target is
    neither a file-bearing module nor an analyzed path -- the two things the
    grammar's index is built from.  The 21-repository corpus shows the same
    four clauses for kivy's ``packaging`` and pyglet's ``pyglet.experimental``.
    """
    items = _section(
        corpus_f7_namespace_report, "metrics", "families", "dependencies", "items"
    )
    assert [(item["source"], item["target"]) for item in items] == [("user", "nsp")]

    registry = _section(corpus_f7_namespace_report, "source_facts", "module_registry")
    prefixes = registry["package_prefixes"]
    namespace_modules = {
        prefix["module"]
        for prefix in prefixes
        if prefix["node_kind"] == "namespace_package"
    }
    assert "nsp" in namespace_modules

    file_bearing = {
        entry["identity"]["python_module"]["module"]
        for _path, entry in registry["entries_by_path"]["rows"]
        if entry["identity"]["python_module"] is not None
    }
    assert file_bearing == {"nsp.leaf", "user"}
    assert "nsp" not in file_bearing

    scope = _section(corpus_f7_namespace_report, "source_facts", "analysis_scope")
    analyzed = {entry["path"] for entry in scope}
    assert analyzed == {"nsp/leaf.py", "user.py"}
    assert "nsp" not in analyzed


def test_f7_namespace_document_is_refused_by_the_canonical_oracle(
    corpus_f7_namespace_report: dict[str, object],
) -> None:
    """The control beside the strict xfail below -- exact type and message."""
    with pytest.raises(SemanticGrammarError) as excinfo:
        canonical_model_from_legacy_document(corpus_f7_namespace_report)
    assert str(excinfo.value) == _ENDPOINT_REFUSAL


@pytest.mark.xfail(
    strict=True,
    reason=(
        "parse_endpoint resolves a dependency endpoint against file-bearing "
        "registry modules and analyzed paths only, while the producer's own "
        "_is_internal_target admits a package_prefixes node. Measured "
        "2026-09-05: kivy and pyglet emit exactly this. Awaiting the "
        "maintainer's contract decision on which of the two spellings of "
        "'internal module' is authoritative."
    ),
)
def test_f7_namespace_document_ingests_whole(
    corpus_f7_namespace_report: dict[str, object],
) -> None:
    """The wire-freeze end state: a document this CLI produced ingests."""
    canonical_model_from_legacy_document(corpus_f7_namespace_report)
