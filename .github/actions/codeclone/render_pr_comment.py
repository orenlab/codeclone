# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os

from _action_impl import (
    load_report,
    render_pr_comment,
    write_outputs,
    write_step_summary,
)


def main() -> int:
    report_path = os.environ["REPORT_PATH"]
    output_path = os.environ["COMMENT_OUTPUT_PATH"]
    exit_code = int(os.environ["ANALYSIS_EXIT_CODE"])

    if not os.path.exists(report_path):
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            write_outputs(
                github_output,
                {
                    "comment-exists": "false",
                    "comment-body-path": output_path,
                },
            )
        return 0

    body = render_pr_comment(load_report(report_path), exit_code=exit_code)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(body)
        handle.write("\n")

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        write_step_summary(step_summary, body)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        write_outputs(
            github_output,
            {
                "comment-exists": "true",
                "comment-body-path": output_path,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
