# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import importlib.util
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTION_DIR = REPO_ROOT / ".github" / "actions" / "codeclone"
REQUIREMENTS = ACTION_DIR / "requirements.txt"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _requirements_tool() -> ModuleType:
    return _load(
        "codeclone_action_requirements",
        REPO_ROOT / "scripts" / "action_requirements.py",
    )


def _action_impl() -> ModuleType:
    return _load("codeclone_action_impl_lock", ACTION_DIR / "_action_impl.py")


def _toml(path: Path) -> dict[str, Any]:
    name = "tomllib" if sys.version_info >= (3, 11) else "tomli"
    loaded: dict[str, Any] = importlib.import_module(name).loads(
        path.read_text(encoding="utf-8")
    )
    return loaded


def _instant(value: str) -> datetime:
    # uv writes 1-6 fractional digits; Python 3.10 parses only 3 or 6.
    head, _, fraction = value.removesuffix("Z").partition(".")
    return datetime.fromisoformat(f"{head}.{fraction:0<6.6}+00:00")


def _project_version() -> str:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    return match.group(1)


def _copy_inputs(root: Path) -> None:
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(REPO_ROOT / name, root / name)
    target = root / ".github" / "actions" / "codeclone"
    target.mkdir(parents=True)
    shutil.copyfile(REQUIREMENTS, target / "requirements.txt")


def test_action_requirements_match_uv_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)

    assert _requirements_tool().main(["check"]) == 0


def test_action_requirements_pin_every_file_and_one_release_wheel() -> None:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    head = r"^([A-Za-z0-9_.-]+)==(\S+)(?: ; [^\\\n]+)? \\\n"
    hash_lines = r"((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)"
    blocks = re.findall(head + hash_lines, text, re.MULTILINE)
    requirement_lines = [
        line for line in text.splitlines() if line and not line.startswith(("#", " "))
    ]
    names = [name for name, _, _ in blocks]
    hash_count = {name: lines.count("--hash=") for name, _, lines in blocks}
    version = {name: ver for name, ver, _ in blocks}

    assert (len(blocks), names) == (len(requirement_lines), sorted(names))
    assert {"codeclone", "orjson", "packaging", "pygments", "rich"} <= set(names)
    assert (version["codeclone"], hash_count["codeclone"]) == (_project_version(), 1)
    assert min(hash_count.values()) >= 1


def test_action_requirements_check_reddens_when_the_lock_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    tool = _requirements_tool()
    assert tool.main(["check"]) == 0

    lock = tmp_path / "uv.lock"
    text = lock.read_text(encoding="utf-8")
    entry = re.search(r'name = "orjson"\nversion = "([^"]+)"', text)
    assert entry is not None
    lock.write_text(
        text.replace(entry.group(0), 'name = "orjson"\nversion = "0.0.0"'),
        encoding="utf-8",
    )

    assert tool.main(["check"]) == 1


def test_action_requirements_check_reddens_when_the_version_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            f'version = "{_project_version()}"', 'version = "9.9.9"'
        ),
        encoding="utf-8",
    )

    assert _requirements_tool().main(["check"]) == 1


def test_verify_wheel_accepts_only_the_pinned_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    tool = _requirements_tool()
    wheel = tmp_path / "dist" / f"codeclone-{_project_version()}-py3-none-any.whl"
    wheel.parent.mkdir()
    wheel.write_bytes(b"release wheel bytes")
    (tmp_path / ".github" / "actions" / "codeclone" / "requirements.txt").write_text(
        tool.render(tmp_path, hashlib.sha256(wheel.read_bytes()).hexdigest()),
        encoding="utf-8",
    )
    renamed = tmp_path / "dist" / "codeclone-0.0.0-py3-none-any.whl"
    renamed.write_bytes(wheel.read_bytes())

    accepted = tool.main(["verify-wheel", str(wheel)])
    wrong_name = tool.main(["verify-wheel", str(renamed)])
    wheel.write_bytes(b"release wheel bytez")
    wrong_bytes = tool.main(["verify-wheel", str(wheel)])

    assert (accepted, wrong_name, wrong_bytes) == (0, 1, 1)


