# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A ``dead-code`` suppression may not outlive the reason it was written.

One wave writes a symbol before its consumer exists and marks it
``# codeclone: ignore[dead-code]``.  That is legitimate at the moment it is
written.  A later wave adds the consumer -- and nothing removes the directive,
because a suppression that suppresses nothing breaks nothing.  The defect is
silent, self-sustaining, and invisible to every test the repository owns.

The predicate needs no human review:

    a ``dead-code`` suppression whose symbol the detector would not report
    anyway has expired.

Two owners answer it, and they are deliberately not the same one.

*The inventory* -- which declarations carry the directive -- is read from the
source text of every file the run analysed, through the published suppression
parser.  *The verdict* -- whether the symbol would be reported without the
directive -- is read from the analysis run: ``find_suppressed_unused`` strips
the suppression, re-classifies the symbol against the project's whole
reference universe, and only the symbols that stay dead reach
``dead_code.suppressed_items``.  The detector already owns the question "does
this symbol have a consumer", so this module asks it instead of answering it a
second time.

Taking both sides from the run would make the guard self-consistent: a run
that lost the directives on the way in would agree with itself and stay green.
``test_every_honoured_suppression_is_visible_to_the_source_scan`` is where the
two owners are made to meet.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from codeclone.analysis.suppressions import (
    DEAD_CODE_RULE_ID,
    DeclarationKind,
    DeclarationTarget,
    bind_suppressions_to_declarations,
    extract_suppression_directives,
)
from codeclone.contracts import DEFAULT_MIN_LOC, DEFAULT_MIN_STMT
from tests._pipeline_fixtures import analysis_boot, run_pipeline_once

if TYPE_CHECKING:
    from collections.abc import Sequence

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

#: ``(repository-relative path, declaration qualname)`` -- line-independent on
#: purpose, so an unrelated edit above a suppression cannot move a key.
SuppressionKey = tuple[str, str]

#: Suppressions already measured as expired whose file this branch may not
#: touch.  This register is not an exemption list that can be grown quietly:
#: ``test_no_pending_stale_suppression_has_settled`` fails the moment an entry
#: stops being expired -- because the owning wave landed, or because the
#: directive is gone -- and the only way to make that failure go away is to
#: delete the entry.  A key that names a file nobody is editing therefore
#: cannot survive its owner.
_PENDING_STALE_SUPPRESSIONS: Final[Mapping[SuppressionKey, str]] = {}

#: The OPEN + DEAD population this branch froze, measured on this tree by the
#: run's own detector -- ``dead_code.items``, and only those.  The 87
#: ``UNRESOLVED_EXTERNAL`` symbols are a different lane answering a different
#: question and are deliberately not mixed in.
#:
#: A **set**, never a count.  ``len(current) == 36`` stays green while a wave
#: retires one identity and introduces another, which is exactly the trade an
#: inventory freeze exists to forbid.  Shrinking needs no edit here: every
#: subset of this register passes, so ``36 -> 0`` is the direction the guard
#: is built to allow, and only a symbol that is NOT in it can fail the run.
FROZEN_OPEN_DEAD: Final[frozenset[str]] = frozenset(
    {
        "codeclone.analysis.normalizer:_is_proven_commutative_operand",
        "codeclone.analytics.report.interpret:_cluster_size_histogram",
        "codeclone.cache._validators:_is_block_dict",
        "codeclone.cache._validators:_is_class_metrics_dict",
        "codeclone.cache._validators:_is_dead_candidate_dict",
        "codeclone.cache._validators:_is_file_stat_dict",
        "codeclone.cache._validators:_is_function_relationship_facts_dict",
        "codeclone.cache._validators:_is_git_blob_identity",
        "codeclone.cache._validators:_is_module_api_surface_dict",
        "codeclone.cache._validators:_is_module_dep_dict",
        "codeclone.cache._validators:_is_module_docstring_coverage_dict",
        "codeclone.cache._validators:_is_module_typing_coverage_dict",
        "codeclone.cache._validators:_is_runtime_reachability_fact_dict",
        "codeclone.cache._validators:_is_security_surface_dict",
        "codeclone.cache._validators:_is_segment_dict",
        "codeclone.cache._validators:_is_source_content_digest",
        "codeclone.cache._validators:_is_source_stats_dict",
        "codeclone.cache._validators:_is_unit_dict",
        "codeclone.cache.entries:_block_dict_from_model",
        "codeclone.cache.entries:_segment_dict_from_model",
        "codeclone.cache.entries:_unit_dict_from_model",
        "codeclone.findings.structural.detectors:_group_item_sort_key",
        "codeclone.memory.semantic.lancedb_backend:LanceDbSemanticIndex._schema_matches",
        "codeclone.surfaces.cli.console:_make_console",
        "codeclone.surfaces.mcp._session_shared:_load_report_document_payload",
        "codeclone.surfaces.mcp._workspace_intent_lifecycle:is_orphaned",
        "codeclone.surfaces.mcp._workspace_intent_paths:read_payload",
        "codeclone.surfaces.mcp._workspace_intent_staleness:is_stale",
        "codeclone.surfaces.mcp._workspace_intent_store:lazy_close_eligible_records",
        "codeclone.surfaces.mcp._workspace_intent_store:lazy_close_eligible_records_unlocked",
        "codeclone.surfaces.mcp._workspace_intents:_is_pid_alive",
        "codeclone.surfaces.mcp._workspace_intents:is_orphaned",
        "codeclone.surfaces.mcp._workspace_intents:is_stale",
        "codeclone.surfaces.mcp._workspace_intents:list_workspace_intent_records_raw",
        "codeclone.surfaces.mcp._workspace_intents:signed_payload",
        "codeclone.surfaces.mcp._workspace_intents:validate_workspace_record",
    }
)


