# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Behavioral consumers of the ``statement_reachability`` golden fixture.

Phase 39Y slice Y9. CodeClone had no statement-level unreachability detection
at all. The declared rule, version ``STATEMENT_REACHABILITY_POLICY_VERSION``,
is ONE predicate over ONE graph:

    within a function, a statement cannot run exactly when its block is not
    reachable from ``CFG.entry`` by directed traversal of ``Block.successors``.

There is no second clause. Code after a terminator and a branch behind a
literal guard are not separate rules — the norm CFG builder expresses both
structurally, by emitting the post-terminator tail as a real block with no
incoming edge, and by suppressing the edge into a suite whose guard is a
*literal* ``ast.Constant`` that forbids entry (``if False`` / ``while False``
bodies, the ``orelse`` of ``if True``). ``UnreachableReason`` names a cause for
the reader and is evidence only: the block is decided unreachable by traversal
before any origin is consulted, and no verdict depends on it.

There is no value inference and no propagation. ``flag = False`` followed by
``if flag:`` is NOT unreachable, and the restraint test below pins that: the
moment a name lookup becomes evidence, the rule stops being the declared
predicate and becomes the hidden heuristic this phase forbids.

Two structural properties the tests below fence:

* exception dispatch, ``finally`` routing and context-manager suppression are
  ordinary edges of the same graph, so traversal answers them like everything
  else. These edges deliberately *over*-approximate reachability, which
  under-approximates findings — the honest direction for a dead-code detector,
  and the reason a handler body, a ``finally`` clause and the code after a
  suppressing ``with`` are never reported;
* blocks, successors and their statement lists are also the fingerprint input
  (``analysis.fingerprint``) and the complexity input (``metrics.complexity``),
  so the extended graph moves both. That movement is intended and rides the one
  sanctioned ``BASELINE_FINGERPRINT_VERSION`` bump at the 39Y landing; there is
  no side channel and no second source of truth.

Expected outcomes are read from the fixture's ``ground_truth.json`` — never
inlined here.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from codeclone.analysis.fingerprint import _cfg_fingerprint_and_complexity
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.statement_reachability import unreachable_statements
from codeclone.contracts import STATEMENT_REACHABILITY_POLICY_VERSION
from codeclone.observations.contracts import lane_payload_schema
from codeclone.report.document.builder import build_report_body
from tests._ast_metrics_helpers import bindings_for_function_node
from tests._pipeline_fixtures import (
    analysis_boot,
    extract_units,
    golden_case,
    golden_ground_truth,
    package_tree,
    payload_mapping,
    payload_sequence,
    run_pipeline_once,
)

if TYPE_CHECKING:
    from codeclone.core._types import AnalysisResult, BootstrapResult

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "statement_reachability"

# The fixture functions are small on purpose; the reachability lane is
# deliberately independent of the clone floors (39Y Y5), so the floors used
# here must never decide a reachability assertion.
FIXTURE_MIN_LOC = 6
FIXTURE_MIN_STMT = 4


DOMAIN = "statement_reachability"


def _declared_case(case_id: str) -> dict[str, Any]:
    return golden_case(DOMAIN, case_id)


def _cases() -> list[dict[str, Any]]:
    return [dict(case) for case in golden_ground_truth(DOMAIN)["cases"]]


def _case_ids(*, unreachable: bool) -> list[str]:
    return [
        str(case["id"])
        for case in _cases()
        if bool(case["expected"]["unreachable"]) is unreachable
    ]


def _reachability_by_symbol(path: str) -> dict[str, tuple[Any, ...]]:
    """Return the unreachable findings of every function in one fixture file."""

    source = (FIXTURE_ROOT / path).read_text("utf-8")
    found: dict[str, tuple[Any, ...]] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        graph, _fingerprint, _complexity = _cfg_fingerprint_and_complexity(
            node,
            NormalizationConfig(),
            node.name,
            bindings_for_function_node(node),
        )
        found[node.name] = unreachable_statements(graph)
    return found


def _findings_for(case: Mapping[str, Any]) -> tuple[Any, ...]:
    return _reachability_by_symbol(str(case["path"]))[str(case["symbol"])]


# ---------------------------------------------------------------------------
# The declared rule
# ---------------------------------------------------------------------------


def test_policy_version_is_a_named_contract_constant() -> None:
    """No hidden thresholds: the policy carries a named, asserted version."""

    assert STATEMENT_REACHABILITY_POLICY_VERSION == "1"


