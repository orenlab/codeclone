# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import codeclone.cache.reuse as cache_reuse
import codeclone.paths.git_snapshot as git_snapshot_mod
from codeclone.cache._wire_decode import _decode_wire_file_entry
from codeclone.cache.integrity import cache_envelope_checksum
from codeclone.cache.reuse import (
    binding_context_digest,
    git_blob_identity_for_parsed_source,
    prove_cached_source_identity,
    source_content_digest,
)
from codeclone.cache.store import Cache
from codeclone.models import (
    CacheDependentPayload,
    CacheEntryV3,
    CacheNeutralPayload,
    ContentIdentityVerdict,
    DigestObject,
    FileStat,
    GitBlobIdentity,
    GitContentFallbackReason,
    GitContentSnapshot,
    GitIndexEntry,
    GitTrackedContent,
    SemanticFileFacts,
)
from codeclone.paths.git_snapshot import (
    _blob_content_digests,
    _index_mtime_ns,
    _normalize_path,
    _object_format,
    _parse_index_batch,
    _status_entries,
    _worktree_blob_ids,
    collect_git_content_snapshot,
    collect_git_workspace_snapshot,
    dirty_entry_digest,
)
from codeclone.paths.module_identity.inventory import build_module_registry


def _blob(object_id: str = "1" * 40) -> GitBlobIdentity:
    return GitBlobIdentity(object_format="sha1", object_id=object_id)


def _entry(
    raw_source: bytes,
    stat: FileStat,
    *,
    blob: GitBlobIdentity | None = None,
) -> CacheEntryV3:
    neutral_profile = DigestObject(
        domain="codeclone.cache.profile.neutral.v1",
        algorithm="sha256",
        value="2" * 64,
    )
    dependent_profile = DigestObject(
        domain="codeclone.cache.profile.dependent.v1",
        algorithm="sha256",
        value="3" * 64,
    )
    return CacheEntryV3(
        cache_content_binding_version="1",
        binding_context_digest=binding_context_digest(None),
        source_content_digest=source_content_digest(raw_source),
        git_blob_id_at_write=blob,
        stat=stat,
        module_neutral_profile=neutral_profile,
        module_dependent_profile=dependent_profile,
        module_neutral=CacheNeutralPayload(
            source_stats={"lines": 0, "functions": 0, "methods": 0, "classes": 0},
            units=(),
            blocks=(),
            segments=(),
            semantic_facts=SemanticFileFacts(),
        ),
        module_dependent=CacheDependentPayload(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=(),
            referenced_qualnames=(),
            import_names=(),
            class_names=(),
            runtime_reachability=(),
            security_surfaces=(),
            function_relationship_facts=(),
            typing_coverage=None,
            docstring_coverage=None,
            api_surface=None,
            structural_findings=None,
        ),
    )