def stale_dead_code_suppressions(
    *,
    declared: Iterable[SuppressionKey],
    still_suppressing: Iterable[SuppressionKey],
) -> frozenset[SuppressionKey]:
    """The declared suppressions the detector no longer needs.

    ``still_suppressing`` is the detector's own answer: the suppressed symbols
    it *would* report if the directive were removed.  Everything declared and
    absent from it is a directive that suppresses nothing.
    """

    return frozenset(declared) - frozenset(still_suppressing)


def _declaration_targets(
    tree: ast.Module,
    *,
    relative_path: str,
) -> list[DeclarationTarget]:
    """Every function, method and class declaration of one module."""

    targets: list[DeclarationTarget] = []
    pending: list[tuple[ast.AST, str, bool]] = [(tree, "", False)]
    while pending:
        node, prefix, in_function = pending.pop()
        for child in ast.iter_child_nodes(node):
            if not isinstance(
                child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            ):
                pending.append((child, prefix, in_function))
                continue
            # The run spells a function-local declaration the way CPython's
            # ``__qualname__`` does (liveness policy v5), and this witness
            # must spell it the same way or the two could never meet on one.
            boundary = ".<locals>." if in_function else "."
            qualname = f"{prefix}{boundary}{child.name}" if prefix else child.name
            kind: DeclarationKind
            if isinstance(child, ast.ClassDef):
                kind = "class"
            else:
                kind = "method" if isinstance(node, ast.ClassDef) else "function"
            targets.append(
                DeclarationTarget(
                    filepath=relative_path,
                    qualname=qualname,
                    start_line=child.lineno,
                    end_line=child.end_lineno or child.lineno,
                    kind=kind,
                    # The signature's last line, so an inline directive written
                    # after a multi-line signature still binds.
                    declaration_end_line=(
                        max(child.lineno, child.body[0].lineno - 1)
                        if child.body
                        else child.lineno
                    ),
                )
            )
            pending.append((child, qualname, not isinstance(child, ast.ClassDef)))
    return targets


def _declared_dead_code_suppressions(
    *,
    root: Path,
    analysed_paths: Iterable[str],
) -> dict[SuppressionKey, int]:
    """Read the repository's ``dead-code`` directives out of its source text.

    Deliberately independent of the run's own suppression binding: the run is
    the other witness, and a guard whose two witnesses share a producer proves
    nothing about that producer.
    """

    declared: dict[SuppressionKey, int] = {}
    for relative_path in sorted(analysed_paths):
        source = (root / relative_path).read_text("utf-8")
        directives = extract_suppression_directives(source)
        if not any(DEAD_CODE_RULE_ID in item.rules for item in directives):
            continue
        bindings = bind_suppressions_to_declarations(
            directives=directives,
            declarations=_declaration_targets(
                ast.parse(source),
                relative_path=relative_path,
            ),
        )
        for binding in bindings:
            if DEAD_CODE_RULE_ID in binding.rules:
                declared[relative_path, binding.qualname] = binding.start_line
    return declared


def _honoured_dead_code_suppressions(
    suppressed_items: Sequence[object],
    *,
    root: Path,
) -> dict[SuppressionKey, str]:
    """The run's own answer: suppressions that still hold a dead symbol down."""

    honoured: dict[SuppressionKey, str] = {}
    for item in suppressed_items:
        assert isinstance(item, Mapping)
        filepath = Path(str(item["filepath"]))
        relative_path = filepath.relative_to(root).as_posix()
        qualname = str(item["qualname"]).rpartition(":")[2]
        honoured[relative_path, qualname] = str(item["reason"])
    return honoured


