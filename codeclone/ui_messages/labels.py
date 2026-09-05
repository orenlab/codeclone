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

SUMMARY_COMPACT = (
    "Summary  found={found}  analyzed={analyzed}"
    "  cached={cache_hits}  skipped={skipped}"
)
# ``new`` receives a pre-rendered value, the way ``health`` does below: a
# count when the clone lanes were compared against the baseline, and the
# "not compared" word when they were not. "Not compared" is not "zero new",
# so the slot carries the sentence rather than a number.
SUMMARY_COMPACT_CLONES = (
    "Clones   func={function}  block={block}  seg={segment}"
    "  suppressed={suppressed}  low_value={low_value}  new={new}"
)
# Quiet-mode twin of the ``New`` row's absence sentence: why no clone lane
# was compared, and the file the reason is about when there is one.
SUMMARY_COMPACT_NOVELTY = "Novelty  not_compared={reason}"
# ``cycles`` keeps the total; the parenthesised split says how many of them can
# actually fail an import, which is the only part --fail-cycles reads.
# ``health`` receives a pre-rendered value: ``85(B)`` for a measured run, or
# the same absence sentence the rich health line prints when the population
# carries no score — the formatter reads one owner table for both branches.
SUMMARY_COMPACT_METRICS = (
    "Metrics  cc={cc_avg}/{cc_max}  cbo={cbo_avg}/{cbo_max}"
    "  lcom4={lcom_avg}/{lcom_max}"
    "  cycles={cycles}(import={import_cycles},deferred={deferred_cycles})"
    "  dead_code={dead}"
    "  health={health}  overloaded_modules={overloaded_modules}"
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
