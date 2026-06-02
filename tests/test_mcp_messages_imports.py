# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.surfaces.mcp.messages import blast_radius as blast_radius_messages


def test_blast_radius_message_constants_reexport_analysis_symbols() -> None:
    assert blast_radius_messages.BLAST_SUMMARY_UNKNOWN == "unknown"
    assert blast_radius_messages.GUARDRAIL_REVIEW_DEPENDENTS
    assert blast_radius_messages.REVIEW_REASON_SECURITY_BOUNDARY
