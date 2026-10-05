# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The facts of a blast radius, rebuilt from one stored run — one owner.

Consumer migration C7 (``get_blast_radius``).  The computation owner,
``codeclone.analysis.blast_radius``, reads a
:class:`~codeclone.canonical.blast_radius_facts.BlastRadiusFacts` carrier; this
module fills that carrier from the run store's rows, field for field, so the
two carriers of one execution — the document's and the store's — can be held
to each other, and the computation can run on the store's.

**Where each fact is read**, and through which owner:

* ``dependency_edges`` -- the dependency relations (both endpoints spelled as
  the document spells them: a module by its dotted name, a file by its path);
* ``dependent_paths`` -- every importing endpoint through the FILE-MODULE
  relation: the module's file, or the endpoint itself when the run placed it
  in no file.  The document's own module index is a wider, legacy reading
  (it also names modules no edge ever starts from); the computation looks up
  importing endpoints only, and only those are carried;
* ``dependency_cycles`` -- the dependency-cycle rows, members sorted;
* ``clone_groups`` / ``suppressed_clone_paths`` -- the active and the
  suppressed clone-group rows, by their sites' files;
* ``known_debt_paths`` -- ``comparison_projection.known_debt_paths``, the one
  owner of "the paths a finding the comparison called known sits in";
* ``dynamic_frontier_paths`` -- ``summary_projection.dynamic_boundaries``,
  the one owner of the A6 classification;
* ``high_complexity_paths`` / ``high_coupling_paths`` --
  ``evaluation_projection.high_band_files``, the one owner of the band;
* ``low_coverage_paths`` -- ``finding_projection.coverage_group_skeletons``,
  the one owner of the two coverage hotspot rules;
* the overloaded-module and security-surface paths -- their rows.

Nothing here computes a blast radius: there is one computation, and it is
not in this package.
"""

from __future__ import annotations

from typing import Final

from codeclone.canonical.analysis_rows import CloneItemRow
from codeclone.canonical.blast_radius_facts import BlastRadiusFacts
from codeclone.canonical.codec import legacy_symbol_keys
from codeclone.canonical.comparison_projection import known_debt_paths
from codeclone.canonical.evaluation_projection import high_band_files
from codeclone.canonical.finding_projection import coverage_group_skeletons
from codeclone.canonical.identity import DependencyEndpoint, ModuleId
from codeclone.canonical.model import AnalysisFacts, CanonicalModel
from codeclone.canonical.summary_projection import dynamic_boundaries
from codeclone.utils.coerce import as_mapping, as_sequence

#: The overloaded-module status the blast radius reports as a risk signal
#: (one word of ``identity.OVERLOADED_CANDIDATE_STATUSES``).
OVERLOADED_CANDIDATE: Final = "candidate"
#: The two unit-risk dimensions whose high band the blast radius reports
#: (two words of ``evaluation_rows.RISK_UNIT_DIMENSIONS``).
COMPLEXITY_DIMENSION: Final = "complexity"
COUPLING_DIMENSION: Final = "coupling"


def _endpoint_text(endpoint: DependencyEndpoint) -> str:
    """The document's spelling of a dependency endpoint -- the inverse of the
    grammar's ``parse_endpoint``, spelled as ``serving._module_dep`` spells a
    served import source: a module by its dotted name, a file by its path."""
    return endpoint.module if isinstance(endpoint, ModuleId) else endpoint.path


def _dependency_edges(facts: AnalysisFacts) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            {
                (_endpoint_text(row.source), _endpoint_text(row.target))
                for row in facts.dependency_relations
            }
        )
    )


def _dependent_paths(
    model: CanonicalModel, edges: tuple[tuple[str, str], ...]
) -> tuple[tuple[str, str], ...]:
    """The path each importing endpoint answers as a dependent.  A module the
    relation gives two files is placed in the first by path: deterministic,
    and a run that differs from the document there is a divergence the
    serving edge names, never a silent guess it serves."""
    file_of: dict[str, str] = {}
    for relation in sorted(
        model.file_modules, key=lambda item: (item.module.module, item.file.path)
    ):
        file_of.setdefault(relation.module.module, relation.file.path)
    return tuple(sorted({(source, file_of.get(source, source)) for source, _ in edges}))


def _dependency_cycles(facts: AnalysisFacts) -> tuple[tuple[str, ...], ...]:
    return tuple(
        sorted(
            (
                tuple(sorted(module.module for module in row.modules))
                for row in facts.dependency_cycles
            ),
            key=lambda cycle: (len(cycle), cycle),
        )
    )


def _site_files(items: frozenset[CloneItemRow]) -> tuple[str, ...]:
    return tuple(sorted({item.symbol.file.path for item in items}))


def _low_coverage_paths(model: CanonicalModel) -> tuple[str, ...]:
    facts = model.facts.analysis
    legacy = legacy_symbol_keys(
        {row.symbol for row in facts.coverage_units}, model.file_modules
    )
    return tuple(
        sorted(
            {
                str(as_mapping(item).get("relative_path", ""))
                for group in coverage_group_skeletons(facts, legacy)
                for item in as_sequence(group.get("items"))
            }
        )
    )


def _dynamic_frontier_paths(model: CanonicalModel) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(as_mapping(as_mapping(site["source"]).get("file")).get("path"))
                for site in dynamic_boundaries(model)
            }
        )
    )


def blast_radius_facts_from_model(model: CanonicalModel) -> BlastRadiusFacts:
    """The facts of one stored run a blast radius reads."""
    facts = model.facts.analysis
    evaluation = model.facts.evaluation
    edges = _dependency_edges(facts)
    return BlastRadiusFacts(
        dependent_paths=_dependent_paths(model, edges),
        dependency_edges=edges,
        dependency_cycles=_dependency_cycles(facts),
        clone_groups=tuple(
            sorted(_site_files(row.items) for row in facts.clone_groups)
        ),
        suppressed_clone_paths=tuple(
            sorted(
                {
                    path
                    for row in facts.suppressed_clone_groups
                    for path in _site_files(row.items)
                }
            )
        ),
        known_debt_paths=known_debt_paths(model),
        dynamic_frontier_paths=_dynamic_frontier_paths(model),
        high_complexity_paths=high_band_files(evaluation, COMPLEXITY_DIMENSION),
        high_coupling_paths=high_band_files(evaluation, COUPLING_DIMENSION),
        low_coverage_paths=_low_coverage_paths(model),
        overloaded_candidate_paths=tuple(
            sorted(
                {
                    row.file.path
                    for row in facts.overloaded_modules
                    if row.candidate_status == OVERLOADED_CANDIDATE
                }
            )
        ),
        overloaded_module_paths=tuple(
            sorted({row.file.path for row in facts.overloaded_modules})
        ),
        security_surface_paths=tuple(
            sorted({row.file.path for row in facts.security_surfaces})
        ),
    )


__all__ = [
    "COMPLEXITY_DIMENSION",
    "COUPLING_DIMENSION",
    "OVERLOADED_CANDIDATE",
    "blast_radius_facts_from_model",
]
