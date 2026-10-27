# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""No value an outsider controls is pasted into a script by a workflow.

GitHub substitutes ``${{ ... }}`` into a step's ``run:`` text (and into an
``actions/github-script`` ``script:``) before the shell reads it, so a release
tag, a pull-request field or a dispatch input placed there is code, not data.
Such values reach a script only through ``env:`` and are read as quoted shell
variables. The scan below allows a short list of sources the runner or this
repository produces; everything else inside a script is a finding.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)

# Sources a script may read directly: the runner names the event and the
# action's own checkout; a matrix is allowed only while it is written out
# literally in the same file (checked below); the Action's exit code is the
# integer its own analysis step wrote.
_TRUSTED_SOURCES = (
    re.compile(r"github\.event_name"),
    re.compile(r"github\.action_path"),
    re.compile(r"matrix\.[A-Za-z_][A-Za-z0-9_-]*"),
    re.compile(r"steps\.analysis\.outputs\.exit-code"),
)

# GitHub runs ``shell: bash`` steps as ``bash --noprofile --norc -eo pipefail``.
_GITHUB_BASH = ("bash", "--noprofile", "--norc", "-eo", "pipefail")


def _workflow_files() -> list[Path]:
    workflows = sorted((_REPO / ".github" / "workflows").glob("*.yml"))
    actions = sorted((_REPO / ".github" / "actions").glob("*/action.yml"))
    assert workflows, "no workflow found: the scan would pass on nothing"
    assert actions, "no action found: the scan would pass on nothing"
    return [*workflows, *actions]


