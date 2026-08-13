# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one place the CLI decides which report digest names a run."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ...utils.mapping_paths import section

#: The digest tier a CLI run is named by.
#:
#: ``evaluation`` seals the facts, the baseline, the gate thresholds and the
#: outcome. The tier below it -- ``comparison`` -- stops at facts and baseline,
#: so two runs over one tree that answer differently because their thresholds
#: differ were written to the audit trail under one name, and nothing in the
#: trail could tell them apart. The tier above it -- the envelope -- also seals
#: ``meta.runtime.report_generated_at_utc``, the document's only time-like
#: field, so an identity taken from there would be new on every run by
#: construction and no consumer could tell a repeated measurement from a
#: changed one.
_RUN_IDENTITY_TIER: Final = "evaluation"


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

    value = section(report_document, f"integrity.digests.{_RUN_IDENTITY_TIER}").get(
        "value"
    )
    if not isinstance(value, str) or not value.strip():
        raise ReportRunIdentityError(
            "Report document carries no "
            f"integrity.digests.{_RUN_IDENTITY_TIER}.value run identity."
        )
    return value


__all__ = ["ReportRunIdentityError", "report_run_identity"]