@pytest.fixture(scope="module")
def repository_dead_code(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[SuppressionKey, int], dict[SuppressionKey, str], list[object]]:
    """One cold analysis of this repository, shared by every guard below."""

    boot = analysis_boot(
        _REPO_ROOT,
        min_loc=DEFAULT_MIN_LOC,
        min_stmt=DEFAULT_MIN_STMT,
        skip_metrics=False,
    )
    _cache, run = run_pipeline_once(
        boot,
        tmp_path_factory.mktemp("suppression_ratchet") / "cache.json",
        root=_REPO_ROOT,
        warm=False,
    )
    payload = run.result.metrics_payload
    assert payload is not None
    dead_code = payload["dead_code"]
    assert isinstance(dead_code, Mapping)
    suppressed_items = dead_code["suppressed_items"]
    assert isinstance(suppressed_items, list)
    dead_items = dead_code["items"]
    assert isinstance(dead_items, list)
    declared = _declared_dead_code_suppressions(
        root=_REPO_ROOT,
        analysed_paths=run.discovery.module_registry.entries_by_path,
    )
    honoured = _honoured_dead_code_suppressions(suppressed_items, root=_REPO_ROOT)
    return declared, honoured, dead_items


def test_stale_predicate_reports_a_suppression_the_detector_no_longer_needs() -> None:
    key: SuppressionKey = ("pkg/module.py", "Thing.method")
    assert stale_dead_code_suppressions(
        declared=[key],
        still_suppressing=[],
    ) == frozenset({key})


def test_stale_predicate_spares_a_suppression_the_detector_still_needs() -> None:
    key: SuppressionKey = ("pkg/module.py", "Thing.method")
    assert (
        stale_dead_code_suppressions(
            declared=[key],
            still_suppressing=[key],
        )
        == frozenset()
    )


def test_no_dead_code_suppression_outlives_its_cause(
    repository_dead_code: tuple[
        dict[SuppressionKey, int], dict[SuppressionKey, str], list[object]
    ],
) -> None:
    declared, honoured, _dead_items = repository_dead_code
    stale = stale_dead_code_suppressions(
        declared=declared,
        still_suppressing=honoured,
    )
    expired = sorted(stale - set(_PENDING_STALE_SUPPRESSIONS))
    assert not expired, (
        "dead-code suppression outlived its cause -- the symbol has a "
        "consumer, so the directive now suppresses nothing and must be "
        "deleted:\n"
        + "\n".join(
            f"  {path}:{declared[path, qualname]} {qualname}"
            for path, qualname in expired
        )
    )


def test_no_pending_stale_suppression_has_settled(
    repository_dead_code: tuple[
        dict[SuppressionKey, int], dict[SuppressionKey, str], list[object]
    ],
) -> None:
    declared, honoured, _dead_items = repository_dead_code
    stale = stale_dead_code_suppressions(
        declared=declared,
        still_suppressing=honoured,
    )
    settled = sorted(set(_PENDING_STALE_SUPPRESSIONS) - stale)
    assert not settled, (
        "_PENDING_STALE_SUPPRESSIONS names a suppression that is no longer "
        "expired -- its owning wave landed, or the directive is gone. Delete "
        "the entry:\n" + "\n".join(f"  {path} {qualname}" for path, qualname in settled)
    )


def test_every_honoured_suppression_is_visible_to_the_source_scan(
    repository_dead_code: tuple[
        dict[SuppressionKey, int], dict[SuppressionKey, str], list[object]
    ],
) -> None:
    """The two witnesses must see the same directives.

    Without this the ratchet above could go inert unnoticed: a source scan
    that found nothing agrees with every run, and an empty inventory has no
    stale entries to report.
    """

    declared, honoured, _dead_items = repository_dead_code
    invisible = sorted(set(honoured) - set(declared))
    assert not invisible, (
        "the run honours a dead-code suppression the source scan cannot see; "
        "the ratchet's inventory is not measuring the same tree:\n"
        + "\n".join(f"  {path} {qualname}" for path, qualname in invisible)
    )


def test_no_dead_symbol_is_reported_outside_the_frozen_inventory(
    repository_dead_code: tuple[
        dict[SuppressionKey, int], dict[SuppressionKey, str], list[object]
    ],
) -> None:
    """The other half of the pair the ratchet above opens.

    Retiring an expired suppression is safe because the detector no longer
    reports the symbol.  Retiring a suppression that is still load-bearing is
    not, and nothing else in this suite says so -- ``fail_dead_code`` lives in
    the gate, which the test run never reaches.

    The symbol comes back into ``dead_code.items`` under an identity that
    ``FROZEN_OPEN_DEAD`` does not hold, and that -- not a count -- is what
    fails here.  A symbol newly stripped of its last consumer fails the same
    way, for the same reason.
    """

    _declared, _honoured, dead_items = repository_dead_code
    located = {
        str(item["qualname"]): f"{item['filepath']}:{item['start_line']}"
        for item in dead_items
        if isinstance(item, Mapping)
    }
    unexpected = sorted(set(located) - FROZEN_OPEN_DEAD)
    assert not unexpected, (
        "the repository reports a dead symbol the frozen inventory does not "
        "hold; either the symbol has lost its last consumer, or a "
        "still-necessary suppression was removed. This register shrinks and "
        "never grows -- do not add the identity to it:\n"
        + "\n".join(f"  {located[qualname]} {qualname}" for qualname in unexpected)
    )