def test_resolve_install_target_locks_only_the_shipped_version(
    tmp_path: Path,
) -> None:
    impl = _action_impl()
    workspace = tmp_path / "consumer"
    workspace.mkdir()
    action_path = tmp_path / "_actions" / "orenlab" / "codeclone" / "v2"
    action_path = action_path / ".github" / "actions" / "codeclone"
    action_path.mkdir(parents=True)
    repo_root = tmp_path / "codeclone"
    repo_action = repo_root / ".github" / "actions" / "codeclone"
    repo_action.mkdir(parents=True)
    shipped = impl.DEFAULT_CODECLONE_PACKAGE_VERSION
    locked = str(action_path / impl.LOCKED_REQUIREMENTS_FILE)

    def requirements_for(path: Path, root: Path, version: str) -> str:
        target = impl.resolve_install_target(
            action_path=str(path), workspace=str(root), package_version=version
        )
        return str(target.requirements_file)

    resolved = (
        requirements_for(action_path, workspace, ""),
        requirements_for(action_path, workspace, f" {shipped} "),
        requirements_for(action_path, workspace, "2.0.0"),
        requirements_for(repo_action, repo_root, ""),
    )

    assert resolved == (locked, locked, "", "")


def test_locked_requirements_file_ships_next_to_the_action() -> None:
    impl = _action_impl()
    tool = _requirements_tool()

    action_file_name: str = impl.LOCKED_REQUIREMENTS_FILE
    tool_path: Path = tool.REQUIREMENTS_PATH

    assert action_file_name == tool_path.name
    assert ACTION_DIR / action_file_name == REPO_ROOT / tool_path
    assert REQUIREMENTS.is_file()


def test_action_install_step_installs_the_locked_set_by_hash() -> None:
    action = (ACTION_DIR / "action.yml").read_text(encoding="utf-8")
    install = action.split("- name: Install CodeClone", 1)[1].split("- name:", 1)[0]

    assert '"install-requirements": target.requirements_file,' in action
    output = "${{ steps.resolve-install.outputs.install-requirements }}"
    assert f"INSTALL_REQUIREMENTS: {output}" in install
    locked_branch = install.split('if [ -n "${INSTALL_REQUIREMENTS}" ]; then', 1)[1]
    locked_branch = locked_branch.split("else", 1)[0]
    command = " ".join(locked_branch.replace("\\\n", " ").split())
    assert (
        "python -m pip install --require-hashes --only-binary :all: "
        '--disable-pip-version-check -r "${INSTALL_REQUIREMENTS}"'
    ) in command


def test_release_build_is_reproducible_and_gated_on_the_pinned_wheel() -> None:
    publish = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    steps = publish.split("- name: ")
    names = [step.split("\n", 1)[0] for step in steps]
    build = steps[names.index("Build distributions")]
    gate = names.index("Verify the wheel is the one the GitHub Action pins")
    constraints = (REPO_ROOT / ".github" / "release-build-constraints.txt").read_text(
        encoding="utf-8"
    )
    pins = re.findall(
        r"^([A-Za-z0-9_.-]+)==\S+ \\\n    --hash=sha256:", constraints, re.MULTILINE
    )

    recipe = (
        'SOURCE_DATE_EPOCH: "315532800"',
        "umask 0022",
        "find codeclone -type f -exec chmod 0644 {} +",
        "chmod 0644 pyproject.toml LICENSE LICENSE-MIT docs/README-pypi.md",
        "--build-constraints .github/release-build-constraints.txt",
        "--require-hashes",
    )

    assert [part for part in recipe if part not in build] == []
    assert (
        names.index("Build distributions") < gate < names.index("Upload distributions")
    )
    assert (
        "python scripts/action_requirements.py verify-wheel dist/codeclone-*.whl"
        in steps[gate]
    )
    assert {"setuptools", "wheel"} <= set(pins)


def test_runtime_dependencies_stop_below_the_next_major_of_the_lock() -> None:
    project = _toml(REPO_ROOT / "pyproject.toml")["project"]
    locked = {
        package["name"]: package["version"]
        for package in _toml(REPO_ROOT / "uv.lock")["package"]
    }
    caps = {}
    for requirement in project["dependencies"]:
        match = re.fullmatch(
            r"([A-Za-z0-9_.-]+)>=([0-9][^,]*),<([0-9]+)(?:; .+)?", requirement
        )
        assert match is not None, requirement
        name, _floor, cap = match.groups()
        caps[name] = (int(cap), int(locked[name].split(".")[0]) + 1)

    assert {name: cap for name, (cap, _) in caps.items()} == {
        name: next_major for name, (_, next_major) in caps.items()
    }
    assert set(caps) == {"orjson", "packaging", "pygments", "rich", "tomli"}


