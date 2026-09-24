# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The R3 door of the run store's one explicit schema migration.

An open of an existing store never changes its schema: a store of this
generation that lacks a table or an index this build declares is refused,
and the refusal names ``codeclone run-store migrate --path <store>``.  That
verb lives in the CLI (ring ``r4``), which may not import the canonical
package (``r2``) where the store owns its DDL; this door carries the one
operation across, and the store's typed refusals with it, so the CLI answers
a foreign or an absent file with the same words an open would.
"""

from __future__ import annotations

from pathlib import Path

from ..canonical.errors import RunStoreError
from ..canonical.store import migrate_store_schema


def migrate_run_store_schema(path: Path) -> tuple[tuple[str, str], ...]:
    """Add what the store at ``path`` lacks; the ``(type, name)`` objects added.

    Empty when the schema was already complete.  Refuses, typed
    (:class:`RunStoreError`), a path that holds no store and a file whose
    witness is not this build's generation, and writes nothing to either.
    """
    return migrate_store_schema(path)


__all__ = ["RunStoreError", "migrate_run_store_schema"]
