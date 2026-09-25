# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The published PIECES of a finding group, spelled once.

Two readers publish the analysis skeleton of a finding group -- the report
document (``codeclone.report.document``), which assembles the ordered group
dict the renderers and the MCP surface read, and the canonical projection
(``codeclone.canonical``), which rebuilds the same skeleton out of the run
store's rows so the two can be held byte for byte to each other.  Neither
may import the other: the document already imports the canonical package
(``report/document/metrics.py`` reads the authority order key), so a
canonical module that imported the document would close an import cycle
through both packages' ``__init__``.  The pieces both need therefore live
here, in ``codeclone.findings`` -- a ring both can reach and that imports
neither -- placement decided by the frozen edges, not by which reader asked
first (the ``utils.finding_groups`` precedent).

What lives here is what a group asserts as ANALYSIS: the structural
signature and facts of a duplicated-branch group, the facts of a dead
symbol and of an unreachable statement, the design-hotspot thresholds and
the item/fact dicts of every design category, the dependency-cycle member
and facts, the coverage-hotspot kind, item and facts, and the authority
violation's published location and facts.  What does NOT live here is
evaluation and comparison: severity, priority, confidence tiers and novelty
stay with the document builder, which layers them on top of these pieces
in the key order the document has always published.  Every function
returns exactly the dict its former inline spelling returned, in the same
key order, because the document's bytes are a contract and this move is
wire-neutral by construction.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from ..contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    STATEMENT_REACHABILITY_POLICY_VERSION,
)
from ..domain.findings import (
    CATEGORY_COHESION,
    CATEGORY_COMPLEXITY,
    CATEGORY_COUPLING,
    FINDING_KIND_CLASS_HOTSPOT,
    FINDING_KIND_COVERAGE_HOTSPOT,
    FINDING_KIND_COVERAGE_SCOPE_GAP,
    FINDING_KIND_FUNCTION_HOTSPOT,
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
    STRUCTURAL_KIND_DUPLICATED_BRANCHES,
)
from ..domain.quality import CONFIDENCE_HIGH
from ..paths import classify_source_kind
from ..utils.coerce import as_int, as_mapping, as_sequence

# -- structural --------------------------------------------------------------


def csv_values(value: object) -> list[str]:
    """The producer's comma-separated signature values, sorted and unique."""
    raw = str(value).strip()
    if not raw:
        return []
    return sorted({part.strip() for part in raw.split(",") if part.strip()})


def structural_signature(
    finding_kind: str,
    signature: Mapping[str, str],
) -> dict[str, object]:
    """The published ``signature`` block of one structural group."""
    debug = {str(key): str(signature[key]) for key in sorted(signature)}
    match finding_kind:
        case "clone_guard_exit_divergence":
            return {
                "version": "1",
                "stable": {
                    "family": STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
                    "cohort_id": str(signature.get("cohort_id", "")),
                    "majority_guard_count": as_int(
                        signature.get("majority_guard_count")
                    ),
                    "majority_guard_terminal_profile": str(
                        signature.get("majority_guard_terminal_profile", "none")
                    ),
                    "majority_terminal_kind": str(
                        signature.get("majority_terminal_kind", "fallthrough")
                    ),
                    "majority_side_effect_before_guard": (
                        str(signature.get("majority_side_effect_before_guard", "0"))
                        == "1"
                    ),
                },
                "debug": debug,
            }
        case "clone_cohort_drift":
            return {
                "version": "1",
                "stable": {
                    "family": STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
                    "cohort_id": str(signature.get("cohort_id", "")),
                    "drift_fields": csv_values(signature.get("drift_fields")),
                    "majority_profile": {
                        "terminal_kind": str(
                            signature.get("majority_terminal_kind", "")
                        ),
                        "guard_exit_profile": str(
                            signature.get("majority_guard_exit_profile", "")
                        ),
                        "try_finally_profile": str(
                            signature.get("majority_try_finally_profile", "")
                        ),
                        "side_effect_order_profile": str(
                            signature.get("majority_side_effect_order_profile", "")
                        ),
                    },
                },
                "debug": debug,
            }
        case _:
            return {
                "version": "1",
                "stable": {
                    "family": STRUCTURAL_KIND_DUPLICATED_BRANCHES,
                    "stmt_shape": str(signature.get("stmt_seq", "")),
                    "terminal_kind": str(signature.get("terminal", "")),
                    "control_flow": {
                        "has_loop": str(signature.get("has_loop", "0")) == "1",
                        "has_try": str(signature.get("has_try", "0")) == "1",
                        "nested_if": str(signature.get("nested_if", "0")) == "1",
                    },
                },
                "debug": debug,
            }


