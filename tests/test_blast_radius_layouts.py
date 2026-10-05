# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A file's module is the module identity's, on every layout and both roads.

The blast radius matches an origin file to the import edges by the file's
module name.  The edges name a module the way the run's module identity
names it (``pkg.core`` for ``src/pkg/core.py``); the origin used to be named
by its path with the slashes turned into dots (``src.pkg.core``), a module no
edge names, so on every mounted layout a file half the package imports had
no dependents and ``start_controlled_change`` declared a low radius
(measured 2026-10-05: the controller's four-module reproduction, flask's 208
``low`` answers out of 214, and all five layouts of
``tests/_blast_radius_layouts.py``).  The implementation context matched its
subject the same way and lost every import and importer.

The oracle is the flat twin of each layout: the same package at the root,
where the path and the module coincide.  Every answer of the mounted twin --
both depths, every Python file, the memory switch and the store switch, the
MCP tool, the controlled change, the CLI, the implementation context -- must
be the flat twin's answer with its paths moved.  The flat twin itself is held
to the answer its tree states, so a repair that moved the flat answer would
fail here as loudly as the defect did.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import codeclone.surfaces.mcp._implementation_context as context_mod
from codeclone.utils.coerce import as_mapping, as_sequence
from tests._blast_radius_layouts import (
    CONTROLLER_REPRO,
    CORE,
    LAYOUTS,
    Analysed,
    Layout,
    LayoutPopulations,
    analyse,
    blast,
    cli_quiet_line,
    dynamic_view,
    module_roles,
    mounted_view,
    own_view,
    policy,
    related_view,
    shared_layout_populations,
    started,
    structural_context,
    write_repository,
)

LAYOUT_NAMES = list(LAYOUTS)
SWITCHES = ("memory", "run_store")


def _same(path: str) -> str:
    return path


@pytest.fixture(scope="module")
def layouts(tmp_path_factory: pytest.TempPathFactory) -> LayoutPopulations:
    return shared_layout_populations(tmp_path_factory)


def _core_dependents(layout: Layout) -> list[str]:
    """The files importing ``pkg.core`` in the layout's tree, spelled flat."""
    return sorted(
        path
        for path, text in layout.flat_tree.items()
        if "from pkg.core import" in text and path != CORE
    )


def _reason(answer: dict[str, object]) -> object:
    return as_mapping(answer["serving"]).get("reason")


def test_the_controllers_src_reproduction_names_the_three_dependents(
    tmp_path: Path,
) -> None:
    """The controller's reproduction through the real CLI: the package at
    the root and the same package under ``src/`` are one radius."""
    flat = write_repository(tmp_path / "flat", CONTROLLER_REPRO)
    srcl = write_repository(
        tmp_path / "srcl",
        {f"src/{path}": text for path, text in CONTROLLER_REPRO.items()},
    )
    expected = "blast-radius: medium | dependents=3 cohorts=0 cycles=0 do-not-touch=3"
    assert cli_quiet_line(flat, "pkg/core.py") == expected
    assert cli_quiet_line(srcl, "src/pkg/core.py") == expected


@pytest.mark.parametrize("serve_from", SWITCHES)
@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_every_answer_is_the_flat_twins_moved_onto_the_layout(
    layouts: LayoutPopulations, name: str, serve_from: str
) -> None:
    twins = layouts[name]
    layout = twins.layout
    for origin in layout.python_files():
        for depth in ("direct", "transitive"):
            flat = blast(twins.flat, origin, depth, serve_from=serve_from)
            mounted = blast(
                twins.mounted, layout.mounted(origin), depth, serve_from=serve_from
            )
            assert own_view(mounted) == mounted_view(flat, layout), (origin, depth)
            if serve_from == "run_store":
                assert _reason(flat) == _reason(mounted) == "served", (origin, depth)


