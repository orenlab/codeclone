# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""R3 door: the sole reader of the computed-metric-family declaration.

``meta.computed_metric_families`` has three key states, and each carries its
own filter (`RP2`: absence must stay distinguishable from emptiness):

* **key absent** — a legacy document that never declared; every family the
  payload carries is kept;
* **key present and non-empty** — the run declared what it computed; the
  payload is filtered strictly to the declared names;
* **key present and empty** — the run honestly declared it computed nothing;
  no family is kept, because the zeros the payload always carries would
  otherwise render as measurements.

Key *presence* — never the truthiness of the coerced value — separates the
first state from the third. That interpretation lived inline in the HTML
context after it was first fixed, and every further consumer (the text and
markdown renderers read the same container) would have re-derived it in its
own dialect — two semantics for one fact is the drift `G2` forbids. This door
owns the interpretation; presentation rings consume its result and classify
nothing themselves (`P3`, `G1`).
"""

from __future__ import annotations

from collections.abc import Mapping

from ..utils.coerce import as_sequence as _as_sequence

_DECLARATION_KEY = "computed_metric_families"


def presentation_metric_families(
    meta: Mapping[str, object],
    families: Mapping[str, object],
) -> Mapping[str, object]:
    """Filter a family-keyed mapping by the run's family declaration.

    ``meta`` is the canonical document's ``meta`` mapping; ``families`` is any
    mapping keyed by metric-family name — ``metrics.families`` is the
    canonical container. The result preserves the input's family order and
    coerces names once, on both sides of the comparison, so a consumer can
    ask membership questions without re-spelling the declaration's law.
    """

    if _DECLARATION_KEY not in meta:
        return {str(name): payload for name, payload in families.items()}
    declared = frozenset(
        str(name)
        for name in _as_sequence(meta.get(_DECLARATION_KEY))
        if str(name).strip()
    )
    return {
        str(name): payload
        for name, payload in families.items()
        if str(name) in declared
    }


def withheld_metric_families(
    meta: Mapping[str, object],
    families: Mapping[str, object],
) -> frozenset[str]:
    """Family names the declaration withholds from this container.

    The second projection of the same interpretation: a renderer that keeps
    per-family furniture (a section heading with no items) for families the
    container never carried must still drop exactly what the declaration
    removed. Answering "was this family withheld" here keeps that question
    from being re-derived beside each section loop. A name absent from the
    container is never withheld — there is nothing to withhold.
    """

    kept = presentation_metric_families(meta, families)
    return frozenset(str(name) for name in families if str(name) not in kept)


__all__ = ["presentation_metric_families", "withheld_metric_families"]
