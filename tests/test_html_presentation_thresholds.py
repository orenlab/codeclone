# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""No number the renderer invented may decide what the HTML report says.

The Quality tab painted its two average cards ``warn if avg > 5 else good``.
That five exists nowhere else in the product: the calibrated bands belong to a
row's ``risk``, and no band for an *average* is defined in the document, in the
contracts, or in any published reference population. So the renderer was
issuing a verdict of its own -- on a scale it invented, over a repository it
had never been calibrated against -- while the document beside it said nothing
of the kind. A parameter that moves a user-facing verdict is accepted only
through an independent calibration; a threshold introduced in presentation
skips that entirely, whatever number is chosen.

Deleting those two comparisons would pin two lines. Tomorrow there is a third,
because writing ``"warn" if x > 5 else "good"`` is the obvious thing to write.
This module pins the class instead:

    No module under ``codeclone/report/html/`` may compare a value against a
    number of its own without that number being named in a register here.

The scan is mechanical -- every :class:`ast.Compare` in every module of the
package, found by walking the trees, never by matching text or by listing the
files that are known to be interesting. Two refinements, both of which close a
way the rule could otherwise be satisfied without being obeyed:

* A threshold spelled through a module-level constant is still a threshold, so
  names bound to a number at module level -- in the module itself or imported
  from a sibling module of the package -- are resolved and counted. Moving
  ``5`` into ``_AVG_CC_LIMIT`` must not buy silence. Three live sites are found
  only through this step.
* The arity boundaries ``0`` and ``1`` are excluded by the rule itself, not by
  the register. "None of them", "exactly one" and "more than one" state how
  many things exist; that is a fact about the population, and the report is
  entitled to state it. ``x > 0`` colouring a count is the presence of a
  finding, not a judgement of its size -- the distinction the fix above turns
  on.

Both registers are two-sided. A number that appears without an entry fails as
growth; an entry whose comparison is gone from the code fails as a stale entry.
A one-sided register is a ratchet that can be satisfied by choosing a shape it
does not match, and it rots the moment the code moves on.

The split between the two registers is the judgement, and it is deliberately
human: the scanner decides *where the numbers are*, a reader decides *what each
one means*. :data:`_RENDERING_NUMBERS` holds numbers that describe the drawing
-- how long a label may be before it is elided, how many nodes fit a row of the
SVG, how many members a list previews. :data:`_METRIC_BANDS_DEFERRED_TO_F3`
holds the real thing: bands over measured values, invented in presentation,
each one the same defect as the two this module was written for. They are
registered rather than fixed because removing them changes what a user sees,
and that is a calibration decision, not a rendering one.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HTML_PACKAGE = _REPO_ROOT / "codeclone" / "report" / "html"

#: Comparisons the rule allows outright: how many things there are, never how
#: large a measure is.
_ARITY_BOUNDARIES: tuple[float, ...] = (0, 1)

#: Numbers that describe the rendering itself -- geometry, truncation, how many
#: items a preview shows. None of them classifies a measured value, so none of
#: them carries a verdict the document would have to publish.
_RENDERING_NUMBERS: dict[str, tuple[str, ...]] = {
    "codeclone/report/html/_context.py": (
        # "k:v" splits into exactly two parts or it is not a pair.
        "len(pair) == 2",
    ),
    "codeclone/report/html/sections/_clones.py": (
        # A compare note explains which member differs from which; with two
        # members there is nothing to disambiguate.
        "group_arity <= 2",
        # Label and key elision widths.
        "len(bare) >= 16",
        "len(gkey) > 56",
        "len(label) > 72",
    ),
    "codeclone/report/html/sections/_coupling.py": (
        # How many coupled class names the cell shows before it folds the rest
        # into a <details>.
        "len(names) <= 3",
    ),
    "codeclone/report/html/sections/_overview.py": (
        # Radar label anchoring: which side of the centre the label sits on.
        "dx > 5",
    ),
    "codeclone/report/html/sections/_structural.py": (
        # The first two examples are lettered A and B, the rest numbered.
        "idx < 2",
    ),
    "codeclone/report/html/sections/_suggestions.py": (
        # "k:v" splits into exactly two parts or it is not a pair.
        "len(pair) == 2",
    ),
    "codeclone/report/html/widgets/dep_graph_layout.py": (
        # SVG row packing and viewport sizing.
        "len(members) < 3",
        "len(nodes) > _COMPACT_NODE_LIMIT",
        "len(nodes) >= _WIDE_NODE_LIMIT",
        "next_width > _MAX_ROW_WIDTH",
        "vb_w >= 980",
    ),
    "codeclone/report/html/widgets/tables.py": (
        # A column with few distinct values is rendered as chips rather than
        # as text; a property of the drawn column, not of any measure.
        "0 < len(dict.fromkeys(_column_values(rows, index))) "
        "<= _META_COLUMN_MAX_VALUES",
    ),
}