def _assert_profile_input_misses_only_dependent_lane(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile_input: str,
    legacy_value: str,
    current_value: str,
) -> None:
    """Prove one versioned dependent-profile input misses only its own lane.

    A profile built under the input's previous value must miss the dependent
    lane while the neutral fingerprint lane still hits.
    """
    neutral_profile = cache_reuse.build_module_neutral_profile(
        fingerprint_version="2",
        min_loc=1,
        min_stmt=1,
        block_min_loc=20,
        block_min_stmt=8,
        segment_min_loc=20,
        segment_min_stmt=10,
    )
    manifest_digest = DigestObject(
        domain="codeclone.module-registry.v1",
        algorithm="sha256",
        value="3" * 64,
    )
    monkeypatch.setattr(cache_reuse, profile_input, legacy_value)
    legacy_dependent_profile = cache_reuse.build_module_dependent_profile(
        neutral_profile=neutral_profile,
        module_manifest_digest=manifest_digest,
        collect_api_surface=False,
    )
    monkeypatch.setattr(cache_reuse, profile_input, current_value)
    current_dependent_profile = cache_reuse.build_module_dependent_profile(
        neutral_profile=neutral_profile,
        module_manifest_digest=manifest_digest,
        collect_api_surface=False,
    )
    entry = replace(
        _entry(b"source", {"mtime_ns": 1, "size": 6}),
        module_neutral_profile=neutral_profile,
        module_dependent_profile=legacy_dependent_profile,
    )

    decision = cache_reuse.cache_reuse_decision(
        binding_context=entry.binding_context_digest,
        content=ContentIdentityVerdict(
            hit=True,
            reason="digest_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        ),
        entry=entry,
        neutral_profile=neutral_profile,
        dependent_profile=current_dependent_profile,
    )

    assert legacy_dependent_profile != current_dependent_profile
    assert decision.neutral.reason == "hit"
    assert decision.dependent.reason == "dependent_profile_mismatch"


def test_dependency_observation_revision_misses_only_dependent_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _assert_profile_input_misses_only_dependent_lane(
        monkeypatch,
        profile_input="_DEPENDENCY_OBSERVATION_REVISION",
        legacy_value="1",
        current_value="2",
    )


def test_liveness_policy_version_misses_only_dependent_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A liveness policy bump discards exactly the lane it changed.

    ``referenced_qualnames``, dead candidates and live-root reasons ride the
    module-dependent cache lane, and LIVENESS_POLICY_VERSION is an input of
    the dependent reuse profile. A profile built under the previous policy
    must therefore miss the dependent lane while the neutral fingerprint
    lane still hits - a warm cache can never serve a stale liveness verdict.
    """
    _assert_profile_input_misses_only_dependent_lane(
        monkeypatch,
        profile_input="LIVENESS_POLICY_VERSION",
        legacy_value="1",
        current_value="2",
    )


def _write_source_with_stat(root: Path, raw_source: bytes) -> tuple[Path, FileStat]:
    source = root / "module.py"
    source.write_bytes(raw_source)
    return source, {"mtime_ns": 1, "size": len(raw_source)}


def _snapshot(
    root: Path,
    *,
    tracked: tuple[GitTrackedContent, ...] = (),
    git_available: bool = True,
    dirty_paths: frozenset[str] = frozenset(),
    untracked_paths: frozenset[str] = frozenset(),
    index_ambiguous_paths: frozenset[str] = frozenset(),
    racy_paths: frozenset[str] = frozenset(),
) -> GitContentSnapshot:
    return GitContentSnapshot(
        root=str(root.resolve()),
        git_available=git_available,
        object_format="sha1" if git_available else None,
        tracked=tracked,
        dirty_paths=dirty_paths,
        untracked_paths=untracked_paths,
        index_ambiguous_paths=index_ambiguous_paths,
        racy_paths=racy_paths,
    )


def _snapshot_for_fallback(
    root: Path,
    reason: GitContentFallbackReason,
) -> GitContentSnapshot:
    if reason == "git_unavailable":
        return _snapshot(root, git_available=False)
    if reason == "dirty":
        return _snapshot(root, dirty_paths=frozenset({"module.py"}))
    if reason == "untracked":
        return _snapshot(root, untracked_paths=frozenset({"module.py"}))
    if reason == "racy":
        return _snapshot(root, racy_paths=frozenset({"module.py"}))
    return _snapshot(root, index_ambiguous_paths=frozenset({"module.py"}))


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_stat_mismatch_rejects_without_reading_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "module.py"
    source.write_bytes(b"before")
    entry = _entry(b"before", {"mtime_ns": 1, "size": 6})

    def _unexpected_read(_path: Path) -> bytes:
        raise AssertionError("stat mismatch must not read source bytes")

    monkeypatch.setattr(Path, "read_bytes", _unexpected_read)
    verdict = prove_cached_source_identity(
        path=source,
        entry=entry,
        current_stat={"mtime_ns": 2, "size": 6},
        git_snapshot=_snapshot(tmp_path, git_available=False),
    )

    assert verdict.hit is False
    assert verdict.reason == "stat_mismatch"
    assert verdict.stat_fast_reject is True
    assert verdict.digest_verify_cost_us == 0


def test_porcelain_parser_skips_short_rows_and_expands_renames() -> None:
    entries = _status_entries("ab\n   \n M pkg/a.py\nR  pkg/old.py -> pkg/new.py\n")

    assert entries is not None
    assert tuple(entry.path for entry in entries) == (
        "pkg/a.py",
        "pkg/new.py",
        "pkg/old.py",
    )


def test_git_path_normalization_and_invalid_porcelain_fail_closed() -> None:
    assert _normalize_path(" ./pkg\\module.py/ ") == "pkg/module.py"
    assert _normalize_path(".") == ""
    with pytest.raises(ValueError, match="path traversal"):
        _normalize_path("../outside.py")
    assert _status_entries(" M ../outside.py\n") is None


def test_git_command_helpers_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("git unavailable")

    monkeypatch.setattr(subprocess, "run", _raise_oserror)
    assert git_snapshot_mod.git_repository_available(tmp_path) is False
    assert git_snapshot_mod.git_diff_bytes(tmp_path, ["diff"]) is None


def test_workspace_snapshot_preserves_status_and_optional_digest(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    source = tmp_path / "module.py"
    source.write_bytes(b"content")

    without_digest = collect_git_workspace_snapshot(tmp_path, include_digests=False)
    with_digest = collect_git_workspace_snapshot(tmp_path, include_digests=True)

    assert without_digest.git_available is True
    assert without_digest.entries[0].path == "module.py"
    assert without_digest.entries[0].digest is None
    assert without_digest.entries[0].digest_status == "not_requested"
    assert with_digest.entries[0].digest is not None
    assert with_digest.entries[0].digest_status == "ok"


def test_workspace_snapshot_and_dirty_digest_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = collect_git_workspace_snapshot(tmp_path, include_digests=True)
    assert unavailable.git_available is False
    assert dirty_entry_digest(tmp_path, "missing.py", "??") == (
        None,
        "unavailable",
    )
    assert dirty_entry_digest(tmp_path, "../outside.py", "??") == (
        None,
        "unavailable",
    )
    monkeypatch.setattr(git_snapshot_mod, "git_diff_bytes", lambda *_args: None)
    assert dirty_entry_digest(tmp_path, "module.py", "MM") == (
        None,
        "unavailable",
    )


def test_index_and_blob_batch_parsers_are_typed_and_fail_closed(tmp_path: Path) -> None:
    object_id = "1" * 40
    valid_index = (
        f"H 100644 {object_id} 0\tmodule.py".encode()
        + b"\0ctime: 0:0\nmtime: 1:2\ndev: 0\tino: 0\n"
        + b"uid: 0\tgid: 0\nsize: 7\tflags: 0\n"
    )
    parsed = _parse_index_batch(valid_index)
    assert parsed is not None
    assert parsed[0].path == "module.py"
    assert parsed[0].mtime_ns == 1_000_000_002
    assert _parse_index_batch(b"missing-nul") is None
    assert _parse_index_batch(b"bad\0missing-debug-lines") is None
    invalid_integer = valid_index.replace(b"size: 7", b"size: nope")
    assert _parse_index_batch(invalid_integer) is None

    assert _blob_content_digests(tmp_path, []) == {}
    assert _worktree_blob_ids(tmp_path, []) == {}


def test_git_metadata_helpers_reject_unknown_and_missing_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _git_text(
        _root: Path,
        _args: object,
        *,
        timeout: int,
    ) -> str | None:
        del timeout
        return "sha256\n"

    monkeypatch.setattr(git_snapshot_mod, "_run_git_text", _git_text)
    assert _object_format(tmp_path) == "sha256"

    monkeypatch.setattr(
        git_snapshot_mod,
        "_run_git_text",
        lambda *_args, **_kwargs: "unknown\n",
    )
    assert _object_format(tmp_path) is None
    monkeypatch.setattr(
        git_snapshot_mod,
        "_run_git_text",
        lambda *_args, **_kwargs: None,
    )
    assert _index_mtime_ns(tmp_path) is None

    monkeypatch.setattr(
        git_snapshot_mod,
        "_run_git_text",
        lambda *_args, **_kwargs: ".git/index\n",
    )

    def _missing_index(_path: object) -> os.stat_result:
        raise OSError("index vanished")

    monkeypatch.setattr(os, "stat", _missing_index)
    assert _index_mtime_ns(tmp_path) is None


def test_git_batch_helpers_reject_corrupt_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_id = "1" * 40
    responses: list[bytes | None] = [
        None,
        b"missing-newline",
        f"{object_id} tree 1\nx\n".encode(),
        f"{object_id} blob 2\nx\n".encode(),
        b"\xff blob 1\nx\n",
        f"{object_id} blob nope\nx\n".encode(),
        f"{object_id} blob 1\nx\nextra".encode(),
        None,
        b"\xff\n",
        b"one\ntwo\n",
    ]

    def _git_bytes(*_args: object, **_kwargs: object) -> bytes | None:
        return responses.pop(0)

    monkeypatch.setattr(git_snapshot_mod, "_run_git_bytes", _git_bytes)
    for _case in range(7):
        assert _blob_content_digests(tmp_path, [object_id]) is None
    assert _worktree_blob_ids(tmp_path, ["module.py"]) is None
    assert _worktree_blob_ids(tmp_path, ["module.py"]) is None
    assert _worktree_blob_ids(tmp_path, ["module.py"]) is None
    assert responses == []


def test_content_snapshot_classifies_all_non_reusable_index_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = DigestObject(
        domain="codeclone.source-content.v1",
        algorithm="sha256",
        value="0" * 64,
    )

    def _index_entry(
        path: str,
        object_id: str,
        *,
        tag: str = "H",
        stage: int = 0,
        mtime_ns: int = 1,
        flags: int = 0,
    ) -> GitIndexEntry:
        return GitIndexEntry(
            tag=tag,
            mode="100644",
            object_id=object_id,
            stage=stage,
            path=path,
            mtime_ns=mtime_ns,
            size=1,
            flags=flags,
        )

    entries = (
        _index_entry("special.py", "1" * 40, stage=1),
        _index_entry("dirty.py", "2" * 40),
        _index_entry("untracked.py", "3" * 40),
        _index_entry("racy.py", "4" * 40, mtime_ns=100),
        _index_entry("mismatch.py", "5" * 40),
        _index_entry("missing-digest.py", "6" * 40),
        _index_entry("invalid-blob.py", "bad"),
        _index_entry("valid.py", "7" * 40),
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "git_repository_available",
        lambda _root: True,
    )
    monkeypatch.setattr(git_snapshot_mod, "_object_format", lambda _root: "sha1")
    monkeypatch.setattr(git_snapshot_mod, "_index_mtime_ns", lambda _root: 100)
    monkeypatch.setattr(
        git_snapshot_mod,
        "_run_git_text",
        lambda *_args, **_kwargs: " M dirty.py\n?? untracked.py\n",
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "_run_git_bytes",
        lambda *_args, **_kwargs: b"",
    )
    monkeypatch.setattr(git_snapshot_mod, "_parse_index_batch", lambda _output: entries)
    monkeypatch.setattr(
        git_snapshot_mod,
        "_worktree_blob_ids",
        lambda _root, _paths: {
            "mismatch.py": "8" * 40,
            "missing-digest.py": "6" * 40,
            "invalid-blob.py": "bad",
            "valid.py": "7" * 40,
        },
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "_blob_content_digests",
        lambda _root, _ids: {"bad": digest, "7" * 40: digest},
    )

    snapshot = collect_git_content_snapshot(
        tmp_path,
        [str(tmp_path.parent / "outside.py"), *(entry.path for entry in entries)],
    )

    assert snapshot.dirty_paths == frozenset({"dirty.py", "mismatch.py"})
    assert snapshot.untracked_paths == frozenset({"untracked.py"})
    assert snapshot.racy_paths == frozenset({"racy.py"})
    assert snapshot.index_ambiguous_paths == frozenset(
        {"special.py", "missing-digest.py", "invalid-blob.py"}
    )
    assert tuple(item.path for item in snapshot.tracked) == ("valid.py",)


def test_content_snapshot_fails_closed_at_each_batched_git_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = GitIndexEntry(
        tag="H",
        mode="100644",
        object_id="1" * 40,
        stage=0,
        path="module.py",
        mtime_ns=1,
        size=1,
        flags=0,
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "git_repository_available",
        lambda _root: True,
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "_run_git_text",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "_run_git_bytes",
        lambda *_args, **_kwargs: b"",
    )
    monkeypatch.setattr(git_snapshot_mod, "_index_mtime_ns", lambda _root: 100)

    monkeypatch.setattr(git_snapshot_mod, "_object_format", lambda _root: None)
    assert collect_git_content_snapshot(tmp_path, ["module.py"]).git_available is False

    monkeypatch.setattr(git_snapshot_mod, "_object_format", lambda _root: "sha1")
    monkeypatch.setattr(git_snapshot_mod, "_parse_index_batch", lambda _output: None)
    assert collect_git_content_snapshot(tmp_path, ["module.py"]).git_available is False

    monkeypatch.setattr(
        git_snapshot_mod,
        "_parse_index_batch",
        lambda _output: (entry,),
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "_worktree_blob_ids",
        lambda _root, _paths: None,
    )
    assert collect_git_content_snapshot(tmp_path, ["module.py"]).git_available is False

    monkeypatch.setattr(
        git_snapshot_mod,
        "_worktree_blob_ids",
        lambda _root, _paths: {"module.py": "1" * 40},
    )
    monkeypatch.setattr(
        git_snapshot_mod,
        "_blob_content_digests",
        lambda _root, _ids: None,
    )
    assert collect_git_content_snapshot(tmp_path, ["module.py"]).git_available is False


def test_clean_repository_snapshot_proves_blob_and_source_digest(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    source = tmp_path / "module.py"
    raw_source = b"def example():\n    return 1\n"
    source.write_bytes(raw_source)
    _git(tmp_path, "add", "module.py")
    _git(
        tmp_path,
        "-c",
        "user.name=CodeClone Test",
        "-c",
        "user.email=codeclone@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    index = tmp_path / ".git" / "index"
    old_ns = index.stat().st_mtime_ns - 2_000_000_000
    os.utime(source, ns=(old_ns, old_ns))

    snapshot = collect_git_content_snapshot(tmp_path, [str(source)])
    tracked = snapshot.tracked_content(source)

    assert snapshot.git_available is True
    assert snapshot.object_format == "sha1"
    assert snapshot.fallback_reason(source) is None
    assert tracked is not None
    assert tracked.source_content_digest == source_content_digest(raw_source)
    assert tracked.blob.object_id == _git(tmp_path, "rev-parse", "HEAD:module.py")


def test_clean_matching_blob_hits_without_python_source_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_source = b"def example():\n    return 1\n"
    source, stat = _write_source_with_stat(tmp_path, raw_source)
    blob = _blob()
    digest = source_content_digest(raw_source)
    snapshot = _snapshot(
        tmp_path,
        tracked=(
            GitTrackedContent(
                path="module.py",
                blob=blob,
                source_content_digest=digest,
            ),
        ),
    )

    def _unexpected_read(_path: Path) -> bytes:
        raise AssertionError("matching blob proof must not read through pathlib")

    monkeypatch.setattr(Path, "read_bytes", _unexpected_read)
    verdict = prove_cached_source_identity(
        path=source,
        entry=_entry(raw_source, stat, blob=blob),
        current_stat=stat,
        git_snapshot=snapshot,
    )

    assert verdict.hit is True
    assert verdict.reason == "blob_hit"
    assert verdict.git_fallback_reason is None


def test_blob_write_identity_requires_the_digest_of_parsed_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "module.py"
    source.write_bytes(b"current")
    tracked = GitTrackedContent(
        path="module.py",
        blob=_blob(),
        source_content_digest=source_content_digest(b"different"),
    )

    assert (
        git_blob_identity_for_parsed_source(
            path=source,
            source_digest=source_content_digest(b"current"),
            git_snapshot=_snapshot(tmp_path, tracked=(tracked,)),
        )
        is None
    )


def test_digest_fallback_fails_closed_when_source_disappears(tmp_path: Path) -> None:
    source = tmp_path / "missing.py"
    stat: FileStat = {"mtime_ns": 1, "size": 7}

    verdict = prove_cached_source_identity(
        path=source,
        entry=_entry(b"missing", stat),
        current_stat=stat,
        git_snapshot=_snapshot(tmp_path, git_available=False),
    )

    assert verdict.hit is False
    assert verdict.reason == "digest_miss"


@pytest.mark.parametrize(
    "fallback_reason",
    [
        "git_unavailable",
        "dirty",
        "untracked",
        "racy",
        "index_ambiguous",
    ],
)
def test_fallback_paths_use_current_digest(
    tmp_path: Path,
    fallback_reason: GitContentFallbackReason,
) -> None:
    raw_source = b"content"
    source, stat = _write_source_with_stat(tmp_path, raw_source)
    snapshot = _snapshot_for_fallback(tmp_path, fallback_reason)

    verdict = prove_cached_source_identity(
        path=source,
        entry=_entry(raw_source, stat),
        current_stat=stat,
        git_snapshot=snapshot,
    )

    assert verdict.hit is True
    assert verdict.reason == "digest_hit"
    assert verdict.git_fallback_reason == fallback_reason
    assert verdict.stat_fast_reject is False


def test_same_size_mtime_preserved_mutation_is_not_a_hit(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_bytes(b"before")
    stat: FileStat = {"mtime_ns": 123, "size": 6}
    entry = _entry(b"before", stat)
    source.write_bytes(b"after!")

    verdict = prove_cached_source_identity(
        path=source,
        entry=entry,
        current_stat=stat,
        git_snapshot=_snapshot(tmp_path, git_available=False),
    )

    assert verdict.hit is False
    assert verdict.reason == "digest_miss"


def test_batched_git_blob_proof_catches_stat_preserving_mutation(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-q")
    source = tmp_path / "module.py"
    source.write_bytes(b"before")
    old_ns = 946_684_800_000_000_000
    os.utime(source, ns=(old_ns, old_ns))
    _git(tmp_path, "add", "module.py")
    _git(
        tmp_path,
        "-c",
        "user.name=CodeClone Test",
        "-c",
        "user.email=codeclone@example.invalid",
        "commit",
        "-qm",
        "fixture",
    )
    object_id = _git(tmp_path, "rev-parse", "HEAD:module.py")
    stat: FileStat = {"mtime_ns": old_ns, "size": 6}
    entry = _entry(b"before", stat, blob=_blob(object_id))

    source.write_bytes(b"after!")
    os.utime(source, ns=(old_ns, old_ns))
    snapshot = collect_git_content_snapshot(tmp_path, [str(source)])
    verdict = prove_cached_source_identity(
        path=source,
        entry=entry,
        current_stat=stat,
        git_snapshot=snapshot,
    )

    assert snapshot.fallback_reason(source) == "dirty"
    assert verdict.hit is False
    assert verdict.reason == "digest_miss"


def test_dirty_source_write_never_persists_blob_identity(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    raw_source = b"content"
    source.write_bytes(raw_source)
    digest = source_content_digest(raw_source)
    blob = _blob()
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    cache.bind_module_registry(
        build_module_registry(root=tmp_path, source_roots=(".",))
    )
    cache.bind_git_content_snapshot(
        _snapshot(
            tmp_path,
            tracked=(
                GitTrackedContent(
                    path="module.py",
                    blob=blob,
                    source_content_digest=digest,
                ),
            ),
            dirty_paths=frozenset({"module.py"}),
        )
    )
    cache.put_file_entry(
        str(source),
        {"mtime_ns": 1, "size": len(raw_source)},
        [],
        [],
        [],
        source_content_digest=digest,
    )

    entry = cache.get_file_entry(str(source))
    assert entry is not None
    assert entry.git_blob_id_at_write is None


def test_signed_envelope_without_content_binding_cannot_authorize_hit(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": {"module.py": {"st": [1, 2]}},
    }
    cache_path.write_text(
        json.dumps(
            {
                "v": Cache._CACHE_VERSION,
                "payload": payload,
                # Envelope sig over {v, payload} so the sig gate passes and the
                # missing-content-binding gate is what this still exercises.
                "checksum": cache_envelope_checksum(Cache._CACHE_VERSION, payload),
            }
        ),
        "utf-8",
    )

    cache.load()

    assert cache.load_warning == "Cache format invalid; ignoring cache."
    assert cache.get_file_entry("module.py") is None
    assert _decode_wire_file_entry({"st": [1, 2]}, "module.py") is None
