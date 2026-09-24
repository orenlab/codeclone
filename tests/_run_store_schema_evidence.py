# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One instrument and the populations for the run store's schema pins.

Shared by the store-ring pins (``test_run_store_ddl_authority``,
``test_canonical_generation_refusal``) and the surface-ring pins
(``test_run_store_schema_surfaces``), so every one of them measures "the
file was left as it was" the same way, and no test module has to import
another one to borrow it.  Standard library only: nothing here can move a
test module's ring or lengthen an import chain.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final

#: The secondary index this build declares and stores written before it lack.
INDEX: Final = "idx_run_members_object"
#: The real store the revision-1 build produced (see its provenance file).
GENERATION_1: Final = (
    Path(__file__).parent / "fixtures" / "run_store_generation_1" / "runs.sqlite3"
)
#: Header bytes 18-19 of a SQLite file: the write and read format versions,
#: ``1`` for a rollback journal and ``2`` for WAL.  Read off the bytes, so
#: the journal mode is measured without a connection that could change it.
JOURNAL_BYTES: Final = slice(18, 20)


def byte_state(path: Path) -> dict[str, object]:
    """The store file, its ``-wal`` and ``-shm`` (``None`` when absent) and
    its journal mode, all read as bytes -- no SQLite connection involved.

    Checkpoint-independent on purpose: a write a refused handle still holds
    sits in the ``-wal`` while the main file's digest has not moved yet, so
    a pin that hashed the main file alone stayed green over an index written
    into a refused store (index wave, 2026-09-23, mutant p-m5).  Take it
    with no connection open on the file: a connection is what creates the
    side files, and a probe that opened one would measure itself.
    """
    state: dict[str, object] = {}
    for suffix in ("", "-wal", "-shm"):
        side = Path(f"{path}{suffix}")
        state[suffix or "main"] = (
            hashlib.sha256(side.read_bytes()).hexdigest() if side.exists() else None
        )
    main = Path(path)
    state["journal"] = main.read_bytes()[JOURNAL_BYTES] if main.exists() else None
    return state


def drop_the_index(path: Path) -> None:
    """Turn a current store into what every store written before the index
    is: this generation's witness and tables, and no index."""
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(f"DROP INDEX IF EXISTS {INDEX}")
        raw.commit()


def copy_generation_1(path: Path) -> None:
    shutil.copy(GENERATION_1, path)


def foreign_schema(path: Path) -> None:
    """A SQLite file holding somebody else's table and no store witness."""
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("CREATE TABLE notes (body TEXT)")
        raw.execute("INSERT INTO notes VALUES ('somebody else''s')")
        raw.commit()


def empty_file(path: Path) -> None:
    path.write_bytes(b"")
