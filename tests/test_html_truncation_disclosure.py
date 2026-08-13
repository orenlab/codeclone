# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A table that drops rows says so, or the reader cannot tell it apart.

Every quality table in the HTML report cuts its rows at a limit the renderer
chose, and until now almost all of them cut in silence. The card above the
table said ``973`` and the table drew fifty; nothing on the page distinguished
"there are fifty" from "there are nine hundred and seventy-three and you are
looking at fifty of them". That is the same defect as an empty panel that
cannot be told apart from a measurement that never ran.

Two things are pinned here, and they answer different failures:

* **Per panel, behaviourally.** Each cut panel is rendered over a fixture with
  more rows than its limit and must state the count. A fixture shorter than
  the limit would make the statement and its absence identical, so every
  fixture below is deliberately oversized -- that is what stops these tests
  from being hollow.
* **The inventory, mechanically.** :func:`_row_limiting_slices` walks the AST
  of every module in the package and finds every bounded slice, so the list of
  panels is built by the machine and not by whoever remembered which files were
  interesting. Both registers are two-sided: a new slice with no entry fails as
  growth, an entry whose slice is gone fails as rot.

The split between the two registers is the judgement. :data:`_ROW_CUTS` holds
slices that drop *rows a reader came for*, and each one names the test that
proves it is declared. :data:`_NOT_ROW_CUTS` holds the rest -- eliding a label
that is too long, previewing three names inside one cell beside a ``+4 more``
disclosure, splitting a rendered list into two columns -- with the reason it is
not a row cut. Nothing loses data in that second register: it either says how
much it folded, or it folded nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from codeclone.report.html.sections._authority import render_authority_panel
from codeclone.report.html.sections._clones import _render_suppressed_clone_panel
from codeclone.report.html.sections._coupling import render_quality_panel
from codeclone.report.html.sections._coverage_join import render_coverage_join_panel
from codeclone.report.html.sections._dead_code import render_dead_code_panel
from codeclone.report.html.sections._module_map import (
    _render_overloaded_modules_section,
)
from codeclone.report.html.sections._security_surfaces import (
    render_security_surfaces_panel,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HTML_PACKAGE = _REPO_ROOT / "codeclone" / "report" / "html"


# --------------------------------------------------------------------------
# The mechanical inventory
# --------------------------------------------------------------------------

#: Bounded slices that drop table rows. The value names the test in this
#: module that renders the panel oversized and reads the declaration back, so
#: a cut cannot be registered without something proving it speaks.
_ROW_CUTS: dict[str, dict[str, str]] = {
    "codeclone/report/html/sections/_authority.py": {
        "strong_candidates[:_CANDIDATE_ROW_LIMIT]": (
            "test_authority_candidate_table_states_how_many_it_left_out"
        ),
    },
    "codeclone/report/html/sections/_clones.py": {
        "groups[:_SUPPRESSED_GROUP_ROW_LIMIT]": (
            "test_suppressed_clone_table_states_how_many_groups_it_left_out"
        ),
    },
    "codeclone/report/html/sections/_coupling.py": {
        "cx_rows_data[:_QUALITY_TABLE_ROW_LIMIT]": (
            "test_complexity_table_states_how_many_functions_it_left_out"
        ),
        "cp_rows_data[:_QUALITY_TABLE_ROW_LIMIT]": (
            "test_coupling_table_states_how_many_classes_it_left_out"
        ),
        "ch_rows_data[:_QUALITY_TABLE_ROW_LIMIT]": (
            "test_cohesion_table_states_how_many_classes_it_left_out"
        ),
    },
    "codeclone/report/html/sections/_coverage_join.py": {
        "review_items[:_REVIEW_ROW_LIMIT]": (
            "test_coverage_join_table_states_how_many_review_items_it_left_out"
        ),
    },
    "codeclone/report/html/sections/_dead_code.py": {
        "items_data[:_DEAD_CODE_ROW_LIMIT]": (
            "test_dead_code_table_states_how_many_candidates_it_left_out"
        ),
        "suppressed_data[:_DEAD_CODE_ROW_LIMIT]": (
            "test_suppressed_dead_code_table_states_how_many_it_left_out"
        ),
    },
    "codeclone/report/html/sections/_module_map.py": {
        "rows_data[:_OVERLOADED_TABLE_CAP]": (
            "test_overloaded_module_table_states_how_many_modules_it_left_out"
        ),
    },
    "codeclone/report/html/sections/_security_surfaces.py": {
        "items[:_SURFACE_ROW_LIMIT]": (
            "test_security_surface_table_states_how_many_surfaces_it_left_out"
        ),
    },
}

#: Bounded slices that are not row cuts, with what each one actually does.
#: None of them can hide a row a reader came for: a string elision shortens one
#: label, an inline preview folds the rest behind a disclosure that counts it,
#: and a column split renders both halves.
_NOT_ROW_CUTS: dict[str, tuple[str, ...]] = {
    "codeclone/report/html/sections/_authority.py": (
        # Co-producers inside one comment line of the proposal snippet; the
        # line states "+N more, see Producers" and the column holds them all.
        "alternatives[:3]",
    ),
    "codeclone/report/html/sections/_clones.py": (
        # Group display name: three member names, then the label and the group
        # key elided to a width. All three shorten one string.
        "items[:3]",
        "label[:68]",
        "gkey[:24]",
    ),
    "codeclone/report/html/sections/_coupling.py": (
        # Coupled-classes cell preview; the rest opens from "(+N more)" in the
        # same cell.
        "names[:3]",
    ),
    "codeclone/report/html/sections/_dependencies.py": (
        # The hub bar is labelled "Top connected": showing the five strongest
        # is what it is for, not a cut of a list the reader was promised.
        "sorted(deg_map, key=lambda n: (-deg_map[n], n))[:5]",
    ),
    "codeclone/report/html/sections/_meta.py": (
        # Middle-elision of one long path.
        "value[:head]",
    ),
    "codeclone/report/html/sections/_overview.py": (
        # Two strongest finding kinds on a directory's meta line, and the
        # overview's five-entry preview of the overloaded-module candidates
        # whose full table lives in the Module map tab. The last one splits the
        # rendered entries into two columns -- both halves are drawn.
        "kind_rows[:2]",
        (
            "[_as_mapping(item) for item in "
            "_as_sequence(overloaded_modules.get('items')) "
            "if str(_as_mapping(item).get('candidate_status', '')).strip() == "
            "'candidate'][:5]"
        ),
        "rows_html[:mid]",
    ),
    "codeclone/report/html/sections/_structural.py": (
        # Occurrences beyond the visible limit move into a <details> in the
        # same table, and the example cards state "Showing the first N of M".
        "deduped_items[:visible_limit]",
        "items[:2]",
    ),
    "codeclone/report/html/widgets/badges.py": (
        # Chain label elision, and the inline hops of a chain whose tail opens
        # from "+N more".
        "label[:half]",
        "parts[:_CHAIN_INLINE_HOPS]",
    ),
    "codeclone/report/html/widgets/dep_graph_layout.py": (
        # SVG layout: one seed node per layer, and a marker id suffix.
        "sorted(nodes, key=lambda node: -out_degree.get(node, 0))[:1]",
        "sha1(payload.encode('utf-8')).hexdigest()[:10]",
    ),
    "codeclone/report/html/widgets/snippets.py": (
        # The requested line window of a source file, not a cut of a list.
        "lines[start_index:end_index]",
    ),
    "codeclone/report/html/widgets/tables.py": (
        # Values lifted onto the meta band; the band appends "+N more".
        "values[:_META_COLUMN_MAX_VALUES]",
    ),
}


def _row_limiting_slices(source: str) -> list[str]:
    """Every bounded slice in one module, as written.

    A slice with no upper bound cannot drop a row, so only bounded ones are
    reported. The scan is over the tree, never over the text: a register
    assembled by grepping for ``[:50]`` misses the same cut spelled through a
    constant, which is most of them.
    """

    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Subscript):
            continue
        node_slice = node.slice
        if isinstance(node_slice, ast.Slice) and node_slice.upper is not None:
            found.append(ast.unparse(node))
    return found


