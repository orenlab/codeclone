# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a ``pyproject.toml`` declares, read without crashing or under-reading.

Two manifest readers live in ``codeclone.core.entrypoints``:

* the entry-point reader roots ``[project.scripts]`` targets as live. A blank
  value (``x = ""``) split to an empty list and indexing it raised
  ``IndexError``, which the CLI turned into exit 5 for any run with metrics;
* the distribution reader names the modules a project ships, which is the
  population of its public API. Poetry's single-module include
  (``include = "my_module.py"``) and glob includes
  (``include = "extra_package/**/*.py"``) were kept verbatim, matched no
  dotted module, and left the public API at zero symbols -- so
  ``--fail-on-api-break`` passed while a public function was deleted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.core.entrypoints import (
    collect_project_distributed_packages,
    collect_project_entrypoint_qualnames,
)
from codeclone.models import DeadCandidate
from tests._pipeline_fixtures import analysis_boot, payload_mapping, run_pipeline_once
from tests._tmp_tree import write_files


def _candidate(qualname: str) -> DeadCandidate:
    module, _sep, local = qualname.partition(":")
    return DeadCandidate(
        qualname=qualname,
        local_name=local,
        filepath=f"{module.replace('.', '/')}.py",
        start_line=1,
        end_line=2,
        kind="function",
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_script_value_is_ignored_and_its_siblings_still_resolve(
    tmp_path: Path, blank: str
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n\n[project.scripts]\n"
        f'bad = "{blank}"\ngood = "pkg.cli:main"\n',
        "utf-8",
    )

    assert collect_project_entrypoint_qualnames(
        root=tmp_path,
        dead_candidates=(_candidate("pkg.cli:main"),),
    ) == frozenset({"pkg.cli:main"})


def test_a_blank_script_value_does_not_crash_a_run_with_metrics(
    tmp_path: Path,
) -> None:
    """The user-facing path: the same manifest under a full pipeline run."""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n\n[project.scripts]\n"
        'bad = ""\ngood = "pkg.cli:main"\n',
        "utf-8",
    )
    write_files(
        tmp_path,
        ("pkg/__init__.py", ""),
        ("pkg/cli.py", "def main():\n    return 0\n"),
    )
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=False)

    _cache, run = run_pipeline_once(
        boot, tmp_path / "cache.json", root=tmp_path, warm=False
    )

    project_metrics = run.result.project_metrics
    assert project_metrics is not None
    # The script target is rooted live, so the run that used to die on the
    # blank sibling now also reports the target as alive.
    assert "pkg.cli:main" not in {item.qualname for item in project_metrics.dead_code}


def _poetry_declares(tmp_path: Path, include: str) -> frozenset[str] | None:
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.poetry]\nname = "x"\npackages = [{{ include = "{include}" }}]\n',
        "utf-8",
    )
    return collect_project_distributed_packages(tmp_path)


@pytest.mark.parametrize(
    ("include", "module"),
    [
        # positive controls: the spellings that already worked
        ("my_package", "my_package"),
        ("src/my_package", "my_package"),
        ("my_package/", "my_package"),
        # a single-module include ships the module, not a file name
        ("my_module.py", "my_module"),
        ("src/my_module.py", "my_module"),
        ("pkg/mod.py", "pkg.mod"),
        # a glob ships what its literal head names
        ("extra_package/**/*.py", "extra_package"),
        ("my_pkg*", "my_pkg"),
    ],
)
def test_a_poetry_include_names_the_module_it_ships(
    tmp_path: Path, include: str, module: str
) -> None:
    assert _poetry_declares(tmp_path, include) == frozenset({module})


def test_a_glob_with_no_literal_head_declares_nothing(tmp_path: Path) -> None:
    """``*.py`` names no module; it must not become an empty-name package."""

    assert _poetry_declares(tmp_path, "*.py") is None


def test_a_poetry_single_module_project_has_a_public_api(tmp_path: Path) -> None:
    """The population end to end: the module is shipped, its API is counted."""

    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry]\nname = "x"\npackages = [{ include = "my_module.py" }]\n',
        "utf-8",
    )
    (tmp_path / "my_module.py").write_text(
        "def public_function(value: int) -> int:\n    return value + 1\n",
        "utf-8",
    )
    boot = analysis_boot(
        tmp_path, min_loc=1, min_stmt=1, skip_metrics=False, api_surface=True
    )

    _cache, run = run_pipeline_once(
        boot, tmp_path / "cache.json", root=tmp_path, warm=False
    )

    project_metrics = run.result.project_metrics
    assert project_metrics is not None
    snapshot = project_metrics.api_surface
    assert snapshot is not None
    assert [
        (module.module, module.surface_kind, symbol.qualname, symbol.exposure)
        for module in snapshot.modules
        for symbol in module.symbols
    ] == [("my_module", "product_public", "my_module:public_function", "reachable")]
    family = payload_mapping(payload_mapping(run.result.metrics_payload)["api_surface"])
    assert payload_mapping(family["summary"])["public_symbols"] == 1