@pytest.mark.parametrize("twin", ["flat", "mounted"])
@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_the_core_answer_is_the_one_its_tree_states(
    layouts: LayoutPopulations, name: str, twin: str
) -> None:
    """Both twins, held to the tree rather than to each other: the oracle is
    right, and every field of the answer is reached (Probe Validity Law)."""
    twins = layouts[name]
    layout = twins.layout
    analysed, move = (
        (twins.flat, _same) if twin == "flat" else (twins.mounted, layout.mounted)
    )
    answer = blast(analysed, move(CORE), "transitive", serve_from="memory")
    assert answer["radius_level"] == "high"
    assert answer["direct_dependents"] == sorted(
        move(path) for path in _core_dependents(layout)
    )
    assert answer["transitive_dependents"] == [move("pkg/top.py")]
    assert answer["clone_cohort_members"] == [move("pkg/twin.py")]
    assert answer["in_dependency_cycle"] == [move(CORE)]
    risk = as_mapping(answer["structural_risk"])
    assert risk["high_complexity_in_blast_zone"] == [move("pkg/user_2.py")]
    assert risk["high_coupling_in_blast_zone"] == [move("pkg/hub.py")]
    review = [as_mapping(entry) for entry in as_sequence(answer["review_context"])]
    assert {
        (entry["path"], entry["category"])
        for entry in review
        if entry["category"] != "report_only_context"
    } == {
        (move("pkg/loader.py"), "dynamic_frontier_boundary"),
        # ``importlib.import_module`` is a security surface of its own
        (move("pkg/loader.py"), "security_boundary_context"),
        (move("pkg/user_3.py"), "security_boundary_context"),
    }
    assert "high blast radius requires explicit human scope approval" in as_sequence(
        answer["guardrails"]
    )


@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_the_do_not_touch_zone_is_the_flat_twins(
    layouts: LayoutPopulations, name: str
) -> None:
    """A declared scope of the origin alone: the zone outside it is the
    same zone, on the store switch."""
    twins = layouts[name]
    layout = twins.layout
    flat = policy(twins.flat, CORE)
    mounted = policy(twins.mounted, layout.mounted(CORE))
    assert own_view(mounted) == mounted_view(flat, layout)
    zone = {
        as_mapping(entry)["path"]
        for entry in as_sequence(mounted["do_not_touch"])
        if as_mapping(entry)["category"] == "affected_but_not_allowed"
    }
    assert layout.mounted("pkg/user_1.py") in zone
    assert _reason(flat) == _reason(mounted) == "served"


def _start_view(block: dict[str, object]) -> dict[str, object]:
    summary = block.get("direct_dependents_summary")
    return {
        "radius_level": block["radius_level"],
        "guardrails": block["guardrails"],
        "direct_total": (
            as_mapping(summary)["total"]
            if summary is not None
            else len(as_sequence(block["direct_dependents"]))
        ),
    }


@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_start_controlled_change_declares_the_flat_twins_radius(
    layouts: LayoutPopulations, name: str
) -> None:
    twins = layouts[name]
    layout = twins.layout
    flat = _start_view(started(twins.flat, CORE))
    assert _start_view(started(twins.mounted, layout.mounted(CORE))) == flat
    assert flat["radius_level"] == "high"
    assert flat["direct_total"] == len(_core_dependents(layout))


@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_the_cli_names_the_flat_twins_radius(
    layouts: LayoutPopulations, name: str
) -> None:
    twins = layouts[name]
    layout = twins.layout
    flat = cli_quiet_line(twins.flat.root, CORE)
    assert flat.startswith(
        f"blast-radius: high | dependents={len(_core_dependents(layout))} "
        "cohorts=1 cycles=1 "
    ), flat
    assert cli_quiet_line(twins.mounted.root, layout.mounted(CORE)) == flat


@pytest.mark.parametrize("name", LAYOUT_NAMES)
def test_the_implementation_context_is_the_flat_twins(
    layouts: LayoutPopulations, name: str
) -> None:
    """Imports, importers and dynamic boundaries of every Python file; and
    the module each file is named by -- the identity's, never its path."""
    twins = layouts[name]
    layout = twins.layout
    related: set[str] = set()
    for origin in layout.python_files():
        flat = structural_context(twins.flat, origin)
        mounted = structural_context(twins.mounted, layout.mounted(origin))
        assert related_view(mounted, _same) == related_view(flat, layout.mounted)
        assert dynamic_view(mounted, _same) == dynamic_view(flat, layout.mounted)
        ((flat_path, flat_module),) = module_roles(flat)
        assert flat_path == origin
        mounted_by_it = any(origin.startswith(flat) for flat, _ in layout.mounts)
        assert module_roles(mounted) == [
            (layout.mounted(origin), flat_module if mounted_by_it else None)
        ], origin
        if mounted.get("related_modules"):
            related.add(origin)
    # the population reaches the lane: the core, every file importing it,
    # and the file outside every mount (``tests_beside``) all relate
    assert {CORE, *_core_dependents(layout)} <= related


