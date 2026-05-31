# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from collections.abc import Mapping

_NUMBERED_HEADING_RE = re.compile(r"^(\d+)\)\s*(.+)$")


def normalize_doc_heading(raw: str) -> str:
    """Normalize markdown headings for stable, readable link statements."""
    text = raw.strip()
    if not text:
        return "root"
    match = _NUMBERED_HEADING_RE.match(text)
    if match is not None:
        return f"§{match.group(1)} · {match.group(2).strip()}"
    return text


def format_document_link_statement(
    *,
    doc_file: str,
    heading: str,
    anchored_path: str,
) -> str:
    normalized = normalize_doc_heading(heading)
    return f"{doc_file} · {normalized} → {anchored_path}"


def format_memory_record_line(item: Mapping[str, object]) -> str:
    record_type = str(item.get("type", "?"))
    statement = str(item.get("statement", ""))
    if record_type != "document_link":
        return statement
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return statement
    doc_file = payload.get("doc_file")
    heading = payload.get("heading")
    anchored = payload.get("anchored_symbols")
    if not isinstance(doc_file, str) or not isinstance(heading, str):
        return statement
    path = ""
    if isinstance(anchored, list) and anchored:
        path = str(anchored[0])
    if not path:
        return statement
    return format_document_link_statement(
        doc_file=doc_file,
        heading=heading,
        anchored_path=path,
    )


__all__ = [
    "format_document_link_statement",
    "format_memory_record_line",
    "normalize_doc_heading",
]
