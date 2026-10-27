# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The GitHub Action publishes only the reports this run wrote.

A pull request can commit ``.cache/codeclone/report.json`` and
``report.sarif`` and make the analysis stop before it writes anything -- a
``pyproject.toml`` path the run refuses is enough. The Action then announced
the committed files as this run's reports: the PR comment was rendered from the
planted JSON and the planted SARIF went to code scanning. The tests run
``run_codeclone.py`` and ``render_pr_comment.py`` the way ``action.yml`` does,
with the real ``codeclone`` command.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest
import yaml  # type: ignore[import-untyped]

_ACTION = Path(__file__).resolve().parents[1] / ".github" / "actions" / "codeclone"
_CODECLONE = Path(sys.executable).with_name("codeclone")
_JSON = ".cache/codeclone/report.json"
_SARIF = ".cache/codeclone/report.sarif"
_PLANTED = "planted-by-the-pull-request"
_INPUT = re.compile(r"\$\{\{\s*inputs\.([A-Za-z0-9_-]+)\s*\}\}")

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="the Action's run steps are exercised with POSIX paths"
)


def _analysis_env(**overrides: str) -> dict[str, str]:
    """The analysis step's ``env:`` with the Action's default inputs filled in."""

    action = yaml.safe_load((_ACTION / "action.yml").read_text(encoding="utf-8"))
    inputs = {
        name: str(spec.get("default", "")) for name, spec in action["inputs"].items()
    }
    inputs.update(overrides)
    (step,) = [step for step in action["runs"]["steps"] if step.get("id") == "analysis"]
    return {
        name: _INPUT.sub(lambda match: inputs[match.group(1)], str(value))
        for name, value in step["env"].items()
    }


def _runner_env(runner_temp: Path) -> dict[str, str]:
    assert _CODECLONE.is_file(), "the Action runs the installed codeclone command"
    (runner_temp / "home").mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.pathsep.join((str(_CODECLONE.parent), os.defpath)),
        "HOME": str(runner_temp / "home"),
        # The workspace sits in this process's temporary directory. codeclone
        # refuses to scan under system directories such as /private/var (the
        # macOS temporary root) unless the root is inside its own temporary
        # directory, so the run shares it; a runner's workspace needs no such
        # exemption.
        "TMPDIR": tempfile.gettempdir(),
    }


def _read_outputs(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return dict(line.split("=", 1) for line in lines)


def _run_action(
    workspace: Path, runner_temp: Path, **inputs: str
) -> tuple[dict[str, str], str | None]:
    """Run the analysis step, then the PR summary step when the Action would.

    Returns the analysis step's outputs and the rendered comment, if any.
    """

    runner = _runner_env(runner_temp)
    analysis_output = runner_temp / "analysis-output"
    subprocess.run(
        [sys.executable, str(_ACTION / "run_codeclone.py")],
        cwd=workspace,
        env={
            **runner,
            **_analysis_env(**inputs),
            "GITHUB_OUTPUT": str(analysis_output),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    outputs = _read_outputs(analysis_output)
    if outputs.get("json-exists") != "true":
        return outputs, None
    comment = runner_temp / "codeclone-pr-comment.md"
    subprocess.run(
        [sys.executable, str(_ACTION / "render_pr_comment.py")],
        cwd=workspace,
        env={
            **runner,
            "REPORT_PATH": outputs["json-path"],
            "ANALYSIS_EXIT_CODE": outputs["exit-code"],
            "COMMENT_OUTPUT_PATH": str(comment),
            "GITHUB_OUTPUT": str(runner_temp / "render-output"),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return outputs, comment.read_text(encoding="utf-8")


def _workspace(tmp_path: Path, *, planted: bool, refused: bool) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "pkg").mkdir(parents=True)
    (workspace / "pkg" / "a.py").write_text(
        "def f(x):\n    return x + 1\n", encoding="utf-8"
    )
    if refused:
        # Any early refusal does; this one needs nothing but the repository.
        (workspace / "pyproject.toml").write_text(
            '[tool.codeclone]\nbaseline = "../outside.json"\n', encoding="utf-8"
        )
    if planted:
        (workspace / ".cache" / "codeclone").mkdir(parents=True)
        (workspace / _JSON).write_text(
            json.dumps(
                {
                    "meta": {"codeclone_version": _PLANTED},
                    "metrics": {"summary": {"health": {"score": 100, "grade": "A"}}},
                }
            ),
            encoding="utf-8",
        )
        (workspace / _SARIF).write_text(
            json.dumps(
                {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": _PLANTED}}}]}
            ),
            encoding="utf-8",
        )
    return workspace


def test_committed_reports_are_not_published_when_the_run_writes_none(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, planted=True, refused=True)

    outputs, comment = _run_action(
        workspace, tmp_path / "runner", **{"fail-on-new": "false"}
    )

    assert outputs["exit-code"] == "2"
    assert (outputs["json-exists"], outputs["sarif-exists"], comment) == (
        "false",
        "false",
        None,
    )


def test_fresh_reports_over_committed_ones_are_published(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, planted=True, refused=False)

    outputs, comment = _run_action(
        workspace, tmp_path / "runner", **{"fail-on-new": "false"}
    )

    assert outputs["exit-code"] == "0"
    assert (outputs["json-exists"], outputs["sarif-exists"]) == ("true", "true")
    assert comment is not None
    assert _PLANTED not in comment
    assert _PLANTED not in (workspace / _JSON).read_text(encoding="utf-8")
    assert _PLANTED not in (workspace / _SARIF).read_text(encoding="utf-8")


def test_fresh_reports_with_nothing_committed_are_published(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, planted=False, refused=False)

    outputs, comment = _run_action(
        workspace, tmp_path / "runner", **{"fail-on-new": "false"}
    )

    assert (outputs["json-exists"], outputs["sarif-exists"]) == ("true", "true")
    assert comment is not None
    assert "## CodeClone Review" in comment


def _load_action_impl() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "codeclone_action_impl_freshness", _ACTION / "_action_impl.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_report_that_could_not_be_observed_before_the_run_is_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A failed look before the run is not evidence that the file was absent:
    # whatever is there afterwards cannot be shown to be this run's.
    workspace = _workspace(tmp_path, planted=True, refused=False)
    action_impl = _load_action_impl()
    runner = _runner_env(tmp_path / "runner")
    for name, value in {**runner, **_analysis_env(**{"fail-on-new": "false"})}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(workspace)
    original_stat = Path.stat
    unobserved: set[str] = {_JSON, _SARIF}

    def _stat(self: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if str(self) in unobserved:
            unobserved.discard(str(self))
            raise PermissionError(13, "Permission denied", str(self))
        return original_stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", _stat)

    result = action_impl.run_codeclone(
        action_impl.build_inputs_from_env(dict(os.environ))
    )

    assert unobserved == set(), "the probe never reached the look before the run"
    assert result.exit_code == 0
    assert _PLANTED not in (workspace / _JSON).read_text(encoding="utf-8")
    assert (result.json_exists, result.sarif_exists) == (False, False)