def _live_slices() -> dict[str, set[str]]:
    live: dict[str, set[str]] = {}
    for path in sorted(_HTML_PACKAGE.rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        for expression in _row_limiting_slices(path.read_text("utf-8")):
            live.setdefault(relative, set()).add(expression)
    return live


def _registered_slices() -> dict[str, set[str]]:
    registered: dict[str, set[str]] = {}
    for module, cuts in _ROW_CUTS.items():
        registered.setdefault(module, set()).update(cuts)
    for module, expressions in _NOT_ROW_CUTS.items():
        registered.setdefault(module, set()).update(expressions)
    return registered


def test_every_bounded_slice_in_the_package_is_registered() -> None:
    """The growth side: a new panel that cuts in silence fails here."""

    live = _live_slices()
    registered = _registered_slices()
    unregistered = {
        module: tuple(sorted(expressions - registered.get(module, set())))
        for module, expressions in live.items()
        if expressions - registered.get(module, set())
    }

    assert unregistered == {}, (
        "these slices drop items and are in neither register; if the slice "
        "cuts table rows, make the panel state the count and register it in "
        "_ROW_CUTS with the test that proves it, otherwise register it in "
        f"_NOT_ROW_CUTS with what it actually elides: {unregistered}"
    )


def test_no_registered_slice_has_gone_stale() -> None:
    """The stale side: an entry whose slice is gone fails here."""

    live = _live_slices()
    stale = {
        module: tuple(sorted(expressions - live.get(module, set())))
        for module, expressions in _registered_slices().items()
        if expressions - live.get(module, set())
    }

    assert stale == {}, (
        f"these registered slices are gone from the code; delete them: {stale}"
    )


def test_every_row_cut_names_a_test_that_reads_its_declaration_back() -> None:
    """A register entry with no test behind it is a promise, not a pin."""

    missing = sorted(
        f"{module}::{expression} -> {test_name}"
        for module, cuts in _ROW_CUTS.items()
        for expression, test_name in cuts.items()
        if not callable(globals().get(test_name))
    )

    assert missing == [], (
        f"these row cuts name a test this module does not define: {missing}"
    )


# --------------------------------------------------------------------------
# The fixture: every panel is rendered over more rows than it draws
# --------------------------------------------------------------------------

#: Deliberately different per family so one panel's declaration can never be
#: mistaken for another's in the same rendered page.
_COMPLEXITY_ROWS = 61
_COUPLING_ROWS = 57
_COHESION_ROWS = 53
_COVERAGE_REVIEW_ROWS = 64
_SECURITY_SURFACE_ROWS = 59
_DEAD_CODE_ROWS = 214
_SUPPRESSED_DEAD_CODE_ROWS = 207
_SUPPRESSED_CLONE_ROWS = 233
_OVERLOADED_ROWS = 66
_AUTHORITY_CANDIDATE_ROWS = 71

#: High-risk share of each oversized fixture, chosen to exceed the limit so
#: the coverage half of the sentence carries a number of its own rather than
#: repeating the row count.
_COMPLEXITY_HIGH_RISK = 55
_COUPLING_HIGH_RISK = 52
_COHESION_HIGH_RISK = 51
_COVERAGE_HIGH_RISK = 58
_DEAD_CODE_HIGH_CONFIDENCE = 205


def _ctx(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "complexity_map": {},
        "coupling_map": {},
        "cohesion_map": {},
        "dead_code_map": {},
        "overloaded_modules_map": {},
        "security_surfaces_map": {},
        "metrics_map": {},
        "report_document": {},
        "metrics_available": True,
        "scan_root": "",
        "relative_path": lambda filepath: filepath,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _graded_rows(
    count: int,
    high: int,
    *,
    field: str,
    prefix: str,
) -> list[dict[str, object]]:
    """``count`` rows of which the first ``high`` carry the top grade.

    Worst first, exactly as the canonical document orders these families, so
    the fixture exercises the ordering the panels state rather than a shape no
    run produces.
    """

    return [
        {
            "qualname": f"pkg.mod:{prefix}_{index:04d}",
            "relative_path": f"pkg/{prefix}_{index:04d}.py",
            "start_line": index + 1,
            "cyclomatic_complexity": 30 - index % 7,
            "nesting_depth": 2,
            "cbo": 20 - index % 5,
            "lcom4": 9 - index % 3,
            "method_count": 4,
            "instance_var_count": 3,
            "kind": "function",
            field: "high" if index < high else "low",
        }
        for index in range(count)
    ]


def _quality_ctx() -> SimpleNamespace:
    complexity = _graded_rows(
        _COMPLEXITY_ROWS, _COMPLEXITY_HIGH_RISK, field="risk", prefix="cx"
    )
    coupling = _graded_rows(
        _COUPLING_ROWS, _COUPLING_HIGH_RISK, field="risk", prefix="cp"
    )
    cohesion = _graded_rows(
        _COHESION_ROWS, _COHESION_HIGH_RISK, field="risk", prefix="ch"
    )
    return _ctx(
        complexity_map={
            "summary": {"high_risk": _COMPLEXITY_HIGH_RISK, "total": _COMPLEXITY_ROWS},
            "functions": complexity,
            "items": complexity,
        },
        coupling_map={
            "summary": {"high_risk": _COUPLING_HIGH_RISK, "total": _COUPLING_ROWS},
            "classes": coupling,
            "items": coupling,
        },
        cohesion_map={
            "summary": {"low_cohesion": _COHESION_HIGH_RISK, "total": _COHESION_ROWS},
            "classes": cohesion,
            "items": cohesion,
        },
    )


def test_complexity_table_states_how_many_functions_it_left_out() -> None:
    html = render_quality_panel(cast(Any, _quality_ctx()))

    assert (
        f"Showing 50 of {_COMPLEXITY_ROWS} rows · worst first "
        f"· 50 of {_COMPLEXITY_HIGH_RISK} high-risk rows"
    ) in html


def test_coupling_table_states_how_many_classes_it_left_out() -> None:
    html = render_quality_panel(cast(Any, _quality_ctx()))

    assert (
        f"Showing 50 of {_COUPLING_ROWS} rows · worst first "
        f"· 50 of {_COUPLING_HIGH_RISK} high-risk rows"
    ) in html


def test_cohesion_table_states_how_many_classes_it_left_out() -> None:
    html = render_quality_panel(cast(Any, _quality_ctx()))

    assert (
        f"Showing 50 of {_COHESION_ROWS} rows · worst first "
        f"· 50 of {_COHESION_HIGH_RISK} high-risk rows"
    ) in html


def test_a_table_that_drew_every_row_it_had_says_nothing() -> None:
    """The silent branch, which the oversized fixtures above never reach.

    The band is deliberately absent when nothing was cut -- a "Showing 4 of 4"
    on every table in the report would be noise, and noise is what stops the
    warning from being read where it matters. That makes the "no cut" branch a
    guard, and a guard no input reaches is theatre: this is the input that
    reaches it.
    """

    rows = _graded_rows(4, 2, field="risk", prefix="cx")
    ctx = _ctx(
        complexity_map={
            "summary": {"high_risk": 2, "total": 4},
            "functions": rows,
            "items": rows,
        },
    )

    html = render_quality_panel(cast(Any, ctx))

    assert "Showing" not in html
    assert "table-meta-count" not in html


def test_the_band_says_all_when_the_whole_graded_population_fits() -> None:
    """The other half of the coverage sentence.

    "50 of 61 high-risk" and "all 12 high-risk" are different answers to the
    reader's actual question, and the fixtures above only ever produce the
    first. Without this, the branch that says the cut lost nothing that
    matters could be deleted or inverted and every other test would stay
    green.
    """

    rows = _graded_rows(_COMPLEXITY_ROWS, 12, field="risk", prefix="cx")
    ctx = _ctx(
        complexity_map={
            "summary": {"high_risk": 12, "total": _COMPLEXITY_ROWS},
            "functions": rows,
            "items": rows,
        },
    )

    html = render_quality_panel(cast(Any, ctx))

    assert (
        f"Showing 50 of {_COMPLEXITY_ROWS} rows · worst first · all 12 high-risk rows"
    ) in html
    assert "12 of 12 high-risk rows" not in html


def test_coverage_join_table_states_how_many_review_items_it_left_out() -> None:
    items = [
        {
            **row,
            "coverage_review_item": True,
            "coverage_hotspot": index < _COVERAGE_HIGH_RISK,
            "scope_gap_hotspot": False,
            "coverage_permille": 400,
            "coverage_status": "below_threshold",
        }
        for index, row in enumerate(
            _graded_rows(
                _COVERAGE_REVIEW_ROWS,
                _COVERAGE_HIGH_RISK,
                field="risk",
                prefix="cov",
            )
        )
    ]
    ctx = _ctx(
        metrics_map={
            "coverage_join": {
                "summary": {
                    "status": "ok",
                    "source": "coverage.xml",
                    "coverage_hotspots": _COVERAGE_HIGH_RISK,
                    "scope_gap_hotspots": 0,
                    "overall_permille": 800,
                    "hotspot_threshold_percent": 60,
                },
                "items": items,
            }
        },
    )

    html = render_coverage_join_panel(cast(Any, ctx))

    assert (
        f"Showing 50 of {_COVERAGE_REVIEW_ROWS} rows · worst first "
        f"· 50 of {_COVERAGE_HIGH_RISK} high-risk rows"
    ) in html


def test_security_surface_table_states_how_many_surfaces_it_left_out() -> None:
    items = [
        {
            "category": "filesystem",
            "capability": "read",
            "evidence_symbol": f"open_{index:04d}",
            "source_kind": "production",
            "location_scope": "callable",
            "qualname": f"pkg.mod:surface_{index:04d}",
            "relative_path": f"pkg/surface_{index:04d}.py",
            "start_line": index + 1,
        }
        for index in range(_SECURITY_SURFACE_ROWS)
    ]
    ctx = _ctx(
        security_surfaces_map={
            "summary": {
                "items": _SECURITY_SURFACE_ROWS,
                "category_count": 1,
                "modules": _SECURITY_SURFACE_ROWS,
                "production": _SECURITY_SURFACE_ROWS,
                "tests": 0,
                "exact_items": _SECURITY_SURFACE_ROWS,
                "fixtures": 0,
            },
            "items": items,
        },
    )

    html = render_security_surfaces_panel(cast(Any, ctx))

    assert (f"Showing 50 of {_SECURITY_SURFACE_ROWS} rows · in file order") in html


def _dead_code_ctx() -> SimpleNamespace:
    active = _graded_rows(
        _DEAD_CODE_ROWS,
        _DEAD_CODE_HIGH_CONFIDENCE,
        field="confidence",
        prefix="dead",
    )
    suppressed = [
        {**row, "suppressed_by": [{"rule": "dead-code", "source": "inline"}]}
        for row in _graded_rows(
            _SUPPRESSED_DEAD_CODE_ROWS, 0, field="confidence", prefix="supp"
        )
    ]
    return _ctx(
        dead_code_map={
            "summary": {
                "total": _DEAD_CODE_ROWS,
                "high_confidence": _DEAD_CODE_HIGH_CONFIDENCE,
                "suppressed": _SUPPRESSED_DEAD_CODE_ROWS,
            },
            "items": active,
            "suppressed_items": suppressed,
        },
    )


def test_dead_code_table_states_how_many_candidates_it_left_out() -> None:
    html = render_dead_code_panel(cast(Any, _dead_code_ctx()))

    assert (
        f"Showing 200 of {_DEAD_CODE_ROWS} rows · worst first "
        f"· 200 of {_DEAD_CODE_HIGH_CONFIDENCE} high-confidence rows"
    ) in html


def test_suppressed_dead_code_table_states_how_many_it_left_out() -> None:
    html = render_dead_code_panel(cast(Any, _dead_code_ctx()))

    assert (f"Showing 200 of {_SUPPRESSED_DEAD_CODE_ROWS} rows · in file order") in html


def test_suppressed_clone_table_states_how_many_groups_it_left_out() -> None:
    groups = [
        {
            "id": f"group-{index:04d}",
            "clone_kind": "function",
            "clone_type": "exact",
            "count": 2,
            "suppression_rule": f"golden-fixture-{index:04d}",
            "suppression_source": "pyproject",
            "matched_patterns": [f"tests/fixtures/case_{index:04d}/**"],
            "items": [
                {
                    "filepath": f"tests/fixtures/case_{index:04d}/mod.py",
                    "qualname": f"case_{index:04d}:fn",
                    "relative_path": f"tests/fixtures/case_{index:04d}/mod.py",
                }
            ],
        }
        for index in range(_SUPPRESSED_CLONE_ROWS)
    ]

    html = _render_suppressed_clone_panel(cast(Any, _ctx()), groups)

    assert (
        f"Showing 200 of {_SUPPRESSED_CLONE_ROWS} rows "
        "· functions, then blocks, then segments"
    ) in html


def test_overloaded_module_table_states_how_many_modules_it_left_out() -> None:
    items = [
        {
            "module": f"pkg.mod_{index:04d}",
            "relative_path": f"pkg/mod_{index:04d}.py",
            "score": f"{9.0 - index / 100:.2f}",
            "candidate_status": "candidate" if index < 55 else "ranked_only",
            "loc": 400,
            "fan_in": 3,
            "fan_out": 4,
            "complexity_total": 90,
            "size_score": 1.0,
            "dependency_score": 1.0,
        }
        for index in range(_OVERLOADED_ROWS)
    ]
    ctx = _ctx(
        overloaded_modules_map={
            "summary": {
                "total": _OVERLOADED_ROWS,
                "candidates": 55,
                "max_score": 9.0,
                "cutoff": 5.0,
            },
            "items": items,
        },
    )

    html = _render_overloaded_modules_section(cast(Any, ctx))

    assert (
        f"Showing 50 of {_OVERLOADED_ROWS} rows · candidates first, "
        "by score · 50 of 55 candidate rows"
    ) in html


def test_authority_candidate_table_states_how_many_it_left_out() -> None:
    candidates = [
        {
            "item_kind": "candidate",
            "level": "exact_contract_ir",
            "score": 90 - index % 10,
            "producers": [f"pkg.mod:producer_{index:04d}"],
            "candidate_id": f"cand-{index:04d}",
        }
        for index in range(_AUTHORITY_CANDIDATE_ROWS)
    ]
    ctx = _ctx(
        metrics_map={
            "semantic_authority": {
                "summary": {
                    "enforcement_enabled": True,
                    "sinks": 900,
                    "governed_sinks": 3,
                    "active_violations": 0,
                    "suppressed_violations": 0,
                    "registry_contracts": 2,
                    "candidates": _AUTHORITY_CANDIDATE_ROWS,
                },
                "items": candidates,
            }
        },
    )

    html = render_authority_panel(cast(Any, ctx))

    assert (
        f"Showing 50 of {_AUTHORITY_CANDIDATE_ROWS} rows · strongest evidence first"
    ) in html
