# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The class of mounted layouts a blast radius has to name modules on.

One package -- a module half the package imports, a cycle, a clone twin, a
transitive dependent, a high-complexity and a high-coupling dependent, a
security surface and an opaque dynamic load in the zone, a package
``__init__`` that a module imports by name -- written twice for every
layout: once as a flat repository (the package at the root, the layout every
answer was already right on) and once mounted the way the layout mounts it.
The module identity of every file is the same in both (``pkg.core`` is
``pkg.core`` under ``src/``), so every answer of the mounted twin must be the
flat twin's answer with its paths moved: the flat twin is the oracle.

The layouts are the class, not one symptom (measured 2026-10-05 on the
blast radius and on the implementation context, all five understated):

* ``src``           -- the conventional ``src/`` layout, autodetected;
* ``nested``        -- ``lib/python/pkg``, mounted by ``source_roots``;
* ``multi_root``    -- ``src/`` and ``plugins/``, two ``source_roots``;
* ``namespace``     -- the package has no ``__init__.py``;
* ``tests_beside``  -- ``src/pkg`` with ``tests/`` beside it, outside the
  mount, so the test file has NO module and its edges spell it by path.

This module is a helper, not a test module, so it may drive the surface and
read the store beside it (the Phase 39S test-import law binds
``tests/test_*.py`` only).
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._blast_radius import blast_radius_to_payload
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping, as_sequence
from tests import conftest as corpora
from tests._run_summary_serving import serving_environment

_FOLD = '''

def fold(values: list[int]) -> int:
    """Fold."""
    total = 0
    count = 0
    for value in values:
        count += 1
        if value > 10:
            total += value * 2
        elif value > 5:
            total += value
        else:
            total -= 1
    if count == 0:
        return -1
    total += count
    return total
'''

#: The package, spelled flat (the paths of the flat twin).
LAYOUT_PACKAGE: dict[str, str] = {
    "pkg/__init__.py": '"""The package."""\n\nVERSION = 1\n',
    "pkg/core.py": (
        '"""Core: imported by every user, a cycle with helper, a clone of twin."""'
        "\n\nfrom pkg.helper import assist\n\n\n"
        'def core_value(x: int) -> int:\n    """Core value."""\n'
        "    return assist(x) + 1\n" + _FOLD
    ),
    "pkg/helper.py": (
        '"""Helper: closes the cycle with core."""\n\n'
        "from pkg.core import core_value\n\n\n"
        'def assist(x: int) -> int:\n    """Assist."""\n'
        "    return x if x < 0 else -core_value(-x - 1)\n"
    ),
    "pkg/twin.py": '"""Twin: the clone of the fold in core."""\n' + _FOLD,
    "pkg/user_1.py": (
        '"""User 1."""\n\nfrom pkg.core import core_value\n\n\n'
        'def use_1(y: int) -> int:\n    """Use."""\n    return core_value(y) + 1\n'
    ),
    "pkg/user_2.py": (
        '"""User 2: a high-complexity dependent."""\n\n'
        "from pkg.core import core_value\n\n\n"
        "def tangle(a: int) -> int:\n    t = core_value(a)\n"
        + "".join(f"    if a > {i}:\n        t += {i}\n" for i in range(24))
        + "    return t\n"
    ),
    "pkg/user_3.py": (
        '"""User 3: a security surface in the zone."""\n\n'
        "from pkg.core import core_value\n\n\n"
        'def run(source: str) -> object:\n    """Run."""\n'
        "    return eval(source) or core_value(1)\n"
    ),
    "pkg/loader.py": (
        '"""Loader: an opaque dynamic load in the zone."""\n\n'
        "import importlib\n\nfrom pkg.core import core_value\n\n\n"
        'def load(name: str) -> object:\n    """Load."""\n'
        "    return importlib.import_module(name) if core_value(0) else None\n"
    ),
    "pkg/top.py": (
        '"""Top: a transitive dependent of core."""\n\n'
        "from pkg.user_1 import use_1\n\n\n"
        'def top() -> int:\n    """Top."""\n    return use_1(2)\n'
    ),
    "pkg/meta.py": (
        '"""Meta: imports the package itself, by name."""\n\n'
        "from pkg import VERSION\n\n\n"
        'def meta() -> int:\n    """Meta."""\n    return VERSION\n'
    ),
    "pkg/parts.py": "\n\n".join(
        f"class Part{i}:\n    def value(self) -> int:\n        return {i}\n"
        for i in range(14)
    ),
    "pkg/hub.py": "from pkg.core import core_value\nfrom pkg.parts import "
    + ", ".join(f"Part{i}" for i in range(14))
    + "\n\n\nclass Hub:\n    def __init__(self) -> None:\n"
    + "\n".join(f"        self.p{i} = Part{i}()" for i in range(14))
    + "\n        self.v = core_value(1)\n",
}

