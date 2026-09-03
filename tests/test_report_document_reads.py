# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every report-document read must address a key the document carries.

Phase 39 I-19 forbids wire aliases and dual read paths: when a key is replaced
its old spelling is deleted at the producer in the same slice. Producers were
swept; consumers were not. Two survived because
:func:`codeclone.utils.coerce.as_mapping` answers a missing key with an empty
mapping, so a read of a key that no longer exists is indistinguishable from a
read of an empty section -- it silently falls through to whatever default the
caller wrote next.

``_receipt_digest`` was the visible case: it asked ``integrity.digest`` for the
digest algorithm and got ``{}``, so the receipt reported ``"sha256"`` because
that string was also its fallback. Correct output, produced by coincidence.

Pinning those two call sites would pin two places, not the class. This module
pins the class: it reconstructs every report-document key path read anywhere in
``codeclone/`` -- through the dotted accessor, through a ``.get()`` chain, and
through a chain broken across a local alias -- and resolves each one against a
maximally populated document built by the product's own builder. A consumer that
starts reading a key the document does not carry turns this test red wherever it
is written.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from codeclone.surfaces.mcp._review_receipt import derive_baseline_status
from codeclone.surfaces.mcp._session_shared import (
    ExecutionEvent,
    build_served_projection,
    mint_execution_event_id,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest, MCPRunRecord

from ._report_fixtures import build_maximal_report_document

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_ROOT = _REPO_ROOT / "codeclone"

#: Calls that coerce a value on its way through a read chain without changing
#: which key was asked for.
_COERCIONS = frozenset({"as_mapping", "_as_mapping", "dict"})

#: The dotted-path accessor owned by ``codeclone.utils.mapping_paths``.
_ACCESSORS = frozenset({"section", "sections"})

#: Identifiers that name the report document itself. A ``.get()`` chain is a
#: report-document read when it starts at one of these; anything else is some
#: other mapping that happens to share a key name.
_ANCHORS = frozenset({"report_document", "document", "payload"})

#: Identifiers that name the SERVED PROJECTION of a report -- the index the
#: MCP session retains in place of the proof. A read rooted here addresses the
#: same key space, but must resolve against what the projection carries: the
#: projection deliberately withholds ``source_facts``, so a consumer that
#: starts reading a withheld lane off a record turns this test red at the line
#: it is written, rather than at the runtime that would have refused it.
_SERVED_ANCHORS = frozenset({"served_report"})

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Reads of absent keys that this wave did not own. Two-sided on purpose: a new
#: absent read fails as growth, and a fixed one fails as a stale entry, so the
#: register can only shrink and cannot rot.
#:
#: Emptied once ``fix/a2-memory-ingest-paths`` landed: its entry for
#: ``codeclone/memory/project.py`` went stale the moment that fix merged, the
#: stale side of the ratchet said so by name, and the entry was deleted rather
#: than carried. Add an entry only for a read another live branch already owns,
#: and delete it the moment that branch lands.
#:
#: Emptied once ``extract_public_surfaces`` stopped reading
#: ``metrics.api_surface``: that entry was added by the commit that taught this
#: scan to follow a section bound through tuple unpacking, and deleted by the
#: commit that fixed the read it exposed. Both sides of the ratchet did their
#: job -- the growth side while the defect was live, the stale side the moment
#: it was not.
#:
#: The entries below were exposed by the second alias fix in the same series:
#: teaching the scan to bind the names unpacked from one ``sections()`` call
#: made a whole renderer's and a whole audit event's key access visible for the
#: first time. They are read from a document that does not carry them, they are
#: not caused by that fix, and each is owned by its own following commit in
#: this branch. The register is a work queue with a deadline, not a permit: the
#: stale side reds the moment a read is repaired and the entry is not removed.
#:
#: Emptied again once that queue was worked off, in the order it was written:
#: the seven reads of ``codeclone/audit/analysis_completed.py`` first -- the
#: audit event now takes its counts from ``inventory.files``/``inventory.code``
#: and ``findings.summary`` and its health figures from
#: ``metrics.summary.health`` -- and then the three of the Markdown integrity
#: block, which now prints the canonicalization block and the envelope tier
#: whole. Both entries were deleted by the commit that repaired the reads, and
#: the stale side named each one the moment it was not deleted.
_ABSENT_READS_OWNED_ELSEWHERE: dict[str, tuple[str, ...]] = {}


def _callee_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _strip_coercions(node: ast.expr) -> ast.expr:
    while (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and not node.keywords
        and _callee_name(node.func) in _COERCIONS
    ):
        node = node.args[0]
    return node


def _names_the_document(node: ast.expr, anchors: frozenset[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in anchors
    if isinstance(node, ast.Attribute):
        return node.attr in anchors
    return False


def _section_path(
    node: ast.Call,
    aliases: Mapping[str, str],
    handouts: Mapping[str, Mapping[int | None, str]],
    anchors: frozenset[str] = _ANCHORS,
) -> str | None:
    """Reconstruct the path a single ``section(x, "a.b")`` call addresses."""

    if (
        _callee_name(node.func) != "section"
        or len(node.args) != 2
        or not isinstance(node.args[1], ast.Constant)
        or not isinstance(node.args[1].value, str)
    ):
        return None
    path = node.args[1].value
    source = _strip_coercions(node.args[0])
    if _names_the_document(source, anchors):
        return path
    parent = _read_path(source, aliases, handouts, anchors)
    return None if parent is None else f"{parent}.{path}"


def _read_path(
    node: ast.expr,
    aliases: Mapping[str, str],
    handouts: Mapping[str, Mapping[int | None, str]],
    anchors: frozenset[str] = _ANCHORS,
) -> str | None:
    """Reconstruct the dotted key path one read addresses, or None.

    Covers every shape a consumer writes: a ``.get()`` chain rooted at the
    document, a ``section()`` call, either of those reached through a local
    that an earlier statement bound, and either of those reached through a
    module-local helper that hands a section back to its caller. The alias step
    is what makes the scan see
    ``integrity = as_mapping(document.get("integrity"))`` followed by
    ``integrity.get("digest")`` -- the exact shape the withdrawn alias survived
    in, and the shape a ``section()`` result is usually consumed in too. The
    handout step covers the same read spelled across a function boundary.
    """

    node = _strip_coercions(node)
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Call) and _callee_name(node.func) == "section":
        return _section_path(node, aliases, handouts, anchors)
    if isinstance(node, ast.Call):
        handed_out = handouts.get(_callee_name(node.func))
        if handed_out is not None and None in handed_out:
            return handed_out[None]
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return None
    key = node.args[0].value
    receiver = _strip_coercions(node.func.value)
    if _names_the_document(receiver, anchors):
        return key
    parent = _read_path(receiver, aliases, handouts, anchors)
    return None if parent is None else f"{parent}.{key}"


def _scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Yield one scope's nodes in source order, without entering nested scopes."""

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*_SCOPES, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from _scope_nodes(child)


def _section_handouts(
    tree: ast.AST,
    anchors: frozenset[str] = _ANCHORS,
) -> dict[str, dict[int | None, str]]:
    """Which section each module-local function hands back to its callers.

    Keyed by function name, then by tuple index -- or by ``None`` when the
    function returns the section itself rather than a tuple carrying it. A
    consumer that reaches a section through such a helper is reading that
    section, and resolving the read at the call site is what makes the spelling
    irrelevant to the class pin.

    Deliberately one level deep and module-local: it resolves the shape this
    tree actually uses, and a helper built on another helper stays unresolved
    rather than guessed. Under-reporting is the safe direction here -- the pin
    fails on reads it can see, so a missed chain costs coverage, while an
    invented chain would cost trust.
    """

    handouts: dict[str, dict[int | None, str]] = {}
    for scope in (node for node in ast.walk(tree) if isinstance(node, _SCOPES)):
        aliases: dict[str, str] = {}
        handed_out: dict[int | None, str] = {}
        for node in _scope_nodes(scope):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                path = _read_path(node.value, aliases, {}, anchors)
                if path is None:
                    aliases.pop(node.targets[0].id, None)
                else:
                    aliases[node.targets[0].id] = path
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            returned = _strip_coercions(node.value)
            elements: tuple[tuple[int | None, ast.expr], ...] = (
                tuple(enumerate(returned.elts))
                if isinstance(returned, ast.Tuple)
                else ((None, returned),)
            )
            for index, element in elements:
                path = _read_path(element, aliases, {}, anchors)
                if path is not None:
                    handed_out[index] = path
        if handed_out:
            handouts[scope.name] = handed_out
    return handouts


def _accessor_paths(node: ast.Call) -> dict[int | None, str]:
    """Which section each result of one ``sections(doc, *paths)`` call carries.

    The accessor returns one section per path, in argument order, so the
    positions are the contract and nothing else needs resolving. Keyed the same
    way as the handout table above so both tuple sources bind identically.
    """

    if _callee_name(node.func) not in _ACCESSORS or len(node.args) < 2:
        return {}
    return {
        index: argument.value
        for index, argument in enumerate(node.args[1:])
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
    }


def _rebind(
    aliases: dict[str, str],
    target: ast.expr,
    path: str | None,
) -> None:
    """Bind one name to a path, or drop whatever it was bound to before.

    Dropping is the half that was missing: a name rebound by a statement the
    scan cannot resolve kept its previous binding, so the scan reported a read
    at a line that performs a different one.
    """

    if not isinstance(target, ast.Name):
        return
    if path is None:
        aliases.pop(target.id, None)
    else:
        aliases[target.id] = path


def _bind_assignment(
    aliases: dict[str, str],
    *,
    target: ast.expr,
    value: ast.expr,
    handouts: Mapping[str, Mapping[int | None, str]],
    anchors: frozenset[str] = _ANCHORS,
) -> None:
    """Update the alias table for one assignment, whatever its target shape.

    A tuple target takes its paths from the callee's handout table by index;
    every other target resolves the right-hand side directly. Both shapes go
    through :func:`_rebind`, so an unresolvable right-hand side drops the
    binding either way instead of leaving a stale one behind.
    """

    if isinstance(target, ast.Tuple):
        source = _strip_coercions(value)
        by_index = (
            _accessor_paths(source) or handouts.get(_callee_name(source.func), {})
            if isinstance(source, ast.Call)
            else {}
        )
        for index, element in enumerate(target.elts):
            _rebind(aliases, element, by_index.get(index))
        return
    _rebind(aliases, target, _read_path(value, aliases, handouts, anchors))


def report_document_reads(
    source: str,
    anchors: frozenset[str] = _ANCHORS,
) -> list[tuple[int, str]]:
    """Every report-document key path one module reads, with its line.

    ``anchors`` names which identifiers the scan treats as the document. The
    default is the report itself; :data:`_SERVED_ANCHORS` scans the reads that
    address a served projection instead, which is the same key space resolved
    against a different carrier.
    """

    tree = ast.parse(source)
    handouts = _section_handouts(tree, anchors)
    scopes: list[ast.AST] = [tree]
    scopes.extend(node for node in ast.walk(tree) if isinstance(node, _SCOPES))
    reads: list[tuple[int, str]] = []
    for scope in scopes:
        aliases: dict[str, str] = {}
        for node in _scope_nodes(scope):
            if isinstance(node, ast.Call):
                if _callee_name(node.func) in _COERCIONS:
                    # A wrapper, not a read: the call it wraps is visited too.
                    continue
                if _callee_name(node.func) in _ACCESSORS and node.args:
                    reads.extend(
                        (argument.lineno, argument.value)
                        for argument in node.args[1:]
                        if isinstance(argument, ast.Constant)
                        and isinstance(argument.value, str)
                    )
                    continue
                path = _read_path(node, aliases, handouts, anchors)
                if path is not None:
                    reads.append((node.lineno, path))
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                _bind_assignment(
                    aliases,
                    target=node.targets[0],
                    value=node.value,
                    handouts=handouts,
                    anchors=anchors,
                )
    return reads


def _document_carries(document: object, path: str) -> bool:
    current = document
    for key in path.split("."):
        if not isinstance(current, Mapping) or key not in current:
            return False
        current = current[key]
    return True


def _uncarried_reads(
    source: str,
    carrier: Mapping[str, object],
    anchors: frozenset[str],
    top_level: frozenset[str],
) -> set[str]:
    """Report-document reads in ``source`` that ``carrier`` does not carry."""

    return {
        path
        for _line, path in report_document_reads(source, anchors)
        if path.split(".")[0] in top_level and not _document_carries(carrier, path)
    }


def _absent_reads() -> dict[str, tuple[str, ...]]:
    """Absent reads of both carriers, resolved against the right one each.

    The key space is one -- a served projection indexes a report -- so whether
    a path addresses the report is decided by the report's own top level in
    both scans. What differs is who has to carry it: a read rooted at the
    record resolves against the projection, which withholds ``source_facts``,
    so reaching for a withheld lane off a record is reported here as a read of
    a key its carrier does not have.
    """

    document = build_maximal_report_document()
    carriers = (
        (document, _ANCHORS),
        (build_served_projection(document), _SERVED_ANCHORS),
    )
    top_level = frozenset(document)
    absent: dict[str, set[str]] = {}
    for module in sorted(_PACKAGE_ROOT.rglob("*.py")):
        relative = module.relative_to(_REPO_ROOT).as_posix()
        source = module.read_text("utf-8")
        paths = {
            path
            for carrier, anchors in carriers
            for path in _uncarried_reads(source, carrier, anchors, top_level)
        }
        if paths:
            absent[relative] = paths
    return {module: tuple(sorted(paths)) for module, paths in sorted(absent.items())}


def test_report_document_reads_address_keys_the_document_carries() -> None:
    """No consumer reads a report-document key its carrier does not carry."""

    absent = _absent_reads()
    unexpected = {
        module: tuple(
            sorted(set(paths) - set(_ABSENT_READS_OWNED_ELSEWHERE.get(module, ())))
        )
        for module, paths in absent.items()
        if set(paths) - set(_ABSENT_READS_OWNED_ELSEWHERE.get(module, ()))
    }
    resolved = {
        module: tuple(sorted(set(paths) - set(absent.get(module, ()))))
        for module, paths in _ABSENT_READS_OWNED_ELSEWHERE.items()
        if set(paths) - set(absent.get(module, ()))
    }
    assert unexpected == {}, (
        "these consumers read report-document keys the document does not carry; "
        "read the key the producer emits instead of growing the register: "
        f"{unexpected}"
    )
    assert resolved == {}, (
        "these registered absent reads are gone; shrink "
        f"_ABSENT_READS_OWNED_ELSEWHERE: {resolved}"
    )


def test_report_document_read_scanner_reconstructs_every_chain_shape() -> None:
    """The scanner sees all three shapes a consumer can use to read a key.

    Without this the class pin could quietly go blind: a scanner that
    reconstructs nothing reports no absent reads and stays green forever. Each
    shape below is one a real consumer in this tree uses.

    Scanned under both anchor families at once: the served record is where the
    aliased shape is written in this tree now, and a scan that resolved only
    the report anchors would have gone blind on it the moment the run store
    stopped holding the proof.
    """

    source = (
        "def direct(report_document):\n"
        "    return as_mapping(report_document.get('integrity')).get('ghost')\n"
        "def aliased(record):\n"
        "    integrity = as_mapping(record.served_report.get('integrity'))\n"
        "    return as_mapping(integrity.get('ghost'))\n"
        "def dotted(document):\n"
        "    return section(document, 'integrity.ghost')\n"
        "def dotted_then_get(document):\n"
        "    integrity = section(document, 'integrity')\n"
        "    return integrity.get('ghost')\n"
        "def unrelated(row):\n"
        "    return as_mapping(row.get('integrity')).get('ghost')\n"
    )

    both = _ANCHORS | _SERVED_ANCHORS
    assert sorted(path for _line, path in report_document_reads(source, both)) == [
        "integrity",
        "integrity",
        "integrity",
        "integrity.ghost",
        "integrity.ghost",
        "integrity.ghost",
        "integrity.ghost",
    ]


def test_a_withheld_lane_read_off_a_served_record_is_reported() -> None:
    """The served anchor is scanned, and the projection decides what is carried.

    Both halves are required and each fails on its own. A scan that did not
    know ``served_report`` names a document would reconstruct nothing here and
    report no read at all; a scan that resolved this read against the whole
    proof would find ``source_facts`` carried and report nothing either. The
    read below is the one this projection exists to make impossible, so it has
    to arrive as an absent read of the carrier that does not have it.
    """

    source = (
        "def consumer(record):\n"
        "    lanes = as_mapping(record.served_report.get('source_facts'))\n"
        "    return lanes.get('semantic')\n"
    )
    served_reads = sorted(
        path for _line, path in report_document_reads(source, _SERVED_ANCHORS)
    )
    assert served_reads == ["source_facts", "source_facts.semantic"]
    served = build_served_projection(build_maximal_report_document())
    assert not any(_document_carries(served, path) for path in served_reads)
    assert all(
        _document_carries(build_maximal_report_document(), path)
        for path in served_reads
    )


def test_report_document_read_scanner_follows_a_helper_return_through_unpacking() -> (
    None
):
    """A helper that hands the document out is still a read at its callers.

    The withdrawn-key class does not care which statement spells the read.
    ``codeclone/memory/ingest/extractors.py`` binds the ``metrics`` section
    through ``batch, now, metrics = _new_metrics_batch(report_document)`` and
    then asks it for a family by name; that is the same defect as a direct
    ``document.get("metrics").get(...)`` chain, and the scan saw none of it
    because an alias was recorded only for a single ``ast.Name`` target.

    Both halves are required. Seeing the tuple target without following the
    helper's return binds nothing, and following the return without unpacking
    the tuple binds the wrong name.

    The two helpers are counted differently, and the difference is the point.
    ``_single`` returns the section, so its call site *is* a read of that
    section and ``findings`` is counted twice -- once inside the helper, once
    at the caller. ``_split`` returns a tuple that carries the section, so its
    call site reads a tuple and not a section; ``metrics`` is counted once,
    inside the helper, and the caller's read is the ``metrics.ghost`` the
    unpacked name goes on to perform.
    """

    source = (
        "def _split(report_document):\n"
        "    return (Batch(), stamp(), as_mapping(report_document.get('metrics')))\n"
        "def _single(document):\n"
        "    return as_mapping(document.get('findings'))\n"
        "def caller(report_document):\n"
        "    batch, now, metrics = _split(report_document)\n"
        "    findings = _single(report_document)\n"
        "    return metrics.get('ghost'), findings.get('groups')\n"
    )

    assert sorted(path for _line, path in report_document_reads(source)) == [
        "findings",
        "findings",
        "findings.groups",
        "metrics",
        "metrics.ghost",
    ]


def test_report_document_read_scanner_binds_a_sections_tuple_by_position() -> None:
    """``sections()`` hands back one section per path, in argument order.

    Both report renderers open with a dozen-name unpacking of a single
    ``sections(payload, ...)`` call and then read sub-keys off those names. The
    scan saw the paths passed to the accessor and none of the reads performed
    through the names it bound, so a whole renderer's key access was invisible
    -- which is how two absent reads survived in the integrity block of the
    Markdown and text reports.

    Position is the entire contract: the second name carries the second path. A
    binding off by one would resolve every read against the wrong section and
    report absent keys that are in fact present.
    """

    source = (
        "def render(payload):\n"
        "    meta, canonicalization = sections(\n"
        "        payload, 'meta', 'integrity.canonicalization'\n"
        "    )\n"
        "    return meta.get('project_name'), canonicalization.get('ghost')\n"
    )

    assert sorted(path for _line, path in report_document_reads(source)) == [
        "integrity.canonicalization",
        "integrity.canonicalization.ghost",
        "meta",
        "meta.project_name",
    ]


def test_report_document_read_scanner_drops_an_alias_rebound_by_unpacking() -> None:
    """A name that stops naming a section must stop resolving to it.

    Unpacking was not merely unseen, it was ignored: a name already bound to a
    section kept that binding after a tuple assignment rebound it to something
    else, so the scan could report a path the code never reads. A scanner that
    invents reads is worse than one that misses them -- it sends the reader to
    a line that is not the defect.
    """

    source = (
        "def caller(document):\n"
        "    metrics = as_mapping(document.get('metrics'))\n"
        "    metrics, other = unrelated()\n"
        "    return metrics.get('ghost')\n"
    )

    assert sorted(path for _line, path in report_document_reads(source)) == ["metrics"]


def _run_record(document: Mapping[str, object]) -> MCPRunRecord:
    root = Path("/repo")
    return MCPRunRecord(
        run_id="i19receipt000001",
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        served_report=build_served_projection(dict(document)),
        summary={"run_id": "i19receipt000001"},
        changed_paths=(),
        changed_projection=None,
        func_clones_count=0,
        block_clones_count=0,
        reachable_qualnames=frozenset(),
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
        execution=ExecutionEvent(
            execution_event_id=mint_execution_event_id(),
            root=root,
            semantic_report_id="i19receipt000001",
        ),
    )


def test_receipt_digest_names_the_algorithm_the_document_declares() -> None:
    """The receipt's algorithm label tracks the document, not a constant.

    ``_receipt_digest`` read ``integrity.digest.algorithm``, a key withdrawn
    when the digest hierarchy replaced the single digest with five named tiers.
    The read yielded nothing and the ``"sha256"`` fallback happened to be the
    truth, so the label was right by coincidence. Changing the algorithm the
    document declares must change the label; a receipt that cannot report the
    algorithm it actually used is not provenance.

    Value and label must name the *same* tier. The receipt attests to a
    verdict, so its value is the run identity -- the ``evaluation`` tier -- and
    reading the algorithm off ``comparison`` would label one tier's digest with
    another tier's algorithm and be right only while both say ``sha256``.
    """

    service = CodeCloneMCPService(history_limit=2)
    document = build_maximal_report_document()
    record = _run_record(document)
    evaluation = document["integrity"]["digests"]["evaluation"]  # type: ignore[index]
    comparison = document["integrity"]["digests"]["comparison"]  # type: ignore[index]
    assert isinstance(evaluation, dict)
    assert isinstance(comparison, dict)
    assert evaluation["value"] != comparison["value"]

    digest = service._receipt_digest(record)

    assert digest == f"{evaluation['algorithm']}:{evaluation['value']}"

    other = deepcopy(document)
    other["integrity"]["digests"]["evaluation"]["algorithm"] = "blake2b"  # type: ignore[index]
    other_digest = service._receipt_digest(
        replace(record, served_report=build_served_projection(other))
    )

    assert other_digest.split(":", 1)[0] == "blake2b"


def test_receipt_generated_at_reads_the_runtime_timestamp() -> None:
    """The report carries its generation time in one place: ``meta.runtime``.

    ``_receipt_generated_at`` tried ``meta.report_generated_at_utc`` first --
    the location the v3 document stopped using -- and only then the runtime
    block. Deleting the runtime value must leave the receipt with nothing to
    report, which proves the runtime block is what it reads.
    """

    service = CodeCloneMCPService(history_limit=2)
    document = build_maximal_report_document()
    runtime = document["meta"]["runtime"]  # type: ignore[index]
    assert isinstance(runtime, dict)
    runtime["report_generated_at_utc"] = "2026-08-11T00:00:00Z"

    assert service._receipt_generated_at(_run_record(document)) == (
        "2026-08-11T00:00:00Z"
    )

    stripped = deepcopy(document)
    stripped["meta"]["runtime"]["report_generated_at_utc"] = ""  # type: ignore[index]

    assert service._receipt_generated_at(_run_record(stripped)) == ""

    # The withdrawn location must not be consulted at all. Asserting only the
    # runtime value stays green with the legacy lookup restored in front of it,
    # because falling through it reaches the same answer.
    legacy_only = deepcopy(stripped)
    legacy_only["meta"]["report_generated_at_utc"] = "2026-legacy"  # type: ignore[index]

    assert service._receipt_generated_at(_run_record(legacy_only)) == ""


def test_baseline_status_is_decided_by_the_status_the_document_carries() -> None:
    """``trusted_for_diff`` is a CLI-side field the report never projects.

    ``derive_baseline_status`` accepted it as an alternative route to
    ``"trusted"``, so the branch could not fire in any configuration. The
    status field is the only input, and both of its outcomes must be reachable.
    """

    document = build_maximal_report_document()
    baseline_meta = document["meta"]["baseline"]  # type: ignore[index]
    assert isinstance(baseline_meta, dict)
    assert "trusted_for_diff" not in baseline_meta

    baseline_meta.update({"loaded": True, "status": "ok"})
    assert derive_baseline_status(document) == "trusted"

    baseline_meta["status"] = "fingerprint_mismatch"
    assert derive_baseline_status(document) == "untrusted"

    # Injected into the block the report never fills, the withdrawn field must
    # not flip the verdict; asserting only the two status outcomes stays green
    # with the disjunct restored, because no real document can trigger it.
    baseline_meta["trusted_for_diff"] = True
    assert derive_baseline_status(document) == "untrusted"
    del baseline_meta["trusted_for_diff"]

    baseline_meta["loaded"] = False
    assert derive_baseline_status(document) == "not_loaded"


def test_maximal_report_document_populates_the_conditional_sections() -> None:
    """The document the pin resolves against is maximal, not merely valid.

    A default run omits these sections, and resolving against a default run
    would report every conditional read as a withdrawn key.
    """

    document = build_maximal_report_document()
    for path in (
        "metrics.families.coverage_join.summary",
        "metrics.families.semantic_authority.summary",
        "findings.groups.clones.suppressed",
        "integrity.digests.evaluation.algorithm",
    ):
        assert _document_carries(document, path), path