def structural_facts(
    finding_kind: str,
    signature: Mapping[str, str],
    *,
    count: int,
) -> dict[str, object]:
    """The published ``facts`` block of one structural group."""
    match finding_kind:
        case "clone_guard_exit_divergence":
            return {
                "cohort_id": str(signature.get("cohort_id", "")),
                "cohort_arity": as_int(signature.get("cohort_arity")),
                "divergent_members": as_int(signature.get("divergent_members"), count),
                "majority_entry_guard_count": as_int(
                    signature.get("majority_guard_count"),
                ),
                "majority_guard_terminal_profile": str(
                    signature.get("majority_guard_terminal_profile", "none")
                ),
                "majority_terminal_kind": str(
                    signature.get("majority_terminal_kind", "fallthrough")
                ),
                "majority_side_effect_before_guard": (
                    str(signature.get("majority_side_effect_before_guard", "0")) == "1"
                ),
                "guard_count_values": csv_values(signature.get("guard_count_values")),
                "guard_terminal_values": csv_values(
                    signature.get("guard_terminal_values"),
                ),
                "terminal_values": csv_values(signature.get("terminal_values")),
                "side_effect_before_guard_values": csv_values(
                    signature.get("side_effect_before_guard_values"),
                ),
            }
        case "clone_cohort_drift":
            return {
                "cohort_id": str(signature.get("cohort_id", "")),
                "cohort_arity": as_int(signature.get("cohort_arity")),
                "divergent_members": as_int(signature.get("divergent_members"), count),
                "drift_fields": csv_values(signature.get("drift_fields")),
                "stable_majority_profile": {
                    "terminal_kind": str(signature.get("majority_terminal_kind", "")),
                    "guard_exit_profile": str(
                        signature.get("majority_guard_exit_profile", "")
                    ),
                    "try_finally_profile": str(
                        signature.get("majority_try_finally_profile", "")
                    ),
                    "side_effect_order_profile": str(
                        signature.get("majority_side_effect_order_profile", "")
                    ),
                },
            }
        case _:
            return {
                "occurrence_count": count,
                "non_overlapping": True,
                "call_bucket": as_int(signature.get("calls", "0")),
                "raise_bucket": as_int(signature.get("raises", "0")),
            }


# -- dead code ---------------------------------------------------------------


def dead_symbol_facts(
    *,
    kind: str,
    confidence: str,
    reason: str,
    test_reference_sources: object,
) -> dict[str, object]:
    """The published ``facts`` of one unused-symbol group."""
    return {
        "kind": kind,
        "confidence": confidence,
        "reason": reason,
        "test_reference_sources": sorted(
            {
                str(source)
                for source in as_sequence(test_reference_sources)
                if str(source)
            }
        ),
    }


def unreachable_statement_facts(
    *, reason: str, statement_count: object
) -> dict[str, object]:
    """The published ``facts`` of one unreachable-statement group."""
    return {
        "reason": reason,
        "confidence": CONFIDENCE_HIGH,
        "statement_count": as_int(statement_count),
        "policy_version": STATEMENT_REACHABILITY_POLICY_VERSION,
    }


# -- design ------------------------------------------------------------------


def coerced_nonnegative_threshold(value: object, *, default: int) -> int:
    """A design threshold as an int, the default for anything below zero."""
    threshold = as_int(value, default)
    return threshold if threshold >= 0 else default


#: The realized design-hotspot thresholds of one run, keyed by category --
#: the same three keys ``meta.analysis_thresholds.design_findings`` carries.
#: A mapping rather than a typed carrier on purpose: typed model
#: definitions live in the model store (``codeclone.models``,
#: ``codeclone.canonical``) and nowhere else (the architecture ratchet), and
#: three integers keyed by a closed vocabulary need no carrier of their own.
DesignThresholds = Mapping[str, int]

#: The default of each category, the value a threshold below zero falls to.
_DESIGN_THRESHOLD_DEFAULTS: Final[Mapping[str, int]] = {
    CATEGORY_COMPLEXITY: DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    CATEGORY_COUPLING: DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    CATEGORY_COHESION: DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
}


def design_thresholds(design_findings: object) -> DesignThresholds:
    """The realized thresholds of one run, read off the document meta's
    ``analysis_thresholds.design_findings`` block."""
    thresholds = as_mapping(design_findings)
    return {
        category: coerced_nonnegative_threshold(
            as_mapping(thresholds.get(category)).get("value"), default=default
        )
        for category, default in _DESIGN_THRESHOLD_DEFAULTS.items()
    }


