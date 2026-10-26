# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A stored report digest that is not ASCII is a mismatch, not an exception.

``hmac.compare_digest`` raises ``TypeError`` when a ``str`` argument holds a
non-ASCII character. The stored value is untrusted input, so a tampered or
corrupted ``.codeclone/report.json`` escaped the bounded reader as a raw
``TypeError``: ``codeclone memory init`` printed it and stopped with exit 2
instead of refusing the document and running a fresh analysis. A computed
digest is lowercase hex, so a value that is not ASCII can never equal it;
the reader now refuses it with the same typed reason as any other mismatch,
naming the tier that was tampered with.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeclone.models import ReportReadFailure, ReportReadSuccess
from codeclone.report.document.reader import read_report_document_v3
from tests._cli_child import run_codeclone

_TIERS = ("analysis_facts", "comparison", "evaluation", "envelope")


@pytest.fixture(scope="module")
def report_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("report-digest")
    package = tmp / "proj" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "mod.py").write_text("def f(a: int) -> int:\n    return a\n", "utf-8")
    out = tmp / "report.json"
    run = run_codeclone(tmp, str(tmp / "proj"), "--json", str(out), "--no-progress")
    assert run.returncode == 0, run.stdout + run.stderr
    return out


def _tampered(report_path: Path, tmp_path: Path, tier: str, value: str) -> Path:
    document = json.loads(report_path.read_text("utf-8"))
    document["integrity"]["digests"][tier]["value"] = value
    path = tmp_path / f"{tier}.json"
    path.write_text(json.dumps(document), "utf-8")
    return path


def test_an_untampered_report_reads(report_path: Path) -> None:
    assert isinstance(read_report_document_v3(report_path), ReportReadSuccess)


@pytest.mark.parametrize(
    "value",
    ["0" * 64, "é" * 64, "\udc80" * 64],
    ids=["ascii", "non-ascii", "lone-surrogate"],
)
@pytest.mark.parametrize("tier", _TIERS)
def test_a_tampered_digest_is_a_typed_refusal_naming_its_tier(
    report_path: Path, tmp_path: Path, tier: str, value: str
) -> None:
    result = read_report_document_v3(_tampered(report_path, tmp_path, tier, value))

    assert isinstance(result, ReportReadFailure), result
    assert result.detail == f"report {tier} digest mismatch"
