# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every run's settings reach its workers, whatever the start method.

On Linux with Python 3.14 the default start method is ``forkserver``. Its
server process is started once and keeps the state it started with, the
environment among them (measured 2026-10-26: a variable a test set after the
server started never reached the workers it forked). So a run's settings may
reach a worker only as arguments, never as state the server inherited.

Each case is its own controlling process, with the start method forced, and
runs two analyses back to back with different settings. Under ``forkserver``
the second analysis reuses the server the first one started, and its workers
must still apply the second analysis's settings.
"""

from __future__ import annotations

import json
import multiprocessing
import subprocess
import sys
from pathlib import Path

import pytest

from tests._cli_child import child_env

_FILES = 24
_RUN_TWO_ANALYSES = """
import json
import multiprocessing
import sys
from pathlib import Path

if __name__ == "__main__":
    method, root, work = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    multiprocessing.set_start_method(method, force=True)

    from concurrent.futures import ProcessPoolExecutor

    import codeclone.core.parallelism as parallelism
    from codeclone.cache.store import Cache
    from codeclone.core.discovery import discover
    from tests._pipeline_fixtures import analysis_boot

    pools = []

    class CountingPool(ProcessPoolExecutor):
        def __init__(self, *args, **kwargs):
            pools.append(kwargs.get("max_workers"))
            super().__init__(*args, **kwargs)

    parallelism.ProcessPoolExecutor = CountingPool

    def server_pid():
        if method != "forkserver":
            return None
        from multiprocessing import forkserver
        return forkserver._forkserver._forkserver_pid

    api_modules, analyzed, servers = [], [], []
    for api_surface in (False, True):
        boot = analysis_boot(
            root, min_loc=1, min_stmt=1, skip_metrics=False, api_surface=api_surface
        )
        boot.args.processes = 2
        cache = Cache(work / f"cache-{api_surface}.json", root=root)
        discovery = discover(boot=boot, cache=cache)
        result = parallelism.process(boot=boot, discovery=discovery, cache=cache)
        api_modules.append(len(result.api_modules))
        analyzed.append(result.files_analyzed)
        servers.append(server_pid())
    print(json.dumps({
        "method": multiprocessing.get_start_method(),
        "api_modules": api_modules,
        "analyzed": analyzed,
        "pools": pools,
        "servers": servers,
    }))
"""


@pytest.mark.parametrize(
    "method",
    [
        method
        for method in ("spawn", "forkserver", "fork")
        if method in multiprocessing.get_all_start_methods()
    ],
)
def test_the_second_analysis_settings_reach_its_workers(
    tmp_path: Path, method: str
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    for index in range(_FILES):
        (root / f"m{index:02d}.py").write_text(
            f"def unused_{index}(value):\n    return value + {index}\n", "utf-8"
        )
    work = tmp_path / "work"
    work.mkdir()
    script = tmp_path / "run_two_analyses.py"
    script.write_text(_RUN_TWO_ANALYSES, "utf-8")

    run = subprocess.run(
        [sys.executable, str(script), method, str(root), str(work)],
        cwd=str(tmp_path),
        env=child_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )

    assert run.returncode == 0, run.stdout + run.stderr
    outcome = json.loads(run.stdout.strip().splitlines()[-1])
    assert outcome["method"] == method
    # Probe validity: both analyses went through a pool of two workers, and
    # both analysed every file.
    assert outcome["pools"] == [2, 2]
    assert outcome["analyzed"] == [_FILES, _FILES]
    # The first analysis asks its workers for no API surface, the second for
    # one per module -- and the second's workers deliver it.
    assert outcome["api_modules"] == [0, _FILES]
    if method == "forkserver":
        # The second analysis ran on the server the first one started.
        first, second = outcome["servers"]
        assert first is not None and first == second
