# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared setup for suites that build a small tree under ``tmp_path``.

Almost every behavioural suite starts by laying out two or three directories
and source files under ``tmp_path``, and each one wrote its own four-line
run of ``mkdir`` / ``write_text`` calls. The clones lane reported four separate
groups covering nothing but that boilerplate.

These helpers take the layout as data and return the created paths in the order
requested, so a setup block is one call and the test opens with what it is
actually about. Ordering is positional, never derived from a mapping, so the
tree a suite declares is the tree it gets.
"""

from __future__ import annotations

from pathlib import Path

_ENCODING = "utf-8"


def make_dir(parent: Path, name: str) -> Path:
    """Create one directory (and any missing parents) under ``parent``."""

    path = parent / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_dirs(parent: Path, *names: str) -> tuple[Path, ...]:
    """Create directories under ``parent`` and return them in argument order."""

    return tuple(make_dir(parent, name) for name in names)


def write_file(parent: Path, name: str, content: str) -> Path:
    """Write one file under ``parent``, creating missing parent directories."""

    path = parent / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, _ENCODING)
    return path


def write_files(parent: Path, *entries: tuple[str, str]) -> tuple[Path, ...]:
    """Write ``(name, content)`` files and return them in argument order."""

    return tuple(write_file(parent, name, content) for name, content in entries)


__all__ = ["make_dir", "make_dirs", "write_file", "write_files"]