_PLUGIN: dict[str, str] = {
    "plug/__init__.py": "",
    "plug/ext.py": (
        '"""Plugin: a dependent of core from a second source root."""\n\n'
        "from pkg.core import core_value\n\n\n"
        'def ext() -> int:\n    """Ext."""\n    return core_value(3)\n'
    ),
}
_TESTS: dict[str, str] = {
    "tests/test_core.py": (
        '"""Tests beside the package, outside its mount."""\n\n'
        "from pkg.core import core_value\n\n\n"
        "def test_core() -> None:\n    assert core_value(1)\n"
    ),
}


@dataclass(frozen=True, slots=True)
class Layout:
    """One layout: the flat tree, where it mounts, and how it is declared."""

    name: str
    flat_tree: dict[str, str]
    #: ``(flat directory, mounted directory)``, each with its trailing slash.
    mounts: tuple[tuple[str, str], ...]
    #: Extra ``[tool.codeclone]`` lines of the mounted twin.
    declared: str = ""

    def mounted(self, path: str) -> str:
        """The mounted twin's path of a flat path (a directory too)."""
        for flat, mounted in self.mounts:
            if path.startswith(flat):
                return mounted + path[len(flat) :]
            if path == flat.rstrip("/"):
                return mounted.rstrip("/")
        return path

    def python_files(self) -> tuple[str, ...]:
        """Every Python file of the flat tree, the core first."""
        files = sorted(path for path in self.flat_tree if path.endswith(".py"))
        files.remove(CORE)
        return (CORE, *files)


CORE = "pkg/core.py"

LAYOUTS: dict[str, Layout] = {
    "src": Layout("src", dict(LAYOUT_PACKAGE), (("pkg/", "src/pkg/"),)),
    "nested": Layout(
        "nested",
        dict(LAYOUT_PACKAGE),
        (("pkg/", "lib/python/pkg/"),),
        'source_roots = ["lib/python"]\n',
    ),
    "multi_root": Layout(
        "multi_root",
        {**LAYOUT_PACKAGE, **_PLUGIN},
        (("pkg/", "src/pkg/"), ("plug/", "plugins/plug/")),
        'source_roots = ["src", "plugins"]\n',
    ),
    "namespace": Layout(
        "namespace",
        {
            path: source
            for path, source in LAYOUT_PACKAGE.items()
            if path not in {"pkg/__init__.py", "pkg/meta.py"}
        },
        (("pkg/", "src/pkg/"),),
    ),
    "tests_beside": Layout(
        "tests_beside", {**LAYOUT_PACKAGE, **_TESTS}, (("pkg/", "src/pkg/"),)
    ),
}

#: The controller's own reproduction (2026-10-05): four modules, three of
#: them importing the fourth, at the root and under ``src/``.
CONTROLLER_REPRO: dict[str, str] = {
    "pkg/__init__.py": "",
    "pkg/core.py": (
        "def core_value(x):\n    total = x + 1\n    total = total * 2\n"
        "    return total - 3\n"
    ),
    **{
        f"pkg/user_{i}.py": (
            "from pkg.core import core_value\n\n\n"
            f"def use_{i}(y):\n    out = core_value(y)\n    out = out + {i}\n"
            "    return out * 2\n"
        )
        for i in (1, 2, 3)
    },
}


