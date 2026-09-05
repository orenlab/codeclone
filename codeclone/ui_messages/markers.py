# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI markers and display names."""

from __future__ import annotations

from .styling import GLYPH_FAIL

# One line, on every screen, that says what the product does for the reader:
# the run reports structural change against an accepted baseline. "Review
# layer" named a category; a blind reading measured 2026-09-05 filed the
# tool as a linter on it.
BANNER_SUBTITLE = "structural change control for Python"

# Error banners carry the fail glyph so the eye finds them on the grid; the
# body is indented under them by ``fmt_contract_error`` / ``fmt_internal_error``.
MARKER_CONTRACT_ERROR = f"[error]{GLYPH_FAIL} CONTRACT ERROR[/error]"
MARKER_INTERNAL_ERROR = f"[error]{GLYPH_FAIL} INTERNAL ERROR[/error]"

REPORT_BLOCK_GROUP_DISPLAY_NAME_ASSERT_PATTERN = "Assert pattern block"
