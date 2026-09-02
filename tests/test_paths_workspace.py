# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.paths.workspace import (
    WORKSPACE_DIR_NAME,
    default_cache_path,
    emit_legacy_workspace_warnings,
    is_service_path,
    legacy_home_cache_path,
    legacy_repo_workspace_dir,
    legacy_repo_workspace_has_artifacts,
    repo_workspace_dir,
    service_directories,
    workspace_glob_patterns,
)
from codeclone.surfaces.cli.console import PlainConsole


def test_default_cache_path_under_codeclone_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert default_cache_path(root) == root / ".codeclone" / "db" / "cache.sqlite3"


def test_legacy_repo_workspace_has_artifacts_detects_entries(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    legacy = legacy_repo_workspace_dir(root)
    legacy.mkdir(parents=True)
    (legacy / "cache.json").write_text("{}", encoding="utf-8")
    assert legacy_repo_workspace_has_artifacts(root) is True


def test_legacy_repo_workspace_has_artifacts_false_when_missing(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert legacy_repo_workspace_has_artifacts(root) is False


def test_repo_workspace_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    assert repo_workspace_dir(root) == root / ".codeclone"


def test_legacy_repo_workspace_has_artifacts_treats_iterdir_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    legacy = legacy_repo_workspace_dir(root)
    legacy.mkdir(parents=True)
    (legacy / "marker").write_text("x", encoding="utf-8")
    real_iterdir = Path.iterdir

    def _iterdir(self: Path) -> object:
        if self == legacy:
            raise OSError("permission denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _iterdir)
    assert legacy_repo_workspace_has_artifacts(root) is False


def test_workspace_glob_patterns_includes_legacy_and_new_globs() -> None:
    patterns = workspace_glob_patterns()
    assert ".codeclone/**" in patterns
    assert ".cache/codeclone/**" in patterns


def test_legacy_home_cache_path_expands_user() -> None:
    path = legacy_home_cache_path()
    assert path.name == "cache.json"
    assert "codeclone" in path.as_posix()


def test_emit_legacy_home_cache_warning_when_paths_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    legacy_home = tmp_path / "legacy-home-cache.json"
    legacy_home.write_text("{}", encoding="utf-8")
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=default_cache_path(root),
        legacy_home_cache_path=legacy_home,
        console=PlainConsole(),
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" in out
    assert str(legacy_home) in out


def test_emit_legacy_home_cache_skipped_when_resolved_matches_project_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    cache_path = default_cache_path(root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{}", encoding="utf-8")
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=cache_path,
        legacy_home_cache_path=cache_path,
        console=PlainConsole(),
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" not in out


def test_emit_legacy_home_cache_resolve_oserror_still_warns(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    cache_path = default_cache_path(root)
    legacy_home = tmp_path / "legacy-cache.json"
    legacy_home.write_text("{}", encoding="utf-8")
    real_resolve = Path.resolve

    def _resolve(self: Path, strict: bool = False) -> Path:
        if self == legacy_home:
            raise OSError("nope")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve)
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=cache_path,
        legacy_home_cache_path=legacy_home,
        console=PlainConsole(),
    )
    out = capsys.readouterr().out
    assert "Legacy cache file found at" in out


def test_emit_legacy_repo_workspace_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    legacy = legacy_repo_workspace_dir(root)
    legacy.mkdir(parents=True)
    (legacy / "cache.json").write_text("{}", encoding="utf-8")
    emit_legacy_workspace_warnings(
        root_path=root,
        cache_path=default_cache_path(root),
        legacy_home_cache_path=tmp_path / "missing-home-cache.json",
        console=PlainConsole(),
    )
    captured = capsys.readouterr()
    out = captured.out
    assert ".cache/codeclone/" in out
    assert str(legacy) in out
    assert str(repo_workspace_dir(root)) in out


def test_service_directories_are_the_three_codeclone_owns(tmp_path: Path) -> None:
    """The containment boundary is a set of directories, not "inside the repo".

    ``~/.cache/codeclone`` is outside every repository and is still CodeClone's
    own; the repository's ``build/`` is inside one and is not. Asserting the
    membership rule rather than a literal list keeps the pin alive when a
    fourth directory joins.
    """

    root = (tmp_path / "repo").resolve()
    directories = service_directories(root)

    assert repo_workspace_dir(root).resolve() in directories
    assert legacy_repo_workspace_dir(root).resolve() in directories
    assert legacy_home_cache_path().parent.resolve() in directories
    assert root.resolve() not in directories


@pytest.mark.parametrize(
    ("relative", "contained"),
    [
        (".codeclone/db/cache.sqlite3", True),
        (".codeclone/intents/agent.json", True),
        (".cache/codeclone/cache.json", True),
        ("build/cc-cache.sqlite3", False),
        ("cache.sqlite3", False),
        ("codeclone.baseline.json", False),
        ("src/module.py", False),
    ],
)
def test_is_service_path_admits_only_codeclone_service_state(
    tmp_path: Path, relative: str, contained: bool
) -> None:
    """Both verdicts on one root, so a predicate wired to a constant fails."""

    root = (tmp_path / "repo").resolve()
    assert is_service_path(root / relative, root=root) is contained


def test_is_service_path_admits_the_per_user_cache_dir(tmp_path: Path) -> None:
    """Outside the repository and still CodeClone's own."""

    root = (tmp_path / "repo").resolve()
    assert is_service_path(legacy_home_cache_path(), root=root) is True


def test_is_service_path_refuses_a_traversal_back_out_of_the_workspace(
    tmp_path: Path,
) -> None:
    """``.codeclone`` as a prefix is not containment; the path is resolved."""

    root = (tmp_path / "repo").resolve()
    escape = root / ".codeclone" / ".." / ".." / "elsewhere" / "cache.sqlite3"
    assert is_service_path(escape, root=root) is False
    assert is_service_path(tmp_path / ".codeclone-not-ours", root=root) is False


def test_is_service_path_admits_a_root_reached_through_a_symlink(
    tmp_path: Path,
) -> None:
    """A symlinked checkout must still be allowed to write its own cache.

    The queried path is resolved, so the directories it is held against have to
    be resolved too. Compare a resolved path with an unresolved prefix and the
    predicate refuses CodeClone's *own* store: the cold-forever defect this
    boundary exists to remove, walking back in through a symlink, and silently,
    because that refusal is a warning rather than an error.

    Not hypothetical: macOS ``/tmp`` is a symlink, and so is any checkout
    reached through one.
    """

    real = tmp_path / "checkout"
    (real / WORKSPACE_DIR_NAME / "db").mkdir(parents=True)
    linked_root = tmp_path / "link-to-checkout"
    linked_root.symlink_to(real, target_is_directory=True)
    store = linked_root / WORKSPACE_DIR_NAME / "db" / "cache.sqlite3"

    # Population: without a symlink actually in the path this asserts nothing.
    assert store.resolve() != store, "the fixture built no symlink to traverse"
    assert is_service_path(store, root=linked_root) is True


def test_is_service_path_admits_a_workspace_relocated_behind_a_symlink(
    tmp_path: Path,
) -> None:
    """The same failure, on the root the MCP surface actually passes.

    ``_resolve_root`` hands every analysis an already-resolved root, so a
    symlinked *root* cannot reach the predicate through ``analyze_repository``.
    A symlinked ``.codeclone`` under a resolved root can, and does: an operator
    who parks workspace state on another volume gets a store CodeClone refuses
    to write. This is the input that proves the resolved-directory side of the
    predicate is reachable in production, not only in a probe.
    """

    root = (tmp_path / "checkout").resolve()
    root.mkdir()
    storage = tmp_path / "state"
    (storage / "db").mkdir(parents=True)
    (root / WORKSPACE_DIR_NAME).symlink_to(storage, target_is_directory=True)
    store = root / WORKSPACE_DIR_NAME / "db" / "cache.sqlite3"

    assert root.resolve() == root, "the root must be resolved, as the surface passes it"
    assert store.resolve() != store, "the fixture built no symlink to traverse"
    assert is_service_path(store, root=root) is True


def test_is_service_path_refuses_a_symlink_pointing_out_of_the_workspace(
    tmp_path: Path,
) -> None:
    """Escaping by symlink, which is not the same escape as ``..``.

    ``..`` collapses under any lexical normalisation, so the traversal test
    above stays green even if the queried path were normalised textually rather
    than resolved. A symlink out of the workspace survives that normalisation
    and is caught only by real resolution -- so this pins that the queried side
    is resolved physically, which its sibling cannot.
    """

    root = (tmp_path / "checkout").resolve()
    workspace = root / WORKSPACE_DIR_NAME
    workspace.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    target = workspace / "escape" / "cache.sqlite3"

    assert target.resolve() != target, "the fixture built no symlink to traverse"
    assert is_service_path(target, root=root) is False
