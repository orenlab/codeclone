# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One observer timestamp must name one instant on every supported interpreter.

The observer stamps operations and spans through ``observability.runtime``
with a trailing ``Z``, a spelling ``datetime.fromisoformat`` only learned to
accept in 3.11. Read without normalising that designator, every stamp came
back as ``None`` on 3.10, every span offset collapsed to zero, and the cockpit
drew a flat staircase that looked plausible and was wrong -- a silent loss,
not a crash. These tests pin the reading, both when it must succeed and when
it must still refuse.
"""

from __future__ import annotations

import pytest

from codeclone.observability import render_html as render_html_mod
from codeclone.observability.views import OperationView, SpanView

# The shape `observability.runtime._now_utc` actually emits.
_OP_START_Z = "2026-08-30T05:00:00.000000Z"
_SPAN_START_Z = "2026-08-30T05:00:02.500000Z"
_OP_START_OFFSET_FORM = "2026-08-30T05:00:00.000000+00:00"


def test_epoch_ms_reads_z_and_offset_spellings_as_the_same_instant() -> None:
    """``Z`` and ``+00:00`` name one instant, so the renderer must answer one
    number for both. Stated as an identity rather than as a literal epoch, the
    pin holds on every interpreter and still fails on the one that disagrees.
    """

    z_form = render_html_mod._epoch_ms(_OP_START_Z)
    offset_form = render_html_mod._epoch_ms(_OP_START_OFFSET_FORM)

    assert offset_form is not None
    assert z_form == offset_form


def test_span_offset_is_measured_from_a_z_suffixed_operation_start() -> None:
    """The staircase offset is a span's distance from its operation's start.
    An unparsed stamp collapses every offset to 0.0, and the renderer keeps
    drawing instead of reporting that it lost the time ladder."""

    op_start = render_html_mod._epoch_ms(_OP_START_Z)
    span = SpanView(
        span_id="span-1",
        name="probe",
        duration_ms=100.0,
        status="ok",
        started_at_utc=_SPAN_START_Z,
    )

    assert render_html_mod._span_offset_ms(op_start, span) == 2500.0


def test_rendered_span_bar_carries_the_start_offset() -> None:
    """End to end through the emitted SVG: a span opening 2.5s into a 10s
    operation is drawn a quarter of the way in, not at the origin."""

    span = SpanView(
        span_id="span-1",
        name="probe",
        duration_ms=100.0,
        status="ok",
        started_at_utc=_SPAN_START_Z,
    )
    operation = OperationView(
        operation_id="op-1",
        correlation_id="corr-1",
        surface="cli",
        name="analyze",
        started_at_utc=_OP_START_Z,
        duration_ms=10_000.0,
        status="ok",
        spans=(span,),
    )

    html = render_html_mod._op_block(operation, 10_000.0)

    assert 'x="25.0"' in html


def test_span_offset_is_zero_when_the_operation_start_is_unknown() -> None:
    """No operation start is no measurable distance -- the span is drawn from
    the origin rather than guessed at."""

    span = SpanView(
        span_id="span-1",
        name="probe",
        duration_ms=100.0,
        status="ok",
        started_at_utc=_SPAN_START_Z,
    )

    assert render_html_mod._span_offset_ms(None, span) == 0.0


def test_span_offset_is_zero_when_the_span_start_is_unreadable() -> None:
    """A span whose own stamp names no instant contributes no offset."""

    op_start = render_html_mod._epoch_ms(_OP_START_Z)
    span = SpanView(
        span_id="span-1",
        name="probe",
        duration_ms=100.0,
        status="ok",
        started_at_utc="not-a-timestamp",
    )

    assert render_html_mod._span_offset_ms(op_start, span) == 0.0


def test_epoch_ms_reports_no_instant_for_an_absent_timestamp() -> None:
    """An empty stamp is an absent measurement, not a malformed one, and it
    must not reach the parser at all."""

    assert render_html_mod._epoch_ms("") is None


@pytest.mark.parametrize(
    "malformed",
    [
        "not-a-timestamp",
        "2026-08-30T05:00:00ZZ",
        "2026-13-40T99:99:99Z",
        "2026-08-30T05:00:00+00:00Z",
    ],
)
def test_epoch_ms_still_refuses_a_malformed_timestamp(malformed: str) -> None:
    """Accepting ``Z`` must not widen the parser into a sieve.

    ``...00ZZ`` is the load-bearing row: 3.10 accepts ``...00:00Z+00:00``, so
    a normaliser that strips *any* trailing ``Z`` would turn that malformed
    stamp into a valid instant on 3.10 while 3.11+ keeps rejecting it --
    curing the silent divergence by introducing a new one.
    """

    assert render_html_mod._epoch_ms(malformed) is None
