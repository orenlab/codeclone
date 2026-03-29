# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from pathlib import Path

import pytest

import codeclone.scanner as scanner
from codeclone.errors import ValidationError
from codeclone.scanner import iter_py_files, module_name_from_path


def _symlink_or_skip(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not supported on this platform")
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this environment")


def _configure_fake_tempdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_temp = tmp_path / "fake_tmp"
    fake_temp.mkdir()
    monkeypatch.setattr(scanner, "_get_tempdir", lambda: fake_temp.resolve())
    return fake_temp


def test_iter_py_files_in_temp(tmp_path: Path) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    files = list(iter_py_files(str(tmp_path)))
    assert str(src) in files


def test_iter_py_files_excludes(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    good = pkg / "good.py"
    good.write_text("x = 1\n", "utf-8")
    skip_dir = pkg / "__pycache__"
    skip_dir.mkdir()
    skip = skip_dir / "bad.py"
    skip.write_text("x = 2\n", "utf-8")

    files = list(iter_py_files(str(tmp_path)))
    assert str(good) in files
    assert str(skip) not in files


def test_iter_py_files_deterministic_sorted_order(tmp_path: Path) -> None:
    z_file = tmp_path / "z.py"
    z_file.write_text("z = 1\n", "utf-8")
    a_dir = tmp_path / "pkg"
    a_dir.mkdir()
    a_file = a_dir / "a.py"
    a_file.write_text("a = 1\n", "utf-8")

    files = list(iter_py_files(str(tmp_path)))
    assert files == sorted(files)


def test_module_name_from_path(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    init = pkg / "__init__.py"
    init.write_text("", "utf-8")
    module = pkg / "mod.py"
    module.write_text("x = 1\n", "utf-8")

    assert module_name_from_path(str(tmp_path), str(init)) == "pkg"
    assert module_name_from_path(str(tmp_path), str(module)) == "pkg.mod"


def test_iter_py_files_invalid_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ValidationError):
        list(iter_py_files(str(missing)))


def test_iter_py_files_not_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", "utf-8")
    with pytest.raises(ValidationError):
        list(iter_py_files(str(file_path)))


def test_iter_py_files_max_files(tmp_path: Path) -> None:
    src = tmp_path / "a.py"
    src.write_text("x = 1\n", "utf-8")
    with pytest.raises(ValidationError):
        list(iter_py_files(str(tmp_path), max_files=0))


def test_iter_py_files_symlink_skip(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    out_file = outside / "x.py"
    out_file.write_text("x = 1\n", "utf-8")

    root = tmp_path / "root"
    root.mkdir()
    link = root / "link.py"
    _symlink_or_skip(link, out_file)

    files = list(iter_py_files(str(root)))
    assert str(link) not in files


def test_iter_py_files_symlink_to_etc_skipped(tmp_path: Path) -> None:
    passwd = Path("/etc/passwd")
    if not passwd.exists():
        pytest.skip("/etc/passwd not available")

    root = tmp_path / "root"
    root.mkdir()
    link = root / "passwd.py"
    _symlink_or_skip(link, passwd)

    files = list(iter_py_files(str(root)))
    assert str(link) not in files


def test_iter_py_files_symlink_loop_does_not_traverse(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    src = root / "a.py"
    src.write_text("x = 1\n", "utf-8")
    loop = root / "loop"
    _symlink_or_skip(loop, root, target_is_directory=True)

    files = list(iter_py_files(str(root), max_files=10))
    assert files.count(str(src)) == 1


def test_scanner_internal_path_guards_and_symlink_resolve_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()

    inside = root / "inside.py"
    inside.write_text("x = 1\n", "utf-8")
    assert scanner._is_under_root(inside, root) is True

    excluded = root / "__pycache__" / "skip.py"
    excluded.parent.mkdir()
    excluded.write_text("x = 1\n", "utf-8")
    assert (
        scanner._is_included_python_file(
            file_path=excluded,
            excludes_set={"__pycache__"},
            rootp=root,
        )
        is False
    )

    target = root / "target.py"
    target.write_text("x = 1\n", "utf-8")
    link = root / "link.py"
    _symlink_or_skip(link, target)

    original_resolve = Path.resolve

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == link:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    assert (
        scanner._is_included_python_file(
            file_path=link,
            excludes_set=set(),
            rootp=root,
        )
        is False
    )


def test_is_included_python_file_non_py_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    txt = root / "a.txt"
    txt.write_text("x", "utf-8")
    assert (
        scanner._is_included_python_file(
            file_path=txt,
            excludes_set=set(),
            rootp=root,
        )
        is False
    )


def test_is_included_python_file_regular_py_accepted(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    pyf = root / "a.py"
    pyf.write_text("x = 1\n", "utf-8")
    assert (
        scanner._is_included_python_file(
            file_path=pyf,
            excludes_set=set(),
            rootp=root,
        )
        is True
    )


def test_iter_py_files_excluded_root_short_circuit(tmp_path: Path) -> None:
    excluded_root = tmp_path / "__pycache__"
    excluded_root.mkdir()
    (excluded_root / "a.py").write_text("x = 1\n", "utf-8")
    assert list(iter_py_files(str(excluded_root))) == []


def test_iter_py_files_excluded_parent_dir_does_not_short_circuit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "build" / "project"
    root.mkdir(parents=True)
    src = root / "a.py"
    src.write_text("x = 1\n", "utf-8")
    assert list(iter_py_files(str(root))) == [str(src)]


def test_sensitive_prefix_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sensitive_root = Path.cwd() / "tmp_sensitive_root"
    sensitive_root.mkdir()
    sub = sensitive_root / "sub"
    sub.mkdir()

    monkeypatch.setattr(scanner, "SENSITIVE_DIRS", {str(sensitive_root)})

    with pytest.raises(ValidationError):
        list(scanner.iter_py_files(str(sub)))

    sub.rmdir()
    sensitive_root.rmdir()


def test_sensitive_root_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path.cwd() / "tmp_sensitive_root2"
    root.mkdir()
    monkeypatch.setattr(scanner, "SENSITIVE_DIRS", {str(root)})
    with pytest.raises(ValidationError):
        list(scanner.iter_py_files(str(root)))
    root.rmdir()


def test_sensitive_directory_blocked_via_dotdot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_fake_tempdir(tmp_path, monkeypatch)

    base = tmp_path / "base"
    sensitive_root = tmp_path / "sensitive"
    base.mkdir()
    sensitive_root.mkdir()

    try:
        monkeypatch.setattr(scanner, "SENSITIVE_DIRS", {str(sensitive_root)})

        # Path traversal via ".." should resolve to sensitive_root and be blocked
        path_with_dotdot = base / ".." / sensitive_root.name
        with pytest.raises(ValidationError):
            list(scanner.iter_py_files(str(path_with_dotdot)))
    finally:
        base.rmdir()
        sensitive_root.rmdir()


def test_symlink_to_sensitive_directory_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_fake_tempdir(tmp_path, monkeypatch)

    root = tmp_path / "root"
    sensitive_root = tmp_path / "sensitive_link_target"
    root.mkdir()
    sensitive_root.mkdir()
    sensitive_file = sensitive_root / "secret.py"
    sensitive_file.write_text("x = 1\n", "utf-8")

    try:
        monkeypatch.setattr(scanner, "SENSITIVE_DIRS", {str(sensitive_root)})

        link = root / "sensitive_link"
        _symlink_or_skip(link, sensitive_root, target_is_directory=True)

        files = list(scanner.iter_py_files(str(root)))
        assert str(sensitive_file) not in files
    finally:
        link = root / "sensitive_link"
        if link.exists():
            link.unlink()
        if sensitive_file.exists():
            sensitive_file.unlink()
        if sensitive_root.exists():
            sensitive_root.rmdir()
        if root.exists():
            root.rmdir()
