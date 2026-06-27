#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from urllib.parse import urlparse

from codeclone import __version__

DEFAULT_OUTPUT_DIR = Path("site/examples/report/live")
CODECLONE_CLI_MODULE = "codeclone.main"
_ARTIFACT_NAMES: tuple[str, ...] = (
    "index.html",
    "report.json",
    "report.sarif",
    "manifest.json",
)
_RELATIVE_LIVE_HREF = re.compile(r'href="live/([a-zA-Z0-9_.-]+)"')


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


def _load_toml_text(text: str) -> dict[str, object]:
    if sys.version_info >= (3, 11):
        import tomllib

        payload = tomllib.loads(text)
    else:
        tomli_module = importlib.import_module("tomli")
        loads_fn = getattr(tomli_module, "loads", None)
        if not callable(loads_fn):
            msg = "Invalid 'tomli' module: missing callable 'loads'."
            raise RuntimeError(msg)
        payload = loads_fn(text)
    if not isinstance(payload, dict):
        msg = "TOML root must be a table."
        raise ValueError(msg)
    return cast(dict[str, object], payload)


def _read_site_url(repo_root: Path) -> str:
    config_path = repo_root / "zensical.toml"
    payload = _load_toml_text(config_path.read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict):
        raise ValueError(f"{config_path} is missing a [project] table.")
    site_url = project.get("site_url")
    if not isinstance(site_url, str) or not site_url.strip():
        raise ValueError(f"{config_path} must define project.site_url.")
    return site_url.strip()


def _published_artifact_href(site_url: str, artifact_name: str) -> str:
    if artifact_name not in _ARTIFACT_NAMES:
        msg = f"unsupported sample-report artifact: {artifact_name}"
        raise ValueError(msg)
    parsed = urlparse(site_url)
    if not parsed.scheme or not parsed.netloc:
        msg = f"project.site_url must be an absolute URL, got {site_url!r}"
        raise ValueError(msg)
    base_path = parsed.path.rstrip("/")
    artifact_path = f"{base_path}/examples/report/live/{artifact_name}"
    return f"{parsed.scheme}://{parsed.netloc}{artifact_path}"


def _sample_report_page_path(output_dir: Path) -> Path:
    return output_dir.parent / "index.html"


def _patch_sample_report_links(*, output_dir: Path, site_url: str) -> None:
    """Rewrite relative live/* hrefs to absolute published URLs.

    Relative ``live/...`` links break when the Sample Report page URL lacks a
    trailing slash (common with navigation.instant), resolving to
    ``/examples/live/...`` instead of ``/examples/report/live/...``.
    """
    report_page = _sample_report_page_path(output_dir)
    if not report_page.is_file():
        return
    text = report_page.read_text(encoding="utf-8")

    def _replace(match: re.Match[str]) -> str:
        artifact_name = match.group(1)
        href = _published_artifact_href(site_url, artifact_name)
        return f'href="{href}"'

    patched = _RELATIVE_LIVE_HREF.sub(_replace, text)
    if patched != text:
        report_page.write_text(patched, encoding="utf-8")


def _verify_report_artifacts(destination: ReportArtifacts) -> None:
    missing = [
        str(path)
        for path in (
            destination.html,
            destination.json,
            destination.sarif,
            destination.manifest,
        )
        if not path.is_file()
    ]
    if missing:
        joined = ", ".join(missing)
        raise FileNotFoundError(
            f"sample report artifacts missing after build: {joined}"
        )


def build_docs_example_report(output_dir: Path) -> None:
    scan_root = _repo_root()
    destination = _artifacts_for_dir(output_dir)
    with TemporaryDirectory(prefix="codeclone-docs-report-") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        working = _artifacts_for_dir(tmp_dir)
        _run_codeclone(scan_root, working)
        _write_manifest(scan_root, working)
        _copy_artifacts(working, destination)
    _verify_report_artifacts(destination)
    _patch_sample_report_links(
        output_dir=output_dir, site_url=_read_site_url(scan_root)
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    build_docs_example_report(args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
