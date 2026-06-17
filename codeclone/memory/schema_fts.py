# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

CREATE_MEMORY_RECORDS_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_records_fts USING fts5(
    memory_id UNINDEXED,
    project_id UNINDEXED,
    record_type UNINDEXED,
    ingest_source UNINDEXED,
    status UNINDEXED,
    search_text,
    tokenize='unicode61 remove_diacritics 2'
)
"""

__all__ = ["CREATE_MEMORY_RECORDS_FTS_SQL"]