#: Bands over measured values, invented in presentation. Every entry is the
#: same defect as the ``avg_cc > 5`` this module was written for: the number is
#: the renderer's, not the document's, and the reader cannot tell the
#: difference. They are deferred to F-3, where a row classifier is carried into
#: the document and read back here instead of being re-invented; they are not
#: removed now because dropping a band changes a user-facing verdict.
#:
#: The register is a work queue with a deadline, not a permit. The stale side
#: below reds the moment one of these is repaired and its entry is not deleted.
_METRIC_BANDS_DEFERRED_TO_F3: dict[str, tuple[str, ...]] = {
    "codeclone/report/html/sections/_coupling.py": (
        # Max CC / Max CBO / Max LCOM4 card verdicts, and the "deep nesting"
        # population. The document publishes a per-row ``risk``; the maximum's
        # verdict and the nesting depth at which a function counts as deep are
        # not published anywhere, so the cards decide both.
        "_as_int(_as_mapping(r).get('nesting_depth')) > 4",
        "max_cbo > 12",
        "max_cbo > 8",
        "max_cc > 10",
        "max_cc > 15",
        "max_lcom4 > 3",
    ),
    "codeclone/report/html/sections/_dead_code.py": (
        # Hit-rate card: high-confidence share of the dead-code total, banded
        # by two numbers that appear in no contract.
        "pct > 20",
        "pct > 50",
    ),
    "codeclone/report/html/sections/_dependencies.py": (
        # A module is drawn as a hub above a computed threshold *and* above a
        # floor of two edges; the floor is the renderer's.
        "degree > 2",
        # Dependency health below its own maximum turns the tab amber.
        "dependency_health < 100",
    ),
    "codeclone/report/html/sections/_module_map.py": (
        # Same hub floor, second drawing.
        "total_degree > 2",
    ),
    "codeclone/report/html/sections/_overview.py": (
        # Two different band sets for one health score in one file: the ring
        # colours at 75/60 and the insight tone at 80/60. The document already
        # carries ``metrics.summary.health.grade``; neither reads it.
        "health_score >= 60.0",
        "health_score >= 80.0",
        "score >= 60",
        "score >= 75",
        # A radar spoke below 60 is drawn as weak.
        "s < 60",
    ),
    "codeclone/report/html/widgets/badges.py": (
        # Table meters band by share of the column maximum, and the discovery
        # score bar calls itself strong above 0.8.
        "fraction >= 0.33",
        "fraction >= 0.66",
        "score >= 0.8",
    ),
}


def _numeric_value(node: ast.expr) -> float | None:
    """The number a node states outright, or None.

    ``bool`` is a subclass of ``int`` and is excluded on purpose: ``x is True``
    compares a state, not a magnitude.
    """

    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    return None


