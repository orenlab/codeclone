# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""How a report document's finding families are walked — the law itself.

``findings.groups`` holds one container per family, and the containers do not
agree on shape: the clone family carries three sibling **lists** keyed by
bucket, every other family nests its groups under a single ``groups`` key, and
two advisory tiers key sibling containers that are not families at all. The
predicate "walk the families and collect their groups" was written eleven times
against that shape — in the derived overview, the review queue, the text,
markdown and SARIF renderers, the MCP finding and report-section surfaces and
the CLI changed-scope gate — and the copies had already diverged: the CLI gate
counts four families into a total it publishes to the user, having quietly lost
``authority``.

**Why here.** The consumers sit in three rings the boundary ratchet keeps
apart: the derived overview and the report overview are ``r2``, the renderers
and both surface packages are ``r4``, and the presentation door is ``r3``. An
``r4`` module may not import ``r2`` and an ``r2`` module may not import ``r3``,
so the only rings every consumer can reach are ``contracts`` and this one —
the same graph argument that placed ``suppressed_clone_groups`` here, and the
reason the owner is not in ``api`` where a presentation-only door would have
gone. Placement is decided by the frozen edges, not by which consumer asked
first; putting it anywhere else would have meant new boundary-allowlist
entries, and that allowlist is shrink-only.

**What lives here** is the walk and the universe it walks:

* navigation to the container from the address ``contracts`` declares;
* one family's groups, read through the shape that family actually uses, so a
  consumer never spells the clone asymmetry itself;
* the flat list over a **declared** universe. The default universe is the five
  baseline-tracked families; a consumer that must walk fewer says so with an
  explicit subset, which turns a silent omission into a visible declaration;
* the **structural** walk — every list the document publishes under every
  family container, tiers included — for the two universal walkers, which
  filter by a stated predicate of their own rather than by a hard-coded family
  list.

The universe is resolved from the module attribute at call time, on purpose.
That is what makes the reduction provable: redirecting
``BASELINE_TRACKED_GROUP_KEYS`` moves every consumer at once, and a consumer
that kept a private enumeration stays behind and reds
(``tests/test_finding_groups_owner.py``).

**What does not live here** is presentation — section titles, anchors, sort
order and which kinds a surface shows are contracts of the surface that
publishes them — and classification: this module reads, and computes no
finding fact.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from ..contracts import (
    BASELINE_TRACKED_GROUP_KEYS,
    CLONE_GROUP_BUCKET_KEYS,
    FAMILY_CLONES,
    FINDING_GROUPS_PATH,
    NESTED_GROUPS_KEY,
)
from .coerce import as_mapping, as_sequence


def baseline_tracked_group_keys(
    *,
    exclude: Collection[str] = (),
) -> tuple[str, ...]:
    """Return the declared family universe, less an explicitly named subset.

    Resolved from the module attribute on every call so that a consumer's
    universe is provably the owner's universe.
    """

    excluded = frozenset(exclude)
    return tuple(key for key in BASELINE_TRACKED_GROUP_KEYS if key not in excluded)


def groups_root_of_document(document: Mapping[str, object]) -> Mapping[str, object]:
    """Navigate a whole report document to its finding-group container."""

    current: Mapping[str, object] = document
    for segment in FINDING_GROUPS_PATH:
        current = as_mapping(current.get(segment))
    return current


def groups_root_of_findings(findings: Mapping[str, object]) -> Mapping[str, object]:
    """Navigate the document's ``findings`` section to the same container.

    Two entry points because two rings hold two different slices of the same
    document, not because the address is ambiguous: both walk
    ``FINDING_GROUPS_PATH``, one of them from one segment in.
    """

    return as_mapping(findings.get(FINDING_GROUPS_PATH[-1]))


def family_group_list(
    groups_root: Mapping[str, object],
    family: str,
) -> tuple[Mapping[str, object], ...]:
    """Return one family's active groups, in document order.

    The clone family's three buckets are concatenated in their declared order;
    every other family is read from its nested ``groups`` key. The clone
    family's ``suppressed`` container is NOT included: a suppressed group
    carries no novelty term and enters no total, and the surfaces that show it
    read it through ``utils.suppressed_clone_groups``.
    """

    container = as_mapping(groups_root.get(family))
    if family == FAMILY_CLONES:
        return tuple(
            as_mapping(raw)
            for bucket in CLONE_GROUP_BUCKET_KEYS
            for raw in as_sequence(container.get(bucket))
        )
    return tuple(
        as_mapping(raw) for raw in as_sequence(container.get(NESTED_GROUPS_KEY))
    )


def iter_family_groups(
    groups_root: Mapping[str, object],
    *,
    families: Collection[str] | None = None,
) -> dict[str, tuple[Mapping[str, object], ...]]:
    """Return each declared family's groups, keyed by family, in walk order.

    A plain mapping rather than a record type: insertion order carries the
    declared order, and this project keeps model definitions in the model
    store (``test_architecture``), so a walk living in ``utils`` does not get
    to add one.
    """

    keys = baseline_tracked_group_keys() if families is None else tuple(families)
    return {family: family_group_list(groups_root, family) for family in keys}


def flatten_finding_groups(
    groups_root: Mapping[str, object],
    *,
    families: Collection[str] | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Return every group of the declared universe as one flat sequence."""

    return tuple(
        group
        for groups in iter_family_groups(groups_root, families=families).values()
        for group in groups
    )


def iter_published_group_lists(
    document: Mapping[str, object],
) -> tuple[tuple[str, str, Sequence[object]], ...]:
    """Return every group list the document publishes, tiers included.

    Each entry is ``(family_key, container_key, entries)``. This is the
    *structural* universe, not the declared one: whatever families and
    containers the document carries, in sorted order so the sequence is a
    function of the document rather than of mapping iteration. A container
    whose value is not a list — the clone family's ``suppressed`` mapping, a
    tier's ``state`` string, its ``count`` — yields no entries, which is the
    reading both universal walkers already performed.

    ``entries`` is handed over uncoerced. The two walkers apply different
    policies to a malformed entry — one keeps the empty mapping, one drops it
    — and both were correct before this module existed; coercing here would
    have silently picked a winner and moved a number.
    """

    root = groups_root_of_document(document)
    return tuple(
        (str(family), str(container_key), as_sequence(value))
        for family, family_payload in sorted(
            root.items(), key=lambda item: str(item[0])
        )
        for container_key, value in sorted(
            as_mapping(family_payload).items(), key=lambda item: str(item[0])
        )
    )


__all__ = [
    "baseline_tracked_group_keys",
    "family_group_list",
    "flatten_finding_groups",
    "groups_root_of_document",
    "groups_root_of_findings",
    "iter_family_groups",
    "iter_published_group_lists",
]
