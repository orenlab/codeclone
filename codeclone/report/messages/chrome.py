# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""HTML report chrome: tabs, modals, footer."""

from __future__ import annotations

from typing import Final

REPORT_TITLE_DEFAULT: Final = "CodeClone Report"
BRAND_TITLE: Final = "CodeClone Report"

TAB_OVERVIEW: Final = "Overview"
TAB_CLONES: Final = "Clones"
TAB_QUALITY: Final = "Quality"
TAB_MODULE_MAP: Final = "Module map"
TAB_DEPENDENCIES: Final = "Dependencies"
TAB_DEAD_CODE: Final = "Dead Code"
TAB_SUGGESTIONS: Final = "Suggestions"
TAB_FINDINGS: Final = "Findings"

TABLIST_ARIA_LABEL: Final = "Report sections"
BADGE_BUTTON_LABEL: Final = "Get Badge"
MODAL_FINDING_TITLE: Final = "Finding Details"
MODAL_FINDING_CLOSE: Final = "Close"
MODAL_BADGE_TITLE: Final = "Get Badge"
THEME_TOGGLE_LABEL: Final = "Toggle theme"
THEME_BUTTON_TEXT: Final = "Theme"
FOOTER_DOCS: Final = "Docs"
FOOTER_REPORT_ISSUE: Final = "Report Issue"
FOOTER_BRAND: Final = "CodeClone"

IDE_PICKER_LABEL: Final = "IDE"
IDE_PICKER_TITLE: Final = "Open in IDE"
PROVENANCE_ARIA_LABEL: Final = "Report Provenance"
PROVENANCE_TITLE_PREFIX: Final = "Report Provenance — "

FOOTER_SCHEMA_REPORT: Final = "Report schema "
FOOTER_SCHEMA_BASELINE: Final = "Baseline schema "
FOOTER_SCHEMA_CACHE: Final = "Cache schema "

BADGE_TAB_GRADE: Final = "Grade only"
BADGE_TAB_FULL: Final = "Score + Grade"
BADGE_DISCLAIMER: Final = "Badge reflects the current report snapshot."
BADGE_FIELD_MARKDOWN: Final = "Markdown"
BADGE_FIELD_HTML: Final = "HTML"
BADGE_COPY: Final = "Copy"
