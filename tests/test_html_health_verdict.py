# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One health score, one verdict, read from the document that published it.

The overview drew the same health score twice and graded it twice, with two
different sets of cutoffs it had made up: the ring coloured itself at 75/60
and the executive banner toned itself at 80/60. Between 75 and 79 the page
contradicted itself -- a green ring above a warning sentence about one number.
This repository scores 89, where the two sets happen to agree, which is why
nothing ever pointed at it.

The document already carries the verdict. ``metrics.summary.health.grade`` is
produced by ``codeclone.metrics.health._grade`` and by nothing else, and it is
the only grading of health CodeClone publishes. So the renderer stops grading:
it reads the letter and translates it into a tone. The translation is a table
over letters, in one place, and both drawings ask it -- not two lists of
numbers that agree until someone edits one of them.

The table introduces no band and moves no user-facing colour. ``A``/``B`` are
exactly the scores the ring already painted ``--success`` (``B`` starts at 75),
``C`` exactly those it painted ``--warning``, ``D``/``F`` exactly those it
painted ``--error``; every score renders the colour it rendered before. The
banner is what changes, in 75-79 only, and it changes towards the published
grade rather than away from it.

Every pin below fixes the score and varies the letter, or fixes the letter and
varies the score. A verdict that still came from the number cannot survive the
first; a renderer that ignored the letter cannot survive the second. A fixture
at 89 would have passed under both the old code and the new one, so no fixture
here sits where the old sets agreed.

The producer's grade table is deliberately not imported. This module lives in
the presentation ring, which does not reach into ``codeclone.metrics`` or
``codeclone.models``, and the document it reads types the field as a plain
string -- so at this boundary there is no enumerated vocabulary to consult.
The letters below are restated rather than derived, and a letter this page has
never heard of is drawn as no verdict at all, which is the safe direction and
is pinned like everything else.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

import pytest

from codeclone.report.html import build_html_report
from codeclone.report.html.primitives.escape import _escape_html
from codeclone.report.messages.overview import EXECUTIVE_QUESTION
from tests._report_fixtures import build_test_report_document

_DIMENSION_NAMES = (
    "clones",
    "cohesion",
    "complexity",
    "coupling",
    "coverage",
    "dead_code",
    "dependencies",
)

#: The letters health is graded with, owned by ``HealthScore.grade`` in
#: ``codeclone.models`` and restated here for the ring reason in the module
#: docstring. Every one of them must draw a verdict.
_PUBLISHED_GRADES: tuple[str, ...] = ("A", "B", "C", "D", "F")

#: A score inside the window where the two deleted band sets disagreed: the
#: ring called it the top band, the banner called it the middle one. ``B`` is
#: what the producer grades it, so the pair is a document CodeClone can emit --
#: though nothing below depends on that, which is the point of the change.
_WINDOW_SCORE = 77
_WINDOW_GRADE = "B"

#: What each published letter must look like: the ring's stroke. Not a new
#: calibration -- the ring paints every score exactly the colour it painted
#: before this table existed. The banner beside the ring no longer grades
#: health at all: it answers what changed since the baseline, and its tone is
#: that verdict's, so the same document renders the same banner tone whatever
#: letter or number the health block carries.
_VERDICTS: Mapping[str, str] = {
    "A": "var(--success)",
    "B": "var(--success)",
    "C": "var(--warning)",
    "D": "var(--error)",
    "F": "var(--error)",
}

#: A document that published no grade has no verdict to show, and showing the
#: best or the worst one would invent it.
_NO_VERDICT = "var(--info)"

#: Scores spread across every band either deleted set ever drew, including
#: both their edges. The rendered verdict must be the same at all of them.
_SCORES_ACROSS_THE_OLD_BANDS = (0, 42, 59, 60, 74, 75, 77, 79, 80, 89, 100)

_RING_STROKE = re.compile(r'class="health-ring-fg"[^>]*stroke="(var\(--[a-z]+\))"')
#: Anchored on the executive question: the page draws nine insight banners and
#: an unanchored match would read whichever one came first.
_BANNER_TONE = re.compile(
    r'insight-banner insight-([a-z]+)"><div class="insight-question">'
    + re.escape(_escape_html(EXECUTIVE_QUESTION))
)


def _rendered_verdict(score: object, grade: object) -> tuple[str, str]:
    """Render one health block and return ``(ring stroke, banner tone)``."""

    document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={
            "health": {
                "score": score,
                "grade": grade,
                "dimensions": dict.fromkeys(_DIMENSION_NAMES, 80),
                "population": "complete_nonempty",
            }
        },
    )
    html = build_html_report(report_document=document)
    strokes = _RING_STROKE.findall(html)
    tones = _BANNER_TONE.findall(html)
    assert len(strokes) == 1, strokes
    assert len(tones) == 1, tones
    return strokes[0], tones[0]


def test_ring_and_banner_agree_inside_the_window_the_band_sets_disagreed_on() -> None:
    """The defect, stated as the page a reader saw.

    At 77 the ring said "top band" and the sentence beside it said "middle
    band" -- one number, one document, two answers.
    """

    ring, _tone = _rendered_verdict(_WINDOW_SCORE, _WINDOW_GRADE)

    assert ring == _VERDICTS[_WINDOW_GRADE]


@pytest.mark.parametrize("grade", _PUBLISHED_GRADES)
def test_the_verdict_follows_the_published_grade_not_the_score(grade: str) -> None:
    """One score, five letters: whatever decides the tone, it is not the number.

    The score is held at the window value while the document's grade moves
    through the whole published vocabulary. Any surviving band over the score
    would answer identically five times.
    """

    assert _rendered_verdict(_WINDOW_SCORE, grade)[0] == _VERDICTS[grade]


def test_the_banner_tone_never_moves_with_health() -> None:
    """The banner answers the baseline question; health is the ring's.

    One tone across every published letter and every band edge either set
    ever drew: a surviving band over the score, or over the grade, would
    answer differently somewhere in this sweep.
    """

    tones = {
        _rendered_verdict(score, grade)[1]
        for grade in _PUBLISHED_GRADES
        for score in _SCORES_ACROSS_THE_OLD_BANDS
    }
    assert len(tones) == 1, tones


@pytest.mark.parametrize("score", _SCORES_ACROSS_THE_OLD_BANDS)
def test_the_verdict_does_not_move_when_only_the_score_moves(score: int) -> None:
    """The other direction: one letter, every band edge either set ever used.

    A renderer that still consulted the number would change its answer as the
    score crossed 60, 75 or 80; the letter is what it is told, and the letter
    does not move.
    """

    assert _rendered_verdict(score, _WINDOW_GRADE)[0] == _VERDICTS[_WINDOW_GRADE]


@pytest.mark.parametrize("grade", _PUBLISHED_GRADES)
def test_every_published_grade_is_drawn_as_a_verdict(grade: str) -> None:
    """No published letter may fall through to "no grade published".

    The vocabulary comes from the contract, so a grade added there without a
    verdict beside it fails here rather than rendering as an absence.
    """

    assert _rendered_verdict(_WINDOW_SCORE, grade)[0] != _NO_VERDICT


def test_a_document_that_published_no_grade_is_drawn_without_a_verdict() -> None:
    """Absence of a grade is neither the best band nor the worst one.

    ``health_report_fields`` withholds ``score`` and ``grade`` together, so a
    block carrying a number without a letter is a foreign or hand-built
    document. It still must not be graded here: the page says "no verdict"
    rather than picking one, which is the same rule the population cards
    already follow.
    """

    assert _rendered_verdict(_WINDOW_SCORE, None)[0] == _NO_VERDICT
