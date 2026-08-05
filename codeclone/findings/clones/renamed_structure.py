# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The declared ``renamed_structure`` clone tier (Wave C).

The strict exact tier deliberately keeps semantically meaningful names rigid,
so a pair whose only difference is a bijective, consistent renaming of local
bindings and receiver attributes never matches it. The declared rule closing
that gap:

    two clone-eligible units group as ``renamed_structure`` when their
    ordinal-canonical digests (``analysis.renamed_structure``) are equal.

An exact match in the tier's own digest domain: grouping is one dictionary
pass over digests already computed per unit — O(n), no pairwise matcher, no
similarity score, no tunable floor.

Two confinements keep the tier honest:

- A digest cohort whose members all share one strict-exact fingerprint is the
  exact tier's business and is never constructed here, mirroring "distance
  zero stays the exact tier's business" one lane over.
- This channel never enters ``func_groups``, so it reaches no observation
  lane, no baseline novelty and no gate. Advisory by construction rather than
  by a flag that could be flipped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...models import RenamedStructureGroup, RenamedStructureMember
from ...utils.coerce import as_int

if TYPE_CHECKING:
    from ...models import GroupItemLike, GroupItemsLike

__all__ = ["build_renamed_structure_groups"]


def _member(unit: GroupItemLike) -> RenamedStructureMember:
    return RenamedStructureMember(
        qualname=str(unit.get("qualname", "")),
        filepath=str(unit.get("filepath", "")),
        start_line=as_int(unit.get("start_line", 0)),
        end_line=as_int(unit.get("end_line", 0)),
        fingerprint=str(unit.get("fingerprint", "")),
    )


def build_renamed_structure_groups(
    units: GroupItemsLike,
) -> tuple[RenamedStructureGroup, ...]:
    """Return every declared renamed-structure group among clone-eligible units.

    ``units`` must already be the clone lane's population: the tier inherits
    the lane's floors instead of re-deciding eligibility. Units without a
    digest — served off a wire generation that never carried one is impossible
    by the cache contract, but an empty digest is still skipped rather than
    grouped as "equally absent".
    """

    cohorts: dict[str, list[RenamedStructureMember]] = {}
    for unit in units:
        digest = str(unit.get("renamed_fingerprint", ""))
        if digest:
            cohorts.setdefault(digest, []).append(_member(unit))
    groups: list[RenamedStructureGroup] = []
    for digest in sorted(cohorts):
        members = sorted(
            cohorts[digest],
            key=lambda member: (
                member.filepath,
                member.start_line,
                member.end_line,
                member.qualname,
            ),
        )
        if len(members) < 2:
            continue
        distinct_exact = len({member.fingerprint for member in members})
        if distinct_exact < 2:
            # Every member already matches under the strict exact tier; the
            # renamed tier would only restate that group under a second name.
            continue
        groups.append(
            RenamedStructureGroup(
                group_key=digest,
                members=tuple(members),
                distinct_exact_fingerprints=distinct_exact,
            )
        )
    return tuple(groups)
