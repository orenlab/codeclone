# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Engineering Memory store identity across git worktrees.

Reds for the per-checkout store split: a linked worktree must resolve the
SAME store file as the main checkout (proven by inode via
``os.path.samefile``, not string equality), a write at the worktree root
must be readable from the main root through the real store layer, and every
fallback row of the resolution decision table must be pinned — including
the adversarial wrong-base ``commondir`` join and unmarked-directory decoys
that would otherwise be silently wrong rather than visibly degraded.

Config-sensitive cases exercise the memory layer's own surface
(``resolve_memory_application_context``) against real ``pyproject.toml``
files instead of importing config internals across the ring boundary.

Named residual holes (documented, not papered over):

- Symlinked checkouts: resolution canonicalizes through ``Path.resolve()``,
  so aliases of one tree converge; a main checkout REPLACED by a symlink to
  a different tree after resolution is not re-detected within a process.
- macOS ``/tmp`` -> ``/private/tmp`` aliasing: collapsed by ``resolve()``;
  these tests run inside pytest tmp paths and rely on that collapse.
- ``~`` inside git plumbing files is never expanded (git never writes it);
  a hand-edited ``gitdir: ~/...`` pointer degrades to
  ``git_unresolvable`` instead of guessing the home directory.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from codeclone.memory.application import (
    MemoryApplicationContext,
    resolve_memory_application_context,
)
from codeclone.memory.exceptions import MemorySchemaAuthorityError
from codeclone.memory.models import MemoryQuery
from codeclone.memory.project import compute_project_id
from codeclone.memory.schema import get_meta, open_memory_db
from codeclone.memory.schema_meta import set_meta
from codeclone.memory.sqlite_store import (
    SqliteEngineeringMemoryStore,
    migrate_memory_db_authoritative,
)
from codeclone.utils.repo_identity import (
    classify_repository_checkout,
    resolve_repository_anchor_root,
)
from tests.memory_fixtures import init_git_repo, make_module_record


def _make_committed_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    init_git_repo(path)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def _add_worktree(main_root: Path, worktree_path: Path) -> Path:
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path)],
        cwd=main_root,
        check=True,
        capture_output=True,
    )
    return worktree_path


def _mark_git_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (path / "config").write_text("[core]\n", encoding="utf-8")


def _worktree_and_main_contexts(
    tmp_path: Path,
) -> tuple[MemoryApplicationContext, MemoryApplicationContext]:
    """A linked worktree and its main checkout, each as a memory context.

    Worktree first, because every caller's subject is what the WORKTREE sees;
    the main context is the reference it gets compared against. Extracted so
    the shared-store topology is built exactly one way in this module and each
    test differs only in what it then does to the shared file.
    """
    main_root = _make_committed_repo(tmp_path / "main")
    worktree = _add_worktree(main_root, tmp_path / "wt")
    return (
        resolve_memory_application_context(worktree),
        resolve_memory_application_context(main_root),
    )


def test_repo_identity_linked_worktree_resolves_main_checkout(
    tmp_path: Path,
) -> None:
    main_root = _make_committed_repo(tmp_path / "main")
    worktree = _add_worktree(main_root, tmp_path / "wt")

    assert classify_repository_checkout(main_root) == "main_checkout"
    assert os.path.samefile(resolve_repository_anchor_root(main_root), main_root)
    assert classify_repository_checkout(worktree) == "linked_worktree"
    assert os.path.samefile(resolve_repository_anchor_root(worktree), main_root)


def test_linked_worktree_resolves_same_store_file(tmp_path: Path) -> None:
    """The red for the bug itself: both roots must resolve ONE store file.

    The proof is result-derived: the resolved paths are compared by inode
    (``os.path.samefile``), not by string equality.
    """

    worktree_context, main_context = _worktree_and_main_contexts(tmp_path)

    main_context.db_path.parent.mkdir(parents=True, exist_ok=True)
    main_context.db_path.touch()
    assert os.path.samefile(worktree_context.db_path, main_context.db_path)
    assert main_context.config.store_resolution == "main_checkout"
    assert worktree_context.config.store_resolution == "shared_main_checkout"


