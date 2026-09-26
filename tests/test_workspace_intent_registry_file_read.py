# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Reading one registry file has three outcomes, told apart by exception class.

``read_payload`` answered ``None`` both for bytes no writer produced and for a
file this process was refused permission to open, and the removal path unlinked
on ``None``. The split now happens where the read happens, in the ring that
owns the registry layout; the store and the admission guard consume it.
"""

from __future__ import annotations

import errno
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from codeclone.utils.json_io import BoundedReadError
from codeclone.workspace_intent import paths as intent_paths


def _raising(exc: BaseException) -> Callable[[Path], dict[str, object]]:
    def reader(path: Path) -> dict[str, object]:
        raise exc

    return reader


@pytest.mark.parametrize(
    "exc",
    [
        PermissionError(errno.EACCES, "Permission denied"),
        OSError(errno.EIO, "Input/output error"),
        OSError(errno.EMFILE, "Too many open files"),
    ],
    ids=["eacces", "eio", "emfile"],
)
def test_a_failed_read_is_unreadable_not_corrupt(
    tmp_path: Path,
    exc: OSError,
) -> None:
    read = intent_paths.read_registry_file(tmp_path / "x.json", reader=_raising(exc))

    assert read.kind is intent_paths.RegistryFileReadKind.UNREADABLE
    assert read.payload is None
    assert read.error == type(exc).__name__


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("not json"),
        TypeError("JSON payload must be an object"),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        BoundedReadError("File too large"),
        FileNotFoundError(errno.ENOENT, "No such file or directory"),
    ],
    ids=["value", "type", "unicode", "oversize", "vanished"],
)
def test_bytes_no_writer_produced_stay_corrupt(tmp_path: Path, exc: Exception) -> None:
    """The opposite boundary: damaged bytes keep the existing hygiene policy.

    An over-cap file and a name whose target does not exist are ``OSError``
    subclasses, and neither is an intent some writer holds: no writer emits a
    64 MiB intent, and a dangling link has no bytes at all. Routing them into
    the unreadable lane would block every admission until someone deleted
    junk by hand.
    """

    read = intent_paths.read_registry_file(tmp_path / "x.json", reader=_raising(exc))

    assert read.kind is intent_paths.RegistryFileReadKind.CORRUPT
    assert read.payload is None
    assert read.error == ""


def test_a_readable_object_is_a_payload(tmp_path: Path) -> None:
    read = intent_paths.read_registry_file(
        tmp_path / "x.json",
        reader=lambda path: {"intent_id": "x"},
    )

    assert read.kind is intent_paths.RegistryFileReadKind.PAYLOAD
    assert read.payload == {"intent_id": "x"}
    assert read.error == ""


def test_the_legacy_projection_is_the_same_answer_not_a_second_classifier(
    tmp_path: Path,
) -> None:
    """``read_payload`` keeps its shape for the read-only listers.

    It projects ``read_registry_file`` and owns no except clause of its own,
    so the two can never classify one failure two ways.
    """

    path = tmp_path / "x.json"
    assert intent_paths.read_payload(path, reader=lambda p: {"intent_id": "x"}) == {
        "intent_id": "x"
    }
    denied = _raising(PermissionError(errno.EACCES, "Permission denied"))
    assert intent_paths.read_payload(path, reader=denied) is None
    assert intent_paths.read_payload(path, reader=_raising(ValueError("x"))) is None


def test_a_real_permission_denial_reads_as_unreadable(tmp_path: Path) -> None:
    """The real reader, the real ``open``: no stand-in between them."""

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("permission bits do not deny reads to root")
    path = tmp_path / "123-456-intent-x.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    try:
        read = intent_paths.read_registry_file(path)
    finally:
        os.chmod(path, 0o600)

    assert read.kind is intent_paths.RegistryFileReadKind.UNREADABLE
    assert read.error == "PermissionError"
    # Control: the same file, readable, is a payload.
    assert intent_paths.read_registry_file(path).kind is (
        intent_paths.RegistryFileReadKind.PAYLOAD
    )