@pytest.mark.parametrize("case_id", _case_ids(unreachable=True))
def test_declared_unreachable_cases_are_flagged(case_id: str) -> None:
    case = _declared_case(case_id)
    findings = _findings_for(case)
    assert findings, (
        f"{case_id}: {case['symbol']} declares unreachable code, none was found"
    )


@pytest.mark.parametrize("case_id", _case_ids(unreachable=False))
def test_declared_reachable_cases_are_not_flagged(case_id: str) -> None:
    """The negatives exist precisely so a flag-everything detector fails."""

    case = _declared_case(case_id)
    findings = _findings_for(case)
    assert not findings, (
        f"{case_id}: {case['symbol']} is fully reachable, got {findings!r}"
    )


def test_every_declared_case_is_exercised() -> None:
    """The parametrization above must cover the whole golden, not a subset."""

    covered = set(_case_ids(unreachable=True)) | set(_case_ids(unreachable=False))
    assert covered == {str(case["id"]) for case in _cases()}


# ---------------------------------------------------------------------------
# Mechanical guards (§1.3): rename invariance and negative twins
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pair", golden_ground_truth(DOMAIN)["rename_twins"])
def test_rename_twins_classify_identically(pair: Sequence[str]) -> None:
    """Renaming every identifier must not move a case across the boundary."""

    left, right = _declared_case(str(pair[0])), _declared_case(str(pair[1]))
    left_findings, right_findings = _findings_for(left), _findings_for(right)
    assert bool(left_findings) == bool(right_findings)
    assert [finding.reason for finding in left_findings] == [
        finding.reason for finding in right_findings
    ]
    assert [finding.statement_count for finding in left_findings] == [
        finding.statement_count for finding in right_findings
    ]


@pytest.mark.parametrize("pair", golden_ground_truth(DOMAIN)["negative_twins"])
def test_negative_twins_land_on_opposite_sides(pair: Sequence[str]) -> None:
    """Each twin axis isolates one structural difference; the rule must see it."""

    positive, negative = _declared_case(str(pair[0])), _declared_case(str(pair[1]))
    assert _findings_for(positive)
    assert not _findings_for(negative)


def test_literal_rule_does_not_infer_values() -> None:
    """The restraint: a literal condition is evidence, a name is never evidence.

    Written inline rather than as a golden case because it asserts the ABSENCE
    of a rule against a corpus that is frozen; the fixture gap is reported
    rather than closed by editing a golden.
    """

    source = (
        "def constant_binding(value: int) -> int:\n"
        "    flag = False\n"
        "    if flag:\n"
        "        return value + 1\n"
        "    return value\n"
    )
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    graph, _fingerprint, _complexity = _cfg_fingerprint_and_complexity(
        node,
        NormalizationConfig(),
        node.name,
        bindings_for_function_node(node),
    )
    assert not unreachable_statements(graph), (
        "value propagation is not part of the declared rule"
    )


def test_literal_true_else_branch_is_unreachable() -> None:
    """The mirror of ``if False``; the golden carries only the falsy direction."""

    source = (
        "def always(value: int) -> int:\n"
        "    if True:\n"
        "        return value\n"
        "    else:\n"
        "        return -value\n"
    )
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.FunctionDef)
    graph, _fingerprint, _complexity = _cfg_fingerprint_and_complexity(
        node,
        NormalizationConfig(),
        node.name,
        bindings_for_function_node(node),
    )
    findings = unreachable_statements(graph)
    assert [finding.reason for finding in findings] == ["literal_condition"]
    assert findings[0].start_line == 5


# ---------------------------------------------------------------------------
# Evidence honesty
# ---------------------------------------------------------------------------


def test_findings_carry_the_cfg_proof_and_are_deterministic() -> None:
    """Severity/confidence are fixed high and the reason names the proof."""

    findings = _findings_for(_declared_case("UNREACHABLE-AFTER-RETURN"))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.reason == "after_terminator"
    assert finding.start_line == 3
    assert finding.end_line == 3
    assert finding.statement_count == 1


def test_orphan_block_case_is_proven_by_graph_reachability() -> None:
    """The exhaustive-return case is the one plain block reachability sees."""

    findings = _findings_for(_declared_case("UNREACHABLE-EXHAUSTIVE"))
    assert [finding.reason for finding in findings] == ["unreachable_block"]


def test_spans_are_never_fabricated_for_position_less_nodes() -> None:
    """The CFG synthesizes ``ast.Expr`` nodes that carry no ``lineno``.

    A region built only from synthesized markers has no source span to point
    at, so it is not reported at all; nothing invents a line number, and no
    finding may escape carrying line 0 (the Y8 precedent).
    """

    for path in ("cases.py", "cases_renamed.py"):
        for findings in _reachability_by_symbol(path).values():
            for finding in findings:
                assert finding.start_line > 0
                assert finding.end_line >= finding.start_line


