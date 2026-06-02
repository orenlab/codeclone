# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.memory.display import format_memory_record_line, normalize_doc_heading
from codeclone.memory.identity import make_identity_key
from codeclone.memory.report_trust import cached_report_untrusted_reason


def test_normalize_doc_heading_returns_root_for_empty() -> None:
    assert normalize_doc_heading("   ") == "root"


def test_format_memory_record_line_returns_statement_when_payload_not_dict() -> None:
    statement = "some statement"
    item: dict[str, object] = {
        "type": "document_link",
        "statement": statement,
        "payload": "not-a-dict",
    }
    assert format_memory_record_line(item) == statement


def test_format_memory_record_line_invalid_docfile_or_heading() -> None:
    statement = "some statement"
    item: dict[str, object] = {
        "type": "document_link",
        "statement": statement,
        "payload": {
            "doc_file": 123,
            "heading": "H",
            "anchored_symbols": ["x.py"],
        },
    }
    assert format_memory_record_line(item) == statement


def test_format_memory_record_line_empty_anchored_symbols() -> None:
    statement = "some statement"
    item: dict[str, object] = {
        "type": "document_link",
        "statement": statement,
        "payload": {
            "doc_file": "DOC.md",
            "heading": "H",
            "anchored_symbols": [],
        },
    }
    assert format_memory_record_line(item) == statement


def test_make_identity_key_rejects_empty_segments() -> None:
    with pytest.raises(ValueError, match="identity key segments must be non-empty"):
        make_identity_key(
            type="risk_note",
            subject_kind="path",
            subject_key="",
            discriminator="disc",
        )


def test_cached_report_untrusted_reason_missing_scan_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=root / "report.json",
        report_document={"meta": {}},
    )
    assert reason == "cached report missing meta.scan_root"


def test_cached_report_untrusted_reason_inventory_empty(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=root / "report.json",
        report_document={
            "meta": {"scan_root": str(root)},
            "inventory": {"file_registry": {"items": []}},
        },
    )
    assert reason == "cached report inventory.file_registry is empty"


def test_cached_report_untrusted_reason_invalid_scan_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()

    def _boom(self: Path) -> Path:
        raise OSError("bad path")

    # Cover the OSError handling in cached_report_untrusted_reason.
    monkeypatch.setattr(
        "codeclone.memory.report_trust.Path.resolve",
        _boom,
    )

    reason = cached_report_untrusted_reason(
        root_path=root,
        report_path=root / "report.json",
        report_document={"meta": {"scan_root": "/does/not/matter"}},
    )
    assert reason == "cached report meta.scan_root is invalid"
