# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Projection equivalence: does the store answer what the report answers?

Backend P0 step 4. Step 8 will move one consumer off the report document and
onto the canonical run store. Before that can be an engineering decision
instead of an act of faith, something has to be able to say *no* -- and to
name what disagreed. This module is that instrument.

Three properties make it an instrument rather than a rubber stamp.

**Witness before count.** Every lane names the run-level declaration that
proves its family was measured, and the declaration is read through its
ratified owner (the ``r3`` door ``codeclone.api.metric_families``), never
re-derived here. A family the run did not declare is ``unmeasured``: the
mechanism refuses to compare it at all, because ``0 == 0`` between two
absences is the purest form of a guard that always says yes.

**The two sides do not share a reader.** The report side reads the exact key
path the live consumer reads (``metrics.families.<family>.items``); the
canonical side rebuilds the same assertion out of the normalized model that
came back from the store, through ``file_modules`` and the ratified identity
owners. The two paths meet only at the producer that emitted them.

**What is not compared is named.** A lane declares ``unrepresented_fields``:
report fields a live consumer reads which the canonical model carries no
answer for. A lane with any of those can never be ``equivalent`` -- only
``partial`` -- because a consumer that reads one of them cannot migrate,
however well the compared subset matches.

The report-read inventory reuses ``report_document_reads`` from
``tests.test_report_document_reads``: the mechanical chain reconstructor this
repository already owns and already proves against four scanner shapes.
Writing a second one here would be a second dialect of one question. It is
imported from an underscore module on purpose -- a ``tests/test_*.py`` whose
subject ring is ``r4`` may not also import ``r2`` internals, and this
module's subject is the ``r2`` canonical model.
"""

from __future__ import annotations

import ast
from argparse import Namespace
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version as _installed_version
from pathlib import Path

import codeclone.core.discovery as core_discovery
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.api.metric_families import (
    presentation_metric_families,
    withheld_metric_families,
)
from codeclone.baseline.clone_baseline import Baseline
from codeclone.baseline.metrics_baseline import MetricsBaseline
from codeclone.baseline.trust import BaselineStatus
from codeclone.cache.store import Cache
from codeclone.cache.versioning import CacheStatus
from codeclone.canonical import (
    RISK_DIMENSIONS,
    CanonicalModel,
    ModuleSymbol,
    OpaqueEntity,
    RunStore,
    SymbolId,
    canonical_model_from_legacy_document,
)
from codeclone.canonical.authority_identity import (
    candidate_handle,
    legacy_symbol_key,
    violation_handle,
)
from codeclone.canonical.authority_projection import (
    candidate_projection_rows,
    sink_projection_rows,
    violation_projection_rows,
)
from codeclone.contracts.schemas import ReportMeta
from codeclone.core._types import (
    AnalysisResult,
    BootstrapResult,
    OutputPaths,
    ProcessingResult,
)
from codeclone.core.parallelism import process
from codeclone.core.pipeline import analyze
from codeclone.core.reporting import build_report_body_for_analysis
from codeclone.report.document.builder import finalize_report_document
from codeclone.report.gates.evaluator import GateResult, MetricGateConfig
from codeclone.report.meta import (
    build_report_meta,
    computed_metric_families,
    current_report_timestamp_utc,
)
from codeclone.utils.coerce import as_mapping as _as_mapping
from codeclone.utils.coerce import as_sequence as _as_sequence

from .test_report_document_reads import report_document_reads

#: One semantic assertion, canonicalized as a tuple of strings so that two
#: readers can only agree by asserting the same thing, never by agreeing on
#: a separator.
Assertion = tuple[str, ...]

WITNESS_DECLARED = "declared"
WITNESS_WITHHELD = "withheld"

#: The two run-level owners that can witness a measurement. A metric family
#: is witnessed by the run's own declaration; a source-fact lane is witnessed
#: by the observation contract the analysis sealed.
WITNESS_METRIC_FAMILY = "metric_family"
WITNESS_OBSERVATION_LANE = "observation_lane"
#: The population record exists only when the run declared what it computed:
#: key absent is a legacy document that never declared, and the ingest keeps
#: the record honestly ABSENT rather than fabricating one.
WITNESS_POPULATION_RECORD = "population_record"

VERDICT_EQUIVALENT = "equivalent"
VERDICT_PARTIAL = "partial"
VERDICT_DIVERGENT = "divergent"
VERDICT_UNMEASURED = "unmeasured"

#: Bounded evidence: a diff is a report, not a dump.
MAX_DIFF_SAMPLE = 8


# -- corpus ---------------------------------------------------------------

_CANON = '''import hashlib


class Normalizer:
    """Canonical owner of the probe contract."""

    def __init__(self, salt: str) -> None:
        self.salt = salt
        self.count = 0
        self.seen: list[str] = []

    def canonical_normalize(self, value: str) -> str:
        payload = value.strip()
        self.count += 1
        self.seen.append(payload)
        return hashlib.sha256(payload.encode()).hexdigest()
'''

_SHADOW = """import hashlib
import subprocess

from pkg.canon import Normalizer


def shadow_normalize(value: str, extra: str) -> str:
    first = value.strip()
    second = extra.strip()
    payload = first + second
    return hashlib.sha256(payload.encode()).hexdigest()


def spawn(cmd: list[str]) -> int:
    return subprocess.call(cmd)


def use_owner(salt: str) -> str:
    return Normalizer(salt).canonical_normalize(salt)


def never_called(value: int) -> int:
    total = value
    total += 1
    total += 2
    return total