# ---------------------------------------------------------------------------
# Abstention: where the graph cannot support a proof
# ---------------------------------------------------------------------------
#
# All three shapes below were live false positives found by running the
# detector over this repository: 33 of 33 production "findings" were these.
# The CFG models exception and context-manager flow approximately because it
# exists to fingerprint structure, not to decide reachability, so "no
# predecessor" is not "cannot run" here. Each case is code that demonstrably
# executes.


def _findings_for_source(source: str, symbol: str) -> tuple[Any, ...]:
    node = next(
        item
        for item in ast.parse(source).body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == symbol
    )
    graph, _fingerprint, _complexity = _cfg_fingerprint_and_complexity(
        node,
        NormalizationConfig(),
        symbol,
        bindings_for_function_node(node),
    )
    return unreachable_statements(graph)


def test_finally_clause_after_a_returning_body_is_not_reported() -> None:
    """A ``finally`` always runs, and the graph routes every exit through it.

    The ``return`` does not leave the protected region directly: it leaves via
    the finally block, which therefore has an incoming edge and is reachable.
    """

    source = (
        "def guarded(value: int) -> int:\n"
        "    lock = acquire()\n"
        "    try:\n"
        "        return value\n"
        "    finally:\n"
        "        if lock:\n"
        "            release(lock)\n"
    )
    assert not _findings_for_source(source, "guarded")


def test_exception_handler_body_is_not_reported() -> None:
    """Every handler is linked from its region entry, with nothing guessed.

    The builder emits one dispatch edge per (``try`` region, handler) from the
    region entry block. It never asks which statements "can raise" — a
    syntactic guess that would have to call ``import`` non-raising and would
    then report this handler body as dead code.
    """

    source = (
        "def optional_dependency() -> object | None:\n"
        "    try:\n"
        "        import psutil\n"
        "    except ImportError:\n"
        "        return None\n"
        "    return psutil\n"
    )
    assert not _findings_for_source(source, "optional_dependency")


def test_code_after_a_suppressing_with_is_not_reported() -> None:
    """``__exit__`` may swallow the exception and let the body fall through."""

    source = (
        "def expects_failure() -> int:\n"
        "    with raises(ValueError):\n"
        "        raise ValueError('nope')\n"
        "    return 1\n"
    )
    assert not _findings_for_source(source, "expects_failure")


def test_conservative_edges_do_not_swallow_the_declared_positives() -> None:
    """Over-approximating reachability must not become a blanket amnesty.

    The extra dispatch edges make more blocks reachable, which is the intended
    direction. They must not make a genuinely dead tail reachable too: a
    statement after ``return`` is still reported in a function that also owns a
    ``try`` region, because no edge of that region reaches the tail.
    """

    source = (
        "def mixed(value: int) -> int:\n"
        "    try:\n"
        "        value = int(value)\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    return value\n"
        "    value += 1\n"
    )
    findings = _findings_for_source(source, "mixed")
    assert [finding.reason for finding in findings] == ["after_terminator"]
    assert findings[0].start_line == 7


def test_production_source_unreachable_statements_are_only_the_known_one() -> None:
    """Acceptance 9 as a ratchet: no NEW unreachable statement in production.

    Never satisfied by suppression. Every production finding the condemned
    implementation produced was false and was answered by making the graph
    model exception and suppression flow instead of excusing it. What the norm
    then found is one real defect, recorded here by name so a second one fails
    this test rather than hiding behind it.
    """

    # The single 39Y-recorded offender (governance.py
    # _contains_unnegated_phrase() literal_condition) was retired in the
    # memory-markdown slice, whose scope owned governance.py: the scan loop
    # now has a real condition with identical semantics. The ratchet holds
    # at zero — any unreachable production statement fails this test.
    known: set[str] = set()

    package_root = Path(__file__).resolve().parent.parent / "codeclone"
    offenders: set[str] = set()
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            graph, _fingerprint, _complexity = _cfg_fingerprint_and_complexity(
                node,
                NormalizationConfig(),
                node.name,
                bindings_for_function_node(node),
            )
            offenders.update(
                f"{path.name}:{finding.start_line} {node.name}() {finding.reason}"
                for finding in unreachable_statements(graph)
            )
    assert offenders == known


# ---------------------------------------------------------------------------
# Carriage: the unit fact and the cold/warm guard
# ---------------------------------------------------------------------------


