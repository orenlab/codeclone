# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""F1 discriminator pins (ruling 2026-08-24 §1; fork resolved 2026-08-26).

The measured defect: the bare ``(FILE, qualname, dimension)`` key of the
``risk_observations`` family is blind to 4 real entity groups (3 sets of
``@overload`` declarations and one property/setter pair, 9 lost rows of
17 561 on the frozen corpus) — different declarations, one key.  The
ratified resolution is a producer-native discriminator: the
declaration-site ``start_line``, by the product's own precedent
(``complexity.items`` keys ``(path, qualname, start_line)`` and is
12 285/12 285 unique on the same corpus).

The named fork — declaration site as identity, unlike dependency
occurrences where location is evidence — was RESOLVED by the maintainer's
morning ruling (2026-08-26, variant (b)): the family is now a real wire
family, and the producer carries the site end to end.
"""

from __future__ import annotations

import dataclasses

from codeclone.canonical.registry import (
    FACT_FAMILY_FIELDS,
    RISK_OBSERVATIONS_FAMILY,
    RISK_OBSERVATIONS_KEY,
    wire_columns,
    wire_fact_family_order,
)
from codeclone.models import RiskObservation, Unit


def test_f1_key_is_the_ratified_declaration_site_key() -> None:
    """The exact ratified key — nothing dropped, nothing smuggled in.

    Dropping ``start_line`` reintroduces the measured 9-row collision;
    adding any further component (``end_line``, ``raw_hash``) would exceed
    the ratified complexity.items precedent. Both directions must red.
    """
    assert RISK_OBSERVATIONS_KEY == ("file", "qualname", "dimension", "start_line")


def test_f1_family_is_a_wire_family_with_the_ratified_columns() -> None:
    """Fork (b) landed: the family is real, keyed as ratified, and its wire
    columns are born mechanically from the registry — key components plus
    the one payload column, nothing else."""
    assert RISK_OBSERVATIONS_FAMILY == "risk_observations"
    assert RISK_OBSERVATIONS_FAMILY in FACT_FAMILY_FIELDS
    assert RISK_OBSERVATIONS_FAMILY in wire_fact_family_order()
    assert wire_columns(RISK_OBSERVATIONS_FAMILY) == (
        "dimension",
        "numerator",
        "start_line",
        "symbol",
    )


def test_f1_discriminator_source_claim_is_executed_not_narrated() -> None:
    """The registry declaration says the fact is producer-native.  Execute
    that claim against the real types: ``Unit`` carries ``start_line``, and
    since the K1 lane migration the projection row (``RiskObservation``)
    carries it too — the projection is no longer the lossy step."""
    unit_fields = {field.name for field in dataclasses.fields(Unit)}
    observation_fields = {field.name for field in dataclasses.fields(RiskObservation)}
    assert "start_line" in unit_fields
    assert "start_line" in observation_fields


def test_f7_cycle_kind_vocabulary_mirrors_the_producer() -> None:
    """Executed cross-check: the closed DEPENDENCY_CYCLE_KINDS vocabulary
    equals the producer's Literal — a drift on either side reds here."""
    from typing import get_args

    from codeclone.canonical.identity import DEPENDENCY_CYCLE_KINDS
    from codeclone.models import DependencyCycleKind

    assert get_args(DependencyCycleKind) == DEPENDENCY_CYCLE_KINDS


def test_f8_clone_kind_vocabulary_mirrors_the_contract_constants() -> None:
    """Executed cross-check: the closed CLONE_KINDS vocabulary equals the
    contract's own clone-kind constants, in contract declaration order."""
    from codeclone.canonical.identity import CLONE_KINDS
    from codeclone.contracts import (
        CLONE_KIND_BLOCK,
        CLONE_KIND_FUNCTION,
        CLONE_KIND_SEGMENT,
    )

    assert CLONE_KINDS == (CLONE_KIND_FUNCTION, CLONE_KIND_BLOCK, CLONE_KIND_SEGMENT)


def test_f4_dead_code_vocabularies_mirror_the_producer() -> None:
    """Executed cross-check: the three closed F4 vocabularies equal the
    producer's Literal types — a drift on either side reds here."""
    from typing import get_args

    from codeclone.canonical.identity import (
        DEAD_CODE_CANDIDATE_KINDS,
        DEAD_CODE_OBSERVATION_KINDS,
        LIVE_ROOT_REASONS,
    )
    from codeclone.models import (
        DeadCodeCandidateKind,
        DeadCodeObservationKind,
        LiveRootReason,
    )

    assert get_args(DeadCodeCandidateKind) == DEAD_CODE_CANDIDATE_KINDS
    assert get_args(DeadCodeObservationKind) == DEAD_CODE_OBSERVATION_KINDS
    assert get_args(LiveRootReason) == LIVE_ROOT_REASONS


def test_f1_dimension_vocabulary_mirrors_the_producer() -> None:
    """Executed cross-check, not a narrated one: the closed RISK_DIMENSIONS
    vocabulary equals the dimension set the real producer emits for a unit
    measured on both axes.  A drift on either side reds here."""
    from pathlib import Path

    from codeclone.canonical.identity import RISK_DIMENSIONS
    from codeclone.observations.projection import build_observation_bundle
    from tests._ast_metrics_helpers import module_registry_context

    registry = module_registry_context(
        filepath="pkg/mod.py",
        module_name="pkg.mod",
    )[1]
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=registry,
        units=(
            {
                "filepath": "pkg/mod.py",
                "qualname": "pkg.mod:probe",
                "cyclomatic_complexity": 3,
                "nesting_depth": 2,
                "start_line": 1,
                "end_line": 9,
            },
        ),
    )
    emitted = {row.dimension for row in bundle.structural.risk_observations}
    assert emitted == set(RISK_DIMENSIONS)
