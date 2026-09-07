# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The two producer shapes the canonical wire used to refuse, pinned on data.

Measured 2026-09-05 against 21 frozen external repositories (their SHAs are
recorded in the columnar benchmark's ``PREREGISTRATION.json``):
``canonical_model_from_legacy_document`` refused 18 of the 21 documents,
every one of them produced by this project's own CLI.  Two shapes accounted
for all 18, and neither existed in any fixture in this suite -- which is
precisely why the wire froze without either being seen:

* **A clone group of one item.**  378 singleton ``segments`` groups across
  17 of the 21 members (143 in sympy, 42 in networkx, 37 in kivy, 5 in
  click); ``functions`` and ``blocks`` carried none anywhere.
* **A dependency endpoint outside the identity index.**  ``packaging`` in
  kivy and ``pyglet.experimental`` in pyglet -- both namespace packages.

Both are resolved, and this module now pins the resolutions rather than the
refusals.  Each shape is pinned at BOTH boundaries, because a rule that only
removes is indistinguishable from a rule that removes too much:

* the singleton stage emits nothing, while the F8 stage's multi-occurrence
  segment groups are untouched -- the same reading, in the same module, on a
  document where the population exists;
* the namespace endpoint resolves, while the same document with its prefix
  node withdrawn is refused again, verbatim.

This module's subject is ``codeclone.canonical`` (ring r2), per the Phase
39S test-import law.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from codeclone.canonical import (
    SemanticGrammarError,
    canonical_model_from_legacy_document,
)
from codeclone.canonical.identity import ModuleId

#: The refusal ``parse_endpoint`` raises for an endpoint in NO registry lane,
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


def _clone_groups(document: dict[str, object], kind: str) -> list[dict[str, Any]]:
    groups = _section(document, "findings", "groups", "clones", kind)
    assert isinstance(groups, list)
    return groups


# ---------------------------------------------------------------------------
# Shape 1: a clone group of one item
# ---------------------------------------------------------------------------


def test_the_f8_stage_still_publishes_every_multi_occurrence_segment_group(
    corpus_f8_report: dict[str, object],
) -> None:
    """The positive control the singleton pins are read against.

    Probe Validity: "the singleton stage emits no segment group" is a
    statement about an empty container, and an empty container is also what a
    reading that lost the whole lane would produce.  This test proves the
    same reading finds segment groups where they exist -- three of them, each
    naming two occurrences -- and that the arity rule left every one of them,
    and both other clone kinds, exactly as they were.
    """
    segments = _clone_groups(corpus_f8_report, "segments")
    assert [len(group["items"]) for group in segments] == [2, 2, 2]
    assert all(group["count"] == 2 for group in segments)
    assert [
        len(group["items"]) for group in _clone_groups(corpus_f8_report, "functions")
    ] == [4]
    assert sorted(
        len(group["items"]) for group in _clone_groups(corpus_f8_report, "blocks")
    ) == [2, 3]
    summary = _section(corpus_f8_report, "findings", "summary", "clones")
    assert summary["segments"] == 3
    assert summary["functions"] == 1
    assert summary["blocks"] == 2


def test_the_f8_singleton_stage_emits_no_segment_group_at_all(
    corpus_f8_singleton_report: dict[str, object],
) -> None:
    """The producer stops making the shape at its source.

    The stage's two hosts still carry the raw windows -- ``segments`` groups
    of two and of six windows inside one function -- and both merge branches
    still run.  What changed is that a run that normalizes to ONE occurrence
    is no longer a clone group: the report says nothing rather than saying
    "2 segment / repeated segment / consider a shared utility" about one
    occurrence.

    Measured cost, stated here rather than discovered later: this document's
    whole clones family and whole finding total go to zero.
    """
    assert _clone_groups(corpus_f8_singleton_report, "segments") == []
    summary = _section(corpus_f8_singleton_report, "findings", "summary")
    assert summary["total"] == 0
    assert summary["families"].get("clones", 0) == 0
    # Exhaustive rather than key-by-key: the clone counters are one shape, and
    # naming every key means a counter added or renamed here fails loudly
    # instead of silently escaping the pin.
    assert summary["clones"] == {
        "functions": 0,
        "blocks": 0,
        "segments": 0,
        "instances": 0,
        "new": 0,
        "known": 0,
        "unavailable": 0,
    }


def test_f8_singleton_document_ingests_whole(
    corpus_f8_singleton_report: dict[str, object],
) -> None:
    """The wire-freeze end state: a document this CLI produced ingests.

    This assertion carried a ``strict`` xfail while the producer emitted
    groups of one; the marker went red the day the producer stopped, which is
    what it was written to do.
    """
    model = canonical_model_from_legacy_document(corpus_f8_singleton_report)
    assert model.facts.analysis.clone_groups == frozenset()


def test_the_f8_document_with_real_clone_groups_still_ingests_whole(
    corpus_f8_report: dict[str, object],
) -> None:
    """The other boundary of the ingest: six real groups still cross."""
    model = canonical_model_from_legacy_document(corpus_f8_report)
    rows = model.facts.analysis.clone_groups
    per_kind: dict[str, int] = {}
    for row in rows:
        per_kind[row.clone_kind] = per_kind.get(row.clone_kind, 0) + 1
    assert per_kind == {"function": 1, "block": 2, "segment": 3}
    assert all(len(row.items) >= 2 for row in rows)


# ---------------------------------------------------------------------------
# Shape 2: a dependency endpoint outside the identity index
# ---------------------------------------------------------------------------


def test_f7_namespace_stage_emits_an_endpoint_no_file_bearing_entry_names(
    corpus_f7_namespace_report: dict[str, object],
) -> None:
    """The full accounting for the endpoint, from the document itself.

    Every clause is measured, because the resolution only means what the next
    test says it means if all four hold at once: the edge is emitted, its
    target is a namespace package the registry itself lists, and that target
    is neither a file-bearing module nor an analyzed path -- so it resolves
    through the prefix lane and through nothing else.  The 21-repository
    corpus shows the same four clauses for kivy's ``packaging`` and pyglet's
    ``pyglet.experimental``.
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


def test_f7_namespace_document_ingests_whole(
    corpus_f7_namespace_report: dict[str, object],
) -> None:
    """The wire-freeze end state, and what the endpoint became.

    The namespace package enters the MODULE domain -- the domain the producer
    asserted for it by calling it an internal target -- and the dependency
    relation names it.  This assertion carried a ``strict`` xfail while the
    grammar saw only file-bearing pairs.
    """
    model = canonical_model_from_legacy_document(corpus_f7_namespace_report)
    relations = model.facts.analysis.dependency_relations
    assert {(row.source, row.target) for row in relations} == {
        (ModuleId("user"), ModuleId("nsp"))
    }
    assert ModuleId("nsp") in model.modules


def test_withdrawing_the_prefix_node_restores_the_refusal_verbatim(
    corpus_f7_namespace_report: dict[str, object],
) -> None:
    """The opposite boundary, on the SAME causal path.

    The control perturbs the one thing the resolution now depends on -- the
    registry's ``package_prefixes`` -- and nothing else, so a green result
    above cannot be coming from a neighbouring mechanism that happens to
    admit the string.  With the prefix node withdrawn the document is refused
    again, with the message unchanged: the refusal that guards every endpoint
    naming nothing the run knows is still the one that guards them.
    """
    document = copy.deepcopy(corpus_f7_namespace_report)
    registry = _section(document, "source_facts", "module_registry")
    assert registry["package_prefixes"], "the control needs a prefix node to withdraw"
    registry["package_prefixes"] = []

    with pytest.raises(SemanticGrammarError) as excinfo:
        canonical_model_from_legacy_document(document)
    assert str(excinfo.value) == _ENDPOINT_REFUSAL
