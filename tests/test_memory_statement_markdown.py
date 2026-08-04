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

from pathlib import Path
from typing import cast

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
        assert len(candidates) >= 3, "expected scope + claims + proposal"
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
