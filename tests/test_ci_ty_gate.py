# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""ty is a pinned development tool and a CI gate, with no diagnostics allowed.

2.0.3 brought ``ty check codeclone .github/actions benchmarks`` to zero
diagnostics without suppressions. The checker is pinned in the ``dev`` extra
and locked, so CI runs the same release the code was fixed against, and the
lint job runs exactly that command.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_TY = "ty==0.0.84"
_COMMAND = "uv run ty check codeclone .github/actions benchmarks"


def test_ty_is_pinned_in_the_dev_extra_and_the_lock() -> None:
    pyproject = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    dev = re.search(r"(?ms)^dev = \[\n(.*?)^\]", pyproject)
    lock = (_REPO / "uv.lock").read_text(encoding="utf-8")

    assert dev is not None
    assert f'    "{_TY}",' in dev.group(1).splitlines()
    assert re.search(r'(?m)^name = "ty"\nversion = "0\.0\.84"$', lock)


def test_the_ci_lint_job_runs_ty_on_the_checked_paths() -> None:
    workflow = (_REPO / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    lint = re.search(r"(?ms)^  lint:\n(.*?)(?=^  [\w-]+:\n|\Z)", workflow)
    assert lint is not None
    runs = re.findall(r"(?m)^        run: (.+)$", lint.group(1))

    assert _COMMAND in runs
    assert runs.index(_COMMAND) > runs.index(
        "uv sync --locked --no-build --extra dev --extra mcp"
    )
