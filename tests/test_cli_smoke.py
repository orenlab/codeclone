import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path


def run_cli(
    args: Iterable[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    root_dir = Path(__file__).parents[1]
    env["PYTHONPATH"] = str(root_dir) + os.pathsep + env.get("PYTHONPATH", "")

    # Try to find venv python
    venv_python = root_dir / ".venv" / "bin" / "python"
    executable = str(venv_python) if venv_python.exists() else sys.executable

    return subprocess.run(
        [executable, "-m", "codeclone.cli", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
    )


def test_cli_runs(tmp_path: Path) -> None:
    src = tmp_path / "a.py"
    src.write_text(
        """
def f():
    x = 1
    y = 2
    return x + y
"""
    )

    result = run_cli([str(tmp_path)], cwd=tmp_path)

    assert result.returncode == 0
    assert "Analysis Summary" in result.stdout
    assert "Function clone groups" in result.stdout


def test_cli_baseline_missing_warning(tmp_path: Path) -> None:
    # Should print a warning when baseline is missing and --update-baseline is not set
    src = tmp_path / "a.py"
    src.write_text("def f(): pass")

    baseline_file = tmp_path / "missing.json"

    result = run_cli([str(tmp_path), "--baseline", str(baseline_file), "--no-progress"])

    assert result.returncode == 0
    assert "Baseline file not found at" in result.stdout
    assert baseline_file.name in result.stdout


def test_cli_update_baseline(tmp_path: Path) -> None:
    src = tmp_path / "a.py"
    # Create two identical functions to trigger a clone
    src.write_text("""
def f1():
    print("hello")
    return 1

def f2():
    print("hello")
    return 1
""")

    baseline_file = tmp_path / "codeclone.baseline.json"

    # Update baseline
    result = run_cli(
        [
            str(tmp_path),
            "--baseline",
            str(baseline_file),
            "--update-baseline",
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ]
    )

    assert result.returncode == 0
    assert "Baseline updated" in result.stdout
    assert baseline_file.exists()
    content = baseline_file.read_text()
    assert "functions" in content

    # Run again, check for no new clones
    result2 = run_cli(
        [
            str(tmp_path),
            "--baseline",
            str(baseline_file),
            "--fail-on-new",
            "--min-loc",
            "1",
            "--min-stmt",
            "1",
            "--no-progress",
        ]
    )
    assert result2.returncode == 0
    assert "New vs baseline" in result2.stdout