def test_worktree_write_visible_from_main_root_through_store_layer(
    tmp_path: Path,
) -> None:
    """Write-at-worktree -> read-at-main round trip through the real store."""

    worktree_context, main_context = _worktree_and_main_contexts(tmp_path)
    assert worktree_context.project.id == main_context.project.id

    store = SqliteEngineeringMemoryStore(worktree_context.db_path)
    try:
        store.initialize(worktree_context.project)
        record = make_module_record(
            worktree_context.project.id,
            "pkg.worktree_written",
        )
        store.write_record(record)
    finally:
        store.close()

    assert os.path.samefile(worktree_context.db_path, main_context.db_path)
    reader = SqliteEngineeringMemoryStore(main_context.db_path)
    try:
        rows = reader.query_records(MemoryQuery(project_id=main_context.project.id))
    finally:
        reader.close()
    assert any(row.statement == "pkg.worktree_written module" for row in rows)


def test_worktree_opening_a_behind_shared_store_refuses_without_mutating(
    tmp_path: Path,
) -> None:
    """The actual reference incidents (2026-09-07, 2026-09-08), reproduced
    and shown fixed.

    Both measured incidents were one checkout (a linked worktree, in both
    cases) opening the shared store -- resolved to the MAIN checkout's file
    via ``codeclone.utils.repo_identity`` -- at a schema behind its own
    code's expectation, and that open SILENTLY migrating the shared file.
    Reproducing the identical topology here (real ``git worktree``, real
    shared-store resolution, real ``SqliteEngineeringMemoryStore``) and
    proving the open now refuses instead is the closest this suite gets to
    replaying the incident itself.

    Follows the SAME journal-mode priming as
    ``_old_store_primed_through_open_memory_db`` in test_memory_schema.py:
    the shared store is put through one real ``open_memory_db`` call before
    its version is rolled back, so the byte-hash comparison below is not
    contaminated by the unrelated ``PRAGMA journal_mode=WAL`` a bare
    ``sqlite3.connect``-created file would otherwise trigger on first open.
    """
    worktree_context, main_context = _worktree_and_main_contexts(tmp_path)
    shared_db_path = worktree_context.db_path

    # Prime (creates at current version, sets WAL mode), then roll the
    # shared store back to simulate "main checkout landed code with a lower
    # schema than a sibling worktree already wrote" -- exactly the shape of
    # both reference incidents.
    open_memory_db(shared_db_path).close()
    assert os.path.samefile(worktree_context.db_path, main_context.db_path), (
        "fixture sanity: both roots must resolve the SAME physical file "
        "for this to be the incident shape"
    )
    conn = sqlite3.connect(shared_db_path)
    try:
        set_meta(conn, "schema_version", "1.7")
        conn.commit()
    finally:
        conn.close()
    before_hash = hashlib.sha256(shared_db_path.read_bytes()).hexdigest()

    # The worktree's ordinary open -- exactly what codeclone memory status,
    # codeclone setup status, and every MCP memory-retrieval tool do --
    # must refuse, not silently migrate the file every sibling checkout
    # shares.
    with pytest.raises(MemorySchemaAuthorityError):
        SqliteEngineeringMemoryStore(worktree_context.db_path)

    after_hash = hashlib.sha256(shared_db_path.read_bytes()).hexdigest()
    assert after_hash == before_hash, (
        "opening the shared store from the worktree mutated it -- this IS "
        "the reference incident, reproduced"
    )

    # The main checkout observes the identical refusal against the SAME
    # file (it is the same file, proven by inode elsewhere in this module)
    # -- the defect was never about WHICH checkout opens it, only about
    # opening implicitly migrating at all.
    with pytest.raises(MemorySchemaAuthorityError):
        SqliteEngineeringMemoryStore(main_context.db_path)

    # Recovery: an explicit authoritative migration (run once, from
    # whichever checkout) fixes it for every checkout that shares the file,
    # and afterward an ordinary open from either root works normally again.
    outcome = migrate_memory_db_authoritative(shared_db_path)
    assert outcome.migrated is True
    assert outcome.from_version == "1.7"

    worktree_reader = SqliteEngineeringMemoryStore(worktree_context.db_path)
    try:
        assert (
            get_meta(worktree_reader.connection, "schema_version")
            == ENGINEERING_MEMORY_SCHEMA_VERSION
        )
    finally:
        worktree_reader.close()
    main_reader = SqliteEngineeringMemoryStore(main_context.db_path)
    try:
        assert (
            get_meta(main_reader.connection, "schema_version")
            == ENGINEERING_MEMORY_SCHEMA_VERSION
        )
    finally:
        main_reader.close()


