# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.memory.display import (
    format_document_link_statement,
    format_memory_record_line,
    normalize_doc_heading,
)


def test_normalize_doc_heading_numbered_section() -> None:
    assert normalize_doc_heading("16) Change routing") == "§16 · Change routing"


def test_format_document_link_statement_avoids_stray_paren() -> None:
    statement = format_document_link_statement(
        doc_file="AGENTS.md",
        heading="16) Change routing",
        anchored_path="tests/test_mcp_server.py",
    )
    assert statement == "AGENTS.md · §16 · Change routing → tests/test_mcp_server.py"
    assert ")" not in statement.split("→", maxsplit=1)[0]


def test_format_memory_record_line_rebuilds_from_payload() -> None:
    item = {
        "type": "document_link",
        "statement": (
            "AGENTS.md (16) Change routing) references path tests/test_mcp_server.py."
        ),
        "payload": {
            "doc_file": "AGENTS.md",
            "heading": "16) Change routing",
            "anchored_symbols": ["tests/test_mcp_server.py"],
        },
    }
    assert (
        format_memory_record_line(item)
        == "AGENTS.md · §16 · Change routing → tests/test_mcp_server.py"
    )
