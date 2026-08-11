# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Staleness ownership: which subject witnesses freshness for which record kind.

A record kind declares its own staleness owner. A single global subject-kind
priority cannot serve every kind at once: ``document_link`` asserts that a
document *contains a reference*, so editing the referenced file does not
falsify it, while a ``risk_note`` about a code file is falsified by exactly
that edit. These tests pin the per-kind contract and keep the two questions
apart -- "the owner changed" and "the reference no longer resolves" are
different facts and must never share one fingerprint.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path

import pytest

from codeclone.memory import staleness as staleness_module
from codeclone.memory.enums import (
    MEMORY_RECORD_TYPE_VALUES,
    MemoryRecordType,
    SubjectKind,
    SubjectRelation,
)
from codeclone.memory.identity import make_identity_key
from codeclone.memory.ingest import extractors as extractors_module
from codeclone.memory.ingest.extractors import extract_contradictions
from codeclone.memory.models import (
    MemoryRecord,
    MemorySubject,
    RecordBatch,
    generate_memory_id,
)
from codeclone.memory.ownership import (
    FILE_BACKED_SUBJECT_KINDS,
    RECORD_STALENESS_OWNERSHIP,
    STALE_REASONS,
    owner_subject_kinds_for,
    reference_subject_kinds_for,
    witness_kind_for,
)
from codeclone.memory.project import (
    GitProvenance,
    resolve_project_identity,
    subject_fingerprint_for_subject,
)
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.memory.staleness import apply_refresh_staleness, apply_scope_staleness
from tests.memory_fixtures import memory_store

DOC_REL = "docs/guide.md"
TARGET_REL = "pkg/target.py"
# Fixed rather than read from the clock: these records are compared by
# fingerprint, and a timestamp helper would drag a higher ring into this module.
NOW = "2026-01-01T00:00:00Z"


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _seed_tree(root: Path) -> tuple[Path, Path]:
    """A document that references a code file, and that code file."""

    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    doc = root / DOC_REL
    doc.write_text(f"# Guide\n\nSee `{TARGET_REL}` for details.\n", encoding="utf-8")
    target = root / TARGET_REL
    target.write_text("VALUE = 1\n", encoding="utf-8")
    return doc, target


def _record(
    project_id: str,
    record_type: MemoryRecordType,
    *,
    code_fingerprint: str,
    discriminator: str = "reference",
) -> MemoryRecord:
    now = NOW
    return MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type=record_type,
            subject_kind="doc",
            subject_key=DOC_REL,
            discriminator=discriminator,
        ),
        type=record_type,
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="doc",
        statement=f"{DOC_REL} references {TARGET_REL}.",
        summary=None,
        payload={"doc_file": DOC_REL},
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=code_fingerprint,
        stale_reason=None,
        created_on_branch="main",
        created_at_commit="commit-abc",
        verified_on_branch="main",
        verified_at_commit="commit-abc",
    )


def _write_with_subjects(
    store: SqliteEngineeringMemoryStore,
    record: MemoryRecord,
) -> None:
    """Persist a record carrying both a document and a code-file subject."""

    store.upsert_record(record)
    pairs: tuple[tuple[SubjectKind, str, SubjectRelation], ...] = (
        ("doc", DOC_REL, "documents"),
        ("path", TARGET_REL, "about"),
    )
    for subject_kind, subject_key, relation in pairs:
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind=subject_kind,
                subject_key=subject_key,
                relation=relation,
            )
        )


def test_document_link_is_owned_by_its_document_not_by_the_target(
    tmp_path: Path,
) -> None:
    """Nothing edited at all must not produce staleness.

    The ingest writes the *document* fingerprint, so a refresh that witnesses
    the *target* compares two unrelated files and can never agree.
    """

    with memory_store(tmp_path) as (root, project, store, _db_path):
        doc, _target = _seed_tree(root)
        record = _record(project.id, "document_link", code_fingerprint=_sha1(doc))
        _write_with_subjects(store, record)

        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[record]),
            report_document={},
            root_path=root,
        )

        loaded = store.find_by_identity_key(project.id, record.identity_key)
        assert loaded is not None
        assert loaded.status == "active", (
            f"nothing was edited, yet the record became "
            f"{loaded.status}/{loaded.stale_reason}"
        )


