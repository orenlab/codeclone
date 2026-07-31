# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Clone health arithmetic, stated in the words the report renders.

The clones health dimension is a density score: active function and block clone
groups over analyzed files (``codeclone.metrics.health.compute_health``). A long
list of clone cards therefore says nothing about the score on its own, which is
why every surface that shows the cards also states the arithmetic behind them.

Two rules hold this module together:

* the dimension weight is always read from ``HEALTH_WEIGHTS``, so a rendered
  contribution can never drift from the contract that computed the score;
* duplication is reported as a density and as deduplicated participants, never
  as a share of files or of callables -- one group can span files, one file can
  hold several groups, and one callable can participate in several groups.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...contracts import HEALTH_WEIGHTS
from ...utils.coerce import as_int as _as_int
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence

__all__ = [
    "CLONES_DIMENSION",
    "clone_health_note_sentences",
    "clone_health_points",
    "clone_health_score",
    "clone_health_summary_sentence",
]

#: Health dimension whose score this module explains.
CLONES_DIMENSION = "clones"

#: Buckets of the canonical clone group projection.
_CLONE_BUCKETS = ("functions", "blocks", "segments")


def _number(value: float) -> str:
    """Format a health-point value without trailing zeros (25.0 -> ``25``)."""

    return f"{value:g}"


def clone_health_score(document: Mapping[str, object]) -> int | None:
    """Return the clones dimension score, or ``None`` when it was not computed."""

    families = _as_mapping(_as_mapping(document.get("metrics")).get("families"))
    summary = _as_mapping(_as_mapping(families.get("health")).get("summary"))
    dimensions = _as_mapping(summary.get("dimensions"))
    if CLONES_DIMENSION not in dimensions:
        return None
    return _as_int(dimensions.get(CLONES_DIMENSION))


def clone_health_points(document: Mapping[str, object]) -> tuple[str, str]:
    """Return the contributed and maximum health points as display strings.

    Both are empty when the clones dimension was not computed. The weight comes
    from ``HEALTH_WEIGHTS``: this is the only place the product is formed.
    """

    score = clone_health_score(document)
    if score is None:
        return ("", "")
    weight = HEALTH_WEIGHTS[CLONES_DIMENSION]
    return (_number(score * weight), _number(100 * weight))


def _analyzed_files(document: Mapping[str, object]) -> int:
    """Return the file population the clone density is measured against.

    Cache hits are analyzed files whose facts came off the cache wire, so they
    count here exactly as they do in the health denominator.
    """

    files = _as_mapping(_as_mapping(document.get("inventory")).get("files"))
    return _as_int(files.get("analyzed")) + _as_int(files.get("cached"))


def _unique_callables(document: Mapping[str, object]) -> int:
    """Count distinct callables participating in any active clone group.

    Participants are deduplicated across groups: a callable that appears in a
    function group and again in a block group is one callable, not two.
    """

    groups = _as_mapping(
        _as_mapping(_as_mapping(document.get("findings")).get("groups")).get("clones")
    )
    participants: set[tuple[str, str]] = set()
    for bucket in _CLONE_BUCKETS:
        for raw_group in _as_sequence(groups.get(bucket)):
            for raw_item in _as_sequence(_as_mapping(raw_group).get("items")):
                item = _as_mapping(raw_item)
                qualname = str(item.get("qualname", "")).strip()
                if qualname:
                    participants.add((str(item.get("relative_path", "")), qualname))
    return len(participants)


def clone_health_note_sentences(document: Mapping[str, object]) -> tuple[str, ...]:
    """Return the clone health arithmetic as ready-to-render sentences.

    Returns an empty tuple when the clones dimension was not computed: an
    unavailable score is stated by absence, never by a placeholder number.
    """

    score = clone_health_score(document)
    if score is None:
        return ()

    weight = HEALTH_WEIGHTS[CLONES_DIMENSION]
    points, max_points = clone_health_points(document)
    summary = _as_mapping(
        _as_mapping(_as_mapping(document.get("findings")).get("summary")).get("clones")
    )
    scored_groups = _as_int(summary.get("functions")) + _as_int(summary.get("blocks"))
    segment_groups = _as_int(summary.get("segments"))
    suppressed_groups = _as_int(summary.get("suppressed"))
    instances = _as_int(summary.get("instances"))
    analyzed_files = _analyzed_files(document)
    unique_callables = _unique_callables(document)

    sentences = [
        f"Clones health {score}/100: {score} \u00d7 {_number(weight * 100)}% = "
        f"{points} of {max_points} health points."
    ]
    if analyzed_files > 0:
        sentences.append(
            f"Density: {scored_groups} active groups (functions and blocks) "
            f"across {analyzed_files} analyzed files — a density, not a "
            "share of files."
        )
    instance_sentence = f"Instances: {instances} duplicated fragments"
    if unique_callables > 0:
        instance_sentence += f"; {unique_callables} unique callables participate"
    sentences.append(f"{instance_sentence}.")
    if segment_groups > 0:
        sentences.append(f"Segment groups reported but not scored: {segment_groups}.")
    if suppressed_groups > 0:
        sentences.append(
            "Accepted groups excluded by suppression policy before scoring: "
            f"{suppressed_groups}."
        )
    return tuple(sentences)


def clone_health_summary_sentence(document: Mapping[str, object]) -> str:
    """Return the score-and-density opening of the note, for dimension legends.

    Derived from :func:`clone_health_note_sentences` so the health profile and
    the clones panel can never state the same arithmetic differently.
    """

    return " ".join(clone_health_note_sentences(document)[:2])
