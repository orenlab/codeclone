# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""R3 door: the sole reader of the canonical findings-group container.

``findings.groups`` is not one shape. Non-clone families hold their groups
under a ``groups`` key; the clone family holds three sibling **lists** plus a
``suppressed`` **mapping** one level deeper, whose bucket keys are plural while
the groups inside carry their kind in the singular. Three consumers each
re-derived that shape from the raw document and each got it wrong in its own
way, so one document could state both "seventeen suppressed" and "zero".

This module is the one place that knows the container's shape. It answers on
terms a consumer cannot mis-spell:

* a group's ``category`` comes from the **group**, never from the JSON key that
  happens to hold it — a container key is a container key, not a finding's
  classification (`G2`);
* suppressed groups are keyed by the kind the **group** declares, so the
  producer's bucket spelling is never load-bearing in a consumer;
* an absent ``suppressed`` container is distinguishable from an empty one
  (`G4`, `RP2`), because the producer omits the key entirely when nothing was
  suppressed and "did not run" must not read as "ran and found nothing".

This is a reader. It classifies nothing the canonical report has not already
classified, and it computes no finding facts (`P3`, `G1`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

# The three clone kinds are re-exported from here, not restated downstream. A
# renderer keying its own presentation by kind has to name a kind, and the
# domain module that declares them sits in a ring no presentation layer may
# import; spelling them again there would put one vocabulary in two places and
# hand every reader a second chance to spell it differently (`G2`).
from ..domain.findings import (
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    FAMILY_CLONES,
)
from ..utils.coerce import as_mapping as _as_mapping
from ..utils.coerce import as_sequence as _as_sequence

#: The key under which the clone family nests its suppressed buckets. This is
#: the single site in the codebase that spells it: that is the point.
SUPPRESSED_CONTAINER_KEY: Final = "suppressed"

#: The full document path of that container, declared rather than spelled at
#: the point of use. Navigation reads it below, so it is load-bearing and
#: cannot rot into a decorative constant; a guard that wants to know which
#: address only this module may spell takes it from here instead of restating
#: it, which is how a guard survives the key being renamed.
SUPPRESSED_CONTAINER_PATH: Final[tuple[str, ...]] = (
    "findings",
    "groups",
    FAMILY_CLONES,
    SUPPRESSED_CONTAINER_KEY,
)

#: Canonical presentation order for suppressed clone kinds. The HTML panel
#: declares this order to its readers in prose, so it is a contract of the
#: owner rather than an accident of mapping iteration.
SUPPRESSED_KIND_ORDER: Final[tuple[str, ...]] = (
    CLONE_KIND_FUNCTION,
    CLONE_KIND_BLOCK,
    CLONE_KIND_SEGMENT,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class FindingGroupRef:
    """One finding group with the facts a consumer needs to place it."""

    family: str
    category: str
    suppressed: bool
    group: Mapping[str, object]


@dataclass(frozen=True, kw_only=True, slots=True)
class SuppressedCloneGroups:
    """The suppressed clone lane of one report document.

    ``present`` records whether the document published the container at all,
    which is not the same question as whether it holds anything.
    """

    present: bool
    groups: tuple[Mapping[str, object], ...]
    by_kind: Mapping[str, tuple[Mapping[str, object], ...]]

    @property
    def count(self) -> int:
        return len(self.groups)


def _group_category(group: Mapping[str, object]) -> str:
    """Return the category the group declares for itself.

    There is deliberately no fallback to the container key. A group that does
    not classify itself is reported as unclassified, because substituting the
    JSON key is exactly the defect this module exists to remove.
    """

    return str(group.get("category", "")).strip()


def _group_kind(group: Mapping[str, object]) -> str:
    """Return the clone kind the group declares, preferring its own terms."""

    kind = str(group.get("clone_kind", "")).strip()
    return kind or _group_category(group)


def _groups_in(payload: object) -> tuple[Mapping[str, object], ...]:
    return tuple(
        mapping
        for raw in _as_sequence(payload)
        for mapping in (_as_mapping(raw),)
        if mapping
    )


def _suppressed_container(document: Mapping[str, object]) -> object | None:
    *ancestors, container_key = SUPPRESSED_CONTAINER_PATH
    current: Mapping[str, object] = document
    for segment in ancestors:
        current = _as_mapping(current.get(segment))
    if container_key not in current:
        return None
    return current[container_key]


def suppressed_clone_groups(
    document: Mapping[str, object],
) -> SuppressedCloneGroups:
    """Return every suppressed clone group the document publishes.

    Bucket keys are read structurally, not by name: every list inside the
    container holds suppressed clone groups. A consumer therefore cannot lose
    groups by spelling a bucket key the way it wishes the producer had spelled
    it — the failure mode that had the review receipt counting zero against a
    document publishing seventeen.

    Ordering is by declared kind, then document order within a kind, so the
    order a consumer renders is a property of this owner rather than of JSON
    mapping iteration.
    """

    container = _suppressed_container(document)
    if container is None:
        empty: dict[str, tuple[Mapping[str, object], ...]] = dict.fromkeys(
            SUPPRESSED_KIND_ORDER, ()
        )
        return SuppressedCloneGroups(present=False, groups=(), by_kind=empty)

    collected: list[Mapping[str, object]] = []
    for _bucket_key, bucket in sorted(
        _as_mapping(container).items(), key=lambda item: str(item[0])
    ):
        collected.extend(_groups_in(bucket))

    by_kind: dict[str, tuple[Mapping[str, object], ...]] = {}
    for kind in SUPPRESSED_KIND_ORDER:
        by_kind[kind] = tuple(
            group for group in collected if _group_kind(group) == kind
        )

    ordered: list[Mapping[str, object]] = []
    for kind in SUPPRESSED_KIND_ORDER:
        ordered.extend(by_kind[kind])
    # A group whose kind the producer did not declare is still a suppressed
    # group. It is reported last rather than dropped: a reader silently losing
    # rows is the defect class this module closes.
    known = set(SUPPRESSED_KIND_ORDER)
    ordered.extend(group for group in collected if _group_kind(group) not in known)

    return SuppressedCloneGroups(
        present=True,
        groups=tuple(ordered),
        by_kind=by_kind,
    )


def iter_finding_groups(
    document: Mapping[str, object],
) -> tuple[FindingGroupRef, ...]:
    """Walk every finding group in the document, active and suppressed.

    The clone family's ``suppressed`` container is descended into rather than
    read as a list of groups, which is what silently yielded nothing to a
    consumer running a sequence coercion over a mapping.
    """

    findings = _as_mapping(document.get("findings"))
    groups = _as_mapping(findings.get("groups"))
    refs: list[FindingGroupRef] = []
    for family, family_payload in sorted(groups.items(), key=lambda item: str(item[0])):
        family_name = str(family)
        for container_key, container_payload in sorted(
            _as_mapping(family_payload).items(), key=lambda item: str(item[0])
        ):
            if (
                family_name == FAMILY_CLONES
                and str(container_key) == SUPPRESSED_CONTAINER_KEY
            ):
                continue
            refs.extend(
                FindingGroupRef(
                    family=family_name,
                    category=_group_category(group),
                    suppressed=False,
                    group=group,
                )
                for group in _groups_in(container_payload)
            )

    refs.extend(
        FindingGroupRef(
            family=FAMILY_CLONES,
            category=_group_category(group),
            suppressed=True,
            group=group,
        )
        for group in suppressed_clone_groups(document).groups
    )
    return tuple(refs)


def suppressed_group_items(
    group: Mapping[str, object],
) -> Sequence[Mapping[str, object]]:
    """Return one suppressed group's items as mappings."""

    return _groups_in(group.get("items"))


__all__ = [
    "CLONE_KIND_BLOCK",
    "CLONE_KIND_FUNCTION",
    "CLONE_KIND_SEGMENT",
    "SUPPRESSED_CONTAINER_KEY",
    "SUPPRESSED_CONTAINER_PATH",
    "SUPPRESSED_KIND_ORDER",
    "FindingGroupRef",
    "SuppressedCloneGroups",
    "iter_finding_groups",
    "suppressed_clone_groups",
    "suppressed_group_items",
]