def test_locked_files_respect_the_quarantine_cutoffs() -> None:
    instant = _instant
    uv = _toml(REPO_ROOT / "pyproject.toml")["tool"]["uv"]
    lock = _toml(REPO_ROOT / "uv.lock")
    exceptions = {name: instant(at) for name, at in uv["exclude-newer-package"].items()}
    cutoff = instant(uv["exclude-newer"])
    late = []
    for package in lock["package"]:
        files = [*package.get("wheels", []), *filter(None, [package.get("sdist")])]
        limit = exceptions.get(package["name"], cutoff)
        late += [
            (package["name"], package["version"])
            for file in files
            if "upload-time" in file and instant(file["upload-time"]) >= limit
        ]
    newest_exception = {
        name: max(
            instant(file["upload-time"])
            for package in lock["package"]
            if package["name"] == name
            for file in package.get("wheels", [])
        )
        for name in exceptions
    }

    assert lock["options"]["exclude-newer"] == uv["exclude-newer"]
    assert lock["options"]["exclude-newer-package"] == uv["exclude-newer-package"]
    assert late == []
    assert [name for name, at in newest_exception.items() if at < cutoff] == []


def test_every_action_reference_is_pinned_to_a_full_commit() -> None:
    files = [
        ACTION_DIR / "action.yml",
        *sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")),
    ]
    uses = [
        (path.name, line.split("uses:", 1)[1].strip())
        for path in files
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("uses:", "- uses:"))
    ]
    pinned = re.compile(r"[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+")
    loose = [
        (name, ref)
        for name, ref in uses
        if not ref.startswith("./") and not pinned.fullmatch(ref)
    ]

    assert len(uses) >= 20
    assert loose == []


def test_quarantine_cutoff_is_fourteen_days_before_the_release_date() -> None:
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    heading = re.search(
        rf"^## \[{re.escape(_project_version())}\] - (\d{{4}}-\d{{2}}-\d{{2}})$",
        changelog,
        re.MULTILINE,
    )
    assert heading is not None
    released = datetime.fromisoformat(f"{heading.group(1)}T00:00:00+00:00")
    entry = changelog.split(heading.group(0), 1)[1].split("\n## [", 1)[0]
    uv = _toml(REPO_ROOT / "pyproject.toml")["tool"]["uv"]
    unnamed = [name for name in uv["exclude-newer-package"] if f"`{name}`" not in entry]

    assert _instant(uv["exclude-newer"]) <= released - timedelta(days=14)
    assert unnamed == []


def test_publish_jobs_need_an_unconditional_wheel_gate() -> None:
    publish = (REPO_ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    jobs = dict(
        re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", publish, re.M | re.S)
    )
    gate = jobs["build"].split(
        "- name: Verify the wheel is the one the GitHub Action pins"
    )
    gate_step = gate[1].split("- name:", 1)[0]

    assert len(gate) == 2
    assert [key for key in ("continue-on-error", "if:") if key in gate_step] == []
    assert "continue-on-error" not in jobs["build"]
    # Every publishing job waits for the gated build, directly or through
    # another publishing job, and none of them runs past a failure.
    publishing = sorted(job for job in jobs if job.startswith("publish"))
    assert {"publish-testpypi", "publish-pypi", "publish-registry"} <= set(publishing)
    needs = {
        job: re.findall(r"^    needs: ([\w-]+)$", jobs[job], re.M) for job in publishing
    }
    reaches_build: set[str] = set()
    while True:
        grown = {
            job
            for job in publishing
            if any(need == "build" or need in reaches_build for need in needs[job])
        }
        if grown == reaches_build:
            break
        reaches_build = grown
    assert sorted(reaches_build) == publishing
    assert [
        job
        for job in publishing
        if "continue-on-error" in jobs[job]
        or re.search(r"\b(?:always|failure|cancelled)\(\)", jobs[job])
    ] == []


def test_ci_installs_are_locked_and_never_build_from_source() -> None:
    commands = [
        (path.name, " ".join(command.split()))
        for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
        for command in re.findall(
            r"uv (?:sync|run)\b[^\n]*", path.read_text(encoding="utf-8")
        )
    ]
    syncs = [(name, cmd) for name, cmd in commands if cmd.startswith("uv sync")]
    tools = [(name, cmd) for name, cmd in commands if "--with" in cmd.split()]
    loose = [
        (name, cmd)
        for name, cmd in syncs + tools
        if "--no-build" not in cmd.split()
        or (cmd.startswith("uv sync") and "--locked" not in cmd.split())
        or any("==" not in tool for tool in re.findall(r"--with (\S+)", cmd))
    ]

    assert (len(syncs) >= 4, len(tools) >= 2) == (True, True)
    assert loose == []
