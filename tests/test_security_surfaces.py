# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast

from codeclone.analysis.security_surfaces import (
    _node_end_line,
    _node_start_line,
    _SecuritySurfaceVisitor,
    collect_security_surfaces,
)


def _collect(source: str) -> tuple[tuple[str, str, str, str], ...]:
    tree = ast.parse(source)
    surfaces = collect_security_surfaces(
        tree=tree,
        module_name="pkg.mod",
        filepath="/repo/pkg/mod.py",
    )
    return tuple(
        (
            surface.category,
            surface.capability,
            surface.qualname,
            surface.evidence_symbol,
        )
        for surface in surfaces
    )


def test_collect_security_surfaces_detects_exact_boundaries() -> None:
    source = """
import requests
import subprocess
from importlib import import_module
from pathlib import Path

def run(cmd: list[str]) -> None:
    subprocess.run(cmd)
    import_module("pkg.dynamic")
    eval("1 + 1")
    Path("out.txt").write_text("ok")
"""
    assert _collect(source) == (
        ("network_boundary", "requests_import", "pkg.mod", "requests"),
        (
            "process_boundary",
            "subprocess_import",
            "pkg.mod",
            "subprocess",
        ),
        (
            "dynamic_loading",
            "importlib_import",
            "pkg.mod",
            "importlib.import_module",
        ),
        (
            "process_boundary",
            "subprocess_run",
            "pkg.mod:run",
            "subprocess.run",
        ),
        (
            "dynamic_loading",
            "import_module",
            "pkg.mod:run",
            "importlib.import_module",
        ),
        (
            "dynamic_execution",
            "dynamic_eval",
            "pkg.mod:run",
            "eval",
        ),
        (
            "filesystem_mutation",
            "pathlib_write_text",
            "pkg.mod:run",
            "pathlib.Path.write_text",
        ),
    )


def test_collect_security_surfaces_skips_type_checking_only_imports() -> None:
    source = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import yaml

def save() -> None:
    with open("out.bin", "wb") as handle:
        handle.write(b"ok")
"""
    assert _collect(source) == (
        (
            "filesystem_mutation",
            "builtin_open_write",
            "pkg.mod:save",
            "open[mode=wb]",
        ),
    )


def test_collect_security_surfaces_handles_aliases_guards_and_deduplicates() -> None:
    source = """
import subprocess as sp
import typing
from pathlib import Path
from .local import helper
from yaml import *
from yaml import unsafe_load as unsafe_load_alias

if typing.TYPE_CHECKING:
    pass
else:
    import runpy

class Writer:
    def save(self, cmd: list[str]) -> None:
        sp.run(cmd); sp.run(cmd)
        open("append.log", mode="ab")
        open("read.log", "rb")
        open("dynamic.log", mode=get_mode())
        Path("bin.dat").open(mode="wb")
        unsafe_load_alias("flag: true")
        __import__("pkg.dynamic")
        runpy.run_path("script.py")
        registry["runner"](cmd)
"""

    assert _collect(source) == (
        (
            "process_boundary",
            "subprocess_import",
            "pkg.mod",
            "subprocess",
        ),
        ("deserialization", "yaml_import", "pkg.mod", "yaml.unsafe_load"),
        ("dynamic_loading", "runpy_import", "pkg.mod", "runpy"),
        (
            "process_boundary",
            "subprocess_run",
            "pkg.mod:Writer.save",
            "subprocess.run",
        ),
        (
            "filesystem_mutation",
            "builtin_open_write",
            "pkg.mod:Writer.save",
            "open[mode=ab]",
        ),
        (
            "filesystem_mutation",
            "pathlib_open_write",
            "pkg.mod:Writer.save",
            "pathlib.Path.open",
        ),
        (
            "filesystem_mutation",
            "pathlib_open_write",
            "pkg.mod:Writer.save",
            "pathlib.Path.open[mode=wb]",
        ),
        (
            "deserialization",
            "yaml_unsafe_load",
            "pkg.mod:Writer.save",
            "yaml.unsafe_load",
        ),
        (
            "dynamic_loading",
            "builtin_import",
            "pkg.mod:Writer.save",
            "__import__",
        ),
        (
            "dynamic_loading",
            "run_path",
            "pkg.mod:Writer.save",
            "runpy.run_path",
        ),
    )


def test_security_surface_helper_edges_cover_line_fallbacks_and_blank_imports() -> None:
    assert _node_start_line(ast.Name(id="value")) is None
    assert _node_end_line(ast.Name(id="value")) == 0

    visitor = _SecuritySurfaceVisitor(
        module_name="pkg.mod",
        filepath="/repo/pkg/mod.py",
    )
    visitor.visit_Import(ast.Import(names=[ast.alias(name=" ", asname=None)]))
    visitor._emit(
        category="process_boundary",
        capability="subprocess_run",
        node=ast.Name(id="missing_line"),
        classification_mode="exact_call",
        evidence_kind="call",
        evidence_symbol="subprocess.run",
    )

    assert visitor.items == []
