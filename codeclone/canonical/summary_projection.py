# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The analysis-tier fields of ``get_run_summary`` / ``get_production_triage``,
rebuilt from canonical rows — one owner.

Canonical epoch E1 (2026-09-25).  The serving census (§4-§5) classified every
field the two MCP tools answer by tier; the ANALYSIS-tier ones are the fields
this module answers from the run store's families, in the surface's own
key order, so a shadow pin can hold each against the surface's answer byte
for byte.  Comparison, evaluation, execution and presentation fields stay
with the parent's memory until E2/E3 and are not spelled here at all.

Aggregates (A7) are PROJECTED, never stored, wherever they are strictly
derivable from stored rows — the ``RunScalars`` precedent (ruling
2026-08-24 §1): the three design maxima off the two observation lanes, the
dead-code ``total``/``high_confidence`` off the dead-symbol groups, the
coverage sums off the unit rows, the security summary off its rows, the
authority counts off the violation rows.  The one aggregate that is not
derivable — the dead-code lane's abstention and population counters — is
the stored ``dead_code_summary`` record, read here and never recomputed.

The dynamic import boundaries (A6) are the ``import_observations`` rows
the module walk classified ``unresolved_dynamic``, projected as the
document's ``dependencies.dynamic_boundaries`` sites; the ``python_module``
block the document nests under each site is a registry identity fact
(package, origin, mount) the model does not carry and is named as such.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Final

from codeclone.canonical.finding_projection import (
    PROJECTED_FAMILIES,
    projected_finding_groups,
)
from codeclone.canonical.identity import ModuleId
from codeclone.canonical.model import AnalysisFacts, CanonicalModel
from codeclone.contracts import FAMILY_CLONES
from codeclone.domain.findings import FAMILY_CLONE
from codeclone.domain.quality import CONFIDENCE_HIGH
from codeclone.domain.source_scope import (
    SOURCE_KIND_BREAKDOWN_KEYS,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)
from codeclone.metrics.coverage_join import permille
from codeclone.report.derived import normalized_source_kind
from codeclone.utils.coerce import as_mapping

#: The analysis-profile keys the surface answers, in its order.
ANALYSIS_PROFILE_KEYS: Final[tuple[str, ...]] = (
    "min_loc",
    "min_stmt",
    "block_min_loc",
    "block_min_stmt",
    "segment_min_loc",
    "segment_min_stmt",
)

#: The reason the document stamps on every dynamic boundary site.
DYNAMIC_BOUNDARY_REASON: Final = "dynamic_load_argument_opaque"

#: The import resolution that makes an observation a dynamic boundary.
_UNRESOLVED_DYNAMIC: Final = "unresolved_dynamic"


def analysis_mode(model: CanonicalModel) -> str:
    """``mode``: the realized profile mode, or the empty string the surface
    answers for a run that never declared one."""
    population = model.facts.analysis.analysis_population
    return "" if population is None else population.analysis_mode


def analysis_profile(model: CanonicalModel) -> dict[str, int]:
    """``analysis_profile``: the six thresholds the surface publishes, in
    its order, only those the run declared (the surface omits the key when
    nothing was declared)."""
    population = model.facts.analysis.analysis_population
    if population is None:
        return {}
    declared = dict(population.analysis_profile)
    return {key: declared[key] for key in ANALYSIS_PROFILE_KEYS if key in declared}


def inventory(model: CanonicalModel) -> dict[str, object]:
    """``inventory``: files/lines/functions/classes off ``run_scalars``.

    The surface answers ``files`` from ``inventory.files.total_found`` (the
    found population) and folds methods into ``functions``; the population
    branch it takes when ``code.scope`` is not the analysis root
    (``entity_counts`` unavailable) has no carrier here and is named in the
    census as remaining with memory.
    """
    scalars = model.facts.analysis.run_scalars
    if scalars is None:
        return {}
    return {
        "files": scalars.files_found,
        "lines": scalars.parsed_lines,
        "functions": scalars.functions + scalars.methods,
        "classes": scalars.classes,
    }


def _dominant_kind(group: Mapping[str, object]) -> str:
    return normalized_source_kind(
        as_mapping(group.get("source_scope")).get("dominant_kind")
    )


def finding_counts(model: CanonicalModel) -> dict[str, object]:
    """``findings.total`` / ``by_family`` / ``production`` and the triage's
    ``by_source_kind``, over the projected groups of the five tracked
    families — the same universe the surface flattens."""
    groups = projected_finding_groups(model)
    by_family: dict[str, int] = {}
    kinds: Counter[str] = Counter()
    total = 0
    for family in PROJECTED_FAMILIES:
        family_key = FAMILY_CLONES if family == FAMILY_CLONE else family
        by_family[family_key] = len(groups[family])
        total += len(groups[family])
        kinds.update(_dominant_kind(group) for group in groups[family])
    return {
        "total": total,
        "by_family": dict(sorted(by_family.items())),
        "production": kinds[SOURCE_KIND_PRODUCTION],
        "by_source_kind": {kind: kinds[kind] for kind in _SOURCE_KIND_BREAKDOWN_ORDER},
    }


#: The surface's breakdown order: the four source kinds, then ``mixed``.
_SOURCE_KIND_BREAKDOWN_ORDER: Final[tuple[str, ...]] = (
    *SOURCE_KIND_BREAKDOWN_KEYS,
    "mixed",
)