"""

_HELPER = '''from pkg.canon import Normalizer
from pkg.shadow import spawn


class Runner:
    """A class nobody references, so the dead-code lane is non-empty."""

    def __init__(self) -> None:
        self.jobs: list[str] = []
        self.done = 0
        self.failed = 0
        self.normalizer = Normalizer("salt")

    def label(self, value: str) -> str:
        marker = Normalizer(value)
        return marker.canonical_normalize(value)

    def run(self, cmd: list[str]) -> int:
        self.jobs.append(" ".join(cmd))
        self.done += 1
        return spawn(cmd)

    def reset(self) -> None:
        self.jobs = []
        self.done = 0
        self.failed = 0
'''

#: Two byte-identical bodies in different modules: the clone lane needs a
#: group, and a group needs two items.
_TWIN_BODY = """

def twin_{tag}(rows: list[int]) -> int:
    total = 0
    seen = []
    for row in rows:
        total += row
        total += 1
        seen.append(row)
    if total > 10:
        total = total - 1
    else:
        total = total + 1
    return total
"""

#: An import cycle, so ``dependency_cycles`` is a measured non-empty family
#: rather than a comparison nothing reaches.
_CYCLE_A = """from pkg.cycle_b import step_b


def step_a(value: int) -> int:
    return step_b(value) + 1
"""

_CYCLE_B = """from pkg.cycle_a import step_a


def step_b(value: int) -> int:
    return step_a(value) - 1
"""

_AUTHORITY_REGISTRY: tuple[dict[str, object], ...] = (
    {
        "contract_id": "projection-equivalence.normalize/v1",
        "canonical_owner": "pkg.canon:Normalizer.canonical_normalize",
        "allowed_adapters": [],
        "forbidden_raw_inputs": ["param:0"],
        "required_provenance": ["producer:pkg.canon:Normalizer.canonical_normalize"],
    },
)


def write_probe_tree(root: Path) -> None:
    """Lay out the distinguishing corpus every lane is measured on."""

    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    (package / "canon.py").write_text(_CANON + _TWIN_BODY.format(tag="one"), "utf-8")
    (package / "shadow.py").write_text(_SHADOW + _TWIN_BODY.format(tag="two"), "utf-8")
    (package / "helper.py").write_text(_HELPER, "utf-8")
    (package / "cycle_a.py").write_text(_CYCLE_A, "utf-8")
    (package / "cycle_b.py").write_text(_CYCLE_B, "utf-8")


def _boot(root: Path) -> BootstrapResult:
    return BootstrapResult(
        root=root,
        config=NormalizationConfig(),
        args=Namespace(
            processes=1,
            min_loc=6,
            min_stmt=4,
            block_min_loc=20,
            block_min_stmt=8,
            segment_min_loc=20,
            segment_min_stmt=10,
            skip_metrics=False,
            skip_dependencies=False,
            skip_dead_code=False,
            near_miss=False,
            renamed_structure=False,
            semantic_authority=True,
            authority=list(_AUTHORITY_REGISTRY),
            api_surface=True,
        ),
        output_paths=OutputPaths(html=None, json=None, text=None),
        cache_path=root / "cache.json",
    )


def _probe_report_meta(
    root: Path,
    *,
    boot: BootstrapResult,
    processing: ProcessingResult,
    result: AnalysisResult,
) -> ReportMeta:
    """The corpus meta, built by the product's own owner.

    Hand-writing the two or three keys a consumer happens to read is how a
    corpus stops being representative: the run-identity wave landed an
    ``AnalysisPopulation`` oracle that reads ``meta.analysis_profile``, a key
    a minimal fixture never carried, and every lane went red on a document
    no producer emits. ``build_report_meta`` is the single owner of what a
    run says about itself, so the corpus asks it rather than guessing which
    subset is enough -- and the next key some oracle starts reading is
    already here.
    """

    args = boot.args
    return build_report_meta(
        codeclone_version=_installed_version("codeclone"),
        scan_root=root,
        baseline_path=root / "codeclone.baseline.json",
        baseline=Baseline(root / "codeclone.baseline.json"),
        baseline_loaded=False,
        baseline_status=BaselineStatus.MISSING.value,
        cache_path=boot.cache_path,
        cache_used=False,
        cache_status=CacheStatus.MISSING.value,
        cache_schema_version=None,
        files_skipped_source_io=len(processing.source_read_failures),
        metrics_baseline_path=root / "codeclone.baseline.json",
        metrics_baseline=MetricsBaseline(root / "codeclone.baseline.json"),
        metrics_baseline_loaded=False,
        metrics_baseline_status=BaselineStatus.MISSING.value,
        health_score=(
            result.project_metrics.health.total if result.project_metrics else None
        ),
        health_grade=(
            result.project_metrics.health.grade if result.project_metrics else None
        ),
        analysis_mode="clones_only" if args.skip_metrics else "full",
        metrics_computed=computed_metric_families(
            metrics_payload=result.metrics_payload,
            skip_dependencies=args.skip_dependencies,
            skip_dead_code=args.skip_dead_code,
            api_surface=args.api_surface,
        ),
        min_loc=args.min_loc,
        min_stmt=args.min_stmt,
        block_min_loc=args.block_min_loc,
        block_min_stmt=args.block_min_stmt,
        segment_min_loc=args.segment_min_loc,
        segment_min_stmt=args.segment_min_stmt,
        analysis_started_at_utc=None,
        report_generated_at_utc=current_report_timestamp_utc(),
    )


def build_probe_document(root: Path) -> dict[str, object]:
    """Run the real pipeline over the probe tree and seal its document.

    Every hop is the product's own: discovery, processing, ``analyze``, the
    report body builder and the document finalizer. Nothing about the
    document's shape is authored here, because the shape is exactly what a
    consumer depends on.
    """

    write_probe_tree(root)
    boot = _boot(root)
    cache = Cache(root / "cache.json", root=root)
    discovery = core_discovery.discover(boot=boot, cache=cache)
    processing = process(boot=boot, discovery=discovery, cache=cache)
    result = analyze(boot=boot, discovery=discovery, processing=processing)
    if processing.semantic_authority is None:
        raise AssertionError("probe corpus lost its authority producer")
    if result.project_metrics is None or result.metrics_payload is None:
        raise AssertionError("probe corpus lost its metrics producers")
    gate_config = MetricGateConfig(
        fail_complexity=-1,
        fail_coupling=-1,
        fail_cohesion=-1,
        fail_cycles=False,
        fail_dead_code=False,
        fail_health=-1,
        fail_on_new_metrics=False,
    )
    body = build_report_body_for_analysis(
        discovery=discovery,
        processing=processing,
        analysis=result,
        report_meta=_probe_report_meta(
            root, boot=boot, processing=processing, result=result
        ),
        new_func=None,
        new_block=None,
    )
    return finalize_report_document(
        body=body,
        observation_bundle=result.observation_bundle,
        baseline_container=None,
        baseline_trust=None,
        gate_config=gate_config,
        gate_result=GateResult(exit_code=0, reasons=()),
    )


@dataclass(frozen=True, slots=True)
class ProjectionCorpus:
    """One report document and the model that came back out of the store."""

    document: Mapping[str, object]
    model: CanonicalModel
    stored_model: CanonicalModel
    run_id: str


def build_corpus(root: Path, *, store_path: Path) -> ProjectionCorpus:
    """Publish the probe run and read it back; both models are returned.

    ``model`` is what ingest produced, ``stored_model`` is what survived the
    sqlite round trip. A lane is compared against ``stored_model`` -- the
    thing a migrated consumer would actually hold.
    """

    document = build_probe_document(root)
    model = canonical_model_from_legacy_document(document)
    with RunStore(store_path) as store:
        receipt = store.write_full_run(
            model,
            namespace="projection-equivalence",
            target="probe",
            expected_generation=0,
        )
        stored = store.read_run(receipt.run_id)
    return ProjectionCorpus(
        document=document,
        model=model,
        stored_model=stored,
        run_id=receipt.run_id,
    )


# -- witness --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WitnessRef:
    """Which run-level declaration proves a lane's family was measured."""

    kind: str
    name: str


