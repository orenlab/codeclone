# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.observability.db_fingerprint import (
    SqlFingerprint,
    SqlShape,
    describe_fingerprint,
    fingerprint_sql,
)


@pytest.mark.parametrize(
    ("sql", "expected_fp", "table_hint", "kind"),
    [
        (
            "SELECT * FROM memory_evidence WHERE memory_id = 'abc'",
            "select * from memory_evidence where memory_id = ?",
            "memory_evidence",
            "select",
        ),
        (
            "select   *\n from   memory_records  where id = 42",
            "select * from memory_records where id = ?",
            "memory_records",
            "select",
        ),
        (
            "INSERT INTO memory_subjects (a, b) VALUES (?, ?, ?)",
            "insert into memory_subjects (a, b) values (?)",
            "memory_subjects",
            "insert",
        ),
        (
            "UPDATE platform_spans SET counters_json = '{}' WHERE span_id = 'x'",
            "update platform_spans set counters_json = ? where span_id = ?",
            "platform_spans",
            "update",
        ),
        (
            "DELETE FROM memory_links WHERE id IN (1, 2, 3)",
            "delete from memory_links where id in (?)",
            "memory_links",
            "delete",
        ),
        (
            "SELECT e.* FROM memory_evidence e "
            "JOIN memory_records r ON r.id = e.memory_id",
            "select e.* from memory_evidence e "
            "join memory_records r on r.id = e.memory_id",
            "memory_evidence",
            "select",
        ),
        ("PRAGMA query_only = ON", "pragma query_only = on", None, "other"),
    ],
)
def test_fingerprint_sql_shapes(
    sql: str, expected_fp: str, table_hint: str | None, kind: str
) -> None:
    assert fingerprint_sql(sql) == SqlFingerprint(
        fingerprint=expected_fp, table_hint=table_hint, kind=kind
    )


def test_fingerprint_strips_numbers_and_hex() -> None:
    fp = fingerprint_sql("select * from t where a = 3.14 and b = 0xFF")
    assert fp.fingerprint == "select * from t where a = ? and b = ?"
    assert fp.table_hint == "t"


def test_fingerprint_is_idempotent_on_its_own_output() -> None:
    once = fingerprint_sql("SELECT * FROM memory_evidence WHERE memory_id IN (10, 20)")
    twice = fingerprint_sql(once.fingerprint)
    assert twice == once
    assert once.table_hint == "memory_evidence"


def test_fingerprint_empty_sql() -> None:
    assert fingerprint_sql("   \n ") == SqlFingerprint(
        fingerprint="", table_hint=None, kind="other"
    )


def test_fingerprint_caps_length() -> None:
    long_sql = "select " + ", ".join(f"col{i}" for i in range(200)) + " from big_table"
    fp = fingerprint_sql(long_sql)
    assert len(fp.fingerprint) <= 200
    assert fp.kind == "select"
    assert fp.table_hint == "big_table"


@pytest.mark.parametrize(
    ("sql", "kind", "table", "where_columns", "summary"),
    [
        (
            "select count(*) from controller_events "
            "where repo_root_digest = ? and (workflow_id is null or workflow_id = ?)",
            "select",
            "controller_events",
            ("repo_root_digest", "workflow_id"),
            "count by repo_root_digest, workflow_id",
        ),
        (
            "select distinct workflow_id from controller_events "
            "where repo_root_digest = ? and id > ? and workflow_id is not null",
            "select",
            "controller_events",
            ("repo_root_digest", "id", "workflow_id"),
            "distinct workflow_id by repo_root_digest, id, workflow_id",
        ),
        (
            "SELECT * FROM memory_evidence WHERE memory_id = 7",
            "select",
            "memory_evidence",
            ("memory_id",),
            "by memory_id",
        ),
        (
            "SELECT * FROM controller_events",
            "select",
            "controller_events",
            (),
            "all rows",
        ),
        (
            "UPDATE memory_records SET status = ? WHERE id = ?",
            "update",
            "memory_records",
            ("id",),
            "by id",
        ),
    ],
)
def test_describe_fingerprint(
    sql: str,
    kind: str,
    table: str,
    where_columns: tuple[str, ...],
    summary: str,
) -> None:
    assert describe_fingerprint(sql) == SqlShape(
        kind=kind, table=table, where_columns=where_columns, summary=summary
    )


def test_describe_fingerprint_caps_where_columns_in_summary() -> None:
    shape = describe_fingerprint(
        "select * from t where a = ? and b = ? and c = ? and d = ? and e = ?"
    )
    assert shape.where_columns == ("a", "b", "c", "d", "e")
    assert shape.summary == "by a, b, c, d, …"


def test_describe_fingerprint_insert_has_no_predicate_summary() -> None:
    shape = describe_fingerprint("INSERT INTO memory_records (id) VALUES (?)")
    assert shape.kind == "insert"
    assert shape.summary == ""