def test_code_note_is_owned_by_its_code_file_not_by_the_mentioning_document(
    tmp_path: Path,
) -> None:
    """The opposite side of the same contract.

    A note *about code* is witnessed by the code file even when a document
    subject sits alongside it -- the mirror of ``document_link``, and the
    reason one global order cannot serve both.
    """

    with memory_store(tmp_path) as (root, project, store, _db_path):
        _doc, target = _seed_tree(root)
        record = _record(project.id, "risk_note", code_fingerprint=_sha1(target))
        _write_with_subjects(store, record)

        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[record]),
            report_document={},
            root_path=root,
        )

        loaded = store.find_by_identity_key(project.id, record.identity_key)
        assert loaded is not None
        assert loaded.status == "active", (
            f"code note lost its own witness: {loaded.status}/{loaded.stale_reason}"
        )


def test_owner_depends_on_record_kind_not_on_a_global_priority(
    tmp_path: Path,
) -> None:
    """One global subject-kind order cannot serve two kinds at once.

    Both records carry the same ``(doc, path)`` subject pair. The link is
    owned by the document, the risk note by the code file; each is anchored on
    its own owner, so neither may go stale while the tree is untouched.
    """

    with memory_store(tmp_path) as (root, project, store, _db_path):
        doc, target = _seed_tree(root)
        link = _record(
            project.id,
            "document_link",
            code_fingerprint=_sha1(doc),
            discriminator="link",
        )
        code_note = _record(
            project.id,
            "risk_note",
            code_fingerprint=_sha1(target),
            discriminator="code",
        )
        _write_with_subjects(store, link)
        _write_with_subjects(store, code_note)

        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[link, code_note]),
            report_document={},
            root_path=root,
        )

        loaded_link = store.find_by_identity_key(project.id, link.identity_key)
        loaded_code = store.find_by_identity_key(project.id, code_note.identity_key)
        assert loaded_link is not None
        assert loaded_code is not None
        assert (loaded_link.status, loaded_code.status) == ("active", "active"), (
            f"document_link={loaded_link.status}/{loaded_link.stale_reason} "
            f"risk_note={loaded_code.status}/{loaded_code.stale_reason}"
        )


def test_vanished_reference_is_not_reported_as_fingerprint_drift(
    tmp_path: Path,
) -> None:
    """A deleted target changes resolvability, not the document's content.

    The document still exists and still contains the reference, so the record
    must not become ``historical`` and must not borrow the drift reason.
    """

    with memory_store(tmp_path) as (root, project, store, _db_path):
        doc, target = _seed_tree(root)
        record = _record(project.id, "document_link", code_fingerprint=_sha1(doc))
        _write_with_subjects(store, record)
        target.unlink()

        report = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[record]),
            report_document={},
            root_path=root,
        )

        loaded = store.find_by_identity_key(project.id, record.identity_key)
        assert loaded is not None
        assert loaded.status != "historical"
        assert loaded.stale_reason == "reference_unresolved", (
            f"got {loaded.status}/{loaded.stale_reason}"
        )
        assert report.reasons.get("reference_unresolved") == 1


def test_reference_resolution_branch_is_reachable_and_not_always_on(
    tmp_path: Path,
) -> None:
    """Some input reaches the new branch, and some input does not trip it.

    A guard no input can reach is theater; a guard every input trips is noise.
    """

    with memory_store(tmp_path) as (root, project, store, _db_path):
        doc, target = _seed_tree(root)
        intact = _record(
            project.id,
            "document_link",
            code_fingerprint=_sha1(doc),
            discriminator="intact",
        )
        _write_with_subjects(store, intact)

        untouched = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[intact]),
            report_document={},
            root_path=root,
        )
        assert "reference_unresolved" not in untouched.reasons

        target.unlink()
        after_delete = apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[intact]),
            report_document={},
            root_path=root,
        )
        assert after_delete.reasons.get("reference_unresolved") == 1