def family_witness(document: Mapping[str, object], family: str) -> str:
    """Did this run declare that it measured metric family ``family``?

    The declaration is interpreted by its ratified owner, the ``r3`` door
    ``codeclone.api.metric_families``. A withheld family's payload -- which
    the container carries either way -- is a zero nobody measured.
    """

    meta = _as_mapping(document.get("meta"))
    families = _as_mapping(_as_mapping(document.get("metrics")).get("families"))
    declared = presentation_metric_families(meta, families)
    return WITNESS_DECLARED if family in declared else WITNESS_WITHHELD


def lane_witness(document: Mapping[str, object], lane: str) -> str:
    """Did the sealed observation contract enable source-fact lane ``lane``?

    ``findings.groups.clones`` is not a metric family, so the declaration
    that answers for it is the analysis-side one: the observation contract
    the run sealed into ``source_facts``. Same law, different owner -- an
    absent lane is not an empty one.
    """

    contract = _as_mapping(
        _as_mapping(document.get("source_facts")).get("observation_contract")
    )
    enabled = {str(name) for name in _as_sequence(contract.get("enabled_lanes"))}
    return WITNESS_DECLARED if lane in enabled else WITNESS_WITHHELD


def declaration_witness(document: Mapping[str, object], key: str) -> str:
    """Does the run declare what it computed at all?

    Key PRESENCE, never the truthiness of the value: a present-and-empty
    declaration is a run that honestly computed nothing, and an absent one is
    a document that never declared. Only the second leaves the canonical
    model without a population record, so only the second is a refusal.
    """

    return (
        WITNESS_DECLARED
        if key in _as_mapping(document.get("meta"))
        else WITNESS_WITHHELD
    )


def witness_state(document: Mapping[str, object], witness: WitnessRef) -> str:
    """Resolve one lane's witness through its own owner."""

    if witness.kind == WITNESS_METRIC_FAMILY:
        return family_witness(document, witness.name)
    if witness.kind == WITNESS_OBSERVATION_LANE:
        return lane_witness(document, witness.name)
    if witness.kind == WITNESS_POPULATION_RECORD:
        return declaration_witness(document, witness.name)
    raise AssertionError(f"unknown witness kind: {witness.kind!r}")


# -- readers --------------------------------------------------------------


def family_items(
    document: Mapping[str, object], family: str
) -> tuple[Mapping[str, object], ...]:
    """``metrics.families.<family>.items`` -- the live consumers' key path."""

    families = _as_mapping(_as_mapping(document.get("metrics")).get("families"))
    payload = _as_mapping(families.get(family))
    return tuple(_as_mapping(row) for row in _as_sequence(payload.get("items")))


#: The ``coverage_adoption`` family states its counts as columns; the model
#: states them as ``(feature, numerator, denominator)`` under the ratified
#: ``ADOPTION_FEATURES`` vocabulary. The binding is the vocabulary's own, so
#: a renamed feature moves both sides or neither.
_ADOPTION_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("docstrings.public_symbols", "public_symbol_documented", "public_symbol_total"),
    ("typing.parameters", "params_annotated", "params_total"),
    ("typing.returns", "returns_annotated", "returns_total"),
)


def _text(value: object) -> str:
    return str(value if value is not None else "")


def _number(value: object) -> int:
    """The row's integer, or zero when the row asserts no number there."""

    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _module_heads(model: CanonicalModel) -> dict[str, str]:
    """FILE path -> the producer's head for that file.

    The head is the registry module name when the file has one and the
    analysis path otherwise -- the single fallback slot of the producer's key
    grammar, not two schemes.
    """

    heads: dict[str, str] = {}
    for relation in model.file_modules:
        path = relation.file.path
        module = relation.module.module
        if heads.setdefault(path, module) != module:
            raise AssertionError(f"file {path!r} carries two module heads")
    for file_id in model.files:
        heads.setdefault(file_id.path, file_id.path)
    return heads