def is_complexity_hotspot(
    cyclomatic_complexity: int, thresholds: DesignThresholds
) -> bool:
    return cyclomatic_complexity > thresholds[CATEGORY_COMPLEXITY]


def is_coupling_hotspot(cbo: int, thresholds: DesignThresholds) -> bool:
    return cbo > thresholds[CATEGORY_COUPLING]


def is_cohesion_hotspot(lcom4: int, thresholds: DesignThresholds) -> bool:
    return lcom4 >= thresholds[CATEGORY_COHESION]


#: The published ``kind`` of each metric-backed design category.
DESIGN_HOTSPOT_KINDS: Final[Mapping[str, str]] = {
    CATEGORY_COMPLEXITY: FINDING_KIND_FUNCTION_HOTSPOT,
    CATEGORY_COUPLING: FINDING_KIND_CLASS_HOTSPOT,
    CATEGORY_COHESION: FINDING_KIND_CLASS_HOTSPOT,
}


def complexity_item_data(
    *, cyclomatic_complexity: int, nesting_depth: int, risk: str
) -> dict[str, object]:
    return {
        "cyclomatic_complexity": cyclomatic_complexity,
        "nesting_depth": nesting_depth,
        "risk": risk,
    }


def complexity_facts(
    *, cyclomatic_complexity: int, nesting_depth: int
) -> dict[str, object]:
    return {
        "cyclomatic_complexity": cyclomatic_complexity,
        "nesting_depth": nesting_depth,
    }


def coupling_item_data(
    *, cbo: int, risk: str, coupled_classes: Sequence[object]
) -> dict[str, object]:
    return {"cbo": cbo, "risk": risk, "coupled_classes": list(coupled_classes)}


def coupling_facts(*, cbo: int, coupled_classes: Sequence[object]) -> dict[str, object]:
    return {"cbo": cbo, "coupled_classes": list(coupled_classes)}


def cohesion_item_data(
    *, lcom4: int, risk: str, method_count: int, instance_var_count: int
) -> dict[str, object]:
    return {
        "lcom4": lcom4,
        "risk": risk,
        "method_count": method_count,
        "instance_var_count": instance_var_count,
    }


def cohesion_facts(
    *, lcom4: int, method_count: int, instance_var_count: int
) -> dict[str, object]:
    return {
        "lcom4": lcom4,
        "method_count": method_count,
        "instance_var_count": instance_var_count,
    }


# -- dependency cycles -------------------------------------------------------

CYCLE_MEASURED_IMPORT: Final = "cycle over import-time edges"
CYCLE_MEASURED_DEFERRED: Final = (
    "cycle only over deferred edges (function-scope, module "
    "__getattr__, or lazy imports)"
)


def dependency_cycle_measured(kind: str) -> str:
    """What the cycle's kind says was measured, in the published words."""
    return CYCLE_MEASURED_IMPORT if kind == "import_cycle" else CYCLE_MEASURED_DEFERRED


def dependency_cycle_facts(*, kind: str, cycle_length: int) -> dict[str, object]:
    return {"cycle_length": cycle_length, "measured": dependency_cycle_measured(kind)}


def module_classification_path(module: str, member_path: str | None) -> str:
    """Path used ONLY for source-kind classification, never reported.

    A resolved member classifies by its real file. An unresolved member
    classifies by its dotted segments spelled as a directory -- a segment
    sequence, not a file claim; no ``.py`` is ever invented for it.
    """
    return member_path if member_path else module.replace(".", "/")


def dependency_member_item(
    *, module: str, member_path: str | None
) -> dict[str, object]:
    """One published member of a dependency-cycle group.

    Path honesty: only a registry-resolved file is ever reported; an
    unresolved member keeps its module identity and claims no path.
    """
    item: dict[str, object] = {
        "module": module,
        "source_kind": classify_source_kind(
            module_classification_path(module, member_path)
        ),
    }
    if member_path:
        item["relative_path"] = member_path
    return item


# -- coverage ----------------------------------------------------------------

COVERAGE_HOTSPOT_DETAIL: Final = (
    "Joined line coverage is below the configured hotspot threshold."
)
COVERAGE_SCOPE_GAP_DETAIL: Final = (
    "The supplied coverage.xml did not map to this function's file."
)


def coverage_group_kind(*, scope_gap_hotspot: bool) -> tuple[str, str]:
    """The published ``(kind, detail)`` of one coverage group: a scope gap
    outranks a low-coverage hotspot when both flags are raised."""
    if scope_gap_hotspot:
        return FINDING_KIND_COVERAGE_SCOPE_GAP, COVERAGE_SCOPE_GAP_DETAIL
    return FINDING_KIND_COVERAGE_HOTSPOT, COVERAGE_HOTSPOT_DETAIL


