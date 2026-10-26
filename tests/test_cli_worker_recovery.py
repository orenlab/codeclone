# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a user sees when a worker death cannot be recovered: exit 5.

The CLI runs in a real child process with its worker entry point swapped
for a probe that kills every process the marked file runs in. The isolated
retry dies too, so the run must end as an internal error naming the file --
never a verdict. ``--patch-verify`` must not answer ``accepted``, and
``--update-baseline`` must not publish a baseline from what was read.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _worker_death_probe as probe
from tests._cli_child import child_env, run_codeclone

_SCOPE_ID = "0f5c6f3d-9d2e-4a2a-9a5f-6b0f9a1a2b3c"
_KILLER = f"{probe.WORKER_KILLER_PREFIX}_mod.py"
#: A healthy run of this tree takes a few seconds; a run past this is stuck.
_RUN_DEADLINE_SECONDS = 120.0
_RUN_WITH_PROBE = """
import sys
import codeclone.core.parallelism as parallelism
from tests import _worker_death_probe as probe
from codeclone.main import main

if __name__ == "__main__":
    parallelism._invoke_process_file = probe.die_always_in_worker
    sys.argv = ["codeclone", *sys.argv[1:]]
    main()
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n', "utf-8"
    )
    for index in range(16):
        (root / f"m{index:02d}.py").write_text(
            f"def unused_{index}(value):\n    return value + {index}\n", "utf-8"
        )
    (root / _KILLER).write_text("def killer():\n    return 0\n", "utf-8")
    published = run_codeclone(tmp_path, str(root), "--update-baseline", "--no-progress")
    assert published.returncode == 0, published.stdout + published.stderr
    return root


def _run_with_dying_worker(
    tmp_path: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    """Run the CLI in its own session, so a run that never ends -- recovery
    spawning one child after another -- is ended with every process it
    started, not left behind as an orphan when the test gives up."""

    probe_dir = tmp_path / "probe"
    probe_dir.mkdir(exist_ok=True)
    script = tmp_path / "run_with_probe.py"
    script.write_text(_RUN_WITH_PROBE, "utf-8")
    command = [sys.executable, str(script), *args]
    with subprocess.Popen(
        command,
        cwd=str(tmp_path),
        env=child_env(tmp_path, {probe.PROBE_DIR_ENV: str(probe_dir)}),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as child:
        try:
            stdout, stderr = child.communicate(timeout=_RUN_DEADLINE_SECONDS)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.communicate()
            pytest.fail(f"the run did not end within {_RUN_DEADLINE_SECONDS:g} s")
    return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)


@pytest.mark.parametrize(
    "flags",
    [
        ["--patch-verify"],
        ["--update-baseline"],
        ["--ci"],
    ],
    ids=["patch-verify", "update-baseline", "ci"],
)
def test_an_unrecoverable_worker_death_is_an_internal_error(
    tmp_path: Path, project: Path, flags: list[str]
) -> None:
    baseline = project / "codeclone.baseline.json"
    before = baseline.read_bytes()

    run = _run_with_dying_worker(
        tmp_path,
        str(project),
        "--processes",
        "2",
        "--no-progress",
        "--cache-path",
        str(tmp_path / "fresh-cache.db"),
        *flags,
    )

    # The console wraps long lines; the checks read the words, not the layout.
    output = " ".join((run.stdout + run.stderr).split())
    assert run.returncode == 5, output
    assert "INTERNAL ERROR" in output, output
    assert _KILLER in output, output
    assert "attempts on this file: 2" in output, output
    assert "accepted" not in output.lower(), output
    assert baseline.read_bytes() == before
