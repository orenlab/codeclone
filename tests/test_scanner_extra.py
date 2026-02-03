from __future__ import annotations

from pathlib import Path

import pytest

import codeclone.scanner as scanner
from codeclone.errors import ValidationError
from codeclone.scanner import iter_py_files, module_name_from_path


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
    link.symlink_to(out_file)

    files = list(iter_py_files(str(root)))
    assert str(link) not in files


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
    fake_temp = tmp_path / "fake_tmp"
    fake_temp.mkdir()
    monkeypatch.setattr(scanner, "_get_tempdir", lambda: fake_temp.resolve())

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
    fake_temp = tmp_path / "fake_tmp"
    fake_temp.mkdir()
    monkeypatch.setattr(scanner, "_get_tempdir", lambda: fake_temp.resolve())

    root = tmp_path / "root"
    sensitive_root = tmp_path / "sensitive_link_target"
    root.mkdir()
    sensitive_root.mkdir()
    sensitive_file = sensitive_root / "secret.py"
    sensitive_file.write_text("x = 1\n", "utf-8")

    try:
        monkeypatch.setattr(scanner, "SENSITIVE_DIRS", {str(sensitive_root)})

        link = root / "sensitive_link"
        link.symlink_to(sensitive_root, target_is_directory=True)

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
