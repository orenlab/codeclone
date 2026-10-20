# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from codeclone.surfaces.cli import tips as tips_mod
from codeclone.utils.json_io import (
    BoundedReadError,
    read_bounded_bytes,
    read_json_document,
    read_json_object,
    write_json_document_atomically,
)


def test_read_bounded_bytes_reads_without_stat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "payload.json"
    path.write_text('{"ok": true}', encoding="utf-8")

    def _raise_stat(_self: Path, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("stat must not be used for bounded reads")

    monkeypatch.setattr(Path, "stat", _raise_stat)

    assert read_bounded_bytes(path, max_bytes=32) == b'{"ok": true}'


def test_read_bounded_bytes_rejects_payload_over_limit(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_bytes(b"123456789")

    with pytest.raises(BoundedReadError, match="File too large"):
        read_bounded_bytes(path, max_bytes=8)


def test_read_bounded_bytes_requires_positive_limit(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_bytes(b"{}")

    with pytest.raises(ValueError, match="max_bytes"):
        read_bounded_bytes(path, max_bytes=0)


def test_read_json_document_and_object_use_bounded_reader(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text('{"items": [1, 2]}', encoding="utf-8")

    assert read_json_document(path, max_bytes=32) == {"items": [1, 2]}
    assert read_json_object(path, max_bytes=32) == {"items": [1, 2]}

    with pytest.raises(BoundedReadError):
        read_json_document(path, max_bytes=4)


def test_read_json_object_rejects_non_object_payload(tmp_path: Path) -> None:
    path = tmp_path / "payload.json"
    path.write_text("[1, 2]", encoding="utf-8")

    with pytest.raises(TypeError, match="must be an object"):
        read_json_object(path)


def test_write_json_document_atomically_rejects_symlink_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(OSError, match="symlink target"):
        write_json_document_atomically(link, {"ok": True})

    assert target.read_text(encoding="utf-8") == "{}"


def test_write_json_document_atomically_rejects_symlink_parent(
    tmp_path: Path,
) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link_dir = tmp_path / "link"
    try:
        link_dir.symlink_to(real_dir, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(OSError, match="symlink directory"):
        write_json_document_atomically(link_dir / "payload.json", {"ok": True})

    assert not (real_dir / "payload.json").exists()


@pytest.fixture
def permissive_umask() -> Iterator[None]:
    previous = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previous)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.mark.usefixtures("permissive_umask")
def test_a_new_written_file_takes_the_umask_mode(tmp_path: Path) -> None:
    path = tmp_path / "report.json"

    write_json_document_atomically(path, {"ok": True})

    assert _mode(path) == 0o644


@pytest.mark.usefixtures("permissive_umask")
def test_rewriting_a_file_keeps_the_mode_it_had(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o640)

    write_json_document_atomically(path, {"ok": True})

    assert _mode(path) == 0o640


@pytest.mark.usefixtures("permissive_umask")
def test_an_explicit_mode_is_the_mode_whatever_was_there(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o644)

    write_json_document_atomically(path, {"ok": True}, mode=0o600)

    assert _mode(path) == 0o600


def test_the_replacement_is_made_durable_in_its_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced_directories: list[bool] = []
    real_fsync = os.fsync

    def _spy(fd: int) -> None:
        synced_directories.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", _spy)

    write_json_document_atomically(tmp_path / "report.json", {"ok": True})

    assert synced_directories == [False, True]


@pytest.mark.usefixtures("permissive_umask")
def test_tip_state_stays_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "tips.json"

    tips_mod._remember_tip_shown(path=path, state={}, tip_key="a")
    assert _mode(path) == 0o600
    path.chmod(0o644)
    tips_mod._remember_tip_version(
        path=path, state={}, tip_key="b", codeclone_version="0"
    )

    assert _mode(path) == 0o600
