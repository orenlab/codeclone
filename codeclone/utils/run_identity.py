# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one place a report document is asked which run it reports.

This lived in ``surfaces/cli`` (ring r4) while the controller plane that needs
the same answer -- ``controller_insights`` (r2p) -- may only import r0, r1 and
its own ring. The answer was therefore unreachable from the surface that most
needed it, and the status line grew its own address into the document instead:
one fact, two owners, and the two drifted. Ring r1 is the lowest ring that can
both reach :mod:`codeclone.utils.mapping_paths` and be reached by r2p and r4
alike, so the reader belongs here and the tier it reads belongs one ring lower,
in :mod:`codeclone.contracts`.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..contracts import REPORT_RUN_IDENTITY_TIER
from .mapping_paths import section

_RUN_IDENTITY_PATH = f"integrity.digests.{REPORT_RUN_IDENTITY_TIER}"


class ReportRunIdentityError(RuntimeError):
    """The report document carries no run identity."""


def report_run_identity(report_document: Mapping[str, object]) -> str:
    """Return the identity of the run this document reports, or refuse.

    Refusing closed is the point. The earlier form answered four different
    absences -- no ``integrity`` block, no ``digests`` block, no tier, no
    value -- with the same empty string, and the caller dropped the audit row
    on it. Downstream that left a trail in which "this run was not recorded"
    and "audit was switched off" are the same absence, so the surface could
    not say which had happened. Every finalized report document carries this
    tier, so the absence is a broken document, not a state to paper over.

    Callers that must stay alive catch :class:`ReportRunIdentityError` and say
    so; none of them may substitute a value for it.
    """

    value = section(report_document, _RUN_IDENTITY_PATH).get("value")
    if not isinstance(value, str) or not value.strip():
        raise ReportRunIdentityError(
            f"Report document carries no {_RUN_IDENTITY_PATH}.value run identity."
        )
    return value


__all__ = ["ReportRunIdentityError", "report_run_identity"]