def test_unit_carries_the_unreachable_fact_regardless_of_clone_floors() -> None:
    """Y5 discipline: the clone floors must not decide what reachability sees."""

    units = {
        unit.qualname.rsplit(":", 1)[-1]: unit
        for unit in extract_units(
            FIXTURE_ROOT, min_loc=FIXTURE_MIN_LOC, min_stmt=FIXTURE_MIN_STMT
        )
    }
    for case in _cases():
        symbol = str(case["symbol"])
        unit = units.get(symbol)
        assert unit is not None, f"no unit fact for {symbol}"
        expected = bool(case["expected"]["unreachable"])
        assert bool(unit.unreachable_statements) is expected, symbol


def _fixture_boot(root: Path) -> BootstrapResult:
    """Lay the fixture package out under ``root`` and bootstrap over it."""

    package_tree(root, FIXTURE_ROOT / "cases.py")
    return analysis_boot(
        root,
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
        skip_metrics=False,
    )


def _unreachable_signature(units: Sequence[Any]) -> tuple[str, ...]:
    rows: list[str] = []
    for unit in units:
        qualname = unit["qualname"] if isinstance(unit, dict) else unit.qualname
        facts = (
            unit.get("unreachable_statements", ())
            if isinstance(unit, dict)
            else unit.unreachable_statements
        )
        rows.extend(
            f"{qualname}|{fact.reason}|{fact.start_line}-{fact.end_line}"
            f"|{fact.statement_count}"
            for fact in facts
        )
    return tuple(sorted(rows))


def test_unreachable_facts_match_cold_and_warm(tmp_path: Path) -> None:
    """The carriage guard (39J pattern) over the in-flight CACHE_VERSION 3.2 wire.

    The CFG is built only on the analysed path: a warm run takes its units
    straight off the wire and never rebuilds a graph. Unless the per-unit
    reachability fact rides that wire, a warm run silently reports no
    unreachable statements at all.
    """

    boot = _fixture_boot(tmp_path)
    cache_path = tmp_path / "cache.json"

    cold_cache, cold = run_pipeline_once(boot, cache_path, root=tmp_path, warm=False)
    cold_cache.save()
    _warm_cache, warm = run_pipeline_once(boot, cache_path, root=tmp_path, warm=True)

    cold_signature = _unreachable_signature(cold.processing.units)
    assert cold_signature, "cold run found no unreachable statement to compare"
    assert cold_signature == _unreachable_signature(warm.processing.units)


# ---------------------------------------------------------------------------
# The dead_code family join
# ---------------------------------------------------------------------------


def _dead_code_family(payload: object) -> dict[str, Any]:
    return payload_mapping(payload_mapping(payload)["dead_code"])


def _cold_run_rows(root: Path) -> tuple[AnalysisResult, list[Any]]:
    """One cold run over the fixture package, with its unreachable rows."""

    boot = _fixture_boot(root)
    _cache, run = run_pipeline_once(boot, root / "cache.json", root=root, warm=False)
    family = _dead_code_family(run.result.metrics_payload)
    return run.result, list(family["unreachable_statements"])


def test_findings_join_the_dead_code_family_with_the_new_kind(
    tmp_path: Path,
) -> None:
    """One family, one lane, one extra kind — no new closed-list surgery."""

    result, rows = _cold_run_rows(tmp_path)
    family = _dead_code_family(result.metrics_payload)
    assert rows, "the dead_code family carries no unreachable statement"
    assert {str(row["reason"]) for row in rows} <= {
        "after_terminator",
        "unreachable_block",
        "literal_condition",
    }
    for row in rows:
        assert row["confidence"] == "high"
        assert int(row["start_line"]) > 0
    # A dead symbol and an unreachable statement are different defects; the
    # statement lane must never be folded into the symbol total, and it adds no
    # summary counter of its own — the list is the authority.
    assert family["summary"]["total"] == len(list(family["items"]))
    assert "unreachable_statements" not in family["summary"]

    lane_rows = [
        row
        for row in result.observation_bundle.structural.dead_code
        if row.observation_kind == "unreachable_statement"
    ]
    assert len(lane_rows) == len(rows)
    # The discriminator is the whole extension: the lane keeps one payload
    # schema and tells the two row types apart by kind alone.
    assert lane_payload_schema("dead_code") == "3"
    assert {row.entity for row in lane_rows} == {
        f"{row['qualname']}#{row['start_line']}-{row['end_line']}" for row in rows
    }
    assert len({row.entity for row in lane_rows}) == len(lane_rows)