def test_scope_change_to_the_target_does_not_stale_the_document_link(
    tmp_path: Path,
) -> None:
    """Editing the referenced file does not falsify "this document links here"."""

    with memory_store(tmp_path) as (root, project, store, _db_path):
        doc, _target = _seed_tree(root)
        record = _record(project.id, "document_link", code_fingerprint=_sha1(doc))
        _write_with_subjects(store, record)

        apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=[TARGET_REL],
        )

        loaded = store.find_by_identity_key(project.id, record.identity_key)
        assert loaded is not None
        assert loaded.status == "active", (
            f"target edit leaked into the document's record: "
            f"{loaded.status}/{loaded.stale_reason}"
        )


def test_scope_change_to_the_document_does_stale_the_document_link(
    tmp_path: Path,
) -> None:
    """The owner-aware scope filter still fires for the owner's own file."""

    with memory_store(tmp_path) as (root, project, store, _db_path):
        doc, _target = _seed_tree(root)
        record = _record(project.id, "document_link", code_fingerprint=_sha1(doc))
        _write_with_subjects(store, record)

        apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=[DOC_REL],
        )

        loaded = store.find_by_identity_key(project.id, record.identity_key)
        assert loaded is not None
        assert loaded.status == "stale"
        assert loaded.stale_reason == "scope_files_changed"


