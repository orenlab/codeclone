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


def test_published_artifact_href_uses_site_url_path_prefix() -> None:
    module = _load_docs_report_namespace()
    published_artifact_href = module["_published_artifact_href"]
    assert callable(published_artifact_href)
    href = published_artifact_href(
        "https://orenlab.github.io/codeclone/",
        "index.html",
    )
    assert href == "https://orenlab.github.io/codeclone/examples/report/live/index.html"


def test_patch_sample_report_links_rewrites_relative_live_hrefs(
    tmp_path: Path,
) -> None:
    module = _load_docs_report_namespace()
    patch_sample_report_links = module["_patch_sample_report_links"]
    assert callable(patch_sample_report_links)

    output_dir = tmp_path / "examples" / "report" / "live"
    output_dir.mkdir(parents=True)
    report_page = tmp_path / "examples" / "report" / "index.html"
    report_page.write_text(
        "\n".join(
            [
                '<a href="live/index.html">HTML</a>',
                '<a href="live/report.json">JSON</a>',
            ]
        ),
        encoding="utf-8",
    )

    patch_sample_report_links(
        output_dir=output_dir,
        site_url="https://orenlab.github.io/codeclone/",
    )

    patched = report_page.read_text(encoding="utf-8")
    assert 'href="live/index.html"' not in patched
    assert (
        'href="https://orenlab.github.io/codeclone/examples/report/live/index.html"'
        in patched
    )
    assert (
        'href="https://orenlab.github.io/codeclone/examples/report/live/report.json"'
        in patched
    )


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