def registry_source_facts(*pairs: tuple[str, str | None]) -> dict[str, object]:
    """The ``source_facts`` of a stand-in report: a module registry with one
    row per ``(path, module)`` pair, in the producer's shape (``module``
    ``None`` is a file the identity gives no module).  A stand-in report
    without it names no file's module, exactly as a real one would not."""
    return {
        "module_registry": {
            "entries_by_path": {
                "rows": [
                    [
                        path,
                        {
                            "identity": {
                                "file": {"path": path},
                                "python_module": (
                                    None if module is None else {"module": module}
                                ),
                            }
                        },
                    ]
                    for path, module in pairs
                ]
            }
        }
    }


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def write_repository(root: Path, tree: dict[str, str], declared: str = "") -> Path:
    """A committed repository holding ``tree`` (the controlled change needs
    a git work tree)."""
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.codeclone]\n" + declared, "utf-8")
    (root / ".gitignore").write_text(".codeclone/\n", "utf-8")
    corpora._write_tree(root, tree)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "tree")
    return root


@dataclass(frozen=True, slots=True)
class Analysed:
    """One MCP execution of one repository, its run published to its store."""

    root: Path
    store_path: Path
    service: CodeCloneMCPService

    @property
    def record(self) -> MCPRunRecord:
        return self.service._runs.get_for_root(None, root=self.root)


def analyse(root: Path, store_path: Path) -> Analysed:
    service = CodeCloneMCPService(history_limit=4)
    with serving_environment(store_path, serve_from=None):
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    analysed = Analysed(root, store_path, service)
    corpora._published_store_run_id(analysed.record)
    return analysed


@dataclass(frozen=True, slots=True)
class Twins:
    """A layout's flat twin and its mounted twin, each analysed once."""

    layout: Layout
    flat: Analysed
    mounted: Analysed


class LayoutPopulations:
    """Every layout's twins, built on first use, once per session."""

    def __init__(self, factory: pytest.TempPathFactory) -> None:
        self._factory = factory
        self._built: dict[str, Twins] = {}

    def __getitem__(self, name: str) -> Twins:
        if name not in self._built:
            layout = LAYOUTS[name]
            base = self._factory.mktemp(f"blast_layout_{name}").resolve()
            flat = write_repository(base / "flat", layout.flat_tree)
            mounted = write_repository(
                base / "mounted",
                {layout.mounted(path): text for path, text in layout.flat_tree.items()},
                layout.declared,
            )
            self._built[name] = Twins(
                layout,
                analyse(flat, base / "flat.sqlite3"),
                analyse(mounted, base / "mounted.sqlite3"),
            )
        return self._built[name]


_SHARED: dict[str, LayoutPopulations] = {}


def shared_layout_populations(factory: pytest.TempPathFactory) -> LayoutPopulations:
    key = str(factory.getbasetemp())
    if key not in _SHARED:
        _SHARED[key] = LayoutPopulations(factory)
    return _SHARED[key]


def forget(analysed: Analysed) -> None:
    with analysed.service._state_lock:
        analysed.service._blast_radius_cache.clear()


def blast(
    analysed: Analysed, origin: str, depth: str, *, serve_from: str
) -> dict[str, object]:
    """``get_blast_radius`` of one origin, computed afresh on one switch."""
    forget(analysed)
    with serving_environment(analysed.store_path, serve_from=serve_from):
        return analysed.service.get_blast_radius(
            files=[origin], root=str(analysed.root), depth=depth
        )


def policy(analysed: Analysed, origin: str) -> dict[str, object]:
    """The declare / context-shaped question: a declared scope of the origin
    alone, so the whole zone outside it is ``affected_but_not_allowed``."""
    forget(analysed)
    with serving_environment(analysed.store_path, serve_from="run_store"):
        result, serving = analysed.service._served_blast_radius(
            record=analysed.record,
            files=(origin,),
            depth="transitive",
            forbidden_patterns=(),
            allowed_scope=(origin,),
        )
    return {**blast_radius_to_payload(result), "serving": serving}


def started(analysed: Analysed, scope_entry: str) -> dict[str, object]:
    """The blast radius ``start_controlled_change`` declares for one scope
    entry; the intent is cleared again before returning."""
    forget(analysed)
    with serving_environment(analysed.store_path, serve_from=None):
        answer = analysed.service.start_controlled_change(
            root=str(analysed.root),
            scope={"allowed_files": [scope_entry]},
            intent="layout probe",
            blast_radius_depth="auto",
        )
        assert answer["status"] == "active", answer
        analysed.service.manage_change_intent(
            action="clear", intent_id=str(answer["intent_id"]), root=str(analysed.root)
        )
    return dict(as_mapping(answer["blast_radius"]))


