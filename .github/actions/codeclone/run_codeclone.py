# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

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
