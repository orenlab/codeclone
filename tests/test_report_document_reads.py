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

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Reads of absent keys that this wave did not own. Two-sided on purpose: a new
#: absent read fails as growth, and a fixed one fails as a stale entry, so the
#: register can only shrink and cannot rot.
#:
#: Empty since ``fix/a2-memory-ingest-paths`` landed: its entry for
#: ``codeclone/memory/project.py`` went stale the moment that fix merged, the
#: stale side of the ratchet said so by name, and the entry was deleted rather
#: than carried. Add an entry only for a read another live branch already owns,
#: and delete it the moment that branch lands.
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


def _names_the_document(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _ANCHORS
    if isinstance(node, ast.Attribute):
        return node.attr in _ANCHORS
    return False


def _section_path(node: ast.Call, aliases: Mapping[str, str]) -> str | None:
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
    if _names_the_document(source):
        return path
    parent = _read_path(source, aliases)
    return None if parent is None else f"{parent}.{path}"


def _read_path(node: ast.expr, aliases: Mapping[str, str]) -> str | None:
    """Reconstruct the dotted key path one read addresses, or None.

    Covers all three shapes a consumer writes: a ``.get()`` chain rooted at the
    document, a ``section()`` call, and either of those reached through a local
    that an earlier statement bound. The alias step is what makes the scan see
    ``integrity = as_mapping(document.get("integrity"))`` followed by
    ``integrity.get("digest")`` -- the exact shape the withdrawn alias survived
    in, and the shape a ``section()`` result is usually consumed in too.
    """

    node = _strip_coercions(node)
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Call) and _callee_name(node.func) == "section":
        return _section_path(node, aliases)
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
    if _names_the_document(receiver):
        return key
    parent = _read_path(receiver, aliases)
    return None if parent is None else f"{parent}.{key}"


def _scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    """Yield one scope's nodes in source order, without entering nested scopes."""

    for child in ast.iter_child_nodes(node):
        if isinstance(child, (*_SCOPES, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from _scope_nodes(child)


def report_document_reads(source: str) -> list[tuple[int, str]]:
    """Every report-document key path one module reads, with its line."""

    tree = ast.parse(source)
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
                path = _read_path(node, aliases)
                if path is not None:
                    reads.append((node.lineno, path))
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                target = node.targets[0].id
                path = _read_path(node.value, aliases)
                if path is None:
                    aliases.pop(target, None)
                else:
                    aliases[target] = path
    return reads


def _document_carries(document: object, path: str) -> bool:
    current = document
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return False
        current = current[key]
    return True


def _absent_reads() -> dict[str, tuple[str, ...]]:
    document = build_maximal_report_document()
    top_level = frozenset(document)
    absent: dict[str, set[str]] = {}
    for module in sorted(_PACKAGE_ROOT.rglob("*.py")):
        relative = module.relative_to(_REPO_ROOT).as_posix()
        for _line, path in report_document_reads(module.read_text("utf-8")):
            addresses_the_report = path.split(".")[0] in top_level
            if not addresses_the_report or _document_carries(document, path):
                continue
            absent.setdefault(relative, set()).add(path)
    return {module: tuple(sorted(paths)) for module, paths in sorted(absent.items())}


def test_report_document_reads_address_keys_the_document_carries() -> None:
    """No consumer reads a report-document key the document does not carry."""

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
    """

    source = (
        "def direct(report_document):\n"
        "    return as_mapping(report_document.get('integrity')).get('ghost')\n"
        "def aliased(record):\n"
        "    integrity = as_mapping(record.report_document.get('integrity'))\n"
        "    return as_mapping(integrity.get('ghost'))\n"
        "def dotted(document):\n"
        "    return section(document, 'integrity.ghost')\n"
        "def dotted_then_get(document):\n"
        "    integrity = section(document, 'integrity')\n"
        "    return integrity.get('ghost')\n"
        "def unrelated(row):\n"
        "    return as_mapping(row.get('integrity')).get('ghost')\n"
    )

    assert sorted(path for _line, path in report_document_reads(source)) == [
        "integrity",
        "integrity",
        "integrity",
        "integrity.ghost",
        "integrity.ghost",
        "integrity.ghost",
        "integrity.ghost",
    ]


def _run_record(document: Mapping[str, object]) -> MCPRunRecord:
    root = Path("/repo")
    return MCPRunRecord(
        run_id="i19receipt000001",
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        report_document=dict(document),
        summary={"run_id": "i19receipt000001"},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        coverage_join=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )


def test_receipt_digest_names_the_algorithm_the_document_declares() -> None:
    """The receipt's algorithm label tracks the document, not a constant.

    ``_receipt_digest`` read ``integrity.digest.algorithm``, a key withdrawn
    when the digest hierarchy replaced the single digest with five named tiers.
    The read yielded nothing and the ``"sha256"`` fallback happened to be the
    truth, so the label was right by coincidence. Changing the algorithm the
    document declares must change the label; a receipt that cannot report the
    algorithm it actually used is not provenance.
    """

    service = CodeCloneMCPService(history_limit=2)
    document = build_maximal_report_document()
    record = _run_record(document)
    comparison = document["integrity"]["digests"]["comparison"]  # type: ignore[index]
    assert isinstance(comparison, dict)

    digest = service._receipt_digest(record)

    assert digest == f"{comparison['algorithm']}:{comparison['value']}"

    other = deepcopy(document)
    other["integrity"]["digests"]["comparison"]["algorithm"] = "blake2b"  # type: ignore[index]
    other_digest = service._receipt_digest(replace(record, report_document=other))

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
        "integrity.digests.comparison.algorithm",
    ):
        assert _document_carries(document, path), path
