# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Markdown-subset statement hygiene: security rejects, discipline rules, gates.

Every reject/warn rule here was pinned RED against the pre-markdown seam
(record_candidate / validate_memory_claims silently accepted the construct)
before the rule existed, per the red-test-every-failure law.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, NamedTuple, cast

import pytest

from codeclone.memory.exceptions import MemoryContractError
from codeclone.memory.governance import record_candidate, validate_memory_claims
from codeclone.memory.models import (
    MemoryProject,
    MemoryRecord,
    MemorySubject,
    generate_memory_id,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore


class _EmptyStubStore:
    def query_records(self, _query: object) -> list[object]:
        return []


def _claims_store() -> SqliteEngineeringMemoryStore:
    return cast(SqliteEngineeringMemoryStore, _EmptyStubStore())


def _open_store(
    tmp_path: Path,
) -> tuple[SqliteEngineeringMemoryStore, MemoryProject]:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    project = resolve_project_identity(root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    store.initialize(project)
    return store, project


def _record(
    store: SqliteEngineeringMemoryStore,
    project: MemoryProject,
    statement: str,
) -> MemoryRecord:
    return record_candidate(
        store,
        project=project,
        record_type="risk_note",
        statement=statement,
        subject_path="codeclone/memory/governance.py",
        max_candidates=100,
    )


# --- Security class: typed rejects at the record_candidate seam -------------


def test_record_candidate_rejects_markdown_image(tmp_path: Path) -> None:
    """Images are an exfiltration channel: the renderer pings the URL."""
    store, project = _open_store(tmp_path)
    try:
        with pytest.raises(MemoryContractError, match="memory_md_image"):
            _record(
                store,
                project,
                "Cache probe result ![probe](https://evil.example/x.png) stored.",
            )
    finally:
        store.close()


def test_record_candidate_rejects_raw_html(tmp_path: Path) -> None:
    """Raw HTML injects into webview render surfaces."""
    store, project = _open_store(tmp_path)
    try:
        with pytest.raises(MemoryContractError, match="memory_md_html"):
            _record(
                store,
                project,
                'The badge markup <span class="badge">P1</span> is emitted here.',
            )
    finally:
        store.close()


def test_record_candidate_rejects_masked_link(tmp_path: Path) -> None:
    """[text](url) masks the target in rendered UI; bare URLs only."""
    store, project = _open_store(tmp_path)
    try:
        with pytest.raises(MemoryContractError, match="memory_md_link"):
            _record(
                store,
                project,
                "See [the docs](https://evil.example/payload) for details.",
            )
    finally:
        store.close()


def test_record_candidate_rejects_reference_link_and_definition(
    tmp_path: Path,
) -> None:
    """Reference links resolve through definitions — the same masking channel."""
    store, project = _open_store(tmp_path)
    try:
        with pytest.raises(MemoryContractError, match="memory_md_link"):
            _record(store, project, "See [the docs][ref] for details.")
        with pytest.raises(MemoryContractError, match="memory_md_link"):
            _record(
                store,
                project,
                "Details below.\n[ref]: https://evil.example/payload",
            )
    finally:
        store.close()


def test_reject_messages_carry_next_step_and_help(tmp_path: Path) -> None:
    """In-band procedures law: a typed reject ships its own remediation."""
    store, project = _open_store(tmp_path)
    try:
        with pytest.raises(MemoryContractError) as excinfo:
            _record(store, project, "![x](https://evil.example/x.png)")
    finally:
        store.close()
    message = str(excinfo.value)
    assert "next_step" in message
    assert 'help(topic="engineering_memory")' in message
    assert "record_candidate" in message


# --- Discipline class: one ## heading, first content line -------------------


def test_record_candidate_rejects_multiple_headings(tmp_path: Path) -> None:
    store, project = _open_store(tmp_path)
    try:
        with pytest.raises(MemoryContractError, match="memory_md_heading_structure"):
            _record(
                store,
                project,
                "## First fact\nbody\n## Second fact\nmore body",
            )
    finally:
        store.close()


def test_record_candidate_rejects_heading_not_first(tmp_path: Path) -> None:
    store, project = _open_store(tmp_path)
    try:
        with pytest.raises(MemoryContractError, match="memory_md_heading_structure"):
            _record(store, project, "intro sentence\n## Late title\nbody")
    finally:
        store.close()


def test_validate_claims_warns_on_wrong_heading_level(tmp_path: Path) -> None:
    result = validate_memory_claims(
        _claims_store(),
        project_id="proj",
        text="# Top-level title\nbody of the note",
    )
    assert result.valid
    assert any("memory_md_heading_level" in item for item in result.warnings)


def test_validate_claims_warns_on_deep_list_nesting(tmp_path: Path) -> None:
    result = validate_memory_claims(
        _claims_store(),
        project_id="proj",
        text="## T\n- top\n  - nested once\n      - nested twice",
    )
    assert result.valid
    assert any("memory_md_list_nesting" in item for item in result.warnings)


# --- validate_claims advisory lane mirrors the security class ---------------


def test_validate_claims_errors_on_security_constructs(tmp_path: Path) -> None:
    result = validate_memory_claims(
        _claims_store(),
        project_id="proj",
        text=(
            "![shot](https://evil.example/s.png) and <script>x</script> "
            "and [here](https://evil.example)"
        ),
    )
    assert not result.valid
    joined = " ".join(result.errors)
    assert "memory_md_image" in joined
    assert "memory_md_html" in joined
    assert "memory_md_link" in joined


# --- Average-size gate (batch mean) -----------------------------------------


def test_validate_claims_batch_mean_gate_warns(tmp_path: Path) -> None:
    """Two blank-line-separated notes averaging >200 chars warn (essay drift)."""
    unit_a = "A" * 240
    unit_b = "B" * 240
    result = validate_memory_claims(
        _claims_store(),
        project_id="proj",
        text=f"{unit_a}\n\n{unit_b}",
    )
    assert result.valid
    assert any("batch mean" in item.lower() for item in result.warnings)


def test_validate_claims_batch_mean_gate_quiet_below_limit(tmp_path: Path) -> None:
    result = validate_memory_claims(
        _claims_store(),
        project_id="proj",
        text="short note one\n\nshort note two",
    )
    assert not any("batch mean" in item.lower() for item in result.warnings)


def test_batch_statement_length_warnings_helper() -> None:
    from codeclone.memory.governance import batch_statement_length_warnings

    assert batch_statement_length_warnings([]) == ()
    assert (
        batch_statement_length_warnings([900]) == ()
    )  # single note: per-record gates own it
    assert batch_statement_length_warnings([150, 150]) == ()
    fired = batch_statement_length_warnings([260, 260])
    assert fired and "batch mean" in fired[0].lower()


# --- Allowed subset stays accepted (plain text is a subset by construction) --


TEMPLATE_STATEMENT = (
    "## Cache keys normalize once\n"
    "`resolve_cache_path()` lowercases keys; **eviction compares raw paths** "
    "(miss on case-variant paths).\n"
    "| probe | result |\n"
    "| --- | --- |\n"
    "| `Foo.py` | miss |\n"
    "> Ruling: normalize at write, never at compare.\n"
    "Why: prevents double entries per path casing."
)


def test_record_candidate_accepts_full_template(tmp_path: Path) -> None:
    store, project = _open_store(tmp_path)
    try:
        record = _record(store, project, TEMPLATE_STATEMENT)
        assert record.status == "draft"
    finally:
        store.close()


def test_record_candidate_accepts_plain_text_statement(tmp_path: Path) -> None:
    store, project = _open_store(tmp_path)
    try:
        record = _record(
            store,
            project,
            "Plain legacy-style fact about codeclone/memory/governance.py with "
            "a < b comparisons and handlers[0] indexing kept intact.",
        )
        assert record.status == "draft"
    finally:
        store.close()


def test_code_span_shields_literal_markup(tmp_path: Path) -> None:
    """Backtick spans are the sanctioned escape for literal markup fragments."""
    store, project = _open_store(tmp_path)
    try:
        record = _record(
            store,
            project,
            'The renderer emits `<span class="badge">` and `![img](u)` literally.',
        )
        assert record.status == "draft"
    finally:
        store.close()


def test_validate_claims_allows_bare_urls_and_blockquotes(tmp_path: Path) -> None:
    result = validate_memory_claims(
        _claims_store(),
        project_id="proj",
        text=(
            "## Ruling captured\n"
            "> Maintainer: bare URLs only.\n"
            "Evidence at https://example.org/receipt remains visible."
        ),
    )
    assert result.valid
    assert not any("memory_md" in item for item in result.warnings)


# --- statement_format marker (md-v1 rides payload, absent = plain) -----------


def test_record_candidate_stamps_md_v1_statement_format(tmp_path: Path) -> None:
    store, project = _open_store(tmp_path)
    try:
        record = _record(store, project, "One durable validated fact.")
        assert record.payload is not None
        assert record.payload["statement_format"] == "md-v1"
    finally:
        store.close()


def test_record_summary_exposes_statement_format(tmp_path: Path) -> None:
    from codeclone.memory.retrieval.service import _serialize_record_summary

    store, project = _open_store(tmp_path)
    try:
        record = _record(store, project, "One durable validated fact.")
        summary = _serialize_record_summary(
            record=record,
            subjects=[],
            evidence_count=0,
        )
        assert summary["statement_format"] == "md-v1"
        legacy = record_candidate(
            store,
            project=project,
            record_type="risk_note",
            statement="Legacy-shaped fact.",
            subject_path="codeclone/memory/models.py",
            max_candidates=100,
        )
        object.__setattr__(legacy, "payload", {"subject_path": "x.py"})
        plain_summary = _serialize_record_summary(
            record=legacy,
            subjects=[],
            evidence_count=0,
        )
        assert "statement_format" not in plain_summary
    finally:
        store.close()


def test_resolve_statement_format_owns_the_wire_decision() -> None:
    """Stamp wins; a leading validated '## ' title derives; plain never marks.

    The derivation arm heals md-authored records whose writer predated the
    payload stamp (the Enacta field bug: every wave records its memory notes
    through a server process older than the wave's own code).
    """
    from codeclone.memory.statement_markdown import resolve_statement_format

    md = "## Title\nOne durable fact."
    # 1. Write-time stamp is authorship truth, whatever the statement shape.
    assert resolve_statement_format("plain", {"statement_format": "md-v1"}) == "md-v1"
    # 2. Unstamped md-v1 signature derives (field-shape payload).
    assert resolve_statement_format(md, {"subject_path": "x.py"}) == "md-v1"
    assert resolve_statement_format(md, None) == "md-v1"
    # 3. Rejecting reports stay plain: render-surface security bans hold for
    #    legacy rows (image / raw HTML / masked link / second heading).
    assert resolve_statement_format("## T\n<img src=x>", None) is None
    assert resolve_statement_format("## A\n## B", None) is None
    # 4. No leading title = no unambiguous authorship signal: stays plain
    #    even when markdown-flavored, so legacy text is never force-rendered.
    assert resolve_statement_format("uses `code` span only", None) is None
    assert resolve_statement_format("Legacy plain fact.", {}) is None
    # 5. Unknown stamp values fall through to derivation, never pass through.
    assert resolve_statement_format("plain", {"statement_format": "md-v2"}) is None


# --- Builder seams: the marker rides every statement-bearing projection -------
# (r2p altitude; the r4 MCP wire is walked in test_memory_statement_format_wire,
# whose inventory registry names each test below as the proving driver.)

_TS = "2026-01-01T00:00:00Z"


def _strip_stamp(store: SqliteEngineeringMemoryStore, record_id: str) -> None:
    """Rewrite one payload to the pre-stamp field shape (subject_path only)."""
    store._conn.execute(
        "UPDATE memory_records SET payload_json=? WHERE id=?",
        ('{"subject_path": "pkg/mod.py"}', record_id),
    )
    store.commit()


def test_experience_surfaces_carry_statement_format(tmp_path: Path) -> None:
    from codeclone.memory.experience.models import Experience
    from codeclone.memory.retrieval.service import (
        get_relevant_memory,
        query_engineering_memory,
    )

    def experience(suffix: str, statement: str) -> Experience:
        return Experience(
            id="exp-" + suffix * 16,
            project_id=project.id,
            repo_root_digest="digest",
            subject_family="pkg",
            signal=f"signal_{suffix}",
            outcome_class="accepted:verified",
            support=3,
            quality_min=80,
            information_value=85,
            status="active",
            statement=statement,
            experience_digest=f"digest-{suffix}",
            distillation_version="experience-v1",
            first_observed_at_utc=_TS,
            last_observed_at_utc=_TS,
            distilled_at_utc=_TS,
            updated_at_utc=_TS,
            facets=(),
            evidence=(),
        )

    store, project = _open_store(tmp_path)
    try:
        md = experience("ab", "## Distilled pattern\nMarkdown-authored.")
        plain = experience("cd", "Plain machine-distilled statement.")
        store.replace_experiences(project_id=project.id, experiences=[md, plain])
        got = query_engineering_memory(
            store,
            project_id=project.id,
            root_path=tmp_path / "repo",
            backend="sqlite",
            db_path=tmp_path / "memory.sqlite3",
            mode="experience_get",
            record_id=md.id,
        )
        payload = cast("dict[str, object]", got["payload"])
        node = cast("dict[str, object]", payload["experience"])
        assert node["statement_format"] == "md-v1"
        relevant = get_relevant_memory(
            store,
            project_id=project.id,
            scope_paths=("pkg/mod.py",),
            scope_resolved_from="explicit_scope",
        )
        lane = cast("list[dict[str, object]]", relevant["experiences"])
        by_id = {str(item["id"]): item for item in lane}
        assert by_id[md.id]["statement_format"] == "md-v1"
        assert "statement_format" not in by_id[plain.id]
    finally:
        store.close()


def test_memory_candidates_carry_statement_format(tmp_path: Path) -> None:
    from codeclone.memory.ingest.receipts import propose_memory_from_changed_paths

    store, project = _open_store(tmp_path)
    try:
        candidates = propose_memory_from_changed_paths(
            store,
            project=project,
            changed_paths=["pkg/mod.py"],
            claims_text="## Claims digest\nOne durable md-authored claim.",
            review_text=None,
            verification_profile="python_structural",
            max_candidates=100,
            max_statement_chars=1000,
        )
        # The declared scope no longer mints a record of its own (it only elects
        # the subject path), so the finish batch is claims + the proposal.
        assert len(candidates) >= 2, "expected claims + proposal"
        for node in candidates:
            if node.get("proposal_only"):
                # Synthetic in-response proposal: plain machine text.
                assert "statement_format" not in node
            else:
                # record_candidate-backed drafts are stamped md-v1 today.
                assert node["statement_format"] == "md-v1", node
    finally:
        store.close()


def test_prepare_governance_echo_carries_statement_format(tmp_path: Path) -> None:
    from codeclone.memory.ide_governance import (
        IdeGovernanceSessionState,
        prepare_governance,
        register_ide_governance,
    )

    store, project = _open_store(tmp_path)
    try:
        draft = _record(store, project, "## Field fact\nUnstamped md draft.")
        _strip_stamp(store, draft.id)
        state = IdeGovernanceSessionState(channel_enabled=True)
        registered = register_ide_governance(
            state,
            ide_governance_key="ab" * 32,
            client_name="CodeClone VS Code",
            client_version="0.3.0",
        )
        assert registered["status"] == "ok"
        prepared = prepare_governance(
            state,
            store,
            project_id=project.id,
            root_path=str(tmp_path / "repo"),
            record_id=draft.id,
            decision="approve",
        )
        assert prepared["status"] == "ok"
        record = cast("dict[str, object]", prepared["record"])
        assert record["statement_format"] == "md-v1"
    finally:
        store.close()


def test_export_memory_precedents_carry_statement_format(tmp_path: Path) -> None:
    from codeclone.memory.trajectory import export_context
    from tests.memory_fixtures import seed_trajectory_audit_workflow

    store, project = _open_store(tmp_path)
    try:
        root = tmp_path / "repo"
        audit_db = tmp_path / "audit.sqlite3"
        seed_trajectory_audit_workflow(root=root, audit_db=audit_db)
        trajectory = store.rebuild_trajectories_from_audit(
            project=project,
            root_path=root,
            audit_db_path=audit_db,
        ).trajectories[0]
        statements = {
            "## Precedent fact\nMarkdown-authored active precedent.": True,
            "Plain precedent without a markdown title.": False,
        }
        for statement in statements:
            record = _record(store, project, statement)
            _strip_stamp(store, record.id)
            store._conn.execute(
                "UPDATE memory_records SET status='active' WHERE id=?",
                (record.id,),
            )
            store.write_subject(
                MemorySubject(
                    id=generate_memory_id(prefix="subj"),
                    memory_id=record.id,
                    subject_kind="path",
                    subject_key="pkg/service.py",
                    relation="about",
                )
            )
        store.commit()
        precedents = export_context._memory_precedents(
            store._conn,
            project_id=project.id,
            trajectory=trajectory,
            scope_paths=("pkg/service.py",),
        )
        checked = 0
        for statement, expected in statements.items():
            title = statement.split("\n", 1)[0]
            for node in precedents:
                if not str(node["statement_preview"]).startswith(title):
                    continue
                checked += 1
                if expected:
                    assert node["statement_format"] == "md-v1", node
                else:
                    assert "statement_format" not in node, node
        assert checked == 2, f"seeded precedents did not surface: {precedents}"
    finally:
        store.close()


# --- Validator unit contract: determinism, totality, in-band registry --------


def test_validator_is_deterministic_and_total() -> None:
    from codeclone.memory.statement_markdown import validate_statement_markdown

    weird_inputs = [
        "",
        "\r\n## title\r\nbody\r\n",
        "`unterminated span with <img src=x>",
        "``double `tick` span`` and ```run```",
        "\x00\x01 control chars < > ! [ ] ( ) # * | ` \x7f",
        "a" * 5000,
        "  \n\t\n  ",
        "|" * 300,
        "<" * 100 + ">" * 100,
    ]
    for text in weird_inputs:
        first = validate_statement_markdown(text)
        second = validate_statement_markdown(text)
        assert first == second


def test_every_reject_code_has_next_step_and_help_mention() -> None:
    """The typed-outcome law: no reject code without an in-band procedure."""
    from codeclone.memory.statement_markdown import (
        STATEMENT_MD_REJECT_CODES,
        STATEMENT_MD_WARN_CODES,
        validate_statement_markdown,
    )

    offenders = {
        "memory_md_image": "![x](https://e.example/x.png)",
        "memory_md_html": "<script>alert(1)</script>",
        "memory_md_link": "[x](https://e.example)",
        "memory_md_heading_structure": "## a\n## b",
    }
    assert set(offenders) == set(STATEMENT_MD_REJECT_CODES)
    for code, sample in sorted(offenders.items()):
        report = validate_statement_markdown(sample)
        matching = [issue for issue in report.rejects if issue.code == code]
        assert matching, f"{code} did not fire on its own offender"
        message = matching[0].message
        assert "next_step" in message, f"{code} reject has no next_step"
        assert 'help(topic="engineering_memory")' in message
        assert "record_candidate" in message, f"{code} names no executable action"
    warn_offenders = {
        "memory_md_heading_level": "# top\nbody",
        "memory_md_list_nesting": "- a\n      - deep",
    }
    assert set(warn_offenders) == set(STATEMENT_MD_WARN_CODES)
    for code, sample in sorted(warn_offenders.items()):
        report = validate_statement_markdown(sample)
        assert any(code in item for item in report.warnings), code


def test_validator_single_heading_level_is_h2() -> None:
    from codeclone.memory.statement_markdown import validate_statement_markdown

    good = validate_statement_markdown("## Title\nbody")
    assert not good.rejects and not good.warnings
    warned = validate_statement_markdown("### Title\nbody")
    assert not warned.rejects
    assert any("memory_md_heading_level" in item for item in warned.warnings)


# --- Structure delivery: the md-v1 shape reaches the writer in band ----------
#
# Measured 2026-08-31 on the live store (agent-authored records only): markdown
# adoption fell from 52.9% of new records (08-04..08-19, n=380) to 4.9%
# (08-20..08-31, n=288) once the wave that built the format left context. The
# template never moved -- it sat behind help(topic="engineering_memory"), a
# call the writer had no reason to make. Structure that costs an extra round
# trip is structure nobody writes.
#
# These tests read the size target through the governance seam that binds it,
# never through codeclone.config: this module's subject ring is r2p, and the
# Phase 39S ratchet refuses a fresh r2p->r2 test edge.

_FLAT_LONG = (
    "The compact preview path cuts a statement at a fixed character budget "
    "and the trajectory export path cuts at its own budget, so a record that "
    "carries a table loses its row separator while the payload still "
    "advertises the md-v1 marker to every renderer downstream of the wire, "
    "and the reader sees a half table it cannot parse."
)
_SHORT_FLAT = (
    "Wildcard re-export recovery keeps the exported bindings a star import loses."
)


def test_flat_oversized_statement_gets_the_structure_hint() -> None:
    """A note too long to read as one line is handed the shape, in band."""
    from codeclone.memory.governance import statement_markdown_warnings
    from codeclone.memory.statement_markdown import (
        STATEMENT_SKELETON,
        STATEMENT_STRUCTURE_WARN_CODE,
    )

    hits = [
        item
        for item in statement_markdown_warnings(_FLAT_LONG)
        if STATEMENT_STRUCTURE_WARN_CODE in item
    ]
    assert hits, "flat oversized statement got no structure hint"
    message = hits[0]
    assert f"{len(_FLAT_LONG)} chars" in message, "hint did not measure this input"
    assert STATEMENT_SKELETON in message, "hint carries no copyable shape"
    assert "next_step" in message, "hint carries no executable next step"


def test_titled_statement_is_not_told_to_add_a_title() -> None:
    """Opposite boundary: a note that already carries the shape stays quiet."""
    from codeclone.memory.governance import statement_markdown_warnings
    from codeclone.memory.statement_markdown import STATEMENT_STRUCTURE_WARN_CODE

    titled = f"## Compact preview cuts md-v1 bodies\n{_FLAT_LONG}"
    assert not [
        item
        for item in statement_markdown_warnings(titled)
        if STATEMENT_STRUCTURE_WARN_CODE in item
    ]


def test_short_one_line_fact_is_not_told_to_add_a_title() -> None:
    """Opposite boundary: a single durable line stays legal and unwarned."""
    from codeclone.memory.governance import statement_markdown_warnings
    from codeclone.memory.statement_markdown import STATEMENT_STRUCTURE_WARN_CODE

    assert not [
        item
        for item in statement_markdown_warnings(_SHORT_FLAT)
        if STATEMENT_STRUCTURE_WARN_CODE in item
    ]


def test_advised_shape_obeys_the_rules_it_teaches() -> None:
    """Derivation pin, not a magic number.

    The hint is advice the writer pastes back through record_candidate, so
    the shape must survive the same validator, and it must fit the target it
    invokes -- that is what makes "one fact, not one line" measurable rather
    than aspirational.

    The size half is re-derived through the live seam: a flat note exactly as
    long as the shape must draw no hint, which is true only while the shape
    fits the bound target. Bloating the shape reds it; shrinking
    DEFAULT_MEMORY_TARGET_STATEMENT_CHARS under the shape reds it too. A
    relative pin ("shape <= target") would stay green for any value of
    either.
    """
    from codeclone.memory.governance import statement_markdown_warnings
    from codeclone.memory.statement_markdown import (
        STATEMENT_SKELETON,
        STATEMENT_STRUCTURE_WARN_CODE,
        resolve_statement_format,
        validate_statement_markdown,
    )

    report = validate_statement_markdown(STATEMENT_SKELETON)
    assert not report.rejects, "advised shape would be refused at the seam"
    assert not report.warnings, "advised shape trips its own discipline rules"
    assert resolve_statement_format(STATEMENT_SKELETON) == "md-v1"

    shape_sized_prose = "x" * len(STATEMENT_SKELETON)
    assert not [
        item
        for item in statement_markdown_warnings(shape_sized_prose)
        if STATEMENT_STRUCTURE_WARN_CODE in item
    ], "the advised shape is longer than the target it tells writers to meet"
    # Witness that the silence above is a measurement and not a dead probe:
    # the longest statement record_candidate will accept at all must draw the
    # hint. The pair brackets the boundary from both sides.
    assert [
        item
        for item in statement_markdown_warnings("x" * 1000)
        if STATEMENT_STRUCTURE_WARN_CODE in item
    ], "the structure probe never fires, so the silence above proves nothing"


def test_wire_literals_track_the_owned_constants() -> None:
    """Drift lock for the r4 wire test, which may not import this ring.

    tests/test_memory_statement_format_wire.py asserts on literals because
    the Phase 39S ratchet forbids an r4->r2p test edge. This module is r2p
    and can hold both, so the literals are pinned to their owners here.
    """
    from codeclone.memory.statement_markdown import (
        STATEMENT_SKELETON,
        STATEMENT_STRUCTURE_WARN_CODE,
    )

    from .test_memory_statement_format_wire import (
        _WIRE_HINT_CODE,
        _WIRE_SHAPE_TITLE_LINE,
    )

    assert _WIRE_HINT_CODE == STATEMENT_STRUCTURE_WARN_CODE
    assert STATEMENT_SKELETON.startswith(f"{_WIRE_SHAPE_TITLE_LINE}\n")


# --- Compact preview must not hand a renderer a severed construct ------------

# A test-local budget: the properties below hold at any budget, so pinning the
# shipped default here would only duplicate its declaration.
_PROBE_BUDGET = 160


def test_compact_preview_keeps_lines_whole() -> None:
    """A cut inside a table row leaves a delimiter no renderer can parse."""
    from codeclone.memory.retrieval.service import _statement_preview

    preview = _statement_preview(TEMPLATE_STATEMENT)
    assert preview != TEMPLATE_STATEMENT, "fixture no longer truncates"
    kept = preview.removesuffix("…").rstrip("\n").split("\n")
    assert kept == TEMPLATE_STATEMENT.split("\n")[: len(kept)], (
        f"preview ends mid-line: {preview!r}"
    )


def test_compact_preview_never_unmasks_a_banned_construct() -> None:
    """Truncation must not defeat the memory_md_link ban.

    A link inside a code span is masked, so the statement is accepted. Cut
    the span open and the same bytes become an active link -- while the
    payload still stamps statement_format=md-v1 for the renderer.
    """
    from codeclone.memory.retrieval.service import _statement_preview
    from codeclone.memory.statement_markdown import validate_statement_markdown

    statement = (
        "Evidence pointer kept literal so no renderer activates it, padded "
        "here so the compact preview budget cuts inside the span and unmasks "
        "it: `[ruling](https://example.invalid/ruling)` tail."
    )
    assert not validate_statement_markdown(statement).rejects
    naive = statement[: _PROBE_BUDGET - 1]
    assert [item.code for item in validate_statement_markdown(naive).rejects] == [
        "memory_md_link"
    ], "fixture no longer exercises the unmasking hazard"
    preview = _statement_preview(statement, max_chars=_PROBE_BUDGET)
    assert not validate_statement_markdown(preview).rejects


def test_single_line_preview_still_spends_the_whole_budget() -> None:
    """Opposite boundary: plain one-line prose keeps its character budget."""
    from codeclone.memory.retrieval.service import _statement_preview

    preview = _statement_preview("z" * 400, max_chars=_PROBE_BUDGET)
    assert len(preview) == _PROBE_BUDGET


# --- The declared vocabulary must equal what the validator accepts -----------
#
# Fenced blocks passed by omission, not by contract. ``_mask_code_spans``
# pairs backtick runs the way CommonMark does, so a ``` run collapsed against
# its closer as an ordinary span and nothing ever scanned the body -- while
# every text a model or a renderer author reads listed the subset with no
# fence in it. The maintainer's IDE did not render fences for exactly that
# reason: it followed the declared vocabulary faithfully.
#
# Two drift directions, one pin. The validator can quietly stop accepting a
# declared construct (anyone tightening the masking would have had no red
# test), and a declared text can quietly stop naming an accepted one. A pin
# asserting only "a fence is accepted" would stay green through the second
# direction, which is the class this repository keeps paying for.
#
# The three MCP texts are read as SOURCE, never imported: this module's
# subject ring is r2p and ``codeclone.surfaces`` is r4, so an import would be a
# fresh r2p->r4 test edge that the Phase 39S ratchet refuses. Reading a file
# adds no runtime coupling; it is the same inspection
# tests/test_memory_statement_format_wire.py performs in the other direction.
#
# The tool-level description in tools.py is the fourth copy and the one no
# other guard reaches: mcp_tool_schemas.json stores name and input_schema
# only, so the per-tool description FastMCP publishes is snapshot-invisible.
# Left out of this pin, one MCP tool would serve two descriptions of one
# contract that disagree.

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_MCP_MESSAGES: Final = _REPO_ROOT / "codeclone" / "surfaces" / "mcp" / "messages"


class _Construct(NamedTuple):
    """One vocabulary entry: samples, their shared verdict, its spelling."""

    samples: tuple[str, ...]
    accepted: bool
    reject_code: str | None
    declaration: tuple[str, ...]


# ``declaration`` holds the literal spellings the vocabulary uses -- the
# declared texts write constructs in the constructs themselves (`code spans`,
# '## ' title, [text](url)), so a token check reads the declared spelling
# rather than a paraphrase invented here.
_VOCABULARY: Final[dict[str, _Construct]] = {
    "fenced_code_block": _Construct(
        # The second sample is the load-bearing one. A fence over inert text
        # stays accepted even if the masking stops recognising ``` runs --
        # there is nothing in it for the security rules to catch -- so a pin
        # built only on it would survive the exact regression it exists to
        # prevent. Real snippets carry markup; this one does, and it is
        # accepted only because the fence body is masked.
        samples=(
            "## Fence\n```python\nvalue = 1\n```",
            '## Fence\n```python\nrender("<b>x</b>")\n```',
        ),
        accepted=True,
        reject_code=None,
        declaration=("fenced code block", "```", "language tag"),
    ),
    "raw_html_tag": _Construct(
        samples=("## Tag\n<code>value = 1</code>",),
        accepted=False,
        reject_code="memory_md_html",
        declaration=("raw HTML", "<code>"),
    ),
}

_DOCSTRING_SITE: Final = "codeclone/memory/statement_markdown.py::__doc__"
_PARAM_SITE: Final = "codeclone/surfaces/mcp/messages/params.py::MemoryStatementParam"
_HELP_SITE: Final = "codeclone/surfaces/mcp/messages/help_topics.py::engineering_memory"
_TOOL_SITE: Final = (
    "codeclone/surfaces/mcp/messages/tools.py::MANAGE_ENGINEERING_MEMORY"
)

# Present in every declared vocabulary today: proof the extractor reached the
# vocabulary at all.
_VOCABULARY_ANCHOR: Final = "compact tables"
# One string per site that lives in the same FILE but outside the vocabulary
# node. An extractor that silently widened to the whole file would pick it up.
_OUTSIDE_THE_VOCABULARY: Final[dict[str, str]] = {
    _DOCSTRING_SITE: "STATEMENT_MD_WARN_CODES",
    _PARAM_SITE: "Telemetry section to project",
    _HELP_SITE: "verification_profile",
    _TOOL_SITE: "Mode-based engineering memory inspection router",
}


def _normalized(text: str) -> str:
    """Fold a declared text to one comparable line: whitespace, then case.

    Declared vocabulary is prose wrapped to fit a source line, so a spelling
    is routinely split across a line break ("compact\ntables") and a term
    opening a sentence is capitalised ("Raw HTML" against "raw HTML"). Both
    caught this pin on its own first two runs. Matching the raw text would
    make it depend on where a formatter wrapped and where a sentence began --
    drift the pin must not invent. Case folding never widens a match across
    constructs here: the spellings are distinct words, not case variants.
    """
    return " ".join(text.split()).casefold()


def _string_constants(node: ast.AST) -> str:
    return _normalized(
        "\n".join(
            child.value
            for child in ast.walk(node)
            if isinstance(child, ast.Constant) and isinstance(child.value, str)
        )
    )


def _module_constant(module: str, name: str) -> str:
    """Read one module-level binding's string constants out of SOURCE."""
    source = (_MCP_MESSAGES / module).read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign):
            bound: list[ast.expr] = [node.target]
        elif isinstance(node, ast.Assign):
            bound = list(node.targets)
        else:
            continue
        if any(isinstance(item, ast.Name) and item.id == name for item in bound):
            return _string_constants(node)
    raise AssertionError(f"{name} is no longer a module-level binding in {module}")


def _help_topic_text(topic: str) -> str:
    source = (_MCP_MESSAGES / "help_topics.py").read_text(encoding="utf-8")
    specs = next(
        (
            node.value
            for node in ast.parse(source).body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "HELP_TOPIC_SPECS"
        ),
        None,
    )
    assert isinstance(specs, ast.Dict), "HELP_TOPIC_SPECS is no longer a literal dict"
    for key, value in zip(specs.keys, specs.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == topic:
            return _string_constants(value)
    raise AssertionError(f"help topic {topic!r} is not declared in help_topics.py")


def _declared_texts() -> dict[str, str]:
    from codeclone.memory import statement_markdown

    validator_file = Path(statement_markdown.__file__).resolve()
    assert validator_file.is_relative_to(_REPO_ROOT), (
        f"validator imported from {validator_file}, outside {_REPO_ROOT}: the "
        "declared texts and the behaviour would come from different trees"
    )
    return {
        _DOCSTRING_SITE: _normalized(statement_markdown.__doc__ or ""),
        _PARAM_SITE: _module_constant("params.py", "MemoryStatementParam"),
        _HELP_SITE: _help_topic_text("engineering_memory"),
        _TOOL_SITE: _module_constant("tools.py", "MANAGE_ENGINEERING_MEMORY"),
    }


def test_vocabulary_extractors_read_the_vocabulary_and_nothing_else() -> None:
    """Probe validity for the pin below: a dead extractor would fake it.

    An extractor returning "" fails the reconciliation closed, but one that
    widened to the whole file would find every token somewhere and report
    agreement it never measured. Both ends are bracketed: the anchor proves
    the vocabulary was reached, the outside string proves nothing beyond it
    was.
    """
    texts = _declared_texts()
    assert set(texts) == set(_OUTSIDE_THE_VOCABULARY)
    for site, text in sorted(texts.items()):
        assert _normalized(_VOCABULARY_ANCHOR) in text, (
            f"{site}: extractor missed the vocabulary"
        )
        outside = _OUTSIDE_THE_VOCABULARY[site]
        assert _normalized(outside) not in text, (
            f"{site}: extractor widened past the vocabulary node (found "
            f"{outside!r}), so its token checks prove nothing"
        )


def test_declared_vocabulary_and_validator_agree_on_every_construct() -> None:
    """Reconciliation: both halves derived, neither transcribed.

    The behaviour half runs the live validator over a sample. The declaration
    half reads the four texts a consumer actually gets -- the module contract
    docstring, the ``statement`` parameter description the MCP schema
    publishes, the ``help(topic="engineering_memory")`` topic body, and the
    ``manage_engineering_memory`` tool-level description FastMCP registers. A
    construct must be named by every one of them and classified by the
    validator the way the vocabulary promises.

    The token check proves the construct is *named*, never that the prose
    around it says "allowed": the accepted/refused fact is carried by the
    validator half, which is why the banned construct is registered here too.
    """
    from codeclone.memory.statement_markdown import validate_statement_markdown

    texts = _declared_texts()
    for name, construct in sorted(_VOCABULARY.items()):
        for sample in construct.samples:
            codes = sorted(
                issue.code for issue in validate_statement_markdown(sample).rejects
            )
            if construct.accepted:
                assert not codes, (
                    f"{name}: every declared vocabulary carries it and the "
                    f"validator now refuses {sample!r} ({codes})"
                )
            else:
                assert construct.reject_code in codes, (
                    f"{name}: declared as refused, validator returned {codes}"
                )
        for site, text in sorted(texts.items()):
            missing = [
                token
                for token in construct.declaration
                if _normalized(token) not in text
            ]
            assert not missing, (
                f"{site} does not declare {name}: missing {missing}. What the "
                "validator does and what a model reads have drifted apart."
            )


def test_only_the_backtick_fence_shields_its_body() -> None:
    """The declared block form is the only one that is actually shielded.

    The vocabulary names the backtick fence and no other block form. That is
    a behavioural claim, not a style preference: ``_mask_code_spans`` blanks a
    paired backtick run, so the fence body never reaches the security rules,
    while a ``~~~`` fence and a four-space indented block are scanned as live
    prose and refuse the very snippet the backtick fence accepts. Without this
    the contract sentence would be an unexecuted engineering claim.
    """
    from codeclone.memory.statement_markdown import validate_statement_markdown

    snippet = "print('<b>x</b>')"
    accepted = f"## T\n```python\n{snippet}\n```"
    assert not validate_statement_markdown(accepted).rejects, (
        "the backtick fence no longer shields its body"
    )
    undeclared = {
        "~~~ fence": f"## T\n~~~python\n{snippet}\n~~~",
        "indented block": f"## T\nbody\n\n    {snippet}\n",
    }
    for form, sample in sorted(undeclared.items()):
        codes = [issue.code for issue in validate_statement_markdown(sample).rejects]
        assert "memory_md_html" in codes, (
            f"{form} now accepts a tag in its body, so the contract's claim "
            "that only the backtick fence body is shielded is false"
        )
