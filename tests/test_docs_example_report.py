# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from unittest.mock import patch


def _load_docs_report_namespace() -> dict[str, object]:
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "build_docs_example_report.py"
    )
    return runpy.run_path(str(script_path))


def test_docs_example_report_uses_main_entrypoint(
    tmp_path: Path,
) -> None:
    module = _load_docs_report_namespace()
    observed: dict[str, object] = {}

    def _fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        check: bool,
    ) -> None:
        observed["cmd"] = cmd
        observed["cwd"] = cwd
        observed["check"] = check

    report_artifacts_type = module["ReportArtifacts"]
    assert callable(report_artifacts_type)
    artifacts = report_artifacts_type(
        html=tmp_path / "index.html",
        json=tmp_path / "report.json",
        sarif=tmp_path / "report.sarif",
        manifest=tmp_path / "manifest.json",
    )
    run_codeclone = module["_run_codeclone"]
    assert callable(run_codeclone)

    with patch("subprocess.run", side_effect=_fake_run):
        run_codeclone(tmp_path, artifacts)

    assert observed == {
        "cmd": [
            sys.executable,
            "-m",
            "codeclone.main",
            str(tmp_path),
            "--html",
            str(artifacts.html),
            "--json",
            str(artifacts.json),
            "--sarif",
            str(artifacts.sarif),
            "--no-progress",
            "--quiet",
        ],
        "cwd": tmp_path,
        "check": True,
    }
