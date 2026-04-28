from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests._contract_snapshots import load_text_snapshot


def test_cli_help_snapshot() -> None:
    root_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root_dir) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "codeclone.main", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.replace("\r\n", "\n") == load_text_snapshot("cli_help.txt")