def module_numeric_constants(tree: ast.Module) -> dict[str, float]:
    """Every module-level name in one tree that is bound to a plain number."""

    constants: dict[str, float] = {}
    for statement in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
            value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
            value = statement.value
        number = None if value is None else _numeric_value(value)
        if number is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = number
    return constants


def _imported_constants(
    tree: ast.Module,
    package_constants: Mapping[str, Mapping[str, float]],
) -> dict[str, float]:
    """Numbers this module imports from a sibling module of the package.

    Resolved by the last segment of the imported module, which is what the
    package's relative imports spell. A threshold does not stop being one by
    being defined next door.
    """

    imported: dict[str, float] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        origin = (node.module or "").rsplit(".", 1)[-1]
        exported = package_constants.get(origin, {})
        for alias in node.names:
            if alias.name in exported:
                imported[alias.asname or alias.name] = exported[alias.name]
    return imported


def presentation_thresholds(
    source: str,
    *,
    package_constants: Mapping[str, Mapping[str, float]] | None = None,
) -> list[tuple[int, str]]:
    """Every comparison in one module that states a number of its own.

    Returns the line and the comparison as written, so a failure names the
    thing to go and look at. Arity boundaries are dropped here rather than in
    the register: they are outside the rule, not exceptions to it.
    """

    tree = ast.parse(source)
    known = module_numeric_constants(tree)
    known.update(_imported_constants(tree, package_constants or {}))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        numbers: list[float] = []
        for operand in (node.left, *node.comparators):
            number = _numeric_value(operand)
            if number is None and isinstance(operand, ast.Name):
                number = known.get(operand.id)
            if number is not None:
                numbers.append(number)
        if any(number not in _ARITY_BOUNDARIES for number in numbers):
            found.append((node.lineno, ast.unparse(node)))
    return found


def _package_constants() -> dict[str, dict[str, float]]:
    return {
        path.stem: module_numeric_constants(ast.parse(path.read_text("utf-8")))
        for path in sorted(_HTML_PACKAGE.rglob("*.py"))
    }


