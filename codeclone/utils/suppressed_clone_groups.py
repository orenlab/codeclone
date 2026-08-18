# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""How a report document's suppressed clone container is read — the law itself.

``findings.groups.clones.suppressed`` is a mapping one level deeper than its
sibling lists, its bucket keys are plural, and the groups inside carry their
kind in the singular. Every consumer that re-derived those facts got them wrong
in its own way, and one document came to state both "seventeen suppressed" and
"zero".

The reading is here rather than beside a consumer because of who has to do it.
The blast-radius computation is in the analysis ring and feeds review context
from this container; the report door that serves the renderers is a ring the
analysis layer may not import at all. Only the contracts ring and this one are
reachable from both, so this is where a single reading can live — the same
reason ``mapping_paths`` sits here. Placement is decided by the graph, not by
which consumer asked first.

What lives here is the **law**, not the service:

* navigation to the container, from the address the contracts module declares,
  answering ``None`` when the producer published no container at all — absence
  is not emptiness, and a consumer must be able to tell "no lane ran" from "the
  lane ran and held nothing" (`G4`, `RP2`);
* collection, which reads bucket keys **structurally**: every list inside the
  container holds suppressed clone groups. A consumer therefore cannot lose
  groups by spelling a bucket the way it wishes the producer had spelled it,
  and no hedge across candidate spellings is needed or permitted.

What does *not* live here is presentation: which kinds are shown, in what
order, and how an unclassified group is placed are contracts of the surface
that publishes them to a reader, and the analysis ring has no use for them.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..contracts import SUPPRESSED_CONTAINER_PATH
from .coerce import as_mapping, as_sequence


def suppressed_clone_container(document: Mapping[str, object]) -> object | None:
    """Return the raw suppressed container, or ``None`` when it is absent.

    ``None`` means the document published no container: the producer omits the
    key entirely when nothing was suppressed. An empty mapping means the
    container is there and holds nothing, which is a different fact and MUST
    stay distinguishable from the first (`G4`).
    """

    *ancestors, container_key = SUPPRESSED_CONTAINER_PATH
    current: Mapping[str, object] = document
    for segment in ancestors:
        current = as_mapping(current.get(segment))
    if container_key not in current:
        return None
    return current[container_key]


def suppressed_clone_groups_in(container: object) -> tuple[Mapping[str, object], ...]:
    """Return every suppressed clone group inside one container.

    Bucket keys are read structurally, not by name: every list inside the
    container holds suppressed clone groups, whatever the producer called the
    bucket. Buckets are visited in sorted key order and groups keep their
    document order within a bucket, so the sequence is a function of the
    document and not of mapping iteration.
    """

    return tuple(
        mapping
        for _bucket_key, bucket in sorted(
            as_mapping(container).items(), key=lambda item: str(item[0])
        )
        for raw in as_sequence(bucket)
        for mapping in (as_mapping(raw),)
        if mapping
    )


__all__ = ["suppressed_clone_container", "suppressed_clone_groups_in"]
