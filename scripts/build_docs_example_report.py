#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from codeclone import __version__

DEFAULT_OUTPUT_DIR = Path("site/examples/report/live")
CODECLONE_CLI_MODULE = "codeclone.main"


@dataclass(frozen=True)
class ReportArtifacts:
    html: Path
    json: Path
    sarif: Path
    manifest: Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a live CodeClone sample report for the docs site."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory that should receive index.html/report.json/report.sarif.",
    )
    return parser


def _artifacts_for_dir(output_dir: Path) -> ReportArtifacts:
    return ReportArtifacts(
        html=output_dir / "index.html",
        json=output_dir / "report.json",
        sarif=output_dir / "report.sarif",
        manifest=output_dir / "manifest.json",
    )


def _run_codeclone(scan_root: Path, artifacts: ReportArtifacts) -> None:
    cmd = [
        sys.executable,
        "-m",
        CODECLONE_CLI_MODULE,
        str(scan_root),
        "--html",
        str(artifacts.html),
        "--json",
        str(artifacts.json),
        "--sarif",
        str(artifacts.sarif),
        "--no-progress",
        "--quiet",
    ]
    subprocess.run(cmd, cwd=scan_root, check=True)


def _manifest_payload(scan_root: Path) -> dict[str, object]:
    return {
        "project": scan_root.name,
        "codeclone_version": __version__,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": os.environ.get("GITHUB_SHA", "").strip(),
        "scan_root": str(scan_root),
        "artifacts": {
            "html": "index.html",
            "json": "report.json",
            "sarif": "report.sarif",
        },
    }


def _write_manifest(scan_root: Path, artifacts: ReportArtifacts) -> None:
    artifacts.manifest.write_text(
        json.dumps(_manifest_payload(scan_root), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _copy_artifacts(source: ReportArtifacts, destination: ReportArtifacts) -> None:
    destination.html.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source.html, destination.html)
    shutil.copy2(source.json, destination.json)
    shutil.copy2(source.sarif, destination.sarif)
    shutil.copy2(source.manifest, destination.manifest)


def build_docs_example_report(output_dir: Path) -> None:
    scan_root = _repo_root()
    destination = _artifacts_for_dir(output_dir)
    with TemporaryDirectory(prefix="codeclone-docs-report-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        working = _artifacts_for_dir(tmp_dir)
        _run_codeclone(scan_root, working)
        _write_manifest(scan_root, working)
        _copy_artifacts(working, destination)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    build_docs_example_report(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
