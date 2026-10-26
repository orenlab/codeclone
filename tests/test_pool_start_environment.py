# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A worker pool the operating system refuses: exit 4, and nothing published.

Maintainer rulings 2026-10-26: execution unavailable is not invalid input,
and neither is it proof of an internal defect. When the environment refuses
the pool, the run ends with exit 4 (unverified). No verdict is printed, no
report is written and no baseline is published.

The refusal here is real. Each run is a fresh CLI process. A real process
limit (``RLIMIT_NPROC``) is set in it just before its real pool starts, so the
operating system itself refuses the workers, whatever the start method.
Before it relies on that, the probe checks the limit is enforced by starting
a process under it. An operating system that does not enforce the limit for
this user (root does not count against it) skips the test with that reason:
an unenforced limit would prove nothing either way.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _worker_death_probe as probe
from tests._cli_child import child_env, run_codeclone

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="RLIMIT_NPROC is a POSIX process limit"
)

_SCOPE_ID = "0f5c6f3d-9d2e-4a2a-9a5f-6b0f9a1a2b3c"
_RUN_DEADLINE_SECONDS = 120.0
_ENFORCED = "enforced"
_RUN_UNDER_PROCESS_LIMIT = """
import resource
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import codeclone.core.parallelism as parallelism
import codeclone.core.worker_recovery as worker_recovery
from codeclone.main import main
from tests import _worker_death_probe as probe

PROBE = Path(sys.argv[1])
WHEN = sys.argv[2]


def limit_to_one_process():
    _soft, hard = resource.getrlimit(resource.RLIMIT_NPROC)
    resource.setrlimit(resource.RLIMIT_NPROC, (1, hard))
    try:
        subprocess.run(["true"], check=False)
    except OSError:
        PROBE.write_text("enforced", "utf-8")
    else:
        PROBE.write_text("not enforced", "utf-8")


class LimitedPool(ProcessPoolExecutor):
    \"\"\"The real pool, started under a real limit of one process.\"\"\"

    def __init__(self, *args, **kwargs):
        if WHEN == "at-pool":
            limit_to_one_process()
        super().__init__(*args, **kwargs)


real_start_recovery = worker_recovery._start_recovery_process


def limited_recovery(args):
    \"\"\"The real recovery process, started under the same real limit.\"\"\"

    limit_to_one_process()
    return real_start_recovery(args)


if __name__ == "__main__":
    parallelism.ProcessPoolExecutor = LimitedPool
    if WHEN == "at-start":
        limit_to_one_process()
    if WHEN == "at-recovery":
        # A worker dies on the marked file; the pool itself runs unlimited.
        parallelism._invoke_process_file = probe.die_once_in_worker
        worker_recovery._start_recovery_process = limited_recovery
    sys.argv = ["codeclone", *sys.argv[3:]]
    main()
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n', "utf-8"
    )
    for index in range(17):
        (root / f"m{index:02d}.py").write_text(
            f"def unused_{index}(value):\n    return value + {index}\n", "utf-8"
        )
    published = run_codeclone(
        tmp_path, str(root), "--update-baseline", "--no-progress", "--processes", "1"
    )
    assert published.returncode == 0, published.stdout + published.stderr
    return root


def _run_under_process_limit(
    tmp_path: Path, *args: str, when: str = "at-pool"
) -> subprocess.CompletedProcess[str]:
    """The CLI in its own session, under a limit of one process set ``when``
    -- just before its pool starts, or as it starts. Its own session, so a
    run that never ends is ended with every process it started, not left
    behind when the test gives up."""

    probe = tmp_path / "limit-probe.txt"
    script = tmp_path / "run_under_process_limit.py"
    script.write_text(_RUN_UNDER_PROCESS_LIMIT, "utf-8")
    command = [sys.executable, str(script), str(probe), when, *args]
    with subprocess.Popen(
        command,
        cwd=str(tmp_path),
        env=child_env(tmp_path),
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
    # Nothing the run started outlives it: its process group is empty.
    with pytest.raises(ProcessLookupError):
        os.killpg(child.pid, 0)
    if not probe.is_file():
        pytest.fail("the pool never started: the probe proves nothing\n" + stdout)
    if probe.read_text("utf-8") != _ENFORCED:
        pytest.skip("the operating system does not enforce RLIMIT_NPROC here")
    return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)


def _parallel_run(
    tmp_path: Path, project: Path, *flags: str, when: str
) -> tuple[subprocess.CompletedProcess[str], str]:
    """A two-worker run of ``project`` under the limit set ``when``, with a
    fresh cache, and its output with the console's wrapping undone -- the
    checks read the words, not the layout."""

    run = _run_under_process_limit(
        tmp_path,
        str(project),
        "--processes",
        "2",
        "--no-progress",
        "--cache-path",
        str(tmp_path / "fresh-cache.db"),
        *flags,
        when=when,
    )
    return run, " ".join((run.stdout + run.stderr).split())


def _says(output: str, *, words: tuple[str, ...], never: tuple[str, ...]) -> None:
    """The output says every one of ``words``, in that order, and none of
    ``never``."""

    positions = [output.find(word) for word in words]
    assert -1 not in positions, (words, output)
    assert positions == sorted(positions), (words, output)
    assert [word for word in never if word in output] == [], output


def _verdict_words(output: str) -> list[str]:
    return re.findall(r"\b(?:PASS|ACCEPTED|COMPLETE)\b", output)


@pytest.mark.parametrize(
    "flags",
    [[], ["--patch-verify"], ["--update-baseline"], ["--ci"]],
    ids=["plain", "patch-verify", "update-baseline", "ci"],
)
def test_a_pool_the_operating_system_refuses_is_unverified(
    tmp_path: Path, project: Path, flags: list[str]
) -> None:
    baseline = project / "codeclone.baseline.json"
    before = baseline.read_bytes()
    report = tmp_path / "report.json"
    # A patch verification is terminal-only and refuses report flags; every
    # other run asks for a report, so its absence is evidence.
    report_flags = [] if "--patch-verify" in flags else ["--json", str(report)]

    run, output = _parallel_run(
        tmp_path, project, *report_flags, *flags, when="at-pool"
    )

    assert run.returncode == 4, output
    _says(
        output,
        words=(
            "UNVERIFIED",
            "Could not start the worker process pool",
            "--processes 1",
        ),
        never=("INTERNAL ERROR", "CONTRACT ERROR"),
    )
    assert _verdict_words(output) == [], output
    assert "accepted" not in output.lower(), output
    assert not report.exists()
    assert baseline.read_bytes() == before


def test_a_crash_then_a_refused_recovery_is_internal_and_keeps_both_causes(
    tmp_path: Path, project: Path
) -> None:
    """A worker died for an unknown cause, then the operating system refused
    the recovery process (a real limit, set just before it starts). Exit 5,
    never 4 -- the first failure is unexplained -- and the error keeps both
    failures, the crash first, with no sequential-mode step offered as the
    fix (maintainer law 2026-10-26: a secondary failure must not erase the
    primary one)."""

    (project / f"{probe.WORKER_KILLER_PREFIX}_mod.py").write_text(
        "def killer():\n    return 0\n", "utf-8"
    )
    (tmp_path / probe.PROBE_DIR_NAME).mkdir()

    run, output = _parallel_run(tmp_path, project, when="at-recovery")

    assert run.returncode == 5, output
    # The crash first, then why the recovery failed.
    _says(
        output,
        words=(
            "INTERNAL ERROR",
            "worker crashed (cause unknown)",
            "recovery process could not start",
            "Resource temporarily unavailable",
        ),
        never=("UNVERIFIED", "--processes 1"),
    )


def test_the_step_it_names_works_under_the_same_limit(
    tmp_path: Path, project: Path
) -> None:
    """Positive control, and the remedy proven where it is offered: the same
    tree under the same limit -- set before the run even starts -- analyses
    completely in explicit sequential mode, which never needs a process."""

    report = tmp_path / "report.json"
    run = _run_under_process_limit(
        tmp_path,
        str(project),
        "--processes",
        "1",
        "--no-progress",
        "--json",
        str(report),
        when="at-start",
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert report.is_file()