def test_contradiction_note_is_fingerprinted_from_the_document_it_is_about(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write side and read side must anchor on the same subject.

    A ``contradiction_note`` carries a ``doc`` subject, so storing an analysis
    digest in ``code_fingerprint`` guarantees a mismatch the moment the record
    is approved and the refresh starts witnessing it.
    """

    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    snapshot = root / "snapshot.json"
    snapshot.write_text('{"tools": {"a": {}, "b": {}}}', encoding="utf-8")
    doc = root / "docs" / "tools.md"
    doc.write_text("# Tools\n\nCodeClone exposes 5 MCP tools.\n", encoding="utf-8")

    # Point the extractor straight at the fixture files. Resolving them through
    # config is a separate concern and would pull a higher ring into this
    # module; what is under test is which subject the fingerprint comes from.
    monkeypatch.setattr(
        extractors_module,
        "resolve_mcp_tool_contradiction_sources",
        lambda **_kwargs: (snapshot, (doc,)),
    )

    project = resolve_project_identity(root)
    batch = extract_contradictions(
        project=project,
        root_path=root,
        git=GitProvenance(
            remote=None, branch="main", head="commit-abc", available=True
        ),
        report_digest=None,
        analysis_fingerprint="analysis-digest-not-a-file-hash",
    )

    assert batch.records, "expected a tool-count contradiction record"
    assert batch.records[0].code_fingerprint == _sha1(doc)


def test_every_record_kind_declares_its_staleness_owner() -> None:
    """A kind missing from the table has no witness and fails closed silently."""

    assert set(MEMORY_RECORD_TYPE_VALUES) == set(RECORD_STALENESS_OWNERSHIP)


def test_declared_owner_and_reference_kinds_can_actually_be_witnessed() -> None:
    """Every declared subject kind must be one we can resolve to a file.

    Declaring an owner whose kind carries no fingerprint would leave the kind
    unwitnessed while looking governed.
    """

    for record_type in RECORD_STALENESS_OWNERSHIP:
        declared = set(owner_subject_kinds_for(record_type)) | set(
            reference_subject_kinds_for(record_type)
        )
        assert declared, f"{record_type} declares no subject kinds"
        assert declared <= set(FILE_BACKED_SUBJECT_KINDS), record_type


def test_declared_witness_kind_matches_the_declared_owner() -> None:
    """The witness kind is a claim about the owner, so it must follow it.

    Left free-floating it would be an unexecuted comment that quietly rots
    away from the ownership it describes.
    """

    witness_for_lead = {"doc": "document_content", "test": "test_content"}
    for record_type in RECORD_STALENESS_OWNERSHIP:
        owners = owner_subject_kinds_for(record_type)
        assert owners, record_type
        expected = witness_for_lead.get(owners[0], "code_content")
        assert witness_kind_for(record_type) == expected, (
            f"{record_type} leads with {owners[0]} but claims "
            f"witness {witness_kind_for(record_type)}"
        )


def test_file_backed_kinds_agree_with_the_fingerprint_provider(tmp_path: Path) -> None:
    """The kinds we call file-backed are exactly those that yield a fingerprint."""

    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")

    keys = {"path": "pkg/mod.py", "test": "pkg/mod.py", "doc": "pkg/mod.py"}
    for kind in FILE_BACKED_SUBJECT_KINDS:
        subject = MemorySubject(
            id="s",
            memory_id="m",
            subject_kind=kind,
            subject_key=keys.get(kind, "pkg"),
            relation="about",
        )
        assert subject_fingerprint_for_subject(root, subject) is not None, kind


def test_stale_reasons_are_declared_constants_not_bare_literals() -> None:
    """No reason may be written as an inline string at its call site.

    The vocabulary used to exist only as scattered literals, so the full set
    was unknowable without grepping and each new one arrived invisibly.
    """

    source = Path(inspect.getfile(staleness_module)).read_text(encoding="utf-8")
    literals = [
        str(argument.value)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mark_stale"
        for argument in node.args[1:2]
        if isinstance(argument, ast.Constant)
    ]
    assert literals == [], f"undeclared inline stale reasons: {literals}"


def test_every_written_stale_reason_belongs_to_the_declared_vocabulary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever the machinery writes must be a member of the declared set."""

    captured: list[str] = []
    original = SqliteEngineeringMemoryStore.mark_stale

    def spy(
        self: SqliteEngineeringMemoryStore,
        record_id: str,
        reason: str,
        *,
        commit: bool = True,
    ) -> None:
        captured.append(reason)
        original(self, record_id, reason, commit=commit)

    monkeypatch.setattr(SqliteEngineeringMemoryStore, "mark_stale", spy)

    with memory_store(tmp_path) as (root, project, store, _db_path):
        doc, target = _seed_tree(root)

        # A dropped reference.
        vanished = _record(
            project.id,
            "document_link",
            code_fingerprint=_sha1(doc),
            discriminator="vanished",
        )
        _write_with_subjects(store, vanished)
        target.unlink()
        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[vanished]),
            report_document={},
            root_path=root,
        )

        # A system record the refresh no longer produces.
        orphan = _record(
            project.id,
            "document_link",
            code_fingerprint=_sha1(doc),
            discriminator="orphan",
        )
        store.upsert_record(orphan)
        apply_refresh_staleness(
            store,
            project_id=project.id,
            batch=RecordBatch(records=[]),
            report_document={},
            root_path=root,
        )

        # An owner edited by an accepted patch. Needs a still-active record:
        # scope staleness only considers records that have not already lapsed.
        scoped = _record(
            project.id,
            "document_link",
            code_fingerprint=_sha1(doc),
            discriminator="scoped",
        )
        _write_with_subjects(store, scoped)
        apply_scope_staleness(
            store,
            project_id=project.id,
            changed_paths=[DOC_REL],
        )

    assert len(set(captured)) >= 3, f"too few distinct reasons exercised: {captured}"
    assert set(captured) <= STALE_REASONS, (
        f"undeclared: {set(captured) - STALE_REASONS}"
    )
