# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``statement_format`` must ride EVERY statement-bearing reader surface.

Field bug (maintainer-confirmed, Enacta integration): md-v1 statements reached
external readers with ``## `` bodies but no ``statement_format`` marker — the
stored payload carried only ``subject_path``. Root cause class: the marker
existed solely as a write-time payload stamp, every wave writes its memory
notes through a server process that predates the wave's own code, and several
projection sites never emitted the marker at all. Pinned RED before the fix
per the red-test-every-failure law.

Two guards close the class:

1. An AST inventory of every ``{"statement": ...}`` / ``statement_preview``
   dict construction in the ``codeclone`` package. Every discovered site must
   be registered as covered (with the proving test named) or excluded with a
   reason — a new statement-bearing serialization site fails by construction.
2. A parametrized walk over the MCP wire surfaces with md-authored records
   (wire-stamped, unstamped field-shape, plain legacy) asserting the marker
   rides exactly the md-v1 shapes. This module stays at the r4 test altitude
   (Phase 39S boundary ratchet): records are seeded THROUGH the MCP wire —
   the integrator's own write path — and internal builder seams are proven at
   their own altitude in ``tests/test_memory_statement_markdown.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import cast

import pytest

import codeclone
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.memory_fixtures import cli_memory_repo

# --- Guard 1: inventory of statement-bearing serialization sites --------------

_STATEMENT_KEYS = frozenset({"statement", "statement_preview"})
_PACKAGE_ROOT = Path(codeclone.__file__).resolve().parent
_BUILDER_TESTS = "tests/test_memory_statement_markdown.py"

# Sites proven end to end. Values name the proving surface param or test.
_COVERED_SITES: dict[str, str] = {
    "codeclone/memory/ide_governance.py::prepare_governance": (
        f"{_BUILDER_TESTS}::test_prepare_governance_echo_carries_statement_format"
    ),
    "codeclone/memory/ingest/receipts.py::_try_append_text_candidate": (
        f"{_BUILDER_TESTS}::test_memory_candidates_carry_statement_format"
    ),
    "codeclone/memory/ingest/receipts.py::propose_memory_from_finish_payload": (
        f"{_BUILDER_TESTS}::test_memory_candidates_carry_statement_format"
    ),
    "codeclone/memory/retrieval/service.py::_serialize_experience": (
        f"{_BUILDER_TESTS}::test_experience_surfaces_carry_statement_format"
    ),
    "codeclone/memory/retrieval/service.py::_serialize_record_summary": (
        "wire params query_* / relevant_records_* below"
    ),
    "codeclone/memory/trajectory/export_context.py::_memory_precedent_row": (
        f"{_BUILDER_TESTS}::test_export_memory_precedents_carry_statement_format"
    ),
}

# Sites that are NOT markdown render surfaces; each exclusion carries the
# reason it may omit the marker. Do not add entries without one.
_EXCLUDED_SITES: dict[str, str] = {
    "codeclone/memory/models.py::validate_memory_record": (
        "input validation shim: rebuilds the record as a mapping for the "
        "validator, never leaves the process"
    ),
    "codeclone/surfaces/cli/memory_render.py::_record_mapping": (
        "CLI terminal print: statements render as plain terminal text by "
        "construction and the raw stored payload is echoed verbatim "
        "(evidence-faithful), so the stamped marker already rides it"
    ),
}


