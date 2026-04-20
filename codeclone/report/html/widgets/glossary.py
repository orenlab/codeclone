# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Tooltip glossary for report table headers and stat cards."""

from __future__ import annotations

from ..primitives.escape import _escape_html

GLOSSARY: dict[str, str] = {
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
    "kind": "Symbol type: function, class, import, or variable",
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
    "modules": "Total number of Python modules analyzed",
    "edges": "Total number of import relationships between modules",
    "max depth": "Longest chain of transitive imports",
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
    "critical": "Items with critical status requiring immediate attention",
    "max score": "Highest overload score among all modules",
    "avg loc": "Average lines of code per module",
    # Dead code stat cards
    "candidates": "Total dead code candidates detected by static analysis",
    "high confidence": "Dead code items detected with high or critical confidence",
    "suppressed": "Dead code candidates excluded by suppression rules",
    "hit rate": "Percentage of high-confidence items among all candidates",
    # Clone stat cards
    "clone groups": "Distinct duplication patterns, each containing 2+ code fragments",
    "instances": "Total duplicated code fragments across all groups",
    "new groups": "Clone groups not present in the previous baseline",
    "high spread": "Clone groups spanning multiple files",
    # Suggestion stat cards
    "total suggestions": "Total actionable improvement suggestions generated",
    "warning": "Suggestions with warning severity worth reviewing",
    "easy wins": "Actionable suggestions with low estimated effort",
}


def glossary_tip(label: str) -> str:
    """Return a tooltip ``<span>`` for *label*, or ``''`` if unknown."""
    tip = GLOSSARY.get(label.lower(), "")
    if not tip:
        return ""
    return f' <span class="kpi-help" data-tip="{_escape_html(tip)}">?</span>'
