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

from codeclone.canonical.model import (
    DependencyOccurrenceRow,
    DependencyRelationRow,
)
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


def test_f3_family_is_a_wire_family_with_the_ratified_columns() -> None:
    """F3 landed (wave 4): key ``(scope, feature)`` — measured live at
    HEAD, 2 614/2 614 unique — with the scope as the ratified tagged
    ScopeRef (ruling 2026-08-24 §2), never a polymorphic string.  Wire
    columns are born mechanically from the registry: the two key
    components plus the two observed counters, nothing else."""
    assert "adoption_counts" in FACT_FAMILY_FIELDS
    assert "adoption_counts" in wire_fact_family_order()
    assert wire_columns("adoption_counts") == (
        "denominator",
        "feature",
        "numerator",
        "scope",
    )


def test_f3_feature_vocabulary_mirrors_the_producer_source() -> None:
    """Executed cross-check against the ONE producer: the closed
    ADOPTION_FEATURES vocabulary equals the ``feature=`` literals of
    ``observations/projection.py:_adoption_counts`` — no Literal type
    exists for this lane, so the pin reads the producer's SOURCE (the
    facts-composition AST precedent).  A drift on either side reds here."""
    import ast
    from pathlib import Path

    import codeclone.canonical.registry as registry_module
    from codeclone.canonical.identity import ADOPTION_FEATURES

    package_root = Path(registry_module.__file__).resolve().parents[1]
    source = (package_root / "observations" / "projection.py").read_text("utf-8")
    tree = ast.parse(source)
    producer = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_adoption_counts"
    )
    literals = {
        keyword.value.value
        for call in ast.walk(producer)
        if isinstance(call, ast.Call)
        for keyword in call.keywords
        if keyword.arg == "feature" and isinstance(keyword.value, ast.Constant)
    }
    assert literals == set(ADOPTION_FEATURES)
    assert len(ADOPTION_FEATURES) == 3
    assert tuple(sorted(ADOPTION_FEATURES)) == ADOPTION_FEATURES


def test_f3_scope_ref_is_the_tagged_module_file_union() -> None:
    """The ratified ScopeRef (§2) admits exactly the MODULE | FILE domains
    — measured live at HEAD: 914 module-headed and 9 path-headed scopes,
    zero unresolvable — and orders through the ONE endpoint construction,
    so two MODULE|FILE unions never grow two orderings."""
    from codeclone.canonical.identity import (
        FileId,
        ModuleId,
        ScopeRef,
        endpoint_key,
    )

    module_scope: ScopeRef = ModuleId("pkg.a")
    file_scope: ScopeRef = FileId("pkg.a")  # same text, different domain
    assert endpoint_key(module_scope) != endpoint_key(file_scope)
    assert endpoint_key(module_scope)[0] == "module"
    assert endpoint_key(file_scope)[0] == "file"


def test_f10_family_is_a_wire_family_with_the_ratified_columns() -> None:
    """F10 landed (wave 4, slice 5): key ``(FILE, start_line,
    evidence_symbol)`` — the packet's exhaustive 1-3-field enumeration
    found exactly SIX unique 3-keys, ``evidence_symbol`` in all of them
    (re-measured live at HEAD: 387/387; on the s5 corpus: 11/11).  Wire
    columns are born mechanically from the registry."""
    assert "security_surfaces" in FACT_FAMILY_FIELDS
    assert "security_surfaces" in wire_fact_family_order()
    assert wire_columns("security_surfaces") == (
        "capability",
        "category",
        "classification_mode",
        "end_line",
        "evidence_kind",
        "evidence_symbol",
        "file",
        "location_scope",
        "qualname",
        "source_kind",
        "start_line",
    )


def test_f10_vocabularies_mirror_the_producer_and_the_domain() -> None:
    """Executed cross-check: the four closed F10 vocabularies equal the
    producer's Literal types, and the source-kind verdict vocabulary
    equals the domain's breakdown keys — a drift on either side reds."""
    from typing import get_args

    from codeclone.canonical.identity import (
        SECURITY_CLASSIFICATION_MODES,
        SECURITY_EVIDENCE_KINDS,
        SECURITY_LOCATION_SCOPES,
        SECURITY_SOURCE_KINDS,
        SECURITY_SURFACE_CATEGORIES,
    )
    from codeclone.domain.source_scope import SOURCE_KIND_BREAKDOWN_KEYS
    from codeclone.models import (
        SecuritySurfaceCategory,
        SecuritySurfaceClassificationMode,
        SecuritySurfaceEvidenceKind,
        SecuritySurfaceLocationScope,
    )

    assert get_args(SecuritySurfaceCategory) == SECURITY_SURFACE_CATEGORIES
    assert get_args(SecuritySurfaceLocationScope) == SECURITY_LOCATION_SCOPES
    assert get_args(SecuritySurfaceClassificationMode) == SECURITY_CLASSIFICATION_MODES
    assert get_args(SecuritySurfaceEvidenceKind) == SECURITY_EVIDENCE_KINDS
    assert SECURITY_SOURCE_KINDS == SOURCE_KIND_BREAKDOWN_KEYS


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


def test_the_dependency_relation_key_never_absorbs_the_occurrence_site() -> None:
    """F6 guard (ruling 2026-08-28): the site discriminates an OCCURRENCE.

    F6 put ``line`` on the dependency observation lane, so the site is now
    reachable everywhere an import fact is handled — and that availability
    is precisely the temptation the ruling names: the site must NOT be
    carried into ``(source, target, dependency_type)`` merely because it
    can be.  The relation is one row per triple; keying it by the site
    would turn one entity into as many rows as it has evidence sites,
    which is the metrics dialect the ratified split ended.  Gate and SCC
    read this graph, so the mutation would be a behaviour change, not a
    cosmetic one.

    Both directions red: smuggling the site into the relation breaks the
    first half, dropping it from the occurrence breaks the second.
    """

    relation_fields = {
        field.name for field in dataclasses.fields(DependencyRelationRow)
    }
    assert relation_fields == {"source", "target", "dependency_type"}
    assert wire_columns("dependency_relations") == (
        "dependency_type",
        "source",
        "target",
    )

    occurrence_fields = {
        field.name for field in dataclasses.fields(DependencyOccurrenceRow)
    }
    assert occurrence_fields == {"relation", "line", "binding", "is_lazy"}
    assert wire_columns("dependency_occurrences") == (
        "binding",
        "dependency_type",
        "is_lazy",
        "line",
        "source",
        "target",
    )
