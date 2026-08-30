# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""HTML glossary term definitions for report table headers and stat cards.

A term is addressed by ``(family, label)``, not by the bare word. Three words
were measured serving more than one report family under a single definition:
``suppressed`` (clones, dead code, semantic authority), ``kind`` (the same
three) and ``modules`` (dependencies, module map). A flat namespace answered
every one of them with the definition of whichever family happened to write it
down first, so the clone tab explained itself as dead code.

Families declare only the words they own. Everything whose meaning is the same
wherever it is read stays in :data:`SHARED_TERMS` and is reached by fallback.
An owned word is deliberately absent from ``SHARED_TERMS``: a lookup that names
no family, or names one that claims nothing, must come back empty rather than
borrow a neighbour's meaning. Silence is recoverable; a confident wrong
definition is not.
"""

from __future__ import annotations

from typing import Final

# Which panel is asking. This is presentation vocabulary and is deliberately
# NOT ``contracts.FAMILY_CLONES`` / ``contracts.GROUP_KEY_*``: those name
# containers on the wire and in the baseline, and spelling a tooltip namespace
# with them would put two contracts under one value. It is not the DOM
# ``group_id`` either -- renaming a tab group is a presentation decision and
# must not silently move a definition.
GLOSSARY_FAMILY_AUTHORITY: Final = "authority"
GLOSSARY_FAMILY_CLONES: Final = "clones"
GLOSSARY_FAMILY_COUPLING: Final = "coupling"
GLOSSARY_FAMILY_COVERAGE_JOIN: Final = "coverage_join"
GLOSSARY_FAMILY_DEAD_CODE: Final = "dead_code"
GLOSSARY_FAMILY_DEPENDENCIES: Final = "dependencies"
GLOSSARY_FAMILY_META: Final = "meta"
GLOSSARY_FAMILY_MODULE_MAP: Final = "module_map"
GLOSSARY_FAMILY_OVERVIEW: Final = "overview"
GLOSSARY_FAMILY_REVIEW: Final = "review"
GLOSSARY_FAMILY_SECURITY_SURFACES: Final = "security_surfaces"
GLOSSARY_FAMILY_STRUCTURAL: Final = "structural"
GLOSSARY_FAMILY_SUGGESTIONS: Final = "suggestions"

GLOSSARY_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        GLOSSARY_FAMILY_AUTHORITY,
        GLOSSARY_FAMILY_CLONES,
        GLOSSARY_FAMILY_COUPLING,
        GLOSSARY_FAMILY_COVERAGE_JOIN,
        GLOSSARY_FAMILY_DEAD_CODE,
        GLOSSARY_FAMILY_DEPENDENCIES,
        GLOSSARY_FAMILY_META,
        GLOSSARY_FAMILY_MODULE_MAP,
        GLOSSARY_FAMILY_OVERVIEW,
        GLOSSARY_FAMILY_REVIEW,
        GLOSSARY_FAMILY_SECURITY_SURFACES,
        GLOSSARY_FAMILY_STRUCTURAL,
        GLOSSARY_FAMILY_SUGGESTIONS,
    }
)

# Words a family owns. A word appears here only because it was measured
# reaching more than one family with a meaning that differs between them; a
# word that reads the same everywhere belongs in SHARED_TERMS instead.
FAMILY_TERMS: Final[dict[str, dict[str, str]]] = {
    GLOSSARY_FAMILY_AUTHORITY: {
        "kind": (
            "Authority violation kind, such as owner_bypass, shadow_projection "
            "or divergent_failure_semantics"
        ),
        "suppressed": (
            "Semantic-authority findings held back by a suppression rule and "
            "excluded from the active violation count"
        ),
    },
    GLOSSARY_FAMILY_CLONES: {
        "kind": "Clone kind: function, block, or segment",
        "suppressed": (
            "Clone groups held back by suppression policy, excluded from "
            "active review and from scoring"
        ),
    },
    GLOSSARY_FAMILY_DEAD_CODE: {
        "kind": "Symbol type: function, class, import, or variable",
        "suppressed": "Dead code candidates excluded by suppression rules",
    },
    GLOSSARY_FAMILY_DEPENDENCIES: {
        "modules": "Total number of Python modules analyzed",
    },
    GLOSSARY_FAMILY_MODULE_MAP: {
        "modules": ("Zoom the map to individual modules instead of their packages"),
    },
}

# Words whose meaning does not change with the panel that asks. Measured as
# reaching one family, or several families that read them identically -- for
# example ``file``, ``function``, ``cc``, ``location`` and ``risk``.
SHARED_TERMS: Final[dict[str, str]] = {
    # Complexity
    "function": "Fully-qualified function or method name",
    "class": "Fully-qualified class name",
    "name": "Symbol name (function, class, or variable)",
    "file": "Source file path relative to scan root",
    "location": "File and line range where the symbol is defined",
    "cc": "Cyclomatic complexity — number of independent execution paths",
    "nesting": "Maximum nesting depth of control-flow statements",
    "risk": "Risk level based on metric thresholds (low / medium / high)",
    # Coupling / cohesion
    "cbo": "Coupling Between Objects — number of classes this class depends on",
    "coupled classes": "Resolved class dependencies used to compute CBO for this class",
    "lcom4": "Lack of Cohesion of Methods — connected components in method/field graph",
    "methods": "Number of methods defined in the class",
    "fields": "Number of instance variables (attributes) in the class",
    # Dead code
    "line": "Source line number where the symbol starts",
    "confidence": "Detection confidence (low / medium / high / critical)",
    # Dependencies
    "longest chain": "Longest transitive import chain between modules",
    "length": "Number of modules in the dependency chain",
    "cycle": "Circular import dependency between modules",
    # Suggestions
    "priority": "Computed priority score (higher = more urgent)",
    "severity": "Issue severity: critical, warning, or info",
    "category": (
        "Metric category: clone, complexity, coupling, cohesion, dead_code, dependency"
    ),
    "title": "Brief description of the suggested improvement",
    "effort": "Estimated effort to fix: easy, moderate, or hard",
    "steps": "Actionable steps to resolve the issue",
    # Dependency stat cards
    "edges": "Total number of import relationships between modules",
    "max depth": (
        "Longest internal transitive import chain; compare with avg and p95 depth"
    ),
    "cycles": "Number of circular import dependencies detected",
    # Complexity stat cards
    "high-risk functions": (
        "Functions with cyclomatic complexity above the high-risk threshold"
    ),
    "max cc": "Highest cyclomatic complexity value among all analyzed functions",
    "avg cc": "Average cyclomatic complexity across all analyzed functions",
    "deep nesting": (
        "Functions with nesting depth exceeding recommended threshold (> 4)"
    ),
    # Coupling stat cards
    "high-coupling classes": "Classes with CBO above the high-risk threshold",
    "max cbo": "Highest Coupling Between Objects value among all classes",
    "avg cbo": "Average CBO across all analyzed classes",
    "medium risk": "Items at medium risk level — worth reviewing but not critical",
    # Cohesion stat cards
    "low-cohesion classes": (
        "Classes with LCOM4 > 1, indicating multiple responsibilities"
    ),
    "max lcom4": "Highest Lack of Cohesion value among all classes",
    "high risk": "Items at high risk level requiring attention",
    # Overloaded module stat cards
    "overloaded": (
        "Modules exceeding acceptable thresholds for size, complexity, or coupling"
    ),
    "ranked only": (
        "Modules ranked by overload score but not flagged as candidates "
        "(e.g. small repo population)"
    ),
    "critical": "Items with critical status requiring immediate attention",
    "max score": "Highest overload score among all modules",
    "avg loc": "Average lines of code per module",
    # Dead code stat cards
    "candidates": "Total dead code candidates detected by static analysis",
    "high confidence": "Dead code items detected with high or critical confidence",
    "hit rate": "Percentage of high-confidence items among all candidates",
    # Clone stat cards
    "clone groups": "Distinct duplication patterns, each containing 2+ code fragments",
    "instances": "Total duplicated code fragments across all groups",
    "new groups": "Clone groups not present in the previous baseline",
    "high spread": "Clone groups spanning multiple files",
    "health points": (
        "Health-score points this dimension contributes: dimension score "
        "multiplied by its contract weight"
    ),
    "excluded groups": (
        "Accepted clone groups excluded by suppression policy before scoring"
    ),
    # Semantic-authority stat cards
    "governed contracts": (
        "Contracts declared in [[tool.codeclone.authority]] that analysis checks"
    ),
    "unresolved owners": (
        "Governed owners whose contract could not be resolved, so authority "
        "cannot be asserted for them"
    ),
    # Semantic-authority tabs: product labels, domain terms preserved here
    "contracts": (
        "Governed sinks: the semantic contracts declared in "
        "[[tool.codeclone.authority]] and the owners answering for them"
    ),
    "discovery": (
        "Discovered owner candidates proposed by analysis; promotion into "
        "configuration is a human decision"
    ),
    "violations": "Semantic-authority violations found against governed contracts",
    # The Findings tab used to spend its question slot on this definition.
    # A definition belongs where definitions live; the tab asks about the code.
    "findings": (
        "Repeated non-overlapping branch-body shapes detected inside "
        "individual functions; local, report-only refactoring hints that do "
        "not affect clone detection or CI verdicts"
    ),
    "owner": "The producer proposed as the canonical owner of a shared fact",
    "producers": "Other functions sharing this candidate's fact",
    # The full governance rule. The discovery table states the short form
    # ("Tools propose, humans own.") on its meta band; the reader who wants
    # the whole rule, including where a proposal is pasted, hovers Propose.
    "propose": (
        "Authority is a governance act: tools propose, humans own. Copy a "
        "proposal into [[tool.codeclone.authority]] to govern it; nothing "
        "here changes your configuration"
    ),
    "level": (
        "Evidence strength behind a candidate, strongest first; only the top "
        "levels earn a row, and every level is counted in the strip above"
    ),
    # Suggestion stat cards
    "total suggestions": "Total actionable improvement suggestions generated",
    "warning": "Suggestions with warning severity worth reviewing",
    "easy wins": "Actionable suggestions with low estimated effort",
}


def glossary_term(label: str, *, family: str) -> str:
    """Return the definition *family* gives *label*, or the shared one.

    A family that claims the word answers for it. Otherwise the shared term
    applies. An unknown family therefore reads exactly like a family that
    claims nothing -- it never inherits another family's wording, because an
    owned word is not in :data:`SHARED_TERMS`.
    """
    key = label.strip().lower()
    owned = FAMILY_TERMS.get(family)
    if owned is not None and key in owned:
        return owned[key]
    return SHARED_TERMS.get(key, "")


__all__ = [
    "FAMILY_TERMS",
    "GLOSSARY_FAMILIES",
    "GLOSSARY_FAMILY_AUTHORITY",
    "GLOSSARY_FAMILY_CLONES",
    "GLOSSARY_FAMILY_COUPLING",
    "GLOSSARY_FAMILY_COVERAGE_JOIN",
    "GLOSSARY_FAMILY_DEAD_CODE",
    "GLOSSARY_FAMILY_DEPENDENCIES",
    "GLOSSARY_FAMILY_META",
    "GLOSSARY_FAMILY_MODULE_MAP",
    "GLOSSARY_FAMILY_OVERVIEW",
    "GLOSSARY_FAMILY_REVIEW",
    "GLOSSARY_FAMILY_SECURITY_SURFACES",
    "GLOSSARY_FAMILY_STRUCTURAL",
    "GLOSSARY_FAMILY_SUGGESTIONS",
    "SHARED_TERMS",
    "glossary_term",
]
