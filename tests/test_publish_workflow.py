# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PUBLISH_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "publish.yml"
_USES_LINE = re.compile(r"^\s*(?:-\s+)?uses:\s+(?P<ref>\S+)(?P<comment>.*)$")
_FULL_SHA_REF = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
_RELEASE_COMMENT = re.compile(r"^ # v\d+\.\d+\.\d+$")
_WITH_REQUIREMENT = re.compile(r"--with\s+(\S+)")


def _locked_versions() -> dict[str, str]:
    toml = importlib.import_module(
        "tomllib" if sys.version_info >= (3, 11) else "tomli"
    )
    lock: dict[str, object] = toml.loads(
        (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    )
    packages = lock["package"]
    assert isinstance(packages, list)
    return {
        str(package["name"]): str(package["version"])
        for package in packages
        if isinstance(package, dict) and "version" in package
    }


def test_publish_workflow_pins_every_action_to_a_full_commit_sha() -> None:
    uses_lines = [
        line
        for line in _PUBLISH_WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "uses:" in line
    ]
    assert uses_lines, "the publish workflow declares no actions"

    unpinned = []
    for line in uses_lines:
        match = _USES_LINE.match(line)
        if (
            match is None
            or _FULL_SHA_REF.match(match.group("ref")) is None
            or _RELEASE_COMMENT.match(match.group("comment")) is None
        ):
            unpinned.append(line.strip())

    assert unpinned == []


def test_publish_workflow_pins_build_tools_to_locked_versions() -> None:
    requested: dict[str, tuple[str, str]] = {}
    for requirement in _WITH_REQUIREMENT.findall(
        _PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    ):
        name, separator, version = requirement.partition("==")
        requested[name] = (separator, version)
    locked = _locked_versions()

    assert {"build", "twine"} <= requested.keys()
    assert {
        name: pin
        for name, pin in sorted(requested.items())
        if pin != ("==", locked.get(name, ""))
    } == {}