def structural_context(analysed: Analysed, path: str) -> dict[str, object]:
    """The structural part of ``get_implementation_context`` for one path."""
    with serving_environment(analysed.store_path, serve_from=None):
        answer = analysed.service.get_implementation_context(
            root=str(analysed.root), paths=[path], budget=200
        )
    return dict(as_mapping(answer.get("structural_context")))


def cli_quiet_line(root: Path, origin: str) -> str:
    """The real CLI, in process: ``codeclone <root> --blast-radius <origin>``."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = corpora._run_codeclone_cli_exit(
            [
                str(root),
                "--no-progress",
                "--no-skip-metrics",
                "--quiet",
                "--blast-radius",
                origin,
            ],
            {},
        )
    assert code in (None, 0), (code, out.getvalue())
    (line,) = [
        text for text in out.getvalue().splitlines() if text.startswith("blast-radius")
    ]
    return line


# -- the oracle: the flat answer, moved onto the mounted twin's paths --------

#: The answer fields every layout must agree on (``run_id`` names the report,
#: and ``serving`` is compared on its own).
ANSWER_FIELDS: tuple[str, ...] = (
    "origin",
    "depth",
    "radius_level",
    "direct_dependents",
    "transitive_dependents",
    "clone_cohort_members",
    "in_dependency_cycle",
    "structural_risk",
    "do_not_touch",
    "do_not_touch_summary",
    "review_context",
    "review_context_summary",
    "guardrails",
)


def _sorted(items: list[object]) -> list[object]:
    if all(isinstance(item, str) for item in items):
        return sorted(items, key=str)
    return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))


def _moved(value: object, move: Callable[[str], str]) -> object:
    if isinstance(value, list):
        return _sorted([_moved(item, move) for item in value])
    if isinstance(value, dict):
        return {
            key: move(item)
            if key == "path" and isinstance(item, str)
            else (_moved(item, move))
            for key, item in value.items()
        }
    if isinstance(value, str) and "/" in value:
        return move(value)
    return value


def comparable(
    answer: dict[str, object], move: Callable[[str], str]
) -> dict[str, object]:
    """The answer's fields, every path moved, every list in path order."""
    return {field: _moved(answer[field], move) for field in ANSWER_FIELDS}


def mounted_view(answer: dict[str, object], layout: Layout) -> dict[str, object]:
    """A flat twin's answer as the mounted twin must give it."""
    return comparable(answer, layout.mounted)


def own_view(answer: dict[str, object]) -> dict[str, object]:
    """A mounted twin's answer, in the same canonical order."""
    return comparable(answer, lambda path: path)


def related_view(
    context: dict[str, object], move: Callable[[str], str]
) -> list[object]:
    """The related modules of a context: path, kind and relations (the
    module spelling of a file outside every mount is the layout's own)."""
    return _sorted(
        [
            {
                "path": None if row.get("path") is None else move(str(row["path"])),
                "source_kind": row.get("source_kind"),
                "relations": row.get("relations"),
            }
            for row in (
                as_mapping(item) for item in as_sequence(context.get("related_modules"))
            )
        ]
    )


def dynamic_view(
    context: dict[str, object], move: Callable[[str], str]
) -> list[object]:
    return _sorted(
        [
            {
                "path": move(
                    str(
                        as_mapping(as_mapping(row.get("source")).get("file")).get(
                            "path"
                        )
                    )
                ),
                "syntax_kind": row.get("syntax_kind"),
                "reason": row.get("reason"),
            }
            for row in (
                as_mapping(item)
                for item in as_sequence(context.get("dynamic_boundaries"))
            )
        ]
    )


def module_roles(context: dict[str, object]) -> list[tuple[object, object]]:
    return [
        (as_mapping(item).get("path"), as_mapping(item).get("module"))
        for item in as_sequence(context.get("module_role"))
    ]


__all__ = [
    "ANSWER_FIELDS",
    "CONTROLLER_REPRO",
    "CORE",
    "LAYOUTS",
    "LAYOUT_PACKAGE",
    "Analysed",
    "Layout",
    "LayoutPopulations",
    "Twins",
    "analyse",
    "blast",
    "cli_quiet_line",
    "comparable",
    "dynamic_view",
    "forget",
    "module_roles",
    "mounted_view",
    "own_view",
    "policy",
    "registry_source_facts",
    "related_view",
    "shared_layout_populations",
    "started",
    "structural_context",
    "write_repository",
]