def coverage_item_data(
    *,
    relative_path: str,
    qualname: str,
    start_line: int,
    end_line: int,
    risk: str,
    cyclomatic_complexity: int,
    coverage_permille: int,
    coverage_status: str,
    covered_lines: int,
    executable_lines: int,
    coverage_hotspot: bool,
    scope_gap_hotspot: bool,
) -> dict[str, object]:
    return {
        "relative_path": relative_path,
        "qualname": qualname,
        "start_line": start_line,
        "end_line": end_line,
        "risk": risk,
        "cyclomatic_complexity": cyclomatic_complexity,
        "coverage_permille": coverage_permille,
        "coverage_status": coverage_status,
        "covered_lines": covered_lines,
        "executable_lines": executable_lines,
        "coverage_hotspot": coverage_hotspot,
        "scope_gap_hotspot": scope_gap_hotspot,
    }


def coverage_facts(
    *,
    coverage_permille: int,
    hotspot_threshold_percent: int,
    coverage_status: str,
    covered_lines: int,
    executable_lines: int,
    cyclomatic_complexity: int,
    coverage_hotspot: bool,
    scope_gap_hotspot: bool,
    detail: str,
) -> dict[str, object]:
    return {
        "coverage_permille": coverage_permille,
        "hotspot_threshold_percent": hotspot_threshold_percent,
        "coverage_status": coverage_status,
        "covered_lines": covered_lines,
        "executable_lines": executable_lines,
        "cyclomatic_complexity": cyclomatic_complexity,
        "coverage_hotspot": coverage_hotspot,
        "scope_gap_hotspot": scope_gap_hotspot,
        "detail": detail,
    }


# -- authority ---------------------------------------------------------------


def authority_location(location: Mapping[str, object]) -> dict[str, object]:
    """One published location of an authority-violation group, the
    source-kind verdict classified from its own path."""
    relative_path = str(location.get("relative_path", ""))
    return {
        "relative_path": relative_path,
        "qualname": str(location.get("qualname", "")),
        "start_line": as_int(location.get("start_line")),
        "end_line": as_int(location.get("end_line")),
        "source_kind": classify_source_kind(relative_path),
    }


def authority_group_facts(violation: Mapping[str, object]) -> dict[str, object]:
    """The published ``facts`` of one authority-violation group."""
    return {
        "violation_id": str(violation.get("violation_id", "")),
        "contract_id": str(violation.get("contract_id", "")),
        "violation_kind": str(violation.get("kind", "")),
        "sink_identity": str(violation.get("sink_identity", "")),
        "canonical_owner": str(violation.get("canonical_owner", "")),
        "authority_status": str(violation.get("authority_status", "unavailable")),
        "producer_root_ids": sorted(
            str(value) for value in as_sequence(violation.get("producer_root_ids"))
        ),
        "effect_signature": str(violation.get("effect_signature", "")),
        "resolution_state": str(violation.get("resolution_state", "unavailable")),
        "producers": sorted(
            str(value) for value in as_sequence(violation.get("producers"))
        ),
        "algorithm_revision": str(violation.get("algorithm_revision", "")),
    }


def sorted_unique_strings(values: Iterable[object]) -> list[str]:
    """Sorted, unique, non-empty strings -- the spelling of every published
    string list a group carries."""
    return sorted({str(value) for value in values if str(value)})


__all__ = [
    "COVERAGE_HOTSPOT_DETAIL",
    "COVERAGE_SCOPE_GAP_DETAIL",
    "CYCLE_MEASURED_DEFERRED",
    "CYCLE_MEASURED_IMPORT",
    "DESIGN_HOTSPOT_KINDS",
    "DesignThresholds",
    "authority_group_facts",
    "authority_location",
    "coerced_nonnegative_threshold",
    "cohesion_facts",
    "cohesion_item_data",
    "complexity_facts",
    "complexity_item_data",
    "coupling_facts",
    "coupling_item_data",
    "coverage_facts",
    "coverage_group_kind",
    "coverage_item_data",
    "csv_values",
    "dead_symbol_facts",
    "dependency_cycle_facts",
    "dependency_cycle_measured",
    "dependency_member_item",
    "design_thresholds",
    "is_cohesion_hotspot",
    "is_complexity_hotspot",
    "is_coupling_hotspot",
    "module_classification_path",
    "sorted_unique_strings",
    "structural_facts",
    "structural_signature",
    "unreachable_statement_facts",
]