def test_a_file_outside_every_mount_has_no_module_and_borrows_no_radius(
    tmp_path: Path,
) -> None:
    """``pkg/core.py`` at the root of a ``src/`` repository is outside the
    mount: the identity names it no module.  Its path spells ``pkg.core``,
    the module of ``src/pkg/core.py`` that three files import -- a radius
    read through that spelling would be borrowed from another file."""
    tree = {f"src/{path}": text for path, text in CONTROLLER_REPRO.items()}
    tree["pkg/core.py"] = CONTROLLER_REPRO["pkg/core.py"]
    root = write_repository(tmp_path / "shadow", tree)
    assert cli_quiet_line(root, "pkg/core.py") == (
        "blast-radius: low | dependents=0 cohorts=0 cycles=0 do-not-touch=3"
    )
    analysed = analyse(root, tmp_path / "shadow.sqlite3")
    for serve_from in SWITCHES:
        answer = blast(analysed, "pkg/core.py", "transitive", serve_from=serve_from)
        assert answer["direct_dependents"] == []
        assert answer["radius_level"] == "low"
    real = blast(analysed, "src/pkg/core.py", "direct", serve_from="memory")
    assert len(as_sequence(real["direct_dependents"])) == 3
    context = structural_context(analysed, "pkg/core.py")
    assert module_roles(context) == [("pkg/core.py", None)]
    assert context.get("related_modules") == []


@pytest.mark.parametrize("origin", ["README.md", "nonexistent/zz.py"])
def test_a_path_the_identity_does_not_know_has_no_module(
    layouts: LayoutPopulations, origin: str
) -> None:
    analysed = layouts["src"].flat
    assert module_roles(structural_context(analysed, origin)) == [(origin, None)]


@pytest.mark.parametrize("name", ["src", "nested", "multi_root", "tests_beside"])
def test_a_directory_scope_names_its_regular_package(
    layouts: LayoutPopulations, name: str
) -> None:
    """``allowed_files: ["pkg/"]`` is a directory tree: it stands for its
    regular package, whose module ``pkg/meta.py`` imports by name -- on the
    flat twin as it always did, and now on the mounted one."""
    twins = layouts[name]
    cases: tuple[tuple[Analysed, Callable[[str], str]], ...] = (
        (twins.flat, _same),
        (twins.mounted, twins.layout.mounted),
    )
    for analysed, move in cases:
        directory = move("pkg/").rstrip("/")
        answer = blast(analysed, directory, "direct", serve_from="run_store")
        assert answer["direct_dependents"] == [move("pkg/meta.py")], directory
        assert _reason(answer) == "served"
        block = started(analysed, directory + "/")
        assert block["direct_dependents"] == [move("pkg/meta.py")], directory


def test_a_namespace_directory_has_no_file_and_no_module(tmp_path: Path) -> None:
    """A namespace package has no file for the identity to name: its
    directory has no module, even where a module imports the package by
    name (the flat spelling ``pkg`` used to reach it through the path)."""
    tree = {
        "pkg/core.py": CONTROLLER_REPRO["pkg/core.py"],
        "pkg/user.py": "import pkg\n\n\ndef use() -> object:\n    return pkg\n",
    }
    for name, prefix in (("flat", ""), ("srcl", "src/")):
        root = write_repository(
            tmp_path / name, {prefix + path: text for path, text in tree.items()}
        )
        analysed = analyse(root, tmp_path / f"{name}.sqlite3")
        for serve_from in SWITCHES:
            answer = blast(analysed, prefix + "pkg", "direct", serve_from=serve_from)
            assert answer["direct_dependents"] == [], (name, serve_from)


def test_an_edge_endpoint_names_its_file_and_never_a_module_as_one() -> None:
    """A module's file; a file the edges spell by its path, itself; anything
    else -- a module the identity cannot place (a document without a
    registry) -- no path, never its dotted text read as one."""
    module_paths = {"pkg.core": "src/pkg/core.py"}
    known = frozenset({"src/pkg/core.py", "tests/test_core.py"})
    endpoint_path = context_mod._endpoint_path
    assert endpoint_path("pkg.core", module_paths, known) == "src/pkg/core.py"
    assert endpoint_path("tests/test_core.py", module_paths, known) == (
        "tests/test_core.py"
    )
    assert endpoint_path("pkg.unplaced", module_paths, known) is None
    assert endpoint_path("pkg.core", {}, known) is None