def _statement_bearing_sites() -> set[str]:
    sites: set[str] = set()
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(_PACKAGE_ROOT.parent).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        stack: list[str] = []

        def visit(node: ast.AST, *, rel: str = rel, stack: list[str] = stack) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stack.append(node.name)
                for child in ast.iter_child_nodes(node):
                    visit(child)
                stack.pop()
                return
            if isinstance(node, ast.Dict):
                keys = {
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
                if keys & _STATEMENT_KEYS:
                    scope = next((name for name in reversed(stack)), "<module>")
                    sites.add(f"{rel}::{scope}")
            for child in ast.iter_child_nodes(node):
                visit(child)

        visit(tree)
    return sites


def test_statement_bearing_sites_are_inventoried() -> None:
    """Every statement-bearing serialization site is covered or excluded."""
    discovered = _statement_bearing_sites()
    registered = set(_COVERED_SITES) | set(_EXCLUDED_SITES)
    unmapped = sorted(discovered - registered)
    if unmapped:
        pytest.fail(
            "Statement-bearing serialization sites without a statement_format "
            f"guard entry: {unmapped}. Emit the marker on the new surface "
            "(codeclone.memory.statement_markdown.resolve_statement_format "
            "owns the decision), prove it with a driver, and register the "
            "site in _COVERED_SITES — or record a justified _EXCLUDED_SITES "
            "reason."
        )
    stale = sorted(registered - discovered)
    if stale:
        pytest.fail(
            f"Registered statement-format guard sites no longer exist: {stale}. "
            "Prune the registry so the inventory stays evidence-bound."
        )


# --- Guard 2: the marker rides the MCP wire -----------------------------------

_MD_STAMPED = "## Stamped fact\nMarker must ride every reader surface."
_MD_FIELD = "## Field fact\nWritten by a server that predates the stamp."
_MD_STALE = "## Stale fact\nStill markdown after going stale."
_PLAIN_LEGACY = "Legacy plain fact without a markdown title."
_SUBJECT = "pkg/mod.py"

Check = tuple[str, dict[str, object], bool]


def _seed_wire_records(
    service: CodeCloneMCPService, root: Path, store: object
) -> dict[str, str]:
    """Seed through the MCP wire itself (the integrator's write path), then
    rewrite three payloads to the pre-stamp field shape via the raw store
    connection — no internal writer import at this test altitude."""

    def record(statement: str) -> str:
        payload = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="record_candidate",
            record_type="risk_note",
            statement=statement,
            subject_path=_SUBJECT,
        )
        return cast("str", payload["record_id"])

    ids = {
        "stamped_md": record(_MD_STAMPED),
        "field_md": record(_MD_FIELD),
        "stale_md": record(_MD_STALE),
        "legacy_plain": record(_PLAIN_LEGACY),
    }
    conn = store._conn  # type: ignore[attr-defined]
    for key in ("field_md", "stale_md", "legacy_plain"):
        conn.execute(
            "UPDATE memory_records SET payload_json=? WHERE id=?",
            ('{"subject_path": "pkg/mod.py"}', ids[key]),
        )
    conn.execute(
        "UPDATE memory_records SET status='stale', stale_reason='code_drift' "
        "WHERE id=?",
        (ids["stale_md"],),
    )
    conn.commit()
    return ids


def _record_checks(
    nodes: list[dict[str, object]], ids: dict[str, str], *, surface: str
) -> list[Check]:
    expectations = {
        ids["stamped_md"]: True,
        ids["field_md"]: True,
        ids["stale_md"]: True,
        ids["legacy_plain"]: False,
    }
    checks = [
        (f"{surface}:{node['id']}", node, expectations[cast("str", node["id"])])
        for node in nodes
        if node.get("id") in expectations
    ]
    assert checks, f"{surface}: no seeded records surfaced"
    return checks


def _payload_records(payload: dict[str, object]) -> list[dict[str, object]]:
    inner = cast("dict[str, object]", payload["payload"])
    return cast("list[dict[str, object]]", inner["records"])


def _drive_query_records(tmp_path: Path, **query_kwargs: object) -> list[Check]:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, store):
        service = CodeCloneMCPService(history_limit=2)
        ids = _seed_wire_records(service, root, store)
        payload = service.query_engineering_memory(
            root=str(root.resolve()),
            **query_kwargs,
        )
        surface = str(query_kwargs["mode"])
        return _record_checks(_payload_records(payload), ids, surface=surface)


def _drive_query_get_full(tmp_path: Path) -> list[Check]:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, store):
        service = CodeCloneMCPService(history_limit=2)
        ids = _seed_wire_records(service, root, store)
        payload = service.query_engineering_memory(
            root=str(root.resolve()),
            mode="get",
            record_id=ids["field_md"],
            detail_level="full",
        )
        inner = cast("dict[str, object]", payload["payload"])
        record = cast("dict[str, object]", inner["record"])
        return [("get:field_md", record, True)]