def _scripts(node: object, where: str) -> Iterator[tuple[str, str]]:
    """Every script text in a workflow or action document, with its location."""

    if isinstance(node, Mapping):
        run = node.get("run")
        if isinstance(run, str):
            yield f"{where}.run", run
        uses = node.get("uses")
        with_block = node.get("with")
        if (
            isinstance(uses, str)
            and uses.startswith("actions/github-script@")
            and isinstance(with_block, Mapping)
            and isinstance(with_block.get("script"), str)
        ):
            yield f"{where}.with.script", with_block["script"]
        for key, value in node.items():
            yield from _scripts(value, f"{where}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _scripts(value, f"{where}[{index}]")


def _matrix_is_literal(document: object) -> bool:
    text = yaml.safe_dump(
        [
            job.get("strategy", {}).get("matrix")
            for job in (
                document.get("jobs", {}).values()
                if isinstance(document, Mapping)
                else ()
            )
            if isinstance(job, Mapping)
        ]
    )
    return "${{" not in text


def untrusted_script_expressions(document: object) -> list[str]:
    """``location: ${{ expression }}`` for every untrusted source in a script."""

    matrix_literal = _matrix_is_literal(document)
    findings: list[str] = []
    for where, script in _scripts(document, "$"):
        for match in _EXPRESSION.finditer(script):
            expression = match.group(1).strip()
            trusted = any(
                source.fullmatch(expression) for source in _TRUSTED_SOURCES
            ) and (matrix_literal or not expression.startswith("matrix."))
            if not trusted:
                findings.append(f"{where}: ${{{{ {expression} }}}}")
    return findings


def test_no_workflow_pastes_an_untrusted_value_into_a_script() -> None:
    findings = {
        str(path.relative_to(_REPO)): found
        for path in _workflow_files()
        if (
            found := untrusted_script_expressions(
                yaml.safe_load(path.read_text(encoding="utf-8"))
            )
        )
    }

    assert findings == {}


_PROBE_WORKFLOW = """
on: [release, workflow_dispatch, pull_request]
jobs:
  probe:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        profile: ${{ fromJSON(inputs.profiles) }}
    steps:
      - run: echo "${{ github.event.release.tag_name }}"
      - run: echo "${{ github.head_ref }}" "${{ inputs.profile }}"
      - run: echo "${{ github.event.pull_request.title }}" "${{ matrix.profile }}"
      - uses: actions/github-script@v7
        with:
          script: core.info("${{ github.event.issue.title }}")
      - env:
          RELEASE_TAG: ${{ github.event.release.tag_name }}
        if: ${{ github.event_name == 'release' }}
        run: echo "$RELEASE_TAG" "${{ github.event_name }}" "${{ github.action_path }}"
"""


def test_the_scan_sees_untrusted_values_and_spares_env_and_trusted_sources() -> None:
    # A positive control for the pin above: the scan must find each kind of
    # pasted value it claims to forbid, and nothing that goes through env:.
    assert untrusted_script_expressions(yaml.safe_load(_PROBE_WORKFLOW)) == [
        "$.jobs.probe.steps[0].run: ${{ github.event.release.tag_name }}",
        "$.jobs.probe.steps[1].run: ${{ github.head_ref }}",
        "$.jobs.probe.steps[1].run: ${{ inputs.profile }}",
        "$.jobs.probe.steps[2].run: ${{ github.event.pull_request.title }}",
        "$.jobs.probe.steps[2].run: ${{ matrix.profile }}",
        "$.jobs.probe.steps[3].with.script: ${{ github.event.issue.title }}",
    ]


def _release_tag_step() -> tuple[str, dict[str, str]]:
    document = yaml.safe_load(
        (_REPO / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    )
    steps = [
        step
        for job in document["jobs"].values()
        for step in job["steps"]
        if step.get("name") == "Verify release tag matches project version"
    ]
    assert len(steps) == 1
    step = steps[0]
    assert step["shell"] == "bash"
    return step["run"], dict(step.get("env") or {})


def _render(text: str, context: Mapping[str, str]) -> str:
    """Substitute ``${{ name }}`` the way GitHub does, before any shell runs."""

    def _value(match: re.Match[str]) -> str:
        return context[match.group(1).strip()]

    return _EXPRESSION.sub(_value, text)


def _run_release_tag_check(
    tmp_path: Path, tag: str
) -> subprocess.CompletedProcess[str]:
    script, step_env = _release_tag_step()
    context = {"github.event.release.tag_name": tag}
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "probe"\nversion = "2.0.3"\n', encoding="utf-8"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python").symlink_to(sys.executable)
    script_path = tmp_path / "step.sh"
    script_path.write_text(_render(script, context), encoding="utf-8")
    return subprocess.run(
        [*_GITHUB_BASH, str(script_path)],
        cwd=tmp_path,
        env={
            "PATH": os.pathsep.join((str(bin_dir), os.defpath)),
            "HOME": str(tmp_path),
            **{name: _render(str(value), context) for name, value in step_env.items()},
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.mark.skipif(os.name == "nt", reason="the release job runs bash on Linux")
@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="the release job runs Python 3.14; its step needs tomllib",
)
def test_release_tag_check_reads_the_tag_as_data(tmp_path: Path) -> None:
    # A tag may carry `$(...)`: pasted into the script, the shell ran it.
    result = _run_release_tag_check(tmp_path, "v2.0.3$(touch${IFS}tag-ran)")

    assert not (tmp_path / "tag-ran").exists()
    assert result.returncode == 1
    assert "release tag v2.0.3$(touch${IFS}tag-ran) does not match" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="the release job runs bash on Linux")
@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="the release job runs Python 3.14; its step needs tomllib",
)
@pytest.mark.parametrize(
    ("tag", "returncode"),
    [
        pytest.param("v2.0.3", 0, id="matching-tag-passes"),
        pytest.param("2.0.3", 0, id="tag-without-v-passes"),
        pytest.param("v2.0.4", 1, id="other-version-stops"),
    ],
)
def test_release_tag_check_still_compares_the_tag_with_the_version(
    tmp_path: Path, tag: str, returncode: int
) -> None:
    result = _run_release_tag_check(tmp_path, tag)

    assert result.returncode == returncode, result.stderr


def _run_benchmark_gate(tmp_path: Path, context: Mapping[str, str]) -> str:
    document = yaml.safe_load(
        (_REPO / ".github" / "workflows" / "benchmark.yml").read_text(encoding="utf-8")
    )
    (step,) = [
        step
        for step in document["jobs"]["benchmark"]["steps"]
        if step.get("name") == "Resolve run profile gate"
    ]
    github_env = tmp_path / "github-env"
    github_env.write_text("", encoding="utf-8")
    script_path = tmp_path / "gate.sh"
    script_path.write_text(_render(step["run"], context), encoding="utf-8")
    subprocess.run(
        [*_GITHUB_BASH, str(script_path)],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "GITHUB_ENV": str(github_env),
            **{
                name: _render(str(value), context)
                for name, value in (step.get("env") or {}).items()
            },
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return github_env.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="the benchmark gate runs bash")
@pytest.mark.parametrize(
    ("event", "matrix_profile", "dispatch_profile", "enabled"),
    [
        pytest.param("workflow_dispatch", "extended", "extended", "1", id="chosen"),
        pytest.param("workflow_dispatch", "smoke", "extended", "0", id="not-chosen"),
        pytest.param("push", "smoke", "", "1", id="push-smoke"),
        pytest.param("push", "extended", "", "0", id="push-extended"),
        pytest.param(
            "workflow_dispatch",
            "extended",
            "$(touch dispatch-ran)",
            "0",
            id="input-is-data",
        ),
    ],
)
def test_benchmark_gate_still_reads_the_dispatch_profile(
    tmp_path: Path, event: str, matrix_profile: str, dispatch_profile: str, enabled: str
) -> None:
    github_env = _run_benchmark_gate(
        tmp_path,
        {
            "github.event_name": event,
            "matrix.profile": matrix_profile,
            "inputs.profile": dispatch_profile,
        },
    )

    assert github_env == f"BENCH_ENABLED={enabled}\n"
    assert not (tmp_path / "dispatch-ran").exists()