def dead_code(model: CanonicalModel) -> dict[str, object]:
    """``dead_code``: the surface's block — the two counters derivable from
    the dead-symbol groups projected, the eight stored counters read."""
    facts = model.facts.analysis
    record = facts.dead_code_summary
    if record is None:
        return {}
    return {
        "total": len(facts.dead_symbol_groups),
        "high_confidence": sum(
            1 for row in facts.dead_symbol_groups if row.confidence == CONFIDENCE_HIGH
        ),
        "suppressed": record.suppressed,
        "unresolved_external_override": record.unresolved_external_override,
        "unresolved": record.unresolved,
        "unresolved_internal": record.unresolved_internal,
        "candidates": record.candidates,
        "nested_candidates": record.nested_candidates,
        "world_contract": record.world_contract,
        "live_roots": record.live_roots,
    }


def coverage_join(model: CanonicalModel) -> dict[str, object]:
    """``coverage_join``: the surface's block — empty when the run was
    handed no report (the surface's own absence spelling), else the status,
    the overall permille and the two hotspot counts over the unit rows, the
    threshold, the source (a record always carries one), and the invalid
    reason exactly when the status is invalid."""
    facts = model.facts.analysis
    record = facts.coverage_join
    if record is None:
        return {}
    groups = projected_finding_groups(model)
    coverage_groups = [
        group for group in groups["design"] if group.get("category") == "coverage"
    ]
    executable = sum(row.executable_lines for row in facts.coverage_units)
    covered = sum(row.covered_lines for row in facts.coverage_units)
    payload: dict[str, object] = {
        "status": record.status,
        "overall_permille": permille(covered, executable),
        "coverage_hotspots": sum(
            1 for group in coverage_groups if group["kind"] == "coverage_hotspot"
        ),
        "scope_gap_hotspots": sum(
            1 for group in coverage_groups if group["kind"] == "coverage_scope_gap"
        ),
        "hotspot_threshold_percent": record.hotspot_threshold_percent,
        "source": record.source,
    }
    if record.invalid_reason:
        payload["invalid_reason"] = record.invalid_reason
    return payload


def security_surfaces(model: CanonicalModel) -> dict[str, object]:
    """``security_surfaces``: the analysis half of the surface's block —
    item count, category count and the production/tests split — off the
    surface rows.  ``report_only`` and ``note`` are the surface's own
    constants (presentation) and are not spelled here."""
    rows = model.facts.analysis.security_surfaces
    if not rows:
        return {}
    kinds = Counter(row.source_kind for row in rows)
    return {
        "items": len(rows),
        "categories": len({row.category for row in rows}),
        "production": kinds[SOURCE_KIND_PRODUCTION],
        "tests": kinds[SOURCE_KIND_TESTS],
    }


def security_surface_modules(model: CanonicalModel) -> int:
    """The document summary's ``modules``: distinct registry heads of the
    surface rows — the file's module, or its path when it has none."""
    module_of = {relation.file: relation.module for relation in model.file_modules}
    heads = {
        module_of[row.file].module if row.file in module_of else row.file.path
        for row in model.facts.analysis.security_surfaces
    }
    return len(heads)


def design_maxima(facts: AnalysisFacts) -> dict[str, int]:
    """A7: the three ``summary.max`` values the document publishes, off the
    two observation lanes — the producer drops zero rows, so an absent
    dimension is the measured zero."""
    complexity = [
        row.numerator
        for row in facts.risk_observations
        if row.dimension == "cyclomatic_complexity"
    ]
    coupling = [
        row.numerator
        for row in facts.coupling_cohesion_observations
        if row.dimension == "cbo"
    ]
    cohesion = [
        row.numerator
        for row in facts.coupling_cohesion_observations
        if row.dimension == "lcom4"
    ]
    return {
        "complexity_max": max(complexity, default=0),
        "coupling_max": max(coupling, default=0),
        "cohesion_max": max(cohesion, default=0),
    }


def authority_counts(facts: AnalysisFacts) -> dict[str, int]:
    """A7: the violation counters of the document's authority summary."""
    suppressed = sum(1 for row in facts.violations if row.suppressed)
    return {
        "violations": len(facts.violations),
        "active_violations": len(facts.violations) - suppressed,
        "suppressed_violations": suppressed,
    }


def dynamic_boundaries(model: CanonicalModel) -> list[dict[str, object]]:
    """A6: the document's ``dependencies.dynamic_boundaries`` sites, off the
    import observations classified ``unresolved_dynamic``, in the
    document's order (path, syntax kind).  The site's file is the importing
    FILE — a MODULE-headed source resolves through ``file_modules``.  The
    ``python_module`` identity block the document nests under each site is
    a registry fact outside the model and is not projected."""
    file_of_module = {relation.module: relation.file for relation in model.file_modules}
    sites: set[tuple[str, str]] = set()
    for row in model.facts.analysis.import_observations:
        if row.resolution != _UNRESOLVED_DYNAMIC:
            continue
        source = row.source
        file = file_of_module[source] if isinstance(source, ModuleId) else source
        sites.add((file.path, row.dependency_type))
    return [
        {
            "source": {"file": {"path": path}},
            "syntax_kind": syntax_kind,
            "reason": DYNAMIC_BOUNDARY_REASON,
        }
        for path, syntax_kind in sorted(sites)
    ]


__all__ = [
    "ANALYSIS_PROFILE_KEYS",
    "DYNAMIC_BOUNDARY_REASON",
    "analysis_mode",
    "analysis_profile",
    "authority_counts",
    "coverage_join",
    "dead_code",
    "design_maxima",
    "dynamic_boundaries",
    "finding_counts",
    "inventory",
    "security_surface_modules",
    "security_surfaces",
]