def _drive_relevant_memory(tmp_path: Path, *, detail_level: str) -> list[Check]:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, store):
        service = CodeCloneMCPService(history_limit=2)
        ids = _seed_wire_records(service, root, store)
        payload = service.get_relevant_memory(
            root=str(root.resolve()),
            scope=[_SUBJECT],
            include_drafts=True,
            detail_level=detail_level,
        )
        nodes = cast("list[dict[str, object]]", payload["records"])
        return _record_checks(nodes, ids, surface=f"relevant:{detail_level}")


_SURFACE_DRIVERS: dict[str, object] = {
    "query_drafts_compact": lambda tmp_path: _drive_query_records(
        tmp_path, mode="drafts"
    ),
    "query_drafts_full": lambda tmp_path: _drive_query_records(
        tmp_path, mode="drafts", detail_level="full"
    ),
    "query_get_full": _drive_query_get_full,
    "query_search_compact": lambda tmp_path: _drive_query_records(
        tmp_path, mode="search", query="fact", include_drafts=True
    ),
    "query_for_path_compact": lambda tmp_path: _drive_query_records(
        tmp_path, mode="for_path", path=_SUBJECT
    ),
    "query_stale_compact": lambda tmp_path: _drive_query_records(
        tmp_path, mode="stale"
    ),
    "relevant_records_compact": lambda tmp_path: _drive_relevant_memory(
        tmp_path, detail_level="compact"
    ),
    "relevant_records_full": lambda tmp_path: _drive_relevant_memory(
        tmp_path, detail_level="full"
    ),
}


@pytest.mark.parametrize("surface", sorted(_SURFACE_DRIVERS))
def test_statement_format_rides_every_reader_surface(
    surface: str, tmp_path: Path
) -> None:
    driver = _SURFACE_DRIVERS[surface]  # callable(tmp_path) -> list[Check]
    checks = cast("list[Check]", driver(tmp_path))  # type: ignore[operator]
    for description, node, expect_md in checks:
        if expect_md:
            assert node.get("statement_format") == "md-v1", (
                f"{description}: statement_format missing on an md-v1 "
                f"statement body (wire keys: {sorted(node)})"
            )
        else:
            assert "statement_format" not in node, (
                f"{description}: plain statement must stay unmarked "
                "(absent key = plain rendering)"
            )


# --- Guard 3: the structure hint is reachable by real input -------------------
#
# A guard no input reaches is theatre. These drive the entry point an agent
# actually calls -- manage_engineering_memory(action="record_candidate") -- not
# the governance helper underneath it. This module's subject ring is r4, so the
# expected strings are literals: the Phase 39S ratchet refuses a fresh r4->r2p
# test edge, and tests/test_memory_statement_markdown.py pins these literals to
# the constants that own them.

_WIRE_HINT_CODE = "memory_statement_unstructured"
_WIRE_SHAPE_TITLE_LINE = "## one-line title naming the fact"

_WIRE_FLAT_LONG = (
    "The compact preview path cuts a statement at a fixed character budget "
    "and the trajectory export path cuts at its own budget, so a record that "
    "carries a table loses its row separator while the payload still "
    "advertises the md-v1 marker to every renderer downstream of the wire, "
    "and the reader sees a half table it cannot parse."
)


def _record_over_the_wire(root: Path, statement: str) -> dict[str, object]:
    service = CodeCloneMCPService(history_limit=2)
    return service.manage_engineering_memory(
        root=str(root.resolve()),
        action="record_candidate",
        record_type="risk_note",
        statement=statement,
        subject_path=_SUBJECT,
    )


def _wire_hints(payload: dict[str, object]) -> list[str]:
    raw = cast("list[object]", payload.get("warnings", []))
    return [str(item) for item in raw if _WIRE_HINT_CODE in str(item)]


def test_structure_hint_reaches_the_writer_over_the_mcp_wire(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = _record_over_the_wire(root, _WIRE_FLAT_LONG)
        hits = _wire_hints(payload)
        assert hits, f"no structure hint on the wire (keys: {sorted(payload)})"
        assert _WIRE_SHAPE_TITLE_LINE in hits[0], "wire hint carries no shape"


def test_titled_note_carries_no_hint_over_the_mcp_wire(tmp_path: Path) -> None:
    """Sibling isolation: the same wire stays silent for a shaped note."""
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        payload = _record_over_the_wire(
            root, f"## Preview cuts md-v1 bodies\n{_WIRE_FLAT_LONG}"
        )
        assert not _wire_hints(payload)
