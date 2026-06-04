# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

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
