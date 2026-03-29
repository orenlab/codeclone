# SPDX-License-Identifier: MIT

from __future__ import annotations

import os

from _action_impl import build_inputs_from_env, run_codeclone, write_outputs


def main() -> int:
    result = run_codeclone(build_inputs_from_env(dict(os.environ)))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        write_outputs(
            github_output,
            {
                "exit-code": str(result.exit_code),
                "json-path": result.json_path,
                "json-exists": str(result.json_exists).lower(),
                "sarif-path": result.sarif_path,
                "sarif-exists": str(result.sarif_exists).lower(),
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
