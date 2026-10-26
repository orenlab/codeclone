# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _toml(path: Path) -> dict[str, Any]:
    name = "tomllib" if sys.version_info >= (3, 11) else "tomli"
    loaded: dict[str, Any] = importlib.import_module(name).loads(
        path.read_text(encoding="utf-8")
    )
    return loaded


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
    def instant(value: str) -> datetime:
        # uv writes 1-6 fractional digits; Python 3.10 parses only 3 or 6.
        head, _, fraction = value.removesuffix("Z").partition(".")
        return datetime.fromisoformat(f"{head}.{fraction:0<6.6}+00:00")

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
