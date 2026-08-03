# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Identity guards for ``inventory.file_registry``.

The registry projects a path set contributed by several producers that spell
the same file differently: discovery contributes absolute paths, while some
metric families contribute repository-relative ones. Deduplicating that set
removes duplicate *spellings*, not duplicate *files*, and the report seam only
collapses the survivors onto one relative contract path afterwards -- so a
single file could occupy two registry slots and the registry could contradict
``inventory.files.total_found`` inside the same document.

Which producer spells a path which way depends on cache warmth
(``security_surfaces`` yields relative paths on a fresh analysis and absolute
paths once entries are rehydrated from cache), so the defect made report
*content* a function of cache state. The cold-equals-warm test below is the
owning guard for that property.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_ENTRY = "from codeclone.surfaces.cli.workflow import main; main()"
_SCOPE_ID = "8f14e45f-ceea-467a-9c2b-1a4d2b8f0001"

# `security_surfaces` is the family whose path spelling tracks cache warmth, so
# the fixture has to carry recognisable sinks for the defect to be reachable.
_SINKS_SOURCE = '''"""Module carrying security-surface sinks."""

import hashlib
import pickle
import subprocess


def run_command(name: str) -> str:
    completed = subprocess.run([name], capture_output=True, check=False)
    return completed.stdout.decode("utf-8")


def load_blob(blob: bytes) -> object:
    return pickle.loads(blob)


def weak_digest(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def evaluate(expr: str) -> object:
    return eval(expr)
'''

_API_SOURCE = '''"""Public surface with several exported callables."""


def alpha(value: int) -> int:
    return value + 1


def beta(value: int) -> int:
    return value + 2


class Gamma:
    def method_one(self, value: int) -> int:
        return value * 2

    def method_two(self, value: int) -> int:
        return value * 3
'''


class _Reports(NamedTuple):
    cold: dict[str, object]
    warm: dict[str, object]


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _CLI_ENTRY, *args],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
    )


def _inventory_section(document: dict[str, object], name: str) -> dict[str, object]:
    """Return one mapping section of the report inventory."""

    inventory = document["inventory"]
    assert isinstance(inventory, dict)
    section = inventory[name]
    assert isinstance(section, dict)
    return section


def _items(document: dict[str, object]) -> list[str]:
    items = _inventory_section(document, "file_registry")["items"]
    assert isinstance(items, list)
    return items


def _total_found(document: dict[str, object]) -> int:
    total = _inventory_section(document, "files")["total_found"]
    assert isinstance(total, int)
    return total


@pytest.fixture(scope="module")
def reports(tmp_path_factory: pytest.TempPathFactory) -> _Reports:
    """Analyse one repository twice: once cold, once warm off the same cache."""

    root = tmp_path_factory.mktemp("registry_repo") / "repo"
    package = root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "sinks.py").write_text(_SINKS_SOURCE, "utf-8")
    (package / "api.py").write_text(_API_SOURCE, "utf-8")
    (root / "pyproject.toml").write_text(
        f'[tool.codeclone]\nbaseline_scope_id = "{_SCOPE_ID}"\n',
        "utf-8",
    )

    # The metric families that carry the defect are baseline-gated, so the
    # repository needs a baseline before either measured run.
    seeded = _run_cli(str(root), "--quiet", "--update-baseline")
    assert seeded.returncode == 0, seeded.stderr

    cold_path = root / "cold.json"
    warm_path = root / "warm.json"

    shutil.rmtree(root / ".codeclone", ignore_errors=True)
    cold = _run_cli(str(root), "--quiet", "--json", str(cold_path))
    assert cold.returncode == 0, cold.stderr
    warm = _run_cli(str(root), "--quiet", "--json", str(warm_path))
    assert warm.returncode == 0, warm.stderr

    cold_document = json.loads(cold_path.read_text("utf-8"))
    warm_document = json.loads(warm_path.read_text("utf-8"))

    # Guard the guard: if these stop describing a cold and a warm run the
    # comparison below would pass without exercising anything.
    assert _inventory_section(cold_document, "files")["cached"] == 0
    assert _inventory_section(warm_document, "files")["analyzed"] == 0
    return _Reports(cold=cold_document, warm=warm_document)


def test_file_registry_items_are_unique(reports: _Reports) -> None:
    """One file occupies exactly one registry slot, whatever spelled it."""

    for label, document in (("cold", reports.cold), ("warm", reports.warm)):
        items = _items(document)
        duplicates = sorted({path for path in items if items.count(path) > 1})
        assert not duplicates, f"{label} run repeated registry entries: {duplicates}"


def test_file_registry_count_matches_total_found(reports: _Reports) -> None:
    """The registry cannot contradict the file count in the same document."""

    for label, document in (("cold", reports.cold), ("warm", reports.warm)):
        assert len(_items(document)) == _total_found(document), (
            f"{label} run registry size disagrees with inventory.files.total_found"
        )


def test_file_registry_is_identical_cold_and_warm(reports: _Reports) -> None:
    """Report content must not depend on whether the cache was warm."""

    assert _inventory_section(reports.cold, "file_registry") == _inventory_section(
        reports.warm, "file_registry"
    )
