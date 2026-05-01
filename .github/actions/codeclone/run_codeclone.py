# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Run CodeClone inside the GitHub Action runtime.

This entrypoint normalizes GitHub Action inputs from the environment, executes
CodeClone, and exposes artifact paths plus analyzer exit status through
GITHUB_OUTPUT. The process itself returns 0 so later workflow steps can
decide how to handle the analyzer result.
"""

from __future__ import annotations

import os

from _action_impl import RunResult, build_inputs_from_env, run_codeclone, write_outputs


def main() -> int:
    """Run CodeClone and publish action outputs."""

    result = run_codeclone(build_inputs_from_env(dict(os.environ)))
    _write_run_outputs(github_output=os.environ.get("GITHUB_OUTPUT"), result=result)
    return 0


def _write_run_outputs(*, github_output: str | None, result: RunResult) -> None:
    """Expose CodeClone run metadata through GITHUB_OUTPUT when available."""

    if not github_output:
        return

    write_outputs(
        github_output,
        {
            "exit-code": str(result.exit_code),
            "json-path": result.json_path,
            "json-exists": _bool_output(result.json_exists),
            "sarif-path": result.sarif_path,
            "sarif-exists": _bool_output(result.sarif_exists),
        },
    )


def _bool_output(value: bool) -> str:
    """Format a boolean value for GitHub Action outputs."""

    return str(value).lower()


if __name__ == "__main__":
    raise SystemExit(main())
