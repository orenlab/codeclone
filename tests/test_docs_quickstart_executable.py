# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The README quick start, run as written.

Step 2 of the quick start is the first thing a new user runs against their own
repository. When the sequence stops working -- a configuration key the command
now requires, a renamed subcommand -- the reader meets an exit code where the
README promised a baseline. So the commands are read out of ``README.md`` and
run, in order, on a temporary project: the text is the test input, and a
README edit that breaks the sequence fails here.

Step 2 needs the 2.1 alpha, and says so: its heading carries the release line
and the section opens with the install of the exact prerelease in
``pyproject.toml``. That install is the one command here that is never run --
it fetches the published package, and the test runs this checkout instead --
so it sits in its own block, and the section is pinned to exactly those two
blocks, which leaves no third one to go unexecuted in silence.

The upgrade guide quotes the refusal that sends a reader to that first step,
and it is held to the CLI's own rendering of it here, beside the README pin
on the same constant.
"""

from __future__ import annotations

import importlib
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from codeclone.ui_messages.formatters import fmt_baseline_scope_id_required
from codeclone.ui_messages.runtime import HINT_SCOPE_ID_SETUP_COMMAND

_REPO_ROOT = Path(__file__).resolve().parents[1]
_README = _REPO_ROOT / "README.md"
_PYPI_README = _REPO_ROOT / "docs" / "README-pypi.md"
_SECTION_HEADING = "### 2. Record the current structural baseline"
_ALPHA_RELEASE = re.compile(r"(\d+)\.(\d+)\.\d+a\d+")
_UPGRADE_GUIDE = _REPO_ROOT / "docs" / "guides" / "migration-a1-a2.md"
_SCOPE_ID_SECTION = "## `baseline_scope_id` is now required"
# The example values of the refusal the upgrade guide quotes: the page shows
# these two, the CLI generates its own UUID and names the real file.
_GUIDE_EXAMPLE_CONFIG = Path("/srv/acme/pyproject.toml")
_GUIDE_EXAMPLE_SCOPE_ID = UUID("0f5c6f3d-9d2e-4a2a-9a5f-6b0f9a1a2b3c")

#: The quick start exactly as a new user types it. Changing the README block
#: means changing this too -- and then the sequence below has to run.
_EXPECTED_COMMANDS = (
    "codeclone setup apply -y",
    "codeclone . --update-baseline",
    "git add pyproject.toml .gitignore codeclone.baseline.json",
    'git commit -m "chore: add CodeClone structural baseline"',
)

# A throwaway identity with no user or system git configuration, so a signing
# key, a global hook or a template on the host cannot change what the quick
# start does here.
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Quick Start",
    "GIT_AUTHOR_EMAIL": "quickstart@example.invalid",
    "GIT_COMMITTER_NAME": "Quick Start",
    "GIT_COMMITTER_EMAIL": "quickstart@example.invalid",
}


def _project_version() -> str:
    toml = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    pyproject = toml.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(pyproject["project"]["version"])


def _alpha_marker(version: str) -> str:
    """``2.1.0a2`` -> ``CodeClone 2.1 alpha``; a non-alpha version has none."""

    release = _ALPHA_RELEASE.fullmatch(version)
    assert release is not None, (
        f"project.version {version!r} is not an alpha: README step 2 is marked "
        "alpha and installs a prerelease, so it has to be rewritten, not re-pinned"
    )
    return f"CodeClone {release.group(1)}.{release.group(2)} alpha"


def _alpha_install_line(version: str) -> str:
    return f'uv tool install --prerelease allow "codeclone=={version}"'


def _step_two_section() -> tuple[str, str]:
    """The heading line of step 2 and the text under it, up to step 3."""

    text = _README.read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith(_SECTION_HEADING)]
    assert len(headings) == 1, headings
    start = text.index(headings[0])
    end = text.index("\n### ", start + len(headings[0]))
    return headings[0], text[start:end]


def _step_two_blocks() -> list[tuple[str, ...]]:
    _heading, section = _step_two_section()
    return [
        tuple(line.strip() for line in block.splitlines() if line.strip())
        for block in re.findall(r"```bash\n(.*?)```", section, re.DOTALL)
    ]


def _readme_commands() -> tuple[str, ...]:
    """The sequence the test runs: the block after the alpha install."""

    blocks = _step_two_blocks()
    assert len(blocks) == 2, f"step 2 must hold the install and the sequence: {blocks}"
    return blocks[1]


def _argv(command: str, *, cache_path: Path) -> list[str]:
    """Run ``codeclone`` from this checkout; keep analysis caches in tmp."""

    argv = shlex.split(command)
    if argv[0] != "codeclone":
        return argv
    runnable = [sys.executable, "-m", "codeclone.main", *argv[1:]]
    if argv[1] == "setup":
        return runnable
    return [*runnable, "--cache-path", str(cache_path)]


def test_readme_quick_start_sequence_is_pinned() -> None:
    commands = _readme_commands()

    assert commands == _EXPECTED_COMMANDS
    # The refusal of ``--update-baseline`` names the same first step.
    assert commands[0] == HINT_SCOPE_ID_SETUP_COMMAND


def test_readme_step_two_names_the_alpha_it_needs() -> None:
    """Heading marker and install line both follow ``project.version``.

    The version is read from ``pyproject.toml`` on every run and never written
    here, so a release bump reddens the README until its install line names
    the new prerelease -- and a stable release reddens it until the alpha
    marker is gone.
    """

    version = _project_version()
    heading, _section = _step_two_section()
    install = _alpha_install_line(version)

    assert heading == f"{_SECTION_HEADING} — {_alpha_marker(version)}"
    # First block: the install, never executed (see the module docstring).
    assert _step_two_blocks()[0] == (install,)
    # The PyPI page carries the same two-step split with the same install.
    assert install in _PYPI_README.read_text(encoding="utf-8")


def test_upgrade_guide_quotes_the_scope_id_refusal_the_cli_prints() -> None:
    """The quoted refusal is the CLI's own, rendered from its constants.

    The guide quotes what ``codeclone . --update-baseline`` prints without a
    ``baseline_scope_id``. That quote went stale once: the refusal learned to
    name ``codeclone setup apply -y`` as its first step and the page kept the
    older paste-only text. The expectation is rendered here by the CLI's own
    formatter from the ``ui_messages.runtime`` constants, for the case the page
    shows -- an existing ``[tool.codeclone]`` table -- and compared with line
    wrapping ignored, so a reworded constant reddens the page.
    """

    text = _UPGRADE_GUIDE.read_text(encoding="utf-8")
    start = text.index(_SCOPE_ID_SECTION)
    end = text.index("\n## ", start + len(_SCOPE_ID_SECTION))
    refusal = fmt_baseline_scope_id_required(
        table_state="existing_section",
        config_path=_GUIDE_EXAMPLE_CONFIG,
        scope_id=_GUIDE_EXAMPLE_SCOPE_ID,
    )

    # The case the page shows is one where setup can write the key.
    assert HINT_SCOPE_ID_SETUP_COMMAND in refusal
    assert " ".join(refusal.split()) in " ".join(text[start:end].split())


def _new_git_project(root: Path, *, env: dict[str, str]) -> Path:
    """A reader's repository before the quick start: one module, no config."""

    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (root / "demo.py").write_text(
        "def answer() -> int:\n    return 42\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True)
    return root


def test_readme_quick_start_runs_as_written(tmp_path: Path) -> None:
    env = {**os.environ, **_GIT_ENV}
    project = _new_git_project(tmp_path / "project", env=env)
    cache_path = tmp_path / "cache" / "cache.sqlite3"

    for command in _readme_commands():
        completed = subprocess.run(
            _argv(command, cache_path=cache_path),
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, (
            f"{command!r} exited {completed.returncode}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )

    assert (project / "codeclone.baseline.json").is_file()
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert {"pyproject.toml", ".gitignore", "codeclone.baseline.json"} <= set(tracked)