def test_findings_survive_the_report_document_projection(tmp_path: Path) -> None:
    """The wiring guard: findings must survive projection, not just exist.

    ``build_report_body`` does not hand the raw metrics payload to the findings
    builder — it replaces it with the projected document from
    ``report.document.metrics``, which carries a fixed key set per family. A
    list that is not projected is dropped there, so the detector can be
    completely correct and the report still show nothing. Asserting over the
    raw payload cannot see that; this asserts over the projected document.
    """

    result, rows = _cold_run_rows(tmp_path)
    expected = len(rows)
    assert expected, "nothing to project; the guard would be inert"

    body = build_report_body(
        func_groups=result.func_groups,
        block_groups=result.block_groups_report,
        segment_groups=result.segment_groups,
        meta={"scan_root": str(tmp_path)},
        metrics=result.metrics_payload,
    )

    # 1. the projected metrics family still carries the list
    projected = payload_mapping(
        payload_mapping(payload_mapping(body["metrics"])["families"])["dead_code"]
    )
    assert len(payload_sequence(projected["unreachable_statements"])) == expected
    for row in payload_sequence(projected["unreachable_statements"]):
        row_map = payload_mapping(row)
        assert not str(row_map["relative_path"]).startswith("/")
        start_line = row_map["start_line"]
        assert isinstance(start_line, int)
        assert start_line > 0

    # 2. and the findings built from it reach the report
    dead_code_groups = payload_sequence(
        payload_mapping(
            payload_mapping(payload_mapping(body["findings"])["groups"])["dead_code"]
        )["groups"]
    )
    reported = [
        group
        for group in dead_code_groups
        if payload_mapping(group)["kind"] == "unreachable_statement"
    ]
    assert len(reported) == expected
    for group in reported:
        group_map = payload_mapping(group)
        assert group_map["family"] == "dead_code"
        assert group_map["confidence"] == "high"
        assert group_map["severity"] == "warning"
        # ``category`` is the field the renderers dispatch on, and every
        # sibling dead-code group puts the granular KIND there. Naming the
        # family instead dropped these findings off the end of the SARIF
        # closed list, where they were published as "Unused symbol".
        assert group_map["category"] == group_map["kind"]
        assert group_map["category"] != group_map["family"]
        assert payload_mapping(group_map["facts"])["policy_version"] == (
            STATEMENT_REACHABILITY_POLICY_VERSION
        )
        for item in payload_sequence(group_map["items"]):
            assert not str(payload_mapping(item)["relative_path"]).startswith("/")
    # The dead-symbol groups keep their own kind: one family, two kinds.
    assert {payload_mapping(group)["kind"] for group in dead_code_groups} == {
        "unused_symbol",
        "unreachable_statement",
    }


def test_unreachable_region_requires_positioned_statements() -> None:
    """Position-less synthesized statements carry no span: alone they fold to
    no region, and mixed in they do not widen a real region."""

    from codeclone.analysis.statement_reachability import build_unreachable_region

    assert build_unreachable_region("unreachable_block", [ast.Pass()]) is None

    positioned = ast.parse("x = 1").body
    region = build_unreachable_region("unreachable_block", [*positioned, ast.Pass()])
    assert region is not None
    assert region.statement_count == 1
    assert (region.start_line, region.end_line) == (1, 1)


def test_disjoint_dead_regions_stay_separate_findings() -> None:
    findings = _findings_for_source(
        """
def three_tails(flag):
    if flag:
        return 1
        first_tail = 1
    if not flag:
        return 2
        second_tail = 2
    return 3
    third_tail = 3
""",
        "three_tails",
    )
    assert len(findings) == 3
    spans = [(item.start_line, item.end_line) for item in findings]
    assert spans == sorted(spans)
    assert all(item.statement_count == 1 for item in findings)


def test_tail_after_always_raising_finally_is_unreachable() -> None:
    """A ``finally`` that always raises seals the join: the statement after
    the try can never run. A benign ``finally`` keeps it live."""

    raising = _findings_for_source(
        """
def f():
    try:
        x = 1
    finally:
        raise RuntimeError("cleanup")
    tail = 2
""",
        "f",
    )
    assert [(item.start_line, item.end_line) for item in raising] == [(7, 7)]

    benign = _findings_for_source(
        """
def f():
    try:
        x = 1
    finally:
        x = 2
    tail = 2
""",
        "f",
    )
    assert benign == ()


def test_contained_dead_blocks_fold_into_one_region() -> None:
    """A one-line dead loop is one defect: the loop-body block shares the
    header's span and is swallowed into a single region."""

    findings = _findings_for_source(
        """
def f():
    return 1
    while True: inner = 1
""",
        "f",
    )
    assert len(findings) == 1
    (region,) = findings
    assert (region.start_line, region.end_line) == (4, 4)