def test_project_id_shared_across_worktrees(tmp_path: Path) -> None:
    main_root = _make_committed_repo(tmp_path / "main")
    worktree = _add_worktree(main_root, tmp_path / "wt")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()

    assert compute_project_id(worktree) == compute_project_id(main_root)
    assert compute_project_id(unrelated) != compute_project_id(main_root)


def test_non_git_root_resolves_per_root(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()

    context = resolve_memory_application_context(root)

    assert classify_repository_checkout(root) == "no_git"
    assert os.path.samefile(resolve_repository_anchor_root(root), root)
    assert context.config.store_resolution == "per_root_no_git"
    assert (
        context.db_path
        == (root / ".codeclone" / "memory" / "engineering_memory.sqlite3").resolve()
    )


def test_explicit_config_db_path_wins_at_worktree(tmp_path: Path) -> None:
    main_root = _make_committed_repo(tmp_path / "main")
    worktree = _add_worktree(main_root, tmp_path / "wt")
    (worktree / "pyproject.toml").write_text(
        '[tool.codeclone.memory]\ndb_path = "custom/memory.sqlite3"\n',
        encoding="utf-8",
    )

    context = resolve_memory_application_context(worktree)

    assert context.config.store_resolution == "explicit_config"
    assert context.db_path == (worktree / "custom" / "memory.sqlite3").resolve()


def test_env_db_path_wins_at_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_root = _make_committed_repo(tmp_path / "main")
    worktree = _add_worktree(main_root, tmp_path / "wt")
    monkeypatch.setenv("CODECLONE_MEMORY_DB_PATH", "env_custom/memory.sqlite3")

    context = resolve_memory_application_context(worktree)

    assert context.config.store_resolution == "explicit_env"
    assert context.db_path == (worktree / "env_custom" / "memory.sqlite3").resolve()


def test_semantic_default_paths_follow_shared_store(tmp_path: Path) -> None:
    """Default semantic sidecar paths ride the shared anchor; explicit stay."""

    main_root = _make_committed_repo(tmp_path / "main")
    default_worktree = _add_worktree(main_root, tmp_path / "wt_default")
    explicit_worktree = _add_worktree(main_root, tmp_path / "wt_explicit")
    (explicit_worktree / "pyproject.toml").write_text(
        '[tool.codeclone.memory.semantic]\nindex_path = "own/index.lance"\n',
        encoding="utf-8",
    )

    default_config = resolve_memory_application_context(default_worktree).config
    explicit_config = resolve_memory_application_context(explicit_worktree).config

    main_resolved = main_root.resolve()
    assert Path(default_config.semantic.index_path) == (
        main_resolved / ".codeclone" / "memory" / "semantic_index.lance"
    )
    assert Path(default_config.semantic.embedding_cache_dir) == (
        main_resolved / ".codeclone" / "memory" / "fastembed"
    )
    assert Path(explicit_config.semantic.index_path) == (
        explicit_worktree.resolve() / "own" / "index.lance"
    )


def test_gitfile_malformed_is_git_unresolvable(tmp_path: Path) -> None:
    root = tmp_path / "broken"
    root.mkdir()
    (root / ".git").write_text("this is not a gitfile\n", encoding="utf-8")

    context = resolve_memory_application_context(root)

    assert classify_repository_checkout(root) == "git_unresolvable"
    assert os.path.samefile(resolve_repository_anchor_root(root), root)
    assert context.config.store_resolution == "per_root_git_unresolvable"
    assert (
        context.db_path
        == (root / ".codeclone" / "memory" / "engineering_memory.sqlite3").resolve()
    )


def test_gitfile_empty_pointer_is_git_unresolvable(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    (root / ".git").write_text("gitdir: \n", encoding="utf-8")

    assert classify_repository_checkout(root) == "git_unresolvable"


def test_gitfile_dangling_target_is_git_unresolvable(tmp_path: Path) -> None:
    """Worktree whose main checkout is gone: degraded, never silent."""

    root = tmp_path / "orphan"
    root.mkdir()
    (root / ".git").write_text(
        f"gitdir: {tmp_path / 'gone' / '.git' / 'worktrees' / 'orphan'}\n",
        encoding="utf-8",
    )

    assert classify_repository_checkout(root) == "git_unresolvable"


@pytest.mark.parametrize(
    "commondir_content",
    ["../../missing\n", "\n"],
    ids=["dangling_target", "empty"],
)
def test_commondir_content_failures_are_git_unresolvable(
    tmp_path: Path,
    commondir_content: str,
) -> None:
    gitdir = tmp_path / "state" / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text(commondir_content, encoding="utf-8")
    root = tmp_path / "wtroot"
    root.mkdir()
    (root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    assert classify_repository_checkout(root) == "git_unresolvable"


def test_unmarked_common_dir_is_git_unresolvable(tmp_path: Path) -> None:
    """Existing-but-unmarked ``.git`` directory is wrongness, not health.

    The joined ``commondir`` path exists and is even named ``.git``, but it
    carries no git-common plumbing markers (``HEAD`` + ``config``); the
    result witness must classify it degraded instead of accepting it.
    """

    fake_main = tmp_path / "fakemain"
    common = fake_main / ".git"
    gitdir = common / "worktrees" / "wt"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
    root = tmp_path / "wtroot"
    root.mkdir()
    (root / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

    assert classify_repository_checkout(root) == "git_unresolvable"


def test_wrong_base_commondir_join_decoy_is_not_accepted(
    tmp_path: Path,
) -> None:
    """Adversarial wrong-base pin: ``commondir`` joins against the GITDIR.

    ``commondir`` is relative (``../..``). Joined against the wrong base —
    the worktree root — it lands on an EXISTING directory that is named
    ``.git`` and even carries plumbing markers: a wrong-base resolver
    would silently adopt the decoy repository's store. The resolver must
    reach the true main checkout via the gitdir base instead.
    """

    true_main = tmp_path / "truemain"
    true_common = true_main / ".git"
    _mark_git_dir(true_common)
    true_gitdir = true_common / "worktrees" / "wt"
    true_gitdir.mkdir(parents=True)
    (true_gitdir / "commondir").write_text("../..\n", encoding="utf-8")

    decoy_root = tmp_path / "decoy"
    decoy_common = decoy_root / ".git"
    _mark_git_dir(decoy_common)
    worktree_root = decoy_common / "box" / "wtroot"
    worktree_root.mkdir(parents=True)
    (worktree_root / ".git").write_text(f"gitdir: {true_gitdir}\n", encoding="utf-8")

    anchor = resolve_repository_anchor_root(worktree_root)

    assert classify_repository_checkout(worktree_root) == "linked_worktree"
    assert os.path.samefile(anchor, true_main)
    assert not os.path.samefile(anchor, decoy_root)


def test_submodule_like_gitfile_checkout_is_own_repository(
    tmp_path: Path,
) -> None:
    """External-git-dir checkout (submodule shape) anchors per-root."""

    modules_gitdir = tmp_path / "super" / ".git" / "modules" / "sub"
    _mark_git_dir(modules_gitdir)
    root = tmp_path / "super" / "sub"
    root.mkdir(parents=True)
    (root / ".git").write_text(f"gitdir: {modules_gitdir}\n", encoding="utf-8")

    assert classify_repository_checkout(root) == "main_checkout"
    assert os.path.samefile(resolve_repository_anchor_root(root), root)


def test_external_gitdir_without_markers_is_git_unresolvable(
    tmp_path: Path,
) -> None:
    external = tmp_path / "elsewhere" / "gitstate"
    external.mkdir(parents=True)
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".git").write_text(f"gitdir: {external}\n", encoding="utf-8")

    assert classify_repository_checkout(root) == "git_unresolvable"


def test_count_approved_records_distinguishes_hollow_store(
    tmp_path: Path,
) -> None:
    """A fresh bootstrap counts 0 approved records; approval flips it."""

    main_root = _make_committed_repo(tmp_path / "main")
    context = resolve_memory_application_context(main_root)
    store = SqliteEngineeringMemoryStore(tmp_path / "memory.sqlite3")
    try:
        store.initialize(context.project)
        unapproved = make_module_record(context.project.id, "pkg.unapproved")
        store.write_record(unapproved)
        assert store.count_approved_records(project_id=context.project.id) == 0

        approved = make_module_record(context.project.id, "pkg.approved")
        approved = replace(
            approved,
            approved_by="human",
            approved_at_utc=approved.created_at_utc,
        )
        store.write_record(approved)
        assert store.count_approved_records(project_id=context.project.id) == 1
    finally:
        store.close()
