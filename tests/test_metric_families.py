# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Owner table for the computed-metric-family declaration reader.

``presentation_metric_families`` is the sole interpreter of the three key
states of ``meta.computed_metric_families``. Every presentation consumer
(HTML context, text renderer, markdown renderer) filters through it, so this
table pins the interpretation once; the per-surface tests pin only that each
surface consumes the result.
"""

from __future__ import annotations

from codeclone.api.metric_families import (
    presentation_metric_families,
    withheld_metric_families,
)

_FAMILIES = {
    "complexity": {"summary": {"total": 1}},
    "dependencies": {"summary": {"cycles": 0}},
    "health": {"summary": {"score": 90}},
}


def test_absent_key_keeps_every_family() -> None:
    """A legacy document that never declared keeps every payload family."""

    kept = presentation_metric_families({}, _FAMILIES)

    assert dict(kept) == _FAMILIES


def test_empty_declaration_keeps_no_family() -> None:
    """Declared-empty keeps nothing: the payload's zeros are not measurements."""

    kept = presentation_metric_families({"computed_metric_families": []}, _FAMILIES)

    assert dict(kept) == {}


def test_nonempty_declaration_filters_strictly() -> None:
    """A non-empty declaration keeps exactly the declared names."""

    kept = presentation_metric_families(
        {"computed_metric_families": ["health", "complexity"]}, _FAMILIES
    )

    assert set(kept) == {"complexity", "health"}


def test_key_presence_not_truthiness_separates_the_states() -> None:
    """Blank-only declared names coerce away, and the state stays declared.

    A declaration of whitespace names is a present key, so it must filter
    (strictly, to nothing) — reading it as "never declared" would be the
    truthiness conflation the three-state law exists to forbid.
    """

    kept = presentation_metric_families({"computed_metric_families": ["  "]}, _FAMILIES)

    assert dict(kept) == {}


def test_result_preserves_input_family_order() -> None:
    """The filtered mapping keeps the canonical container's order."""

    kept = presentation_metric_families(
        {"computed_metric_families": ["health", "dependencies", "complexity"]},
        _FAMILIES,
    )

    assert list(kept) == ["complexity", "dependencies", "health"]


def test_withheld_is_empty_for_a_legacy_document() -> None:
    """No declaration withholds nothing: legacy documents keep every family."""

    assert withheld_metric_families({}, _FAMILIES) == frozenset()


def test_withheld_names_everything_on_a_declared_empty_run() -> None:
    """Declared-empty withholds every family the container carries."""

    withheld = withheld_metric_families({"computed_metric_families": []}, _FAMILIES)

    assert withheld == frozenset(_FAMILIES)


def test_withheld_is_the_container_complement_of_the_declaration() -> None:
    """A partial declaration withholds exactly the undeclared container names.

    A declared name the container never carried is not withheld — there is
    nothing to withhold — so a renderer's per-family furniture for absent
    families stays a rendering decision, never a declaration verdict.
    """

    withheld = withheld_metric_families(
        {"computed_metric_families": ["health", "not_in_container"]}, _FAMILIES
    )

    assert withheld == frozenset({"complexity", "dependencies"})
