# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a blast radius counts as its origin, and what it never counts."""

from __future__ import annotations

from dataclasses import fields

from codeclone.analysis.blast_radius import (
    compute_blast_radius,
    compute_blast_radius_from_facts,
)
from codeclone.canonical.blast_radius_facts import BlastRadiusFacts


def _facts(**given: object) -> BlastRadiusFacts:
    empty: dict[str, object] = {field.name: () for field in fields(BlastRadiusFacts)}
    return BlastRadiusFacts(**{**empty, **given})  # type: ignore[arg-type]


def test_an_origin_file_is_not_its_own_direct_dependent() -> None:
    """Declaring the importer with the imported file does not widen the radius."""

    facts = _facts(
        file_modules=(("pkg/a.py", "pkg.a"), ("pkg/b.py", "pkg.b")),
        dependency_edges=(("pkg.b", "pkg.a"),),
    )

    both = compute_blast_radius_from_facts(
        run_id="r", facts=facts, files=["pkg/a.py", "pkg/b.py"]
    )
    alone = compute_blast_radius_from_facts(run_id="r", facts=facts, files=["pkg/a.py"])

    assert (both.direct_dependents, both.radius_level) == ((), "low")
    assert (alone.direct_dependents, alone.radius_level) == (("pkg/b.py",), "medium")


def test_a_directory_origin_reads_the_clone_cohort_of_its_package_file() -> None:
    """``pkg/`` stands for ``pkg/__init__.py``: the same cohort, never itself."""

    facts = _facts(
        file_modules=(("other/mod.py", "other.mod"), ("pkg/__init__.py", "pkg")),
        clone_groups=(("other/mod.py", "pkg/__init__.py"),),
    )

    directory = compute_blast_radius_from_facts(run_id="r", facts=facts, files=["pkg/"])
    package_file = compute_blast_radius_from_facts(
        run_id="r", facts=facts, files=["pkg/__init__.py"]
    )

    assert directory.clone_cohort_members == ("other/mod.py",)
    assert directory.clone_cohort_members == package_file.clone_cohort_members
    assert directory.radius_level == "medium"


def test_an_origin_the_identity_names_no_module_keeps_its_clone_cohort() -> None:
    """Widening by package file adds to the origin paths; it never replaces them."""

    facts = _facts(
        file_modules=(("other/mod.py", "other.mod"),),
        clone_groups=(("other/mod.py", "scripts/tool.py"),),
    )

    result = compute_blast_radius_from_facts(
        run_id="r", facts=facts, files=["scripts/tool.py"]
    )

    assert result.clone_cohort_members == ("other/mod.py",)


def test_an_edge_end_that_is_not_a_string_names_no_module() -> None:
    """``None`` or a number at an edge end is no module, never ``"None"``."""

    document = {
        "metrics": {
            "families": {
                "dependencies": {
                    "items": [
                        {"source": None, "target": "pkg.a"},
                        {"source": 7, "target": "pkg.a"},
                        {"source": "pkg.b", "target": None},
                        {"source": "pkg.c", "target": "pkg.a"},
                    ]
                }
            }
        }
    }

    result = compute_blast_radius(
        run_id="r",
        report_document=document,
        files=["pkg/a.py"],
        file_modules=(("pkg/a.py", "pkg.a"), ("pkg/c.py", "pkg.c")),
    )

    assert result.direct_dependents == ("pkg/c.py",)
