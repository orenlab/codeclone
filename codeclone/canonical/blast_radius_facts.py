# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run facts a blast radius is computed from — one carrier, two sources.

Consumer migration C7 (``get_blast_radius``).  The blast radius has ONE
computation owner, ``codeclone.analysis.blast_radius``, and that owner used to
read its facts straight out of the report document.  The run store states the
same facts as rows, so the computation now takes them through this carrier:

* ``analysis.blast_radius.blast_radius_facts`` reads them off the report
  document the parent holds in memory;
* ``canonical.blast_radius_projection.blast_radius_facts_from_model`` reads
  them off a stored run.

Every field is exactly what the computation reads and nothing it does not,
so two carriers that are equal give the same answer by construction, and two
that differ name the fact that differs.  The carrier lives in the model store
because the analysis ring and the canonical ring both build it; it imports
nothing, so the analysis ring takes no dependency on the store by holding it.

The request (origin files, depth, the do-not-touch policy, the declared edit
scope) is NOT a fact of the run and is not carried: it is the computation's
own input, and the policy literals stay with the computation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class BlastRadiusFacts:
    """The facts of one run a blast radius reads, each in one canonical order.

    * ``dependent_paths`` -- every importing endpoint of an import edge, with
      the repository path it answers as a dependent: its file, or the
      endpoint itself when the run placed it in no file.  The computation
      maps dependents through this and nothing else.
    * ``dependency_edges`` -- the ``(source, target)`` import edges.
    * ``dependency_cycles`` -- each import cycle's modules, sorted, the
      cycles ordered by ``(size, members)``.
    * ``clone_groups`` -- each active clone group's site paths, sorted; one
      entry per group, the groups ordered by their paths.
    * the remaining path sets -- every path that holds the fact named, sorted
      and unique; the computation cuts each with the blast zone.
    """

    dependent_paths: tuple[tuple[str, str], ...]
    dependency_edges: tuple[tuple[str, str], ...]
    dependency_cycles: tuple[tuple[str, ...], ...]
    clone_groups: tuple[tuple[str, ...], ...]
    suppressed_clone_paths: tuple[str, ...]
    known_debt_paths: tuple[str, ...]
    dynamic_frontier_paths: tuple[str, ...]
    high_complexity_paths: tuple[str, ...]
    high_coupling_paths: tuple[str, ...]
    low_coverage_paths: tuple[str, ...]
    overloaded_candidate_paths: tuple[str, ...]
    overloaded_module_paths: tuple[str, ...]
    security_surface_paths: tuple[str, ...]


__all__ = ["BlastRadiusFacts"]
