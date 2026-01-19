import subprocess
import sys
from pathlib import Path


def test_cli_runs(tmp_path: Path):
    src = tmp_path / "a.py"
    src.write_text(
        """
def f():
    x = 1
    y = 2
    return x + y
"""
    )

    result = subprocess.run(
        [sys.executable, "-m", "codeclone.cli", str(tmp_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Function clone groups" in result.stdout