def _live_thresholds() -> dict[str, set[str]]:
    """Every number-of-its-own the HTML package states today, by module."""

    package_constants = _package_constants()
    live: dict[str, set[str]] = {}
    for path in sorted(_HTML_PACKAGE.rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        for _line, comparison in presentation_thresholds(
            path.read_text("utf-8"),
            package_constants=package_constants,
        ):
            live.setdefault(relative, set()).add(comparison)
    return live


def _registered() -> dict[str, set[str]]:
    registered: dict[str, set[str]] = {}
    for register in (_RENDERING_NUMBERS, _METRIC_BANDS_DEFERRED_TO_F3):
        for module, comparisons in register.items():
            registered.setdefault(module, set()).update(comparisons)
    return registered


def test_html_states_no_number_of_its_own_outside_the_register() -> None:
    """The growth side: a new threshold in the package fails here.

    ``avg_cc > 5`` and ``avg_cbo > 5`` were in neither register, which is what
    this test said about them before they were deleted.
    """

    live = _live_thresholds()
    registered = _registered()
    unexpected = {
        module: tuple(sorted(comparisons - registered.get(module, set())))
        for module, comparisons in live.items()
        if comparisons - registered.get(module, set())
    }

    assert unexpected == {}, (
        "these HTML modules compare a value against a number of their own; "
        "the report shows what the document measures, so read a published "
        "band or state the fact without grading it -- and if the number "
        "genuinely describes the drawing rather than a measure, register it "
        f"with the reason: {unexpected}"
    )


def test_registered_html_numbers_are_all_still_in_the_code() -> None:
    """The stale side: a register entry whose comparison is gone fails here.

    Without it the register only grows, and an entry outlives the code it
    excused -- which is how a list of exceptions turns into a list of things
    nobody has read in a year.
    """

    live = _live_thresholds()
    stale = {
        module: tuple(sorted(set(comparisons) - live.get(module, set())))
        for module, comparisons in _registered().items()
        if set(comparisons) - live.get(module, set())
    }

    assert stale == {}, (
        "these registered comparisons are gone from the code; delete the "
        f"entries rather than carrying them: {stale}"
    )


def test_scanner_reads_a_threshold_wherever_it_decides_something() -> None:
    """The scan is about the number, not about what the number is used for.

    A tone, a CSS class, a boolean handed to a style helper and a plain count
    are all the same defect, so the scan must not be taught to recognise only
    the shape the last one happened to take. Without this the class pin could
    go quietly blind: a scanner that reconstructs nothing reports nothing and
    stays green forever.
    """

    source = (
        'tone = "warn" if avg_cc > 5 else "good"\n'
        'css = " meter--high" if fraction >= 0.66 else ""\n'
        "style = node_style(is_hub=degree > 2)\n"
        "deep = sum(1 for r in rows if r.nesting > 4)\n"
    )

    assert [comparison for _line, comparison in presentation_thresholds(source)] == [
        "avg_cc > 5",
        "fraction >= 0.66",
        "degree > 2",
        "r.nesting > 4",
    ]


def test_scanner_lets_the_arity_boundaries_through() -> None:
    """Counting is not grading, and the fix depends on the difference.

    ``high_risk > 0`` states that a finding exists; ``avg_cc > 5`` states that
    an average is too large. A scan that could not tell them apart would have
    forced the presence tones to be registered as exceptions, and the register
    would have become noise on its first day.
    """

    source = (
        'tone = "bad" if high_risk > 0 else "good"\n'
        'word = "file" if spread_files == 1 else "files"\n'
        'spread = "high" if spread_files > 1 else "low"\n'
        "empty = total <= 0\n"
    )

    assert presentation_thresholds(source) == []


def test_scanner_resolves_a_threshold_hidden_behind_a_constant() -> None:
    """Naming the number does not remove it.

    The cheapest way to satisfy a scan that only reads literals is to write
    ``_AVG_CC_LIMIT = 5`` at the top of the module and compare against that.
    The rule is about the renderer stating a number, not about where the number
    is typed, so both spellings have to land in the same place.
    """

    source = (
        "_AVG_CC_LIMIT = 5\n"
        "_MANY: int = 1\n"
        "def band(avg, n):\n"
        "    return avg > _AVG_CC_LIMIT and n > _MANY\n"
    )

    assert [comparison for _line, comparison in presentation_thresholds(source)] == [
        "avg > _AVG_CC_LIMIT"
    ]


def test_scanner_resolves_a_threshold_imported_from_a_sibling_module() -> None:
    """The constant may live next door; the comparison still states a number.

    ``dep_graph_layout`` compares against three limits defined at its own top,
    and this step is what keeps the same move across a module boundary from
    being invisible.
    """

    package_constants = {"_limits": {"AVG_CC_LIMIT": 5.0}}
    source = (
        "from ._limits import AVG_CC_LIMIT\n"
        "def band(avg):\n"
        "    return avg > AVG_CC_LIMIT\n"
    )

    assert [
        comparison
        for _line, comparison in presentation_thresholds(
            source,
            package_constants=package_constants,
        )
    ] == ["avg > AVG_CC_LIMIT"]


def test_scanner_sees_the_whole_package() -> None:
    """The inventory is built by walking the package, not from a list of files.

    A scan pointed at the section modules alone would have missed the meter
    bands in ``widgets/badges.py`` and the layout limits in
    ``widgets/dep_graph_layout.py``, and a register assembled from the files
    someone remembered would be exactly the thing this module exists to stop
    being.
    """

    scanned = {
        path.relative_to(_REPO_ROOT).as_posix() for path in _HTML_PACKAGE.rglob("*.py")
    }

    assert len(scanned) > 20
    assert "codeclone/report/html/widgets/badges.py" in scanned
    assert "codeclone/report/html/sections/_coupling.py" in scanned
    assert set(_registered()) <= scanned