def _symbol_key(model: CanonicalModel, symbol: SymbolId) -> str:
    return legacy_symbol_key(_module_heads(model)[symbol.file.path], symbol.qualname)


def _entity_key(entity: object) -> str:
    if isinstance(entity, SymbolId):
        return legacy_symbol_key(entity.file.path, entity.qualname)
    if isinstance(entity, ModuleSymbol):
        return legacy_symbol_key(entity.module.module, entity.qualname)
    if isinstance(entity, OpaqueEntity):
        return legacy_symbol_key(entity.head, entity.qualname)
    raise AssertionError(f"not a dead-code entity: {entity!r}")


def _endpoint_text(endpoint: object) -> str:
    module = getattr(endpoint, "module", None)
    if module is not None:
        return str(getattr(module, "module", module))
    file_id = getattr(endpoint, "file", None)
    if file_id is not None:
        return str(getattr(file_id, "path", file_id))
    return str(endpoint)


def _authority_items(
    document: Mapping[str, object], kind: str
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        row
        for row in family_items(document, "semantic_authority")
        if _text(row.get("item_kind")) == kind
    )


def authority_candidate_rows(
    document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    """The published candidate rows, in the order the document ranked them."""

    return _authority_items(document, "candidate")


# report readers -----------------------------------------------------------


def _report_candidates(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (_text(row.get("candidate_id")),)
        for row in _authority_items(document, "candidate")
    )


def _report_violations(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (_text(row.get("violation_id")),)
        for row in _authority_items(document, "violation")
    )


def _report_sinks(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (_text(row.get("sink_identity")), _text(row.get("authority_status")))
        for row in _authority_items(document, "sink")
    )


def _report_dependency_relations(
    document: Mapping[str, object],
) -> frozenset[Assertion]:
    return frozenset(
        (
            _text(row.get("source")),
            _text(row.get("target")),
            _text(row.get("import_type")),
        )
        for row in family_items(document, "dependencies")
    )


def _report_dependency_occurrences(
    document: Mapping[str, object],
) -> frozenset[Assertion]:
    return frozenset(
        (
            _text(row.get("source")),
            _text(row.get("target")),
            _text(row.get("import_type")),
            _text(row.get("line")),
            _text(row.get("binding")),
            _text(bool(row.get("is_lazy"))),
        )
        for row in family_items(document, "dependencies")
    )


def _report_dependency_cycles(
    document: Mapping[str, object],
) -> frozenset[Assertion]:
    families = _as_mapping(_as_mapping(document.get("metrics")).get("families"))
    payload = _as_mapping(families.get("dependencies"))
    rows = tuple(_as_mapping(row) for row in _as_sequence(payload.get("cycle_details")))
    return frozenset(
        (
            _text(row.get("kind")),
            " ".join(sorted(_text(name) for name in _as_sequence(row.get("modules")))),
        )
        for row in rows
    )


def _report_api_symbols(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (
            _text(row.get("qualname")),
            _text(row.get("symbol_kind")),
            _text(row.get("params_total")),
        )
        for row in family_items(document, "api_surface")
        if _text(row.get("record_kind")) == "symbol"
    )


def _report_complexity(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (_text(row.get("qualname")), dimension, _text(row.get(dimension)))
        for row in family_items(document, "complexity")
        for dimension in RISK_DIMENSIONS
        if _number(row.get(dimension))
    )


def _report_coupling(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (_text(row.get("qualname")), "cbo", _text(row.get("cbo")))
        for row in family_items(document, "coupling")
        if _number(row.get("cbo"))
    )


def _report_cohesion(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (_text(row.get("qualname")), dimension, _text(row.get(key)))
        for row in family_items(document, "cohesion")
        for dimension, key in (
            ("lcom4", "lcom4"),
            ("methods", "method_count"),
            ("instance_variables", "instance_var_count"),
        )
        if _number(row.get(key))
    )


def _report_dead_code(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (_text(row.get("qualname")), _text(row.get("kind")))
        for row in family_items(document, "dead_code")
    )


def _report_security_surfaces(
    document: Mapping[str, object],
) -> frozenset[Assertion]:
    return frozenset(
        (
            _text(row.get("relative_path")),
            _text(row.get("start_line")),
            _text(row.get("end_line")),
            _text(row.get("category")),
            _text(row.get("capability")),
        )
        for row in family_items(document, "security_surfaces")
    )


def _report_adoption(document: Mapping[str, object]) -> frozenset[Assertion]:
    return frozenset(
        (
            _text(row.get("module")),
            feature,
            _text(row.get(numerator)),
            _text(row.get(denominator)),
        )
        for row in family_items(document, "coverage_adoption")
        for feature, numerator, denominator in _ADOPTION_COLUMNS
        if _number(row.get(denominator))
    )


# canonical readers --------------------------------------------------------


def _model_candidates(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (
            candidate_handle(
                level=row.level,
                shared_fact=row.shared_fact,
                producers=[
                    _symbol_key(model, producer) for producer in row.producer_set
                ],
            ),
        )
        for row in model.facts.analysis.candidates
    )


def _model_violations(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (
            violation_handle(
                contract_id=row.contract_id,
                kind=row.kind,
                sink_identity=_symbol_key(model, row.sink_identity),
                producers=[
                    _symbol_key(model, producer) for producer in row.producer_set
                ],
            ),
        )
        for row in model.facts.analysis.violations
    )


def _model_sinks(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (_symbol_key(model, row.symbol), row.authority_status)
        for row in model.facts.analysis.sink_roles
    )


def _model_dependency_relations(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (
            _endpoint_text(row.source),
            _endpoint_text(row.target),
            row.dependency_type,
        )
        for row in model.facts.analysis.dependency_relations
    )


def _model_dependency_occurrences(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (
            _endpoint_text(row.relation.source),
            _endpoint_text(row.relation.target),
            row.relation.dependency_type,
            _text(row.line),
            row.binding,
            _text(row.is_lazy),
        )
        for row in model.facts.analysis.dependency_occurrences
    )


def _model_dependency_cycles(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (row.kind, " ".join(sorted(module.module for module in row.modules)))
        for row in model.facts.analysis.dependency_cycles
    )


def _model_api_symbols(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (
            _symbol_key(model, row.symbol),
            row.symbol_kind,
            _text(len(row.parameters)),
        )
        for row in model.facts.analysis.api_symbols
    )


def _model_risk(
    model: CanonicalModel, dimensions: frozenset[str]
) -> frozenset[Assertion]:
    return frozenset(
        (_symbol_key(model, row.symbol), row.dimension, _text(row.numerator))
        for row in model.facts.analysis.risk_observations
        if row.dimension in dimensions
    )


def _model_coupling_cohesion(
    model: CanonicalModel, dimensions: frozenset[str]
) -> frozenset[Assertion]:
    return frozenset(
        (_symbol_key(model, row.symbol), row.dimension, _text(row.numerator))
        for row in model.facts.analysis.coupling_cohesion_observations
        if row.dimension in dimensions
    )


def _model_dead_code(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (_entity_key(row.entity), row.candidate_kind)
        for row in model.facts.analysis.dead_code_observations
    )


def _model_security_surfaces(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (
            row.file.path,
            _text(row.start_line),
            _text(row.end_line),
            row.category,
            row.capability,
        )
        for row in model.facts.analysis.security_surfaces
    )


def _model_adoption(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (
            _text(getattr(row.scope, "module", getattr(row.scope, "path", row.scope))),
            row.feature,
            _text(row.numerator),
            _text(row.denominator),
        )
        for row in model.facts.analysis.adoption_counts
    )


# population readers -------------------------------------------------------

#: The meta keys the canonical population record speaks for. Everything else
#: in ``meta`` -- baseline, cache, versions, timestamps -- is outside this
#: record by design, so the lane's rows are these three and no more.
_POPULATION_META_KEYS: tuple[str, ...] = (
    "analysis_mode",
    "analysis_profile",
    "computed_metric_families",
)


def _population_rows(
    document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    meta = _as_mapping(document.get("meta"))
    return ({key: meta[key] for key in _POPULATION_META_KEYS if key in meta},)


def _report_population(document: Mapping[str, object]) -> frozenset[Assertion]:
    """The run's own execution declaration, read through the R3 door.

    Both halves come from the door: what it keeps is ``complete``, what it
    withholds is ``not_executed``. Re-deriving either half here would put a
    second spelling of the declaration law next to its owner.
    """

    meta = _as_mapping(document.get("meta"))
    families = _as_mapping(_as_mapping(document.get("metrics")).get("families"))
    profile = _as_mapping(meta.get("analysis_profile"))
    assertions: set[Assertion] = {("mode", _text(meta.get("analysis_mode")))}
    assertions |= {
        ("profile", str(name), _text(value)) for name, value in profile.items()
    }
    assertions |= {
        ("producer_state", str(name), "complete")
        for name in presentation_metric_families(meta, families)
    }
    assertions |= {
        ("producer_state", str(name), "not_executed")
        for name in withheld_metric_families(meta, families)
    }
    return frozenset(assertions)


def _model_population(model: CanonicalModel) -> frozenset[Assertion]:
    population = model.facts.analysis.analysis_population
    if population is None:
        return frozenset()
    assertions: set[Assertion] = {("mode", population.analysis_mode)}
    assertions |= {
        ("profile", name, _text(value)) for name, value in population.analysis_profile
    }
    assertions |= {
        ("producer_state", family, state)
        for family, state in population.producer_states
    }
    return frozenset(assertions)


# clone readers ------------------------------------------------------------

#: The emitted clone containers and the model's ``clone_kind`` for each. The
#: container names are PLURAL and the kind is singular; reading the singular
#: name finds nothing and reads as an empty family, which is exactly the
#: silence the reachability pin exists to break.
_CLONE_CONTAINERS: tuple[tuple[str, str], ...] = (
    ("functions", "function"),
    ("blocks", "block"),
    ("segments", "segment"),
)


def _clone_rows(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    """``findings.groups.clones.<kind>`` -- what ``blast_radius`` walks.

    The ``suppressed`` container is deliberately not read: it is a different
    population (ruling 2026-08-24 SS10), and folding it in here would rebuild
    the known reader dialect inside the instrument meant to detect it.
    """

    groups = _as_mapping(
        _as_mapping(_as_mapping(document.get("findings")).get("groups")).get("clones")
    )
    return tuple(
        _as_mapping(row)
        for container, _kind in _CLONE_CONTAINERS
        for row in _as_sequence(groups.get(container))
    )


def _report_clone_groups(document: Mapping[str, object]) -> frozenset[Assertion]:
    groups = _as_mapping(
        _as_mapping(_as_mapping(document.get("findings")).get("groups")).get("clones")
    )
    return frozenset(
        (
            _text(row.get("clone_kind")),
            _text(_as_mapping(row.get("facts")).get("group_key")),
            _text(len(_as_sequence(row.get("items")))),
        )
        for container, _kind in _CLONE_CONTAINERS
        for row in (_as_mapping(item) for item in _as_sequence(groups.get(container)))
    )


def _model_clone_groups(model: CanonicalModel) -> frozenset[Assertion]:
    return frozenset(
        (row.clone_kind, row.group_key, _text(len(row.items)))
        for row in model.facts.analysis.clone_groups
    )


# -- lanes ----------------------------------------------------------------


def _metric_rows(
    family: str,
) -> Callable[[Mapping[str, object]], tuple[Mapping[str, object], ...]]:
    def rows(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
        return family_items(document, family)

    return rows


def _authority_rows(
    kind: str,
) -> Callable[[Mapping[str, object]], tuple[Mapping[str, object], ...]]:
    def rows(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
        return _authority_items(document, kind)

    return rows


def _cycle_rows(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    families = _as_mapping(_as_mapping(document.get("metrics")).get("families"))
    payload = _as_mapping(families.get("dependencies"))
    return tuple(_as_mapping(row) for row in _as_sequence(payload.get("cycle_details")))


def _risk(model: CanonicalModel) -> frozenset[Assertion]:
    return _model_risk(model, frozenset(RISK_DIMENSIONS))


def _cbo(model: CanonicalModel) -> frozenset[Assertion]:
    return _model_coupling_cohesion(model, frozenset({"cbo"}))


def _class_shape(model: CanonicalModel) -> frozenset[Assertion]:
    return _model_coupling_cohesion(
        model, frozenset({"lcom4", "methods", "instance_variables"})
    )


@dataclass(frozen=True, slots=True)
class LaneSpec:
    """One semantic family, read twice, plus what the model cannot answer.

    ``represented_fields`` is the POSITIVE declaration: report row keys the
    canonical model carries an answer for. What the model cannot answer is
    derived from it -- ``row keys - represented`` -- so a report that grows a
    new key makes that key unrepresented by default instead of quietly
    joining a hand-written list that nobody updated. The two failure modes
    are both visible: an invented entry names a key no row carries, and a
    forgotten one turns a lane ``partial``.

    ``projection`` is the OTHER way a key stops being a gap: a column the
    model does not store but a named owner rebuilds from what it does store.
    That exemption is never declared -- it is measured per run against the
    report's own rows (:func:`lane_restored_fields`), so a projection that
    stops reproducing a column loses the exemption instead of keeping a
    stale entry in a hand-written list.
    """

    name: str
    witness: WitnessRef
    report_rows: Callable[[Mapping[str, object]], tuple[Mapping[str, object], ...]]
    report_reader: Callable[[Mapping[str, object]], frozenset[Assertion]]
    model_reader: Callable[[CanonicalModel], frozenset[Assertion]]
    represented_fields: tuple[str, ...] = ()
    projection: Callable[[CanonicalModel], Sequence[Mapping[str, object]]] | None = None


def _metric_family(name: str) -> WitnessRef:
    return WitnessRef(kind=WITNESS_METRIC_FAMILY, name=name)


LANES: tuple[LaneSpec, ...] = (
    LaneSpec(
        # The witness itself, compared rather than trusted. Until the tier
        # grammar landed ``AnalysisPopulation`` the model could not say which
        # producers ran, so this instrument could only read the report side
        # and had to take it on faith. Now both sides pronounce it, and a
        # disagreement between the run's declaration and the stored
        # population is a red assertion instead of a silent assumption.
        name="analysis_population.states",
        witness=WitnessRef(
            kind=WITNESS_POPULATION_RECORD, name="computed_metric_families"
        ),
        report_rows=_population_rows,
        report_reader=_report_population,
        model_reader=_model_population,
        represented_fields=_POPULATION_META_KEYS,
    ),
    LaneSpec(
        name="authority.candidates",
        witness=_metric_family("semantic_authority"),
        report_rows=_authority_rows("candidate"),
        report_reader=_report_candidates,
        model_reader=_model_candidates,
        represented_fields=(
            "candidate_id",
            "item_kind",
            "level",
            "producers",
            "shared_fact",
        ),
        # The remaining published columns are rebuilt, not stored: three
        # analysis conclusions the stored graph settles, plus a level score,
        # a ranking classification, a run-provenance label and the union's
        # boolean placeholder. The owner is measured here, never trusted.
        projection=candidate_projection_rows,
    ),
    LaneSpec(
        name="authority.violations",
        witness=_metric_family("semantic_authority"),
        report_rows=_authority_rows("violation"),
        report_reader=_report_violations,
        model_reader=_model_violations,
        represented_fields=(
            "authority_status",
            "canonical_owner",
            "contract_id",
            "effect_signature",
            "item_kind",
            "kind",
            "producers",
            "resolution_state",
            "sink_identity",
            "suppressed",
            "violation_id",
        ),
        # Six of the seven remaining columns are rebuilt: a stored root
        # set, a document-layer ranking term over the stored producers, a
        # run-provenance label and three union placeholders. The seventh,
        # ``locations``, has no stored basis at all -- the projection does
        # not emit it, so this lane stays honestly ``partial``.
        projection=violation_projection_rows,
    ),
    LaneSpec(
        name="authority.sinks",
        witness=_metric_family("semantic_authority"),
        report_rows=_authority_rows("sink"),
        report_reader=_report_sinks,
        model_reader=_model_sinks,
        represented_fields=("authority_status", "item_kind", "sink_identity"),
        # The other nine published columns are rebuilt, not stored: three
        # contract columns the stored graph node already carries, a ranking
        # term, a run-provenance label and the union's four placeholders.
        projection=sink_projection_rows,
    ),
    LaneSpec(
        name="dependencies.relations",
        witness=_metric_family("dependencies"),
        report_rows=_metric_rows("dependencies"),
        report_reader=_report_dependency_relations,
        model_reader=_model_dependency_relations,
        represented_fields=(
            "binding",
            "import_type",
            "is_lazy",
            "line",
            "source",
            "target",
        ),
    ),
    LaneSpec(
        name="dependencies.occurrences",
        witness=_metric_family("dependencies"),
        report_rows=_metric_rows("dependencies"),
        report_reader=_report_dependency_occurrences,
        model_reader=_model_dependency_occurrences,
        represented_fields=(
            "binding",
            "import_type",
            "is_lazy",
            "line",
            "source",
            "target",
        ),
    ),
    LaneSpec(
        name="dependencies.cycles",
        witness=_metric_family("dependencies"),
        report_rows=_cycle_rows,
        report_reader=_report_dependency_cycles,
        model_reader=_model_dependency_cycles,
        represented_fields=("kind", "modules"),
    ),
    LaneSpec(
        name="api_surface.symbols",
        witness=_metric_family("api_surface"),
        report_rows=_metric_rows("api_surface"),
        report_reader=_report_api_symbols,
        model_reader=_model_api_symbols,
        represented_fields=(
            "module",
            "params",
            "params_total",
            "qualname",
            "relative_path",
            "returns_annotated",
            "symbol_kind",
        ),
    ),
    LaneSpec(
        name="complexity.cyclomatic",
        witness=_metric_family("complexity"),
        report_rows=_metric_rows("complexity"),
        report_reader=_report_complexity,
        model_reader=_risk,
        represented_fields=(
            "cyclomatic_complexity",
            "nesting_depth",
            "qualname",
            "relative_path",
            "start_line",
        ),
    ),
    LaneSpec(
        name="coupling.cbo",
        witness=_metric_family("coupling"),
        report_rows=_metric_rows("coupling"),
        report_reader=_report_coupling,
        model_reader=_cbo,
        represented_fields=("cbo", "qualname", "relative_path"),
    ),
    LaneSpec(
        name="cohesion.class_shape",
        witness=_metric_family("cohesion"),
        report_rows=_metric_rows("cohesion"),
        report_reader=_report_cohesion,
        model_reader=_class_shape,
        represented_fields=(
            "instance_var_count",
            "lcom4",
            "method_count",
            "qualname",
            "relative_path",
        ),
    ),
    LaneSpec(
        name="dead_code.candidates",
        witness=_metric_family("dead_code"),
        report_rows=_metric_rows("dead_code"),
        report_reader=_report_dead_code,
        model_reader=_model_dead_code,
        represented_fields=("kind", "qualname", "relative_path"),
    ),
    LaneSpec(
        name="security_surfaces.items",
        witness=_metric_family("security_surfaces"),
        report_rows=_metric_rows("security_surfaces"),
        report_reader=_report_security_surfaces,
        model_reader=_model_security_surfaces,
        represented_fields=(
            "capability",
            "category",
            "classification_mode",
            "end_line",
            "evidence_kind",
            "evidence_symbol",
            "location_scope",
            "qualname",
            "relative_path",
            "source_kind",
            "start_line",
        ),
    ),
    LaneSpec(
        name="coverage_adoption.counts",
        witness=_metric_family("coverage_adoption"),
        report_rows=_metric_rows("coverage_adoption"),
        report_reader=_report_adoption,
        model_reader=_model_adoption,
        represented_fields=(
            "module",
            "params_annotated",
            "params_total",
            "public_symbol_documented",
            "public_symbol_total",
            "relative_path",
            "returns_annotated",
            "returns_total",
        ),
    ),
    LaneSpec(
        name="clones.groups",
        witness=WitnessRef(kind=WITNESS_OBSERVATION_LANE, name="clones.functions"),
        report_rows=_clone_rows,
        report_reader=_report_clone_groups,
        model_reader=_model_clone_groups,
        # The analysis model carries the group; the finding envelope's
        # classification (severity, confidence, priority) and its novelty
        # belong to the comparison and evaluation tiers by the ratified
        # grammar, so their absence here is the model being correct.
        represented_fields=("category", "clone_kind", "count", "facts", "items"),
    ),
)


def lane_row_keys(spec: LaneSpec, document: Mapping[str, object]) -> frozenset[str]:
    """Every key the lane's report rows actually carry, in this run."""

    return frozenset(str(key) for row in spec.report_rows(document) for key in row)


#: Values that assert nothing. The authority container is one union of four
#: item kinds, so a sink row literally carries ``candidate_id: ""``. A column
#: that is empty on every row of a lane is the union's placeholder, not a
#: fact the canonical model failed to carry, and calling it a gap would tell
#: step 8 that a migratable lane cannot migrate.
_EMPTY_VALUES: tuple[object, ...] = (None, "", [], {}, (), frozenset())


def _asserts(value: object) -> bool:
    return not any(value is empty or value == empty for empty in _EMPTY_VALUES)


def lane_placeholder_fields(
    spec: LaneSpec, document: Mapping[str, object]
) -> tuple[str, ...]:
    """Keys this lane's rows carry with no value on any row."""

    rows = spec.report_rows(document)
    keys = lane_row_keys(spec, document)
    return tuple(
        sorted(key for key in keys if not any(_asserts(row.get(key)) for row in rows))
    )


def lane_restored_fields(
    spec: LaneSpec, document: Mapping[str, object], model: CanonicalModel
) -> tuple[str, ...]:
    """Report keys this lane's projection rebuilds -- measured, not declared.

    A key is restored only when the projection emits the same number of rows
    in the same order and the same value for that key on EVERY row. Order is
    part of the claim on purpose: a consumer pages these rows, so a
    projection that agrees as a set and disagrees as a sequence hands page
    two a different slice and must not be called equivalent.
    """

    if spec.projection is None:
        return ()
    reported = spec.report_rows(document)
    projected = tuple(spec.projection(model))
    if len(projected) != len(reported):
        return ()
    pairs = tuple(zip(reported, projected, strict=True))
    return tuple(
        sorted(
            key
            for key in lane_row_keys(spec, document)
            if all(
                key in row and row[key] == rebuilt.get(key) for row, rebuilt in pairs
            )
        )
    )


def lane_unrepresented_fields(
    spec: LaneSpec, document: Mapping[str, object], model: CanonicalModel
) -> tuple[str, ...]:
    """Report keys of this lane that the canonical model cannot answer."""

    return tuple(
        sorted(
            lane_row_keys(spec, document)
            - set(spec.represented_fields)
            - set(lane_placeholder_fields(spec, document))
            - set(lane_restored_fields(spec, document, model))
        )
    )


def stale_represented_fields(
    spec: LaneSpec, document: Mapping[str, object]
) -> tuple[str, ...]:
    """Declared representations that address a key no row carries."""

    return tuple(sorted(set(spec.represented_fields) - lane_row_keys(spec, document)))


# -- comparison -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LaneComparison:
    """The verdict of one lane, and the evidence behind it."""

    lane: str
    verdict: str
    witness: str
    report_count: int | None
    model_count: int | None
    only_in_report: tuple[Assertion, ...] = ()
    only_in_model: tuple[Assertion, ...] = ()
    unrepresented_fields: tuple[str, ...] = ()

    @property
    def migratable(self) -> bool:
        """Can a consumer of this lane read the store instead of the report?"""

        return self.verdict == VERDICT_EQUIVALENT


@dataclass(frozen=True, slots=True)
class EquivalenceReport:
    """Every lane's verdict, plus the one verdict over all of them."""

    lanes: tuple[LaneComparison, ...] = field(default_factory=tuple)

    @property
    def verdict(self) -> str:
        verdicts = {lane.verdict for lane in self.lanes}
        for candidate in (VERDICT_DIVERGENT, VERDICT_UNMEASURED, VERDICT_PARTIAL):
            if candidate in verdicts:
                return candidate
        return VERDICT_EQUIVALENT

    def lane(self, name: str) -> LaneComparison:
        for comparison in self.lanes:
            if comparison.lane == name:
                return comparison
        raise KeyError(name)

    @property
    def migratable_lanes(self) -> tuple[str, ...]:
        return tuple(lane.lane for lane in self.lanes if lane.migratable)


def _sample(assertions: Iterable[Assertion]) -> tuple[Assertion, ...]:
    return tuple(sorted(assertions))[:MAX_DIFF_SAMPLE]


def compare_lane(
    spec: LaneSpec,
    document: Mapping[str, object],
    model: CanonicalModel,
) -> LaneComparison:
    """Compare one lane, refusing to answer at all without a witness."""

    witness = witness_state(document, spec.witness)
    unrepresented = lane_unrepresented_fields(spec, document, model)
    if witness != WITNESS_DECLARED:
        # Witness before count: an undeclared family's payload is a zero
        # nobody measured, and two unmeasured sides are not equivalent.
        return LaneComparison(
            lane=spec.name,
            verdict=VERDICT_UNMEASURED,
            witness=witness,
            report_count=None,
            model_count=None,
            unrepresented_fields=unrepresented,
        )
    reported = spec.report_reader(document)
    modelled = spec.model_reader(model)
    only_report = reported - modelled
    only_model = modelled - reported
    if only_report or only_model:
        verdict = VERDICT_DIVERGENT
    elif unrepresented:
        verdict = VERDICT_PARTIAL
    else:
        verdict = VERDICT_EQUIVALENT
    return LaneComparison(
        lane=spec.name,
        verdict=verdict,
        witness=witness,
        report_count=len(reported),
        model_count=len(modelled),
        only_in_report=_sample(only_report),
        only_in_model=_sample(only_model),
        unrepresented_fields=unrepresented,
    )


def compare_projections(
    document: Mapping[str, object],
    model: CanonicalModel,
    *,
    lanes: Sequence[LaneSpec] = LANES,
) -> EquivalenceReport:
    """Compare every lane of the report document against the stored model."""

    return EquivalenceReport(
        lanes=tuple(compare_lane(spec, document, model) for spec in lanes)
    )


# -- consumer inventory ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConsumerReads:
    """What one consumer module reads out of a report document."""

    module: str
    #: Fully reconstructed key paths, filtered to real document sections.
    paths: tuple[str, ...]
    #: Metric families named by a constant ``family=`` argument. The chain
    #: reconstructor cannot see these: the read is ``families.get(family)``
    #: with ``family`` bound at the call site, so the path it reports stops
    #: at ``metrics.families``.
    family_arguments: tuple[str, ...]


def _family_arguments(tree: ast.AST) -> tuple[str, ...]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "family":
                continue
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names.add(value.value)
    return tuple(sorted(names))


def consumer_reads(
    *, module: str, source: str, sections: frozenset[str]
) -> ConsumerReads:
    """Inventory one consumer, mechanically, from its own source text.

    ``sections`` is the set of top-level keys a real document carries; it is
    measured off the corpus, never listed by hand. The chain reconstructor
    anchors on identifiers named ``document`` / ``payload``, so a local
    mapping with one of those names contributes paths that are not document
    reads at all -- filtering by real sections removes them without asking
    anyone to judge a name.
    """

    paths = {
        path
        for _line, path in report_document_reads(source)
        if path.split(".", 1)[0] in sections
    }
    return ConsumerReads(
        module=module,
        paths=tuple(sorted(paths)),
        family_arguments=_family_arguments(ast.parse(source)),
    )


def document_sections(document: Mapping[str, object]) -> frozenset[str]:
    """The top-level sections a real report document carries."""

    return frozenset(str(key) for key in document)


__all__ = [
    "LANES",
    "MAX_DIFF_SAMPLE",
    "VERDICT_DIVERGENT",
    "VERDICT_EQUIVALENT",
    "VERDICT_PARTIAL",
    "VERDICT_UNMEASURED",
    "WITNESS_DECLARED",
    "WITNESS_METRIC_FAMILY",
    "WITNESS_OBSERVATION_LANE",
    "WITNESS_POPULATION_RECORD",
    "WITNESS_WITHHELD",
    "Assertion",
    "ConsumerReads",
    "EquivalenceReport",
    "LaneComparison",
    "LaneSpec",
    "ProjectionCorpus",
    "WitnessRef",
    "authority_candidate_rows",
    "build_corpus",
    "build_probe_document",
    "compare_lane",
    "compare_projections",
    "consumer_reads",
    "declaration_witness",
    "document_sections",
    "family_items",
    "family_witness",
    "lane_placeholder_fields",
    "lane_restored_fields",
    "lane_row_keys",
    "lane_unrepresented_fields",
    "lane_witness",
    "stale_represented_fields",
    "witness_state",
    "write_probe_tree",
]
