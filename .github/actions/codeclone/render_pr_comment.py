# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Render the CodeClone GitHub Action PR comment from a JSON report.

This entrypoint is intentionally small: it reads action/runtime paths from the
environment, renders the Markdown comment from the canonical JSON report, writes
the comment body file, and exposes GitHub Action outputs for later workflow
steps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from _action_impl import (
    load_report,
    render_pr_comment,
    write_outputs,
    write_step_summary,
)


@dataclass(frozen=True, slots=True)
class _CommentRuntime:
    """Environment-derived runtime paths for PR comment rendering."""

    report_path: Path
    output_path: Path
    exit_code: int
    github_output: str | None
    step_summary: str | None


def main() -> int:
    """Render a PR comment when a CodeClone report exists."""

    runtime = _comment_runtime_from_env(os.environ)

    if not runtime.report_path.exists():
        _write_comment_outputs(runtime, comment_exists=False)
        return 0

    body = render_pr_comment(
        load_report(str(runtime.report_path)),
        exit_code=runtime.exit_code,
    )
    _write_comment_body(runtime.output_path, body)

    if runtime.step_summary:
        write_step_summary(runtime.step_summary, body)

    _write_comment_outputs(runtime, comment_exists=True)
    return 0


def _comment_runtime_from_env(env: os._Environ[str]) -> _CommentRuntime:
    """Build comment-rendering runtime from GitHub Action environment values."""

    return _CommentRuntime(
        report_path=Path(env["REPORT_PATH"]),
        output_path=Path(env["COMMENT_OUTPUT_PATH"]),
        exit_code=int(env["ANALYSIS_EXIT_CODE"]),
        github_output=env.get("GITHUB_OUTPUT"),
        step_summary=env.get("GITHUB_STEP_SUMMARY"),
    )


def _write_comment_body(path: Path, body: str) -> None:
    """Write the rendered Markdown comment body."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{body}\n", encoding="utf-8")


def _write_comment_outputs(
    runtime: _CommentRuntime,
    *,
    comment_exists: bool,
) -> None:
    """Expose PR comment metadata through ``GITHUB_OUTPUT`` when available."""

    if not runtime.github_output:
        return

    write_outputs(
        runtime.github_output,
        {
            "comment-exists": "true" if comment_exists else "false",
            "comment-body-path": str(runtime.output_path),
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
