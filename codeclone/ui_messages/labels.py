# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CLI summary titles, labels, and compact templates."""

from __future__ import annotations

SUMMARY_TITLE = "Summary"
METRICS_TITLE = "Metrics"
CHANGED_SCOPE_TITLE = "Changed Scope"
BLAST_RADIUS_TITLE = "Blast Radius"
PATCH_VERIFY_TITLE = "Patch Verify"

CLI_LAYOUT_MAX_WIDTH = 80
CLI_AUDIT_MAX_WIDTH = 120

SUMMARY_LABEL_FILES_FOUND = "Files found"
SUMMARY_LABEL_FILES_ANALYZED = "  analyzed"
SUMMARY_LABEL_CACHE_HITS = "  from cache"
SUMMARY_LABEL_FILES_SKIPPED = "  skipped"
SUMMARY_LABEL_LINES_ANALYZED = "Lines (this run)"
SUMMARY_LABEL_FUNCTIONS_ANALYZED = "Functions (this run)"
SUMMARY_LABEL_METHODS_ANALYZED = "Methods (this run)"
SUMMARY_LABEL_CLASSES_ANALYZED = "Classes (this run)"
SUMMARY_LABEL_FUNCTION = "Function clones"
SUMMARY_LABEL_BLOCK = "Block clones"
SUMMARY_LABEL_SEGMENT = "Segment clones"
SUMMARY_LABEL_SUPPRESSED = "  suppressed"
SUMMARY_LABEL_NEW_BASELINE = "New vs baseline"

SUMMARY_COMPACT = (
    "Summary  found={found}  analyzed={analyzed}"
    "  cached={cache_hits}  skipped={skipped}"
)
SUMMARY_COMPACT_CLONES = (
    "Clones   func={function}  block={block}  seg={segment}"
    "  suppressed={suppressed}  new={new}"
)
SUMMARY_COMPACT_METRICS = (
    "Metrics  cc={cc_avg}/{cc_max}  cbo={cbo_avg}/{cbo_max}"
    "  lcom4={lcom_avg}/{lcom_max}  cycles={cycles}  dead_code={dead}"
    "  health={health}({grade})  overloaded_modules={overloaded_modules}"
)
SUMMARY_COMPACT_DEPENDENCIES = (
    "Dependencies  avg={avg_depth}  p95={p95_depth}  max={max_depth}"
)
SUMMARY_COMPACT_SECURITY_SURFACES = (
    "Security  items={items}  categories={categories}"
    "  production={production}  tests={tests}"
)
SUMMARY_COMPACT_CHANGED_SCOPE = (
    "Changed  paths={paths}  findings={findings}  new={new}  known={known}"
)
SUMMARY_COMPACT_BLAST_RADIUS = (
    "blast-radius: {level} | dependents={dependents} cohorts={cohorts} "
    "cycles={cycles} do-not-touch={do_not_touch}"
)
SUMMARY_COMPACT_PATCH_VERIFY = (
    "patch-verify: {status} | health={health_before}->{health_after} "
    "regressions={regressions} gates={gate_status}"
)
