# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Code provenance of the process serving an MCP response.

An MCP server is a long-lived process: it keeps the code it imported at startup
and keeps answering with it while the checkout underneath moves on.  The release
string is the same on every commit of a release, so a response carrying only
``version`` cannot tell a consumer whether it is talking to a fresh process or
to one whose code is hours old.

The marker here is a content digest of the Python sources of the loaded
``codeclone`` package, captured **once, when the process builds its session** --
not lazily on the first response, which would report the state of a disk the
process never loaded.  Its derivation rule:

    sha256 over, for every ``*.py`` file under the package directory sorted by
    repo-relative POSIX path: the path, then the sha256 of the file's bytes.

Consequences of the rule, each pinned by a test:

* content-addressed, so it separates commits inside one release, and separates
  a dirty worktree from the commit it sits on -- which a commit hash cannot;
* independent of file metadata and of the wall clock, so it never drifts on its
  own;
* no git required: a wheel install in ``site-packages`` yields a real digest,
  and only genuinely unreadable sources yield ``"unknown"``.

The provenance travels as the response block it will be serialized into: there
is no intermediate record type, so the fact has exactly one representation and
the model store stays the home of models.

The digest never enters analysis truth: no report, ``run_id``, execution
witness or baseline is derived from it, and it authorizes nothing.

It is no longer descriptive only.  :mod:`._engine_fence` reads the value
captured here as the *loaded* generation and re-derives the same digest from
:func:`package_source_root` as the *disk* generation, and refuses the operation
when the two disagree -- the one thing the captured value alone can never
report, since a stale process honestly reports the digest it was launched with
and shows no drift by construction.  Two consequences bind this module:
``compute_code_provenance`` must stay free of any cache keyed by anything
cheaper than content, and ``package_source_root`` must keep naming the tree the
interpreter imported rather than any root a caller supplied.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from types import MappingProxyType

import codeclone

#: Sources were enumerated and digested.
SOURCE_TREE = "source_tree"
#: Sources could not be read; a fabricated value would be worse than an answer.
UNKNOWN = "unknown"

_DIGEST_PREFIX = "sha256:"
_PYTHON_SUFFIX = ".py"

_UNKNOWN_PROVENANCE: Mapping[str, str] = MappingProxyType(
    {"code_digest": UNKNOWN, "source": UNKNOWN, "source_root": ""}
)


def package_source_root() -> Path | None:
    """Directory holding the sources of the ``codeclone`` package this process ran.

    ``None`` when the package exposes no file location (namespace package,
    zipimport, frozen interpreter): those have no source tree to digest.
    """
    location = getattr(codeclone, "__file__", None)
    if not isinstance(location, str) or not location:
        return None
    try:
        return Path(location).resolve().parent
    except OSError:
        return None


def compute_code_provenance(package_root: Path | None) -> dict[str, str]:
    """Digest the Python sources under ``package_root``.

    Returns the honest unknown when there is no readable source tree: no root,
    a root that does not exist, a root with no ``*.py`` files (a compiled-only
    install), or a source file that cannot be read.
    """
    if package_root is None:
        return dict(_UNKNOWN_PROVENANCE)
    try:
        entries = _digest_entries(package_root)
    except OSError:
        return dict(_UNKNOWN_PROVENANCE)
    if not entries:
        return dict(_UNKNOWN_PROVENANCE)
    digest = hashlib.sha256()
    for relative_path, content_digest in entries:
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_digest)
    return {
        "code_digest": f"{_DIGEST_PREFIX}{digest.hexdigest()}",
        "source": SOURCE_TREE,
        "source_root": str(package_root),
    }


def _digest_entries(package_root: Path) -> list[tuple[str, bytes]]:
    """Return ``(relative posix path, sha256 of bytes)`` sorted by path.

    Raises ``OSError`` when a source file cannot be read: an unreadable file
    means the digest would describe a different tree than the one on disk.
    """
    entries: list[tuple[str, bytes]] = []
    for path in package_root.rglob(f"*{_PYTHON_SUFFIX}"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(package_root).as_posix()
        entries.append((relative_path, hashlib.sha256(path.read_bytes()).digest()))
    entries.sort(key=lambda entry: entry[0])
    return entries


@cache
def process_code_provenance() -> Mapping[str, str]:
    """Provenance of this process, computed once and never recomputed.

    Call it while the process is starting up: the value must describe the code
    that was loaded, so it has to be taken before the checkout can move.
    """
    return MappingProxyType(compute_code_provenance(package_source_root()))


def code_provenance_payload(*, process_start_epoch: int) -> dict[str, object]:
    """Response block describing the process, not the analysis.

    ``process_start_epoch`` rides along as the age of the process: it is
    deliberately outside ``code_digest``, which must not move with the clock.
    """
    return {
        **process_code_provenance(),
        "process_start_epoch": process_start_epoch,
    }


__all__ = [
    "SOURCE_TREE",
    "UNKNOWN",
    "code_provenance_payload",
    "compute_code_provenance",
    "package_source_root",
    "process_code_provenance",
]
