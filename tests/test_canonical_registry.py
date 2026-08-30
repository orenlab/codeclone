# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""F1 discriminator pins (ruling 2026-08-24 §1; fork resolved 2026-08-26).

The measured defect: the bare ``(FILE, qualname, dimension)`` key of the
``risk_observations`` family is blind to 4 real declaration groups —
``@overload`` families of 4, 4 and 3 declarations plus one property/setter
pair of 2, so 13 rows collapse onto 4 keys and 9 rows are lost (9 of
20 001 @ 95e4210b 2026-08-30, a dated observation).  Different
declarations, one key.  The ratified resolution is a producer-native
discriminator: the declaration-site ``start_line``, by the product's own
precedent (``complexity.items`` keys ``(path, qualname, start_line)`` and
is unique on it: 12 285/12 285 at ratification, 14 040/14 040 @ 95e4210b).

The named fork — declaration site as identity, unlike dependency
occurrences where location is evidence — was RESOLVED by the maintainer's
morning ruling (2026-08-26, variant (b)): the family is now a real wire
family, and the producer carries the site end to end.

``RISK_OBSERVATIONS_KEY`` has NO production consumer: the key the model
enforces is built inside ``model._prove_unique_keys``.  So the pins below
do not compare the declaration to a literal — that proves only that a
literal was typed twice, and it was measured on 2026-08-30 to stay green
while the executed key both lost ``start_line`` and gained a component.
They drive ``CanonicalModel.normalize`` and bind the declaration to the
key that actually runs, in both directions.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Callable

import pytest

from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import FileId, SymbolId
from codeclone.canonical.model import (
    AnalysisFacts,
    CanonicalFacts,
    CanonicalModel,
    DependencyOccurrenceRow,
    DependencyRelationRow,
    RiskObservationRow,
)
from codeclone.canonical.registry import (
    FACT_FAMILY_FIELDS,
    RISK_OBSERVATIONS_FAMILY,
    RISK_OBSERVATIONS_KEY,
    wire_columns,
    wire_fact_family_order,
)
from codeclone.models import RiskObservation, Unit

# The one base row every F1 pin below mutates, and the sentinel value each
# declarable component contributes to the executed key.  Distinct values on
# purpose: a key that reorders its components reds against these.
_F1_BASE_FILE = "pkg/declared.py"
_F1_BASE_QUALNAME = "Declared.parse_args"
_F1_BASE_DIMENSION = "cyclomatic_complexity"
_F1_BASE_NUMERATOR = 7
_F1_BASE_START_LINE = 11

_F1_SENTINELS: dict[str, object] = {
    "file": _F1_BASE_FILE.encode("utf-8"),
    "qualname": _F1_BASE_QUALNAME.encode("utf-8"),
    "dimension": _F1_BASE_DIMENSION,
    "start_line": _F1_BASE_START_LINE,
    "numerator": _F1_BASE_NUMERATOR,
}


def _f1_row(**overrides: object) -> RiskObservationRow:
    values: dict[str, object] = {
        "symbol": SymbolId(FileId(_F1_BASE_FILE), _F1_BASE_QUALNAME),
        "dimension": _F1_BASE_DIMENSION,
        "numerator": _F1_BASE_NUMERATOR,
        "start_line": _F1_BASE_START_LINE,
    }
    values.update(overrides)
    return RiskObservationRow(**values)  # type: ignore[arg-type]


#: One mutator per component NAME the registry may declare for this family.
#: Each yields a row differing from ``_f1_row()`` in exactly that component,
#: so the pins can ask the MODEL what each name is worth.  A declared name
#: with no mutator here is refused rather than silently skipped.
_F1_COMPONENT_MUTATORS: dict[str, Callable[[], RiskObservationRow]] = {
    "file": lambda: _f1_row(symbol=SymbolId(FileId("pkg/other.py"), _F1_BASE_QUALNAME)),
    "qualname": lambda: _f1_row(
        symbol=SymbolId(FileId(_F1_BASE_FILE), "Declared.other")
    ),
    "dimension": lambda: _f1_row(dimension="nesting_depth"),
    "start_line": lambda: _f1_row(start_line=_F1_BASE_START_LINE + 11),
    "numerator": lambda: _f1_row(numerator=_F1_BASE_NUMERATOR + 2),
}


def _f1_model(*rows: RiskObservationRow) -> CanonicalModel:
    return CanonicalModel(
        facts=CanonicalFacts(analysis=AnalysisFacts(risk_observations=frozenset(rows)))
    )


def _flatten(value: object) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        return (value,)
    return tuple(part for item in value for part in _flatten(item))


def test_f1_declared_key_is_the_key_the_model_executes() -> None:
    """The declaration names the executed key — components AND order.

    The refusal carries the key the model actually built, so this reads
    that value back out of the production path instead of restating the
    literal.  Both directions red: drop a component from either side and
    the arity stops matching; reorder either side and the sentinels stop
    lining up.
    """
    assert set(RISK_OBSERVATIONS_KEY) <= set(_F1_SENTINELS), (
        "a declared key component has no sentinel, so this pin cannot say "
        "what the executed key should contain"
    )
    with pytest.raises(CanonicalModelError) as refusal:
        # Two rows that differ ONLY in the payload column: a collision iff
        # the executed key is exactly the declared one.
        _f1_model(_f1_row(), _F1_COMPONENT_MUTATORS["numerator"]()).normalize()

    marker = "risk_observations.key="
    message = str(refusal.value)
    assert marker in message
    executed = _flatten(ast.literal_eval(message.split(marker, 1)[1]))
    assert executed == tuple(_F1_SENTINELS[name] for name in RISK_OBSERVATIONS_KEY)


def test_f1_declared_key_components_are_executed_as_identity() -> None:
    """Every DECLARED component is identity to the model: two rows differing
    only in it are two facts.  Declaring a component the model treats as
    payload reds here — the model refuses instead of keeping both."""
    declared = tuple(RISK_OBSERVATIONS_KEY)
    assert set(declared) <= set(_F1_COMPONENT_MUTATORS), (
        "a declared component has no mutator, so it would go untested"
    )
    assert set(declared) < set(_F1_COMPONENT_MUTATORS), (
        "the key must be a STRICT subset of the row's components: a family "
        "declared all-key leaves the payload pin with nothing to execute"
    )
    for name in declared:
        model = _f1_model(_f1_row(), _F1_COMPONENT_MUTATORS[name]())
        kept = model.normalize().facts.analysis.risk_observations
        assert len(kept) == 2, (
            f"{name!r} is declared a key component, but the model merged two "
            "rows that differ only in it"
        )


def test_f1_row_fields_outside_the_declared_key_are_executed_as_payload() -> None:
    """The closed half: every component the declaration does NOT name is
    payload, and two rows differing only in it share one key and are
    refused.  Dropping a real key component from the declaration reds here
    — the model keeps both rows and the expected refusal never arrives."""
    payload = tuple(
        name
        for name in sorted(_F1_COMPONENT_MUTATORS)
        if name not in RISK_OBSERVATIONS_KEY
    )
    for name in payload:
        model = _f1_model(_f1_row(), _F1_COMPONENT_MUTATORS[name]())
        with pytest.raises(CanonicalModelError, match=r"risk_observations\.key"):
            model.normalize()


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
