# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.cache._validators as cache_validators
import codeclone.cache._wire_decode as cache_wire_decode
import codeclone.cache._wire_helpers as cache_wire_helpers
import codeclone.cache.entries as cache_entries
import codeclone.core.discovery as core_discovery
from codeclone.cache._validators import (
    _is_class_metrics_dict,
    _is_dead_candidate_dict,
    _is_function_relationship_facts_dict,
    _is_module_api_surface_dict,
    _is_module_dep_dict,
    _is_relationship_record_dict,
    _is_runtime_reachability_fact_dict,
    _is_security_surface_dict,
)
from codeclone.cache._wire_decode import (
    _decode_optional_wire_function_relationship_facts,
    _decode_wire_block,
    _decode_wire_class_metric,
    _decode_wire_dead_candidate,
    _decode_wire_file_entry,
    _decode_wire_module_dep,
    _decode_wire_relationship_record,
    _decode_wire_runtime_reachability,
    _decode_wire_security_surface,
    _decode_wire_segment,
    _decode_wire_unit,
)
from codeclone.cache._wire_encode import _encode_wire_file_entry
from codeclone.cache._wire_helpers import (
    _decode_wire_int_fields,
)
from codeclone.cache.entries import (
    _as_relationship_kind,
    _as_relationship_origin_lane,
    _as_relationship_resolution_status,
    _as_runtime_reachability_confidence,
    _as_runtime_reachability_edge_kind,
    _as_runtime_reachability_framework,
    _as_runtime_reachability_target_kind,
    _as_security_surface_category,
    _as_security_surface_classification_mode,
    _as_security_surface_evidence_kind,
    _as_security_surface_location_scope,
)
from codeclone.cache.integrity import as_str_dict as _as_str_dict
from codeclone.cache.integrity import (
    cache_payload_checksum,
    canonical_json,
)
from codeclone.cache.projection import (
    rehydrate_cache_neutral,
    runtime_filepath_from_wire,
    wire_filepath_from_runtime,
)
from codeclone.cache.reuse import binding_context_digest
from codeclone.cache.store import Cache, file_stat_signature
from codeclone.cache.versioning import CacheStatus, _resolve_root
from codeclone.contracts import CACHE_VERSION
from codeclone.contracts.errors import CacheError
from codeclone.core._types import _unit_to_group_item
from codeclone.core.discovery import _decode_cached_function_relationship_facts
from codeclone.models import (
    ApiParamSpec,
    BlockUnit,
    CacheDependentPayload,
    CacheEntryV3,
    CacheNeutralBlock,
    CacheNeutralPayload,
    CacheNeutralSegment,
    CacheNeutralUnit,
    CacheReuseDecision,
    ClassMetrics,
    ContentIdentityVerdict,
    DigestObject,
    FileMetrics,
    FunctionRelationshipFacts,
    ModuleApiSurface,
    ModuleDep,
    ObservabilityConfig,
    PublicSymbol,
    PythonModuleIdentity,
    RelationshipRecord,
    RuntimeReachabilityFact,
    SecuritySurface,
    SegmentUnit,
    SemanticFileFacts,
    Unit,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observability.query import query_platform_observability
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.utils.repo_paths import PathOutsideRepoError, RepoPathError
from tests._ast_metrics_helpers import (
    build_test_module_registry,
    module_registry_context,
)
from tests._cache_store_fixtures import (
    META_KEY_CHECKSUM,
    META_KEY_FINGERPRINT,
    META_KEY_PYTHON_TAG,
    META_KEY_SCHEMA,
    META_KEY_VERSION,
    TABLE_NEUTRAL,
    envelope_checksum,
)
from tests._cache_store_fixtures import (
    drop_cache_meta as _drop_cache_meta,
)
from tests._cache_store_fixtures import (
    open_store as _open_store,
)
from tests._cache_store_fixtures import (
    overwrite_lane as _overwrite_lane,
)
from tests._cache_store_fixtures import (
    read_cache_meta as _read_cache_meta,
)
from tests._cache_store_fixtures import (
    read_cache_rows as _read_cache_rows,
)
from tests._cache_store_fixtures import (
    sole_cache_row as _sole_cache_row,
)
from tests._cache_store_fixtures import (
    write_cache_meta as _write_cache_meta,
)

_SOURCE_CONTENT_DIGEST = DigestObject(
    domain="codeclone.source-content.v1",
    algorithm="sha256",
    value="0" * 64,
)

_NEUTRAL_PROFILE = DigestObject(
    domain="codeclone.cache.profile.neutral.v1",
    algorithm="sha256",
    value="1" * 64,
)
_DEPENDENT_PROFILE = DigestObject(
    domain="codeclone.cache.profile.dependent.v1",
    algorithm="sha256",
    value="2" * 64,
)


def _empty_v3_entry() -> CacheEntryV3:
    return CacheEntryV3(
        cache_content_binding_version="1",
        binding_context_digest=binding_context_digest(None),
        stat={"mtime_ns": 1, "size": 2},
        source_content_digest=_SOURCE_CONTENT_DIGEST,
        git_blob_id_at_write=None,
        module_neutral_profile=_NEUTRAL_PROFILE,
        module_dependent_profile=_DEPENDENT_PROFILE,
        module_neutral=CacheNeutralPayload(
            source_stats={"lines": 0, "functions": 0, "methods": 0, "classes": 0},
            units=(),
            blocks=(),
            segments=(),
            semantic_facts=SemanticFileFacts(),
        ),
        module_dependent=CacheDependentPayload(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=(),
            referenced_qualnames=(),
            import_names=(),
            class_names=(),
            runtime_reachability=(),
            security_surfaces=(),
            function_relationship_facts=(),
            typing_coverage=None,
            docstring_coverage=None,
            api_surface=None,
            structural_findings=None,
        ),
    )


def _bind_module_paths(cache: Cache, *filepaths: str) -> None:
    assert cache.root is not None
    relative_paths = tuple(
        (
            Path(filepath).resolve().relative_to(cache.root.resolve()).as_posix()
            if Path(filepath).is_absolute()
            else Path(filepath).as_posix()
        )
        for filepath in filepaths
    )
    module_names = tuple(
        ".".join(Path(path).with_suffix("").parts) for path in relative_paths
    )
    cache.bind_module_registry(
        module_registry_context(
            filepath=relative_paths[0],
            module_name=module_names[0],
            inventory_modules=module_names[1:],
        )[1]
    )


def _store_empty_profile_entry(cache: Cache) -> None:
    _bind_module_paths(cache, "x.py")
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    cache.save()


def _content_hit_decision(
    cache: Cache, entry: CacheEntryV3, filepath: str = "x.py"
) -> CacheReuseDecision:
    # The store keys the per-entry binding context by the same absolute runtime
    # path it normalizes writes to, so the read side has to ask with that path.
    assert cache.root is not None
    return cache.reuse_decision(
        runtime_path=str((cache.root / filepath).resolve()),
        content=ContentIdentityVerdict(
            hit=True,
            reason="digest_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        ),
        entry=entry,
    )


def _wire_entry(**fields: object) -> dict[str, object]:
    return {
        "cb": "1",
        "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
        "gb": None,
        **fields,
    }


def _make_unit(filepath: str, *, module_name: str = "x") -> Unit:
    return Unit(
        qualname=f"{module_name}:func",
        filepath=filepath,
        start_line=1,
        end_line=2,
        loc=2,
        stmt_count=1,
        fingerprint="abc",
        loc_bucket="0-19",
    )


def _make_block(filepath: str, *, module_name: str = "x") -> BlockUnit:
    return BlockUnit(
        block_hash="h1",
        filepath=filepath,
        qualname=f"{module_name}:func",
        start_line=1,
        end_line=2,
        size=4,
    )


def _make_segment(filepath: str, *, module_name: str = "x") -> SegmentUnit:
    return SegmentUnit(
        segment_hash="s1",
        segment_sig="sig1",
        filepath=filepath,
        qualname=f"{module_name}:func",
        start_line=1,
        end_line=6,
        size=6,
    )


def _analysis_payload(cache: Cache, *, files: object) -> dict[str, object]:
    return {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": files,
    }


def _assert_loads_cleanly(cache_path: Path, filepath: str) -> Cache:
    """Load the store and assert it warmed without complaint."""

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is None
    assert loaded.get_file_entry(filepath) is not None
    return loaded


def _remint_envelope(cache_path: Path, **overrides: str) -> None:
    """Apply meta overrides and re-mint the envelope digest over the result.

    Tests that target a gate *behind* the integrity gate have to arrive there
    with a digest that still verifies, or they prove only that the integrity
    gate works -- which a different test already proves.
    """

    meta = dict(_read_cache_meta(cache_path))
    meta.update(overrides)
    _write_cache_meta(
        cache_path,
        **overrides,
        **{
            META_KEY_CHECKSUM: envelope_checksum(
                version=meta[META_KEY_VERSION],
                python_tag=meta[META_KEY_PYTHON_TAG],
                fingerprint_version=meta[META_KEY_FINGERPRINT],
            )
        },
    )


def _save_single_cache_entry(cache_path: Path, *, filepath: str = "x.py") -> None:
    cache = Cache(cache_path, root=cache_path.parent)
    _bind_module_paths(cache, filepath)
    cache.put_file_entry(
        filepath,
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    cache.save()


def _load_cache_entry(cache_path: Path, filepath: str) -> tuple[Cache, CacheEntryV3]:
    loaded = Cache(cache_path, root=cache_path.parent)
    loaded.load()
    entry = loaded.get_file_entry(filepath)
    assert entry is not None
    return loaded, entry


def _roundtrip_cache_entry_with_metrics(
    tmp_path: Path,
    *,
    file_metrics: FileMetrics,
) -> CacheEntryV3:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path)
    _bind_module_paths(cache, "x.py")
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
        file_metrics=file_metrics,
    )
    cache.save()

    _, entry = _load_cache_entry(cache_path, "x.py")
    return entry


def test_cached_references_use_module_identity_for_test_named_package_trees() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "source_kind"
    dependent = replace(
        _empty_v3_entry().module_dependent,
        referenced_names=("helper",),
        referenced_qualnames=("example.testing.helpers:helper",),
    )
    entry = replace(_empty_v3_entry(), module_dependent=dependent)

    package_path = "src/example/testing/helpers.py"
    package_registry = build_test_module_registry(
        root=fixture_root / "in_package",
        source_roots=("src",),
    )
    package_metrics = core_discovery.load_cached_metrics_extended(
        entry,
        filepath=package_path,
        module_registry=package_registry,
    )
    assert package_metrics[3] == frozenset({"helper"})
    assert package_metrics[4] == frozenset({"example.testing.helpers:helper"})

    test_path = "testing/case.py"
    test_registry = build_test_module_registry(root=fixture_root / "repo_root")
    test_metrics = core_discovery.load_cached_metrics_extended(
        entry,
        filepath=test_path,
        module_registry=test_registry,
    )
    assert test_metrics[3] == frozenset()
    assert test_metrics[4] == frozenset()


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path)
    _bind_module_paths(cache, "x.py")
    unit = _make_unit("x.py")
    block = _make_block("x.py")
    segment = _make_segment("x.py")
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [unit],
        [block],
        [segment],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    cache.save()

    loaded, entry = _load_cache_entry(cache_path, "x.py")
    assert entry.stat["size"] == 10
    assert entry.module_neutral.units[0].local_name == "func"
    assert loaded.load_status == CacheStatus.OK
    assert loaded.cache_schema_version == Cache._CACHE_VERSION


def test_cache_sqlite_work_reaches_the_observers_db_cost_section(
    tmp_path: Path,
) -> None:
    """The cache's own database work is visible where database work is read.

    A span joins ``db_cost`` by carrying ``db_queries``; the other two counters
    give the section its N+1 shape. Before this the cache was the one store in
    the process whose work could not be looked at -- and the store that
    accelerates every run is the last place that should be a black box.

    Asserted through the observer's own query, not by reading the span table,
    so a counter that never reached the section would fail here.
    """

    cache_path = tmp_path / "cache.sqlite3"
    cache = Cache(cache_path, root=tmp_path)
    _bind_module_paths(cache, "x.py")

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="test.cache_db_cost", surface="test"):
            cache.put_file_entry(
                "x.py",
                {"mtime_ns": 1, "size": 10},
                [],
                [],
                [],
                source_content_digest=_SOURCE_CONTENT_DIGEST,
            )
            cache.save()
            reloaded = Cache(cache_path, root=tmp_path)
            reloaded.load()
            assert reloaded.get_file_entry("x.py") is not None
    finally:
        shutdown()

    section = query_platform_observability(root=tmp_path, section="db_cost")
    rows = cast("list[dict[str, object]]", section["rows"])
    cache_rows = {
        str(row["span"]): row for row in rows if str(row["span"]).startswith("cache.")
    }
    assert cache_rows, section
    for row in cache_rows.values():
        assert cast(int, row["queries"]) > 0
    assert "cache.backend.write_generation" in cache_rows
    assert "cache.backend.load_generation" in cache_rows


def test_cache_load_emits_observability_subspans(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path)
    _bind_module_paths(cache, "x.py")
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    cache.save()

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="test.cache_load", surface="test"):
            loaded = Cache(cache_path, root=tmp_path)
            loaded.load()
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT name, counters_json FROM platform_spans ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()

    counters_by_name = {name: json.loads(counters or "{}") for name, counters in rows}
    # cache.read_json is gone with the document it read; the backend load span
    # that replaced it was already declared in the vocabulary and parked as
    # "no backend exists to instrument". It exists now, so it is wired.
    assert "cache.read_json" not in counters_by_name
    assert set(counters_by_name) >= {
        "cache.backend.load_generation",
        "cache.decode_entries",
        "cache.segment_projection",
        "cache.stat",
        "cache.validate_envelope",
    }
    assert counters_by_name["cache.stat"]["cache_file_bytes"] > 0
    load_counters = counters_by_name["cache.backend.load_generation"]
    assert load_counters["cache_file_bytes"] > 0
    assert load_counters["cache_backend_entries"] == 1
    assert load_counters["cache_backend_read_bytes"] > 0
    # A load reads identity and decodes nothing: the lanes stay on disk until
    # somebody asks. A non-zero decoded_entries here would mean the schema had
    # quietly gone back to reading everything.
    assert counters_by_name["cache.decode_entries"] == {
        "cache_entries": 1,
        "decoded_entries": 0,
    }


def test_cache_release_loaded_entries_clears_clean_loaded_entries(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    loaded = Cache(cache_path, root=tmp_path)
    loaded.load()
    assert loaded.get_file_entry("x.py") is not None
    assert len(loaded.data["files"]) == 1

    # Release frees the materialised lanes -- which is where the memory is --
    # and leaves the row in the store. Under the old shape a release also lost
    # the entry, because the only copy was the one in memory; now asking again
    # simply fetches it back.
    assert loaded.release_loaded_entries() == 1
    assert loaded.data["files"] == {}
    assert loaded.get_file_entry("x.py") is not None
    assert loaded.load_status == CacheStatus.OK
    assert loaded.cache_schema_version == Cache._CACHE_VERSION


def test_cache_release_loaded_entries_refuses_dirty_cache_by_default(
    tmp_path: Path,
) -> None:
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    _bind_module_paths(cache, "x.py")
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )

    assert cache.release_loaded_entries() == 0
    assert cache.get_file_entry("x.py") is not None


def test_cache_read_only_mode_suppresses_entry_writes(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    loaded = Cache(cache_path, root=tmp_path, write_enabled=False)
    loaded.load()

    loaded.put_file_entry(
        "y.py",
        {"mtime_ns": 2, "size": 20},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    assert loaded.prune_file_entries([]) == 0
    loaded.save()

    assert loaded.get_file_entry("x.py") is not None
    assert loaded.get_file_entry("y.py") is None
    reloaded = Cache(cache_path, root=tmp_path)
    reloaded.load()
    assert reloaded.get_file_entry("x.py") is not None
    assert reloaded.get_file_entry("y.py") is None


def test_cache_roundtrip_preserves_function_relationship_facts(
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    filepath = str((root / "pkg" / "module.py").resolve())
    cache_path = root / "cache.json"
    cache = Cache(cache_path, root=root)
    _bind_module_paths(cache, filepath)
    facts = FunctionRelationshipFacts(
        source_qualname="pkg.module:source",
        relationships=(
            RelationshipRecord(
                relation_kind="reference",
                resolution_status="resolved",
                origin_lane="production",
                source_qualname="pkg.module:source",
                target_qualname="pkg.target:handler",
                path=filepath,
                line=7,
                expression="handler",
                resolution_rule="cross_module_import",
            ),
            RelationshipRecord(
                relation_kind="call",
                resolution_status="unresolved",
                origin_lane="test",
                source_qualname="pkg.module:source",
                target_qualname=None,
                path=filepath,
                line=11,
                expression="factory()",
                resolution_rule="dynamic_call",
            ),
        ),
    )
    cache.put_file_entry(
        filepath,
        {"mtime_ns": 1, "size": 10},
        [_make_unit(filepath, module_name="pkg.module")],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
        function_relationship_facts=(facts,),
    )
    cache.save()

    loaded = Cache(cache_path, root=root)
    loaded.load()
    entry = loaded.get_file_entry(filepath)

    assert entry is not None
    stored_facts = entry.module_dependent.function_relationship_facts
    assert len(stored_facts) == 1
    assert stored_facts[0]["source_qualname"] == "pkg.module:source"
    assert tuple(
        (
            record["relation_kind"],
            record["target_qualname"],
            record["resolution_rule"],
        )
        for record in stored_facts[0]["relationships"]
    ) == (
        ("reference", "pkg.target:handler", "cross_module_import"),
        ("call", None, "dynamic_call"),
    )

    # Step 7a: discovery rehydrates the stored dicts back into typed models for
    # cross-file aggregation. Round-trip must be faithful (storage sort order).
    decoded = _decode_cached_function_relationship_facts(
        entry.module_dependent.function_relationship_facts
    )
    assert len(decoded) == 1
    assert decoded[0].source_qualname == "pkg.module:source"
    assert tuple(
        (record.relation_kind, record.target_qualname, record.resolution_rule)
        for record in decoded[0].relationships
    ) == (
        ("reference", "pkg.target:handler", "cross_module_import"),
        ("call", None, "dynamic_call"),
    )
    assert decoded[0].relationships[1].origin_lane == "test"


def test_cache_derives_function_relationship_facts_from_file_metrics(
    tmp_path: Path,
) -> None:
    filepath = str((tmp_path / "pkg" / "module.py").resolve())
    facts = FunctionRelationshipFacts(
        source_qualname="pkg.module:source",
        relationships=(
            RelationshipRecord(
                relation_kind="call",
                resolution_status="resolved",
                origin_lane="production",
                source_qualname="pkg.module:source",
                target_qualname="pkg.target:handler",
                path=filepath,
                line=7,
            ),
        ),
    )
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    _bind_module_paths(cache, filepath)
    cache.put_file_entry(
        filepath,
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
        file_metrics=FileMetrics(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset(),
            function_relationship_facts=(facts,),
        ),
    )

    entry = cache.get_file_entry(filepath)

    assert entry is not None
    assert (
        entry.module_dependent.function_relationship_facts[0]["relationships"][0][
            "target_qualname"
        ]
        == "pkg.target:handler"
    )


def test_cache_rejects_malformed_function_relationship_wire() -> None:
    entry = _decode_wire_file_entry(
        {
            "st": [1, 10],
            "fr": [
                [
                    "pkg.module:source",
                    [["call", "unresolved", "production", "not-null", 7, "f()", None]],
                ]
            ],
        },
        "pkg/module.py",
    )

    assert entry is None


def test_relationship_cache_helpers_enforce_two_axis_contract() -> None:
    resolved = {
        "relation_kind": "call",
        "resolution_status": "resolved",
        "origin_lane": "production",
        "source_qualname": "pkg.module:source",
        "target_qualname": "pkg.target:handler",
        "path": "pkg/module.py",
        "line": 7,
        "expression": "handler()",
        "resolution_rule": "cross_module_import",
    }
    unresolved = {
        **resolved,
        "resolution_status": "unresolved",
        "target_qualname": None,
    }

    assert _as_relationship_kind("call") == "call"
    assert _as_relationship_kind("reference") == "reference"
    assert _as_relationship_kind("other") is None
    assert _as_relationship_resolution_status("resolved") == "resolved"
    assert _as_relationship_resolution_status("unresolved") == "unresolved"
    assert _as_relationship_resolution_status("other") is None
    assert _as_relationship_origin_lane("production") == "production"
    assert _as_relationship_origin_lane("test") == "test"
    assert _as_relationship_origin_lane("other") is None
    assert _is_relationship_record_dict(resolved)
    assert _is_relationship_record_dict(unresolved)
    assert not _is_relationship_record_dict(object())
    assert not _is_relationship_record_dict({**resolved, "line": 0})
    assert not _is_relationship_record_dict({**resolved, "target_qualname": None})
    assert not _is_relationship_record_dict(
        {**unresolved, "target_qualname": "pkg.target:handler"}
    )
    assert not _is_relationship_record_dict({**resolved, "expression": 1})
    assert not _is_relationship_record_dict({**resolved, "resolution_rule": 1})
    assert _is_function_relationship_facts_dict(
        {
            "source_qualname": "pkg.module:source",
            "relationships": [resolved, unresolved],
        }
    )
    assert not _is_function_relationship_facts_dict(object())
    assert not _is_function_relationship_facts_dict(
        {
            "source_qualname": "pkg.module:other",
            "relationships": [resolved],
        }
    )


@pytest.mark.parametrize(
    "row",
    [
        object(),
        ["call", "resolved", "production", None, 7, None, None],
        ["call", "unresolved", "production", "pkg.target:f", 7, None, None],
        ["other", "resolved", "production", "pkg.target:f", 7, None, None],
        ["call", "resolved", "other", "pkg.target:f", 7, None, None],
        ["call", "resolved", "production", "pkg.target:f", 0, None, None],
        ["call", "resolved", "production", "pkg.target:f", 7, 1, None],
        ["call", "resolved", "production", "pkg.target:f", 7, None, 1],
    ],
)
def test_decode_wire_relationship_record_rejects_invalid_rows(row: object) -> None:
    assert (
        _decode_wire_relationship_record(
            row,
            source_qualname="pkg.module:source",
            filepath="pkg/module.py",
        )
        is None
    )


def test_decode_optional_wire_relationship_facts_rejects_invalid_container() -> None:
    assert (
        _decode_optional_wire_function_relationship_facts(
            obj={"fr": "invalid"},
            filepath="pkg/module.py",
        )
        is None
    )
    assert (
        _decode_optional_wire_function_relationship_facts(
            obj={"fr": [["pkg.module:source", "invalid"]]},
            filepath="pkg/module.py",
        )
        is None
    )


def test_cache_rejects_relationship_source_mismatch(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    _bind_module_paths(cache, "pkg/module.py")
    facts = FunctionRelationshipFacts(
        source_qualname="pkg.module:source",
        relationships=(
            RelationshipRecord(
                relation_kind="call",
                resolution_status="resolved",
                origin_lane="production",
                source_qualname="pkg.module:other",
                target_qualname="pkg.target:handler",
                path="pkg/module.py",
                line=7,
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="source_qualname must match its facts container",
    ):
        cache.put_file_entry(
            "pkg/module.py",
            {"mtime_ns": 1, "size": 10},
            [],
            [],
            [],
            source_content_digest=_SOURCE_CONTENT_DIGEST,
            function_relationship_facts=(facts,),
        )


def test_unit_group_projection_is_unchanged_by_relationship_model() -> None:
    unit = _make_unit("pkg/module.py", module_name="mod")

    assert _unit_to_group_item(unit) == {
        "qualname": "mod:func",
        "filepath": "pkg/module.py",
        "start_line": 1,
        "end_line": 2,
        "loc": 2,
        "stmt_count": 1,
        "fingerprint": "abc",
        "loc_bucket": "0-19",
        "cyclomatic_complexity": 1,
        "cfg_cyclomatic_complexity": 1,
        "nesting_depth": 0,
        "risk": "low",
        "raw_hash": "",
        "entry_guard_count": 0,
        "entry_guard_terminal_profile": "none",
        "entry_guard_has_side_effect_before": False,
        "terminal_kind": "fallthrough",
        "try_finally_profile": "none",
        "side_effect_order_profile": "none",
        # 39Y Y8: the near-miss tier reads its statement sequence off the unit
        # fact. Empty for this unit because the tier is a clone lane and never
        # pays for units the clone floors reject.
        "statement_sequence": (),
        # Wave C: the renamed-structure tier reads its digest off the unit
        # fact, on the same clone-lane population rule.
        "renamed_fingerprint": "",
        # The CxB composition: the near-miss renamed token domain reads its
        # canonical sequence off the unit fact, same population rule again.
        "renamed_statement_sequence": (),
        # 39Y Y9: reachability, unlike the sequence above, is computed for every
        # unit regardless of the clone floors. Empty here because this unit has
        # no unreachable statement, not because it was skipped.
        "unreachable_statements": (),
    }


def test_cache_prune_file_entries_removes_stale_paths(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    cache_path = root / "cache.json"
    live = root / "live.py"
    stale = root / "stale.py"
    live.write_text("def live():\n    return 1\n", "utf-8")

    cache = Cache(cache_path, root=root)
    _bind_module_paths(cache, str(live), str(stale))
    cache.put_file_entry(
        str(live),
        file_stat_signature(str(live)),
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    cache.put_file_entry(
        str(stale),
        {"mtime_ns": 1, "size": 1},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    cache.save()

    loaded = Cache(cache_path, root=root)
    loaded.load()

    removed = loaded.prune_file_entries((str(live),))

    assert removed == 1
    # A load leaves the lanes on disk, so the in-memory map is not the register
    # of what exists; the lookup is.
    assert loaded.get_file_entry(str(live)) is not None
    assert loaded.get_file_entry(str(stale)) is None

    loaded.save()

    reloaded = Cache(cache_path, root=root)
    reloaded.load()
    assert reloaded.get_file_entry(str(live)) is not None
    assert reloaded.get_file_entry(str(stale)) is None


def test_cache_roundtrip_preserves_empty_structural_findings(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path)
    _bind_module_paths(cache, "x.py")
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
        structural_findings=[],
    )
    cache.save()

    _, entry = _load_cache_entry(cache_path, "x.py")
    assert entry.module_dependent.structural_findings == ()


def test_cache_roundtrip_preserves_api_surface_parameter_order(
    tmp_path: Path,
) -> None:
    entry = _roundtrip_cache_entry_with_metrics(
        tmp_path,
        file_metrics=FileMetrics(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset(),
            api_surface=ModuleApiSurface(
                module="pkg.mod",
                filepath="x.py",
                all_declared=("run",),
                symbols=(
                    PublicSymbol(
                        qualname="pkg.mod:run",
                        kind="function",
                        start_line=1,
                        end_line=2,
                        params=(
                            ApiParamSpec(
                                name="beta",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                            ApiParamSpec(
                                name="alpha",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    assert entry.module_dependent.api_surface is not None
    params = entry.module_dependent.api_surface["symbols"][0]["params"]
    assert [param["name"] for param in params] == ["beta", "alpha"]


def test_cache_roundtrip_preserves_security_surfaces(tmp_path: Path) -> None:
    entry = _roundtrip_cache_entry_with_metrics(
        tmp_path,
        file_metrics=FileMetrics(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset(),
            security_surfaces=(
                SecuritySurface(
                    category="process_boundary",
                    capability="subprocess_run",
                    module="pkg.runner",
                    filepath="x.py",
                    qualname="pkg.runner:run_command",
                    start_line=10,
                    end_line=10,
                    location_scope="callable",
                    classification_mode="exact_call",
                    evidence_kind="call",
                    evidence_symbol="subprocess.run",
                ),
            ),
        ),
    )
    assert entry.module_dependent.security_surfaces == (
        {
            "category": "process_boundary",
            "capability": "subprocess_run",
            "module": "pkg.runner",
            "filepath": str((tmp_path / "x.py").resolve()),
            "qualname": "pkg.runner:run_command",
            "start_line": 10,
            "end_line": 10,
            "location_scope": "callable",
            "classification_mode": "exact_call",
            "evidence_kind": "call",
            "evidence_symbol": "subprocess.run",
        },
    )


def test_cache_wire_preserves_rule_three_fact_families(tmp_path: Path) -> None:
    """39J guard, cache half: the 3.2 wire must not drop the gating input.

    The tri-state decision table turns on "this class carries an unresolved
    external base" - a fact only visible while parsing. If the wire lost it, a
    cache-hit file would silently fall back to binary liveness and the verdict
    would depend on cache state rather than on code. The behavioural half of
    this guard (equal facts produce equal statuses, and the bypass stays
    narrow) lives in tests/test_metrics_modules.py, which owns the metrics
    ring; together the two halves compose to cold == warm.
    """
    cold_class_metrics = (
        ClassMetrics(
            qualname="x:Adapter",
            filepath="x.py",
            start_line=1,
            end_line=4,
            cbo=1,
            lcom4=1,
            method_count=1,
            instance_var_count=0,
            risk_coupling="low",
            risk_cohesion="low",
            base_names=("Base",),
            has_unresolved_external_base=True,
            decorator_evidenced_methods=("x:Adapter.handle",),
            self_dispatched_methods=("x:Adapter.helper",),
        ),
        ClassMetrics(
            qualname="x:LocalOnly",
            filepath="x.py",
            start_line=7,
            end_line=9,
            cbo=0,
            lcom4=1,
            method_count=1,
            instance_var_count=0,
            risk_coupling="low",
            risk_cohesion="low",
            base_names=("object",),
            has_unresolved_external_base=False,
        ),
    )
    entry = _roundtrip_cache_entry_with_metrics(
        tmp_path,
        file_metrics=FileMetrics(
            class_metrics=cold_class_metrics,
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset({"Adapter", "LocalOnly"}),
        ),
    )

    resolved_path = str((tmp_path / "x.py").resolve())
    rows_by_qualname = {
        row["qualname"]: row for row in entry.module_dependent.class_metrics
    }
    assert rows_by_qualname["x:Adapter"]["base_names"] == ["Base"]
    assert rows_by_qualname["x:Adapter"]["has_unresolved_external_base"] is True
    assert rows_by_qualname["x:Adapter"]["decorator_evidenced_methods"] == [
        "x:Adapter.handle"
    ]
    assert rows_by_qualname["x:Adapter"]["self_dispatched_methods"] == [
        "x:Adapter.helper"
    ]
    assert rows_by_qualname["x:LocalOnly"]["base_names"] == ["object"]
    assert rows_by_qualname["x:LocalOnly"]["has_unresolved_external_base"] is False
    # A class with nothing to declare emits no sidecar row at all, so a
    # 3.1-shaped tree keeps encoding byte-identically.
    assert "decorator_evidenced_methods" not in rows_by_qualname["x:LocalOnly"]
    assert "self_dispatched_methods" not in rows_by_qualname["x:LocalOnly"]

    # Rehydrating through the production read-site returns the cold models
    # unchanged apart from the resolved filepath, so a warm run sees exactly
    # the facts a cold run computed.
    cached_class_metrics = core_discovery.load_cached_metrics_extended(
        entry,
        filepath=resolved_path,
    )[0]
    assert cached_class_metrics == tuple(
        replace(metric, filepath=resolved_path) for metric in cold_class_metrics
    )


def test_cache_wire_preserves_instantiation_candidates(tmp_path: Path) -> None:
    """The resolved-instantiation CBO lane must survive a cache hit.

    Candidates are produced while parsing, and the parse does not run for a
    cached file. If the wire dropped them the project fold would see fewer
    candidates on a warm run, and CBO would depend on cache state rather than
    on code.

    This is the cache half of the guard: the facts survive the round trip
    unchanged. The behavioural half — those facts decide the edges, and
    losing them changes the answer — lives in tests/test_metrics_modules.py,
    which owns the metrics ring. Together the two halves compose to
    cold == warm.
    """
    cold_class_metrics = (
        ClassMetrics(
            qualname="x:Caller",
            filepath="x.py",
            start_line=1,
            end_line=4,
            cbo=0,
            lcom4=1,
            method_count=1,
            instance_var_count=0,
            risk_coupling="low",
            risk_cohesion="low",
            # The already-resolved edge travels beside the unresolved
            # candidates: both sidecars must survive the same round trip.
            coupled_classes=("Peer",),
            instantiation_candidates=(
                "Widget|vendor.widgets:Widget",
                "render|vendor.widgets:render",
            ),
        ),
        ClassMetrics(
            qualname="vendor.widgets:Widget",
            filepath="x.py",
            start_line=7,
            end_line=9,
            cbo=0,
            lcom4=1,
            method_count=1,
            instance_var_count=0,
            risk_coupling="low",
            risk_cohesion="low",
        ),
    )
    entry = _roundtrip_cache_entry_with_metrics(
        tmp_path,
        file_metrics=FileMetrics(
            class_metrics=cold_class_metrics,
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset({"Caller", "Widget"}),
        ),
    )

    resolved_path = str((tmp_path / "x.py").resolve())
    rows_by_qualname = {
        row["qualname"]: row for row in entry.module_dependent.class_metrics
    }
    assert rows_by_qualname["x:Caller"]["instantiation_candidates"] == [
        "Widget|vendor.widgets:Widget",
        "render|vendor.widgets:render",
    ]
    assert rows_by_qualname["x:Caller"]["coupled_classes"] == ["Peer"]
    # A class with neither an edge nor a candidate emits no sidecar row at all.
    assert "instantiation_candidates" not in rows_by_qualname["vendor.widgets:Widget"]
    assert "coupled_classes" not in rows_by_qualname["vendor.widgets:Widget"]

    warm_class_metrics = core_discovery.load_cached_metrics_extended(
        entry,
        filepath=resolved_path,
    )[0]
    assert warm_class_metrics == tuple(
        replace(metric, filepath=resolved_path) for metric in cold_class_metrics
    )
    assert warm_class_metrics[0].instantiation_candidates == (
        "Widget|vendor.widgets:Widget",
        "render|vendor.widgets:render",
    )


def test_cache_roundtrip_preserves_runtime_reachability(tmp_path: Path) -> None:
    entry = _roundtrip_cache_entry_with_metrics(
        tmp_path,
        file_metrics=FileMetrics(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset(),
            runtime_reachability=(
                RuntimeReachabilityFact(
                    target_qualname="pkg.api:list_items",
                    filepath="x.py",
                    start_line=12,
                    end_line=14,
                    target_kind="function",
                    framework="fastapi",
                    edge_kind="registers_handler",
                    confidence="medium",
                    evidence="route decorator",
                    evidence_symbol="router.get",
                    source_qualname="pkg.api:router",
                ),
            ),
        ),
    )
    assert entry.module_dependent.runtime_reachability == (
        {
            "target_qualname": "pkg.api:list_items",
            "filepath": str((tmp_path / "x.py").resolve()),
            "start_line": 12,
            "end_line": 14,
            "target_kind": "function",
            "framework": "fastapi",
            "edge_kind": "registers_handler",
            "confidence": "medium",
            "evidence": "route decorator",
            "evidence_symbol": "router.get",
            "source_qualname": "pkg.api:router",
        },
    )


def test_security_surface_cache_helpers_reject_invalid_values() -> None:
    assert _as_security_surface_category("process_boundary") == "process_boundary"
    assert _as_security_surface_category("broken") is None
    assert _as_security_surface_location_scope("callable") == "callable"
    assert _as_security_surface_location_scope("broken") is None
    assert _as_security_surface_classification_mode("exact_call") == "exact_call"
    assert _as_security_surface_classification_mode("broken") is None
    assert _as_security_surface_evidence_kind("call") == "call"
    assert _as_security_surface_evidence_kind("broken") is None
    assert (
        _is_module_api_surface_dict(
            {
                "module": "pkg.mod",
                "filepath": "pkg/mod.py",
                "all_declared": ["run"],
                "symbols": "bad",
            }
        )
        is False
    )
    assert _is_security_surface_dict(object()) is False
    assert _is_security_surface_dict(
        {
            "category": "process_boundary",
            "capability": "subprocess_run",
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "qualname": "pkg.mod:run",
            "start_line": 1,
            "end_line": 1,
            "location_scope": "callable",
            "classification_mode": "exact_call",
            "evidence_kind": "call",
            "evidence_symbol": "subprocess.run",
        }
    )
    assert _is_runtime_reachability_fact_dict(
        {
            "target_qualname": "pkg.mod:fn",
            "filepath": "pkg/mod.py",
            "start_line": 1,
            "end_line": 2,
            "target_kind": "function",
            "framework": "fastapi",
            "edge_kind": "registers_handler",
            "confidence": "high",
            "evidence": "route",
            "evidence_symbol": "get",
            "source_qualname": "pkg.mod:router",
        }
    )


def test_runtime_reachability_cache_helpers_reject_invalid_values() -> None:
    assert _as_runtime_reachability_framework("aiogram") == "aiogram"
    assert _as_runtime_reachability_framework("aiohttp") == "aiohttp"
    assert _as_runtime_reachability_framework("fastapi") == "fastapi"
    assert _as_runtime_reachability_framework("flask") == "flask"
    assert _as_runtime_reachability_framework("sqlalchemy") == "sqlalchemy"
    assert _as_runtime_reachability_framework("broken") is None
    assert _as_runtime_reachability_edge_kind("registers_handler") == (
        "registers_handler"
    )
    assert _as_runtime_reachability_edge_kind("runtime_hook") == "runtime_hook"
    assert _as_runtime_reachability_edge_kind("broken") is None
    assert _as_runtime_reachability_confidence("medium") == "medium"
    assert _as_runtime_reachability_confidence("broken") is None
    assert _as_runtime_reachability_target_kind("function") == "function"
    assert _as_runtime_reachability_target_kind("broken") is None
    assert _is_runtime_reachability_fact_dict(object()) is False


def test_decode_wire_runtime_reachability_covers_valid_and_invalid_rows() -> None:
    assert _decode_wire_runtime_reachability(object(), "pkg/mod.py") is None
    assert (
        _decode_wire_runtime_reachability(
            [
                "pkg.mod:run",
                10,
                12,
                "function",
                "broken",
                "registers_handler",
                "medium",
                "route decorator",
                "router.get",
                "pkg.mod:router",
            ],
            "pkg/mod.py",
        )
        is None
    )
    decoded = _decode_wire_runtime_reachability(
        [
            "pkg.mod:run",
            10,
            12,
            "function",
            "fastapi",
            "registers_handler",
            "medium",
            "route decorator",
            "router.get",
            "pkg.mod:router",
        ],
        "pkg/mod.py",
    )
    assert decoded == {
        "target_qualname": "pkg.mod:run",
        "filepath": "pkg/mod.py",
        "start_line": 10,
        "end_line": 12,
        "target_kind": "function",
        "framework": "fastapi",
        "edge_kind": "registers_handler",
        "confidence": "medium",
        "evidence": "route decorator",
        "evidence_symbol": "router.get",
        "source_qualname": "pkg.mod:router",
    }


def test_decode_wire_security_surface_covers_valid_and_invalid_rows() -> None:
    assert _decode_wire_security_surface(object(), "pkg/mod.py") is None
    assert (
        _decode_wire_security_surface(
            [
                "broken",
                "subprocess_run",
                "pkg.mod",
                "pkg.mod:run",
                10,
                12,
                "callable",
                "exact_call",
                "call",
                "subprocess.run",
            ],
            "pkg/mod.py",
        )
        is None
    )
    assert (
        _decode_wire_security_surface(
            [
                "process_boundary",
                "subprocess_run",
                "pkg.mod",
                "pkg.mod:run",
                "10",
                12,
                "callable",
                "exact_call",
                "call",
                "subprocess.run",
            ],
            "pkg/mod.py",
        )
        is None
    )
    assert (
        _decode_wire_security_surface(
            [
                "process_boundary",
                "subprocess_run",
                "pkg.mod",
                "pkg.mod:run",
                10,
                12,
                "broken",
                "exact_call",
                "call",
                "subprocess.run",
            ],
            "pkg/mod.py",
        )
        is None
    )
    decoded = _decode_wire_security_surface(
        [
            "process_boundary",
            "subprocess_run",
            "pkg.mod",
            "pkg.mod:run",
            10,
            12,
            "callable",
            "exact_call",
            "call",
            "subprocess.run",
        ],
        "pkg/mod.py",
    )
    assert decoded == {
        "category": "process_boundary",
        "capability": "subprocess_run",
        "module": "pkg.mod",
        "filepath": "pkg/mod.py",
        "qualname": "pkg.mod:run",
        "start_line": 10,
        "end_line": 12,
        "location_scope": "callable",
        "classification_mode": "exact_call",
        "evidence_kind": "call",
        "evidence_symbol": "subprocess.run",
    }


def test_get_file_entry_uses_wire_key_fallback(tmp_path: Path) -> None:
    root = tmp_path / "project"
    file_path = root / "pkg" / "module.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    cache = Cache(tmp_path / "cache.json", root=root)
    runtime_key = str(file_path.resolve())
    cache.data["files"][runtime_key] = cast(
        Any,
        {
            "cache_content_binding_version": "1",
            "source_content_digest": _SOURCE_CONTENT_DIGEST,
            "git_blob_id_at_write": None,
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": [],
        },
    )
    non_canonical = str(root / "pkg" / ".." / "pkg" / "module.py")
    assert cache.get_file_entry(non_canonical) is not None


def test_get_file_entry_keeps_loaded_cache_clean_on_canonical_hit(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded._dirty is False
    assert loaded.get_file_entry("x.py") is not None
    assert loaded._dirty is False


def test_store_canonical_file_entry_marks_dirty_only_when_entry_changes(
    tmp_path: Path,
) -> None:
    cache = Cache(tmp_path / "cache.json")
    canonical_entry = _empty_v3_entry()
    cache.data["files"]["x.py"] = canonical_entry
    cache._canonical_runtime_paths.add("x.py")
    cache._dirty = False

    cache._store_canonical_file_entry(
        runtime_path="x.py",
        canonical_entry=canonical_entry,
    )
    assert cache._dirty is False

    cache._canonical_runtime_paths.clear()
    cache._store_canonical_file_entry(
        runtime_path="x.py",
        canonical_entry=canonical_entry,
    )
    assert cache._dirty is True


def test_get_file_entry_missing_after_fallback_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cache = Cache(tmp_path / "cache.json", root=root)
    assert cache.get_file_entry(str(root / "pkg" / "missing.py")) is None


def test_cache_v13_uses_relpaths_when_root_set(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    target = project_root / "pkg" / "module.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def f():\n    return 1\n", "utf-8")

    cache_path = project_root / ".codeclone" / "cache.json"
    cache = Cache(cache_path, root=project_root)
    _bind_module_paths(cache, str(target))
    cache.put_file_entry(
        str(target),
        {"mtime_ns": 1, "size": 10},
        [_make_unit(str(target), module_name="pkg.module")],
        [_make_block(str(target), module_name="pkg.module")],
        [_make_segment(str(target), module_name="pkg.module")],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    cache.save()

    files = _read_cache_rows(cache_path)
    assert "pkg/module.py" in files
    assert str(target) not in files


def test_cache_row_checksum_covers_content_not_stored_bytes(tmp_path: Path) -> None:
    """Integrity is a claim about the entry, not about how it was serialised.

    The JSON store proved this against document whitespace; a row store proves
    the same property against key order and spacing inside the row payload. A
    checksum that bound the literal bytes would make every re-encoding a false
    integrity failure, which is how a disposable cache turns into a permanent
    cold path.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)

    wire_path, entry = _sole_cache_row(cache_path)
    assert isinstance(entry, dict)
    neutral = entry["n"]
    assert isinstance(neutral, dict)
    # Rewrite the lane with reversed key order and indentation. The identity
    # checksum is untouched and still holds, because it covers the identity;
    # the lane is decoded, not compared byte for byte.
    reordered = dict(reversed(list(neutral.items())))
    reordered.pop("mt", None)
    _overwrite_lane(
        cache_path,
        wire_path,
        TABLE_NEUTRAL,
        json.dumps(reordered, indent=2).encode("utf-8"),
    )

    _assert_loads_cleanly(cache_path, "x.py")


def test_cache_checksum_matches_legacy_string_digest_for_unicode_payload() -> None:
    cache = Cache(Path("cache.json"))
    payload = _analysis_payload(
        cache,
        files={
            "unicodé.py": {
                "st": [1, 10],
                "rn": ["Ω", "é"],
            }
        },
    )
    legacy_digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    assert cache_payload_checksum(payload) == legacy_digest


def test_cache_load_binds_version_into_unicode_payload_signature(
    tmp_path: Path,
) -> None:
    # Candidate 1: the signed scope is {v, payload}. The pre-fix payload-only
    # string digest is therefore no longer accepted, and the envelope digest is.
    # Unicode canonicalization still round-trips cleanly through the signer.
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path, filepath="unicodé.py")
    meta = _read_cache_meta(cache_path)

    # A digest that leaves the version mark outside its scope is refused, so a
    # store retagged to the running generation cannot pass as one written under
    # it. Unicode canonicalisation round-trips through the digest either way.
    _write_cache_meta(
        cache_path,
        **{
            META_KEY_CHECKSUM: hashlib.sha256(
                canonical_json(
                    {
                        "py": meta[META_KEY_PYTHON_TAG],
                        "fp": meta[META_KEY_FINGERPRINT],
                    }
                ).encode("utf-8")
            ).hexdigest()
        },
    )
    rejected = Cache(cache_path)
    rejected.load()
    assert rejected.load_status is CacheStatus.INTEGRITY_FAILED

    _write_cache_meta(
        cache_path,
        **{
            META_KEY_CHECKSUM: envelope_checksum(
                version=meta[META_KEY_VERSION],
                python_tag=meta[META_KEY_PYTHON_TAG],
                fingerprint_version=meta[META_KEY_FINGERPRINT],
            )
        },
    )
    _assert_loads_cleanly(cache_path, "unicodé.py")


def test_cache_checksum_mismatch_warns(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    _save_single_cache_entry(cache_path)

    _write_cache_meta(cache_path, **{META_KEY_CHECKSUM: "bad"})

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "checksum" in loaded.load_warning
    assert loaded.data["version"] == Cache._CACHE_VERSION
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.INTEGRITY_FAILED
    assert loaded.cache_schema_version == Cache._CACHE_VERSION


def test_cache_refuses_a_legacy_json_monolith_at_the_cache_path(
    tmp_path: Path,
) -> None:
    """The document format the SQLite store replaced is refused, not read.

    A repository upgraded in place still has its old ``cache.json``, and a user
    may still point ``--cache-path`` at one. Reading it is impossible and
    guessing at it would be worse; the load has to end in a typed refusal with
    an empty cache, never in a partially understood store.
    """

    cache_path = tmp_path / "cache.json"
    data = {"version": "0.0", "files": {}}
    signature = cache_payload_checksum(data)
    cache_path.write_text(
        json.dumps({**data, "_signature": signature}, ensure_ascii=False, indent=2),
        "utf-8",
    )

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "corrupted" in loaded.load_warning
    assert loaded.data["version"] == Cache._CACHE_VERSION
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.CORRUPT
    assert loaded.cache_schema_version is None


def test_cache_v210_entries_are_rejected_without_partial_reuse(
    tmp_path: Path,
) -> None:
    assert Cache._CACHE_VERSION == "4.0"

    cache_path = tmp_path / "cache.json"
    old_cache = Cache(cache_path, root=tmp_path)
    _bind_module_paths(old_cache, "old_identity.py")
    old_cache.put_file_entry(
        "old_identity.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    old_cache.save()

    assert _read_cache_meta(cache_path)[META_KEY_VERSION] == "4.0"
    _write_cache_meta(cache_path, **{META_KEY_VERSION: "2.10"})

    regenerated = Cache(cache_path, root=tmp_path)
    regenerated.load()

    assert regenerated.load_status == CacheStatus.VERSION_MISMATCH
    assert regenerated.cache_schema_version == "2.10"
    assert regenerated.get_file_entry("old_identity.py") is None
    assert regenerated.data["files"] == {}

    _bind_module_paths(regenerated, "registry_identity.py")
    regenerated.put_file_entry(
        "registry_identity.py",
        {"mtime_ns": 2, "size": 20},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    regenerated.save()

    reloaded = Cache(cache_path, root=tmp_path)
    reloaded.load()
    assert reloaded.load_status == CacheStatus.OK
    assert reloaded.cache_schema_version == Cache._CACHE_VERSION
    assert reloaded.get_file_entry("old_identity.py") is None
    assert reloaded.get_file_entry("registry_identity.py") is not None


@pytest.mark.parametrize("version", ["0.0", "2.2", "2.7"])
def test_cache_v_field_version_mismatch_warns(tmp_path: Path, version: str) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _write_cache_meta(cache_path, **{META_KEY_VERSION: version})

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "version mismatch" in loaded.load_warning
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.VERSION_MISMATCH
    assert loaded.cache_schema_version == version


def test_cache_over_its_budget_still_loads_and_warms(tmp_path: Path) -> None:
    """The inverse of the deleted ``test_cache_too_large_warns``.

    That test pinned the defect: a store past ``max_size_bytes`` was discarded
    whole on load, so the next run went cold. Both directions are now pinned by
    two different tests -- this one says an over-budget store still serves its
    entries, and ``test_cache_budget_evicts_rows_an_older_generation_left``
    says the budget is not thereby inert.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)

    cache = Cache(cache_path, root=cache_path.parent, max_size_bytes=1)
    cache.load()
    assert cache.load_status is CacheStatus.OK
    assert cache.load_warning is None
    assert cache.get_file_entry("x.py") is not None
    assert cache.cache_schema_version == Cache._CACHE_VERSION
    assert not hasattr(CacheStatus, "TOO_LARGE")


def test_cache_budget_evicts_rows_an_older_generation_left(tmp_path: Path) -> None:
    """The budget is reachable: some input trips it and something is evicted.

    A guard no input can reach is theater, and after removing the load-side cap
    the write-side budget is the only thing ``max_size_bytes`` still does. This
    proves it fires -- and that it fires on a row from an *older* generation,
    which is the only kind it is allowed to take.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path, filepath="stale.py")
    assert set(_read_cache_rows(cache_path)) == {"stale.py"}

    second = Cache(cache_path, root=cache_path.parent, max_size_bytes=1)
    second.load()
    _bind_module_paths(second, "fresh.py")
    second.put_file_entry(
        "fresh.py",
        {"mtime_ns": 2, "size": 20},
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    second.save()

    # The previous generation's row is gone; the row this run needs survives,
    # because evicting it would put the next run back on the cold path.
    assert set(_read_cache_rows(cache_path)) == {"fresh.py"}


def test_cache_load_missing_file(tmp_path: Path) -> None:
    cache_path = tmp_path / "missing.json"
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is None
    assert cache.load_status == CacheStatus.MISSING
    assert cache.cache_schema_version is None


def test_file_stat_signature(tmp_path: Path) -> None:
    file_path = tmp_path / "x.py"
    file_path.write_text("print('x')\n", "utf-8")
    stat = file_stat_signature(str(file_path))
    assert stat["size"] == file_path.stat().st_size
    assert isinstance(stat["mtime_ns"], int)


def test_cache_load_corrupted_store(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    cache_path.write_text("{invalid json", "utf-8")
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "corrupted" in cache.load_warning
    assert cache.load_status == CacheStatus.CORRUPT
    assert cache.cache_schema_version is None


def test_cache_load_exists_oserror_graceful_ignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    original_exists = Path.exists

    def _raise_exists(self: Path) -> bool:
        if self == cache_path:
            raise OSError("no exists")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _raise_exists)
    cache = Cache(cache_path)
    cache.load()
    _assert_unreadable_cache_contract(cache)


def test_cache_load_unreadable_existence_probe_graceful_ignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    original_exists = Path.exists

    def _raise_exists(self: Path, *args: object, **kwargs: object) -> bool:
        if self == cache_path:
            raise OSError("no stat")
        return original_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", _raise_exists)
    cache = Cache(cache_path)
    cache.load()
    _assert_unreadable_cache_contract(cache)


def test_cache_load_unopenable_store_graceful_ignore(tmp_path: Path) -> None:
    """A store that cannot be opened is *unreadable*, not corrupt.

    Induced by a real condition rather than a patched seam: a directory at the
    cache path exists, stats fine, and refuses to open as a database. The two
    verdicts ask different things of the reader -- fix your permissions versus
    your cache is damaged -- so collapsing them would misdirect.
    """

    cache_path = tmp_path / "cache.sqlite3"
    cache_path.mkdir()
    cache = Cache(cache_path)
    cache.load()
    _assert_unreadable_cache_contract(cache)


def _assert_unreadable_cache_contract(cache: Cache) -> None:
    assert cache.load_warning is not None
    assert "unreadable" in cache.load_warning
    assert cache.data["files"] == {}
    assert cache.load_status == CacheStatus.UNREADABLE
    assert cache.cache_schema_version is None


def test_cache_load_row_payload_that_is_not_an_object(tmp_path: Path) -> None:
    """A row that decodes to the wrong JSON kind is a format refusal.

    The document store guarded this as ``files`` arriving as a list; a row
    store guards the same class one level down, at a row whose payload is not
    an entry object at all.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _overwrite_lane(cache_path, "x.py", TABLE_NEUTRAL, b"[]")
    cache = Cache(cache_path, root=cache_path.parent)
    cache.load()
    assert cache.load_status is CacheStatus.OK
    assert cache.get_file_entry("x.py") is None


def test_cache_save_error(tmp_path: Path) -> None:
    """A store that cannot be written raises, rather than reporting success.

    Induced by a real condition: a directory sits where the database belongs,
    so opening it for write fails. Silence here would be the worst outcome --
    the run would believe it had left a warm cache behind.
    """

    cache_path = tmp_path / "cache.sqlite3"
    cache_path.mkdir()
    cache = Cache(cache_path)

    with pytest.raises(CacheError):
        cache.save()


def test_cache_legacy_secret_warning_on_init(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_secret = cache_path.parent / ".cache_secret"
    legacy_secret.write_text("legacy", "utf-8")

    cache = Cache(cache_path)
    assert cache.load_warning is not None
    assert "Legacy cache secret file detected" in cache.load_warning
    assert "delete this obsolete file" in cache.load_warning


def test_cache_legacy_secret_warning_preserved_after_successful_load(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_secret = cache_path.parent / ".cache_secret"
    legacy_secret.write_text("legacy", "utf-8")
    _save_single_cache_entry(cache_path)

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.get_file_entry("x.py") is not None
    assert loaded.load_warning is not None
    assert "Legacy cache secret file detected" in loaded.load_warning


def test_cache_legacy_secret_warning_combined_with_other_warning(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_secret = cache_path.parent / ".cache_secret"
    legacy_secret.write_text("legacy", "utf-8")
    cache_path.write_text("{bad json", "utf-8")

    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "Cache corrupted; ignoring cache" in cache.load_warning
    assert "Legacy cache secret file detected" in cache.load_warning


def test_cache_legacy_secret_check_oserror_sets_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    secret_path = cache_path.parent / ".cache_secret"
    original_exists = Path.exists

    def _exists_with_error(self: Path) -> bool:
        if self == secret_path:
            raise OSError("no access")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _exists_with_error)
    cache = Cache(cache_path)
    assert cache.load_warning is not None
    assert "Legacy cache secret check failed" in cache.load_warning


def test_cache_load_foreign_database_is_refused_and_left_untouched(
    tmp_path: Path,
) -> None:
    """A SQLite file that is not a cache is refused without being written to.

    ``--cache-path`` takes any path the user names. Creating our tables inside
    somebody else's database in order to find out it is not ours would be a
    write performed by a read, so the load opens read-only and refuses. The
    second half of this test is the part that matters: the foreign schema is
    exactly as it was.
    """

    cache_path = tmp_path / "cache.sqlite3"
    with _open_store(cache_path) as conn:
        conn.execute("CREATE TABLE somebody_elses(id INTEGER PRIMARY KEY)")
    before = cache_path.read_bytes()

    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning
    assert cache.data["files"] == {}
    assert cache.load_status is CacheStatus.INVALID_TYPE

    with _open_store(cache_path) as conn:
        tables = {
            str(name)
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert tables == {"somebody_elses"}
    assert cache_path.read_bytes() == before


def test_a_store_from_an_older_physical_schema_is_a_version_mismatch(
    tmp_path: Path,
) -> None:
    """An earlier schema generation is a mismatch, not damage.

    Without this gate the load reaches a table the old generation never had
    and reports corruption, which sends a user looking for a fault that is not
    there. The store is intact; it is simply the previous shape.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _write_cache_meta(cache_path, **{META_KEY_SCHEMA: "1"})

    cache = Cache(cache_path, root=cache_path.parent)
    cache.load()

    assert cache.load_status is CacheStatus.VERSION_MISMATCH
    assert cache.load_warning is not None
    assert "schema mismatch" in cache.load_warning
    assert cache.data["files"] == {}


def test_cache_load_missing_version_mark(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _drop_cache_meta(cache_path, META_KEY_VERSION)
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


def test_cache_load_missing_envelope_checksum(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _drop_cache_meta(cache_path, META_KEY_CHECKSUM)
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


@pytest.mark.parametrize(
    "dropped_key",
    [META_KEY_PYTHON_TAG, META_KEY_FINGERPRINT],
    ids=["missing_python_tag", "missing_fingerprint_version"],
)
def test_cache_load_rejects_missing_required_meta_fields(
    tmp_path: Path,
    dropped_key: str,
) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _drop_cache_meta(cache_path, dropped_key)
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


def test_cache_load_python_tag_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _remint_envelope(cache_path, **{META_KEY_PYTHON_TAG: "cp999"})
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "python tag mismatch" in cache.load_warning


def test_cache_load_fingerprint_version_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _remint_envelope(cache_path, **{META_KEY_FINGERPRINT: "old"})
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "fingerprint version mismatch" in cache.load_warning


def test_cache_lane_profiles_reject_neutral_extraction_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path, min_loc=1, min_stmt=1)
    _store_empty_profile_entry(cache)

    loaded = Cache(cache_path, root=tmp_path, min_loc=15, min_stmt=6)
    loaded.load()
    _bind_module_paths(loaded, "x.py")
    entry = loaded.get_file_entry("x.py")
    assert entry is not None
    decision = _content_hit_decision(loaded, entry)

    assert decision.neutral.reason == "neutral_profile_mismatch"
    assert decision.dependent.reason == "dependent_profile_mismatch"
    assert loaded.load_status == CacheStatus.OK


def test_cache_dependent_lane_rejects_api_surface_mismatch(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path, collect_api_surface=False)
    _store_empty_profile_entry(cache)

    loaded = Cache(cache_path, root=tmp_path, collect_api_surface=True)
    loaded.load()
    _bind_module_paths(loaded, "x.py")
    entry = loaded.get_file_entry("x.py")
    assert entry is not None
    decision = _content_hit_decision(loaded, entry)

    assert decision.neutral.reason == "hit"
    assert decision.dependent.reason == "dependent_profile_mismatch"
    assert loaded.load_status == CacheStatus.OK


def test_cache_load_undecodable_lane_costs_one_entry(tmp_path: Path) -> None:
    """A lane the decoder refuses is one miss, not a condemned store.

    Under the monolith a single unreadable entry invalidated the whole
    document. With identity and lanes apart, the identity row still verifies,
    so the load succeeds and only the entry whose lane is broken goes missing.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    _overwrite_lane(cache_path, "x.py", TABLE_NEUTRAL, {"st": "bad"})

    cache = Cache(cache_path, root=cache_path.parent)
    cache.load()
    assert cache.load_status is CacheStatus.OK
    assert cache.get_file_entry("x.py") is None


def test_cache_save_skips_none_entry_from_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": [],
        },
    )

    def _always_none(_self: Cache, _path: str) -> None:
        return None

    monkeypatch.setattr(Cache, "get_file_entry", _always_none)
    cache.save()
    assert _read_cache_rows(cache_path) == {}


def test_wire_filepath_outside_root_falls_back_to_runtime_path(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cache = Cache(tmp_path / "cache.json", root=root)
    outside = tmp_path / "outside.py"
    assert (
        wire_filepath_from_runtime(str(outside), root=cache.root) == outside.as_posix()
    )


def test_wire_filepath_resolve_oserror_falls_back_to_runtime_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime = tmp_path / "outside.py"
    cache = Cache(tmp_path / "cache.json", root=root)
    original_resolve = Path.resolve

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == runtime:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    assert (
        wire_filepath_from_runtime(str(runtime), root=cache.root) == runtime.as_posix()
    )


def test_wire_filepath_resolve_relative_success_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime = tmp_path / "outside.py"
    cache = Cache(tmp_path / "cache.json", root=root)
    original_resolve = Path.resolve
    resolved_runtime = root / "pkg" / "module.py"

    def _resolve_with_mapping(self: Path, *, strict: bool = False) -> Path:
        if self == runtime:
            return resolved_runtime
        if self == root:
            return root
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_mapping)
    assert wire_filepath_from_runtime(str(runtime), root=cache.root) == "pkg/module.py"


def test_runtime_filepath_from_wire_resolve_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cache = Cache(tmp_path / "cache.json", root=root)
    original_resolve = Path.resolve
    combined = root / "pkg" / "module.py"

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == combined:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    with pytest.raises(RepoPathError, match="cannot resolve path"):
        runtime_filepath_from_wire("pkg/module.py", root=cache.root)


@pytest.mark.parametrize("wire_path", ["../outside.py", "pkg/../../outside.py"])
def test_runtime_filepath_from_wire_rejects_traversal_escape(
    tmp_path: Path,
    wire_path: str,
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(PathOutsideRepoError, match="escapes repository root"):
        runtime_filepath_from_wire(wire_path, root=root)


def test_runtime_filepath_from_wire_rejects_external_absolute_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()

    with pytest.raises(PathOutsideRepoError, match="escapes repository root"):
        runtime_filepath_from_wire(str(tmp_path / "outside.py"), root=root)


def test_runtime_filepath_from_wire_accepts_absolute_under_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    absolute_under_root = root / "pkg" / "module.py"

    assert runtime_filepath_from_wire(str(absolute_under_root), root=root) == str(
        absolute_under_root
    )


def test_as_str_dict_rejects_non_string_keys() -> None:
    assert _as_str_dict({1: "x"}) is None


@pytest.mark.parametrize(
    ("entry", "filepath"),
    [
        ("bad", "x.py"),
        ({"st": "bad"}, "x.py"),
        ({"st": [1]}, "x.py"),
        ({"st": [1, "2"]}, "x.py"),
        ({"st": [1, 2], "u": "bad"}, "x.py"),
        ({"st": [1, 2], "u": [["q", 1, 2, 3, 4, "fp"]]}, "x.py"),
        ({"st": [1, 2], "b": "bad"}, "x.py"),
        ({"st": [1, 2], "b": [["q", 1, 2, 3]]}, "x.py"),
        ({"st": [1, 2], "s": "bad"}, "x.py"),
        ({"st": [1, 2], "s": [["q", 1, 2, 3, "h"]]}, "x.py"),
    ],
)
def test_decode_wire_file_entry_invalid_variants(entry: object, filepath: str) -> None:
    assert _decode_wire_file_entry(entry, filepath) is None


def test_decode_wire_item_type_failures() -> None:
    assert _decode_wire_unit(["q", 1, 2, 3, 4, "fp"], "x.py") is None
    assert _decode_wire_unit(["q", 1, 2, 3, 4, "fp", "0-19"], "x.py") is None
    assert _decode_wire_unit(["q", "1", 2, 3, 4, "fp", "0-19"], "x.py") is None
    assert _decode_wire_block(["q", 1, 2, 3], "x.py") is None
    assert _decode_wire_block(["q", 1, 2, "4", "hash"], "x.py") is None
    assert _decode_wire_segment(["q", 1, 2, 3, "h"], "x.py") is None
    assert _decode_wire_segment(["q", 1, 2, "3", "h", "sig"], "x.py") is None


def test_decode_wire_item_rejects_invalid_risk_fields() -> None:
    assert (
        _decode_wire_unit(
            ["q", 1, 2, 3, 4, "fp", "0-19", 2, 1, "critical", "raw"],
            "x.py",
        )
        is None
    )
    assert (
        _decode_wire_class_metric(
            ["pkg.mod:Service", 1, 10, 3, 2, 4, 1, 7, 8],
            "x.py",
        )
        is None
    )


def test_resolve_root_oserror_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_resolve = Path.resolve

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == tmp_path:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    assert _resolve_root(tmp_path) is None


def test_decode_wire_file_entry_rejects_malformed_v3_lanes() -> None:
    wire = _encode_wire_file_entry(_empty_v3_entry())
    malformed_neutral = dict(wire)
    malformed_neutral["n"] = "not-a-lane"
    assert _decode_wire_file_entry(malformed_neutral, "x.py") is None

    malformed_dependent = dict(wire)
    malformed_dependent["d"] = {"cm": "not-a-list"}
    assert _decode_wire_file_entry(malformed_dependent, "x.py") is None

    missing_profile = dict(wire)
    del missing_profile["np"]
    assert _decode_wire_file_entry(missing_profile, "x.py") is None


def test_cache_v3_wire_helpers_reject_malformed_rows_without_partial_decode() -> None:
    assert cache_wire_helpers._decode_wire_qualname_span(["q", 1, 2]) == ("q", 1, 2)
    assert cache_wire_helpers._decode_wire_qualname_span([None, 1, 2]) is None
    assert cache_wire_helpers._decode_wire_qualname_span_size(["q", 1, 2, 3]) == (
        "q",
        1,
        2,
        3,
    )
    assert cache_wire_helpers._decode_wire_qualname_span_size(["q", 1, 2, None]) is None
    assert (
        cache_wire_helpers._decode_optional_wire_items(
            obj={}, key="x", decode_item=lambda item: str(item)
        )
        == []
    )
    assert (
        cache_wire_helpers._decode_optional_wire_items(
            obj={"x": "bad"}, key="x", decode_item=lambda item: str(item)
        )
        is None
    )
    assert (
        cache_wire_helpers._decode_optional_wire_items(
            obj={"x": [1, None]},
            key="x",
            decode_item=lambda item: str(item) if item is not None else None,
        )
        is None
    )
    assert cache_wire_helpers._decode_optional_wire_items_for_filepath(
        obj={"x": [1]},
        key="x",
        filepath="x.py",
        decode_item=lambda item, filepath: f"{filepath}:{item}",
    ) == ["x.py:1"]
    assert (
        cache_wire_helpers._decode_optional_wire_items_for_filepath(
            obj={"x": [None]},
            key="x",
            filepath="x.py",
            decode_item=lambda item, filepath: None,
        )
        is None
    )
    assert cache_wire_helpers._decode_optional_wire_row(
        obj={"x": [1, 2]}, key="x", expected_len=2
    ) == [1, 2]
    assert (
        cache_wire_helpers._decode_optional_wire_row(
            obj={"x": [1]}, key="x", expected_len=2
        )
        is None
    )
    assert cache_wire_helpers._decode_optional_wire_names(obj={}, key="x") == []
    assert (
        cache_wire_helpers._decode_optional_wire_names(obj={"x": ["a", 1]}, key="x")
        is None
    )
    assert cache_wire_helpers._decode_optional_wire_coupled_classes(
        obj={"x": [["q", ["B", "", "A", "A"]]]}, key="x"
    ) == {"q": ["A", "B"]}
    assert (
        cache_wire_helpers._decode_optional_wire_coupled_classes(
            obj={"x": [[None, ["A"]]]}, key="x"
        )
        is None
    )
    assert cache_wire_helpers._decode_wire_named_span(
        ["q", 1, 2], valid_lengths={3}
    ) == (["q", 1, 2], "q", 1, 2)
    assert cache_wire_helpers._decode_wire_named_sized_span(
        ["q", 1, 2, 3], valid_lengths={4}
    ) == (["q", 1, 2, 3], "q", 1, 2, 3)
    assert cache_wire_helpers._decode_wire_named_span("bad", valid_lengths={3}) is None
    assert cache_wire_helpers._decode_wire_int_fields([1, "bad"], 0, 1) is None
    assert cache_wire_helpers._decode_wire_str_fields(["a", 1], 0, 1) is None


def test_cache_v3_type_guards_validate_both_lane_payload_shapes() -> None:
    # 18 columns since CACHE_VERSION 3.3: index 7 is the public
    # source-decision metric, index 17 the diagnostic CFG E-N+2P.
    unit = _decode_wire_unit(
        [
            "q",
            1,
            2,
            3,
            4,
            "fp",
            "0-19",
            1,
            0,
            "low",
            "raw",
            0,
            "none",
            0,
            "fallthrough",
            "none",
            "none",
            1,
        ],
        "x.py",
    )
    block = _decode_wire_block(["q", 1, 2, 3, "hash"], "x.py")
    segment = _decode_wire_segment(["q", 1, 2, 3, "hash", "sig"], "x.py")
    assert cache_validators._is_file_stat_dict({"mtime_ns": 1, "size": 2})
    assert not cache_validators._is_file_stat_dict([])
    assert cache_validators._is_source_content_digest(_SOURCE_CONTENT_DIGEST)
    assert not cache_validators._is_source_content_digest(_NEUTRAL_PROFILE)
    assert not cache_validators._is_git_blob_identity(None)
    assert cache_validators._is_source_stats_dict(
        {"lines": 1, "functions": 1, "methods": 0, "classes": 0}
    )
    assert not cache_validators._is_source_stats_dict(
        {"lines": -1, "functions": 1, "methods": 0, "classes": 0}
    )
    assert unit is not None and cache_validators._is_unit_dict(unit)
    assert block is not None and cache_validators._is_block_dict(block)
    assert segment is not None and cache_validators._is_segment_dict(segment)
    assert not cache_validators._is_unit_dict({"qualname": "q"})
    assert not cache_validators._is_block_dict([])
    assert not cache_validators._is_segment_dict([])

    typing = {
        "module": "m",
        "filepath": "m.py",
        "callable_count": 1,
        "params_total": 1,
        "params_annotated": 1,
        "returns_total": 1,
        "returns_annotated": 1,
        "any_annotation_count": 0,
    }
    docstrings = {
        "module": "m",
        "filepath": "m.py",
        "public_symbol_total": 1,
        "public_symbol_documented": 1,
    }
    param = {
        "name": "x",
        "kind": "pos_or_kw",
        "has_default": False,
        "annotation_hash": "",
    }
    symbol = {
        "qualname": "m:f",
        "kind": "function",
        "exported_via": "name",
        "start_line": 1,
        "end_line": 2,
        "returns_hash": "",
        "params": [param],
    }
    assert cache_validators._is_module_typing_coverage_dict(typing)
    assert cache_validators._is_module_docstring_coverage_dict(docstrings)
    assert cache_validators._is_api_param_spec_dict(param)
    assert cache_validators._is_public_symbol_dict(symbol)
    assert cache_validators._is_module_api_surface_dict(
        {"module": "m", "filepath": "m.py", "all_declared": ["f"], "symbols": [symbol]}
    )
    assert not cache_validators._is_module_api_surface_dict(
        {"module": "m", "filepath": "m.py", "all_declared": [1], "symbols": []}
    )

    class_metrics = {
        "qualname": "m:C",
        "filepath": "m.py",
        "risk_coupling": "low",
        "risk_cohesion": "low",
        "start_line": 1,
        "end_line": 2,
        "cbo": 0,
        "lcom4": 1,
        "method_count": 1,
        "instance_var_count": 0,
        "coupled_classes": ["m:D"],
    }
    dead = {
        "qualname": "m:f",
        "local_name": "f",
        "filepath": "m.py",
        "kind": "function",
        "start_line": 1,
        "end_line": 2,
        "suppressed_rules": ["rule"],
    }
    assert cache_validators._is_class_metrics_dict(class_metrics)
    assert not cache_validators._is_class_metrics_dict(
        {**class_metrics, "coupled_classes": [1]}
    )
    assert cache_validators._is_module_dep_dict(
        {"source": "m", "target": "n", "import_type": "import", "line": 1}
    )
    assert cache_validators._is_dead_candidate_dict(dead)
    assert not cache_validators._is_dead_candidate_dict(
        {**dead, "suppressed_rules": [1]}
    )


def test_cache_v3_semantic_and_binding_decoders_reject_invalid_contracts() -> None:
    event = [
        "event-1",
        "assign",
        "m:f",
        [["param", "x"]],
        ["event", "out"],
        ["guard"],
        1,
        "resolved",
    ]
    for kind in (
        "artifact_write",
        "assign",
        "compatibility_check",
        "compute_digest",
        "construct",
        "field_write",
        "publish_event",
        "resolve_identity",
        "return_value",
        "serialize_field",
        "security_observation",
    ):
        assert (
            cache_wire_decode._decode_semantic_event(
                [event[0], kind, *event[2:]], filepath="m.py"
            )
            is not None
        )
    assert (
        cache_wire_decode._decode_semantic_event(
            [event[0], "unknown", *event[2:]], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_semantic_event(
            [*event[:6], 0, *event[7:]], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_semantic_event(
            [*event[:3], [["bad", "x"]], *event[4:]], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_contract_summary(
            ["m:f", [event], [["x", "out"]], [["event", "out"]], False],
            filepath="m.py",
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_contract_summary(
            ["m:f", [event], [["x"]], [], False], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_semantic_facts(
            {"se": [event], "fc": []}, filepath="m.py"
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_semantic_facts(
            {"se": [None], "fc": []}, filepath="m.py"
        )
        is None
    )

    assert (
        cache_wire_decode._decode_profile_digest(
            ["codeclone.cache.profile.neutral.v1", "sha256", "0" * 64],
            expected_domain="codeclone.cache.profile.neutral.v1",
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_profile_digest(
            ["codeclone.cache.profile.neutral.v1", "sha1", "0" * 64],
            expected_domain="codeclone.cache.profile.neutral.v1",
        )
        is None
    )
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
                "gb": None,
            }
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha1", "0" * 64],
                "gb": None,
            }
        )
        is None
    )


def test_cache_v3_semantic_decoder_covers_closed_vocabulary_edges() -> None:
    for kind in ("param", "event", "const", "unresolved"):
        assert cache_wire_decode._decode_fact_ref([kind, "value"]) is not None
    assert cache_wire_decode._decode_fact_ref("bad") is None
    assert cache_wire_decode._decode_fact_ref(["bad", "value"]) is None
    assert cache_wire_decode._decode_fact_ref(["param", None]) is None

    base_event: list[object] = [
        "event-1",
        "assign",
        "m:f",
        [],
        None,
        [],
        1,
        "unavailable",
    ]
    assert (
        cache_wire_decode._decode_semantic_event(base_event, filepath="m.py")
        is not None
    )
    assert (
        cache_wire_decode._decode_semantic_event(
            [*base_event[:4], ["bad", "value"], *base_event[5:]], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_semantic_event(
            [*base_event[:5], [None], *base_event[6:]], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_semantic_event(
            [*base_event[:7], "bad"], filepath="m.py"
        )
        is None
    )
    assert cache_wire_decode._decode_contract_summary("bad", filepath="m.py") is None
    assert (
        cache_wire_decode._decode_contract_summary(
            ["m:f", [], [], [["bad", "value"]], False], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_contract_summary(
            ["m:f", [], [[None, "out"]], [], False], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_semantic_facts(
            {"se": [], "fc": [None]}, filepath="m.py"
        )
        is None
    )


def test_cache_v3_semantic_facts_decode_reuses_identical_embedded_events() -> None:
    """Perf-ledger #2 dedup proof: value-identical embedded rows share objects.

    Contract summaries embed their events on the wire and four of five
    embedded rows are exact copies of flat ``se`` rows, so the decoder must
    hand back the already-decoded object for a copy (the decode-count
    reduction the ledger demands) while a row that diverges only in its
    resolution view must keep decoding independently with its own values.
    """

    shared_row: list[object] = [
        "event-1",
        "assign",
        "m:f",
        [["param", "x"]],
        ["event", "event-1"],
        [],
        1,
        "unavailable",
    ]
    resolved_row: list[object] = [
        "event-1",
        "assign",
        "m:f",
        [["param", "x"]],
        ["event", "event-1"],
        [],
        1,
        "resolved",
    ]
    fresh_row: list[object] = [
        "event-2",
        "field_write",
        "m:g",
        [["param", "x"], ["param", "y"]],
        None,
        [],
        2,
        "resolved",
    ]
    facts = cache_wire_decode._decode_semantic_facts(
        {
            "se": [shared_row, fresh_row],
            "fc": [
                ["m:f", [shared_row, resolved_row], [], [["param", "x"]], False],
                ["m:g", [fresh_row], [], [], False],
            ],
        },
        filepath="m.py",
    )
    assert facts is not None
    flat_by_id = {event.event_id: event for event in facts.events}
    summary_f, summary_g = facts.function_contract_summaries

    # Exact wire copies decode to the very same object as the flat lane.
    assert summary_f.events[0] is flat_by_id["event-1"]
    assert summary_g.events[0] is flat_by_id["event-2"]

    # The resolution-upgraded copy keeps its own decode and its own values.
    assert summary_f.events[1] is not flat_by_id["event-1"]
    assert summary_f.events[1].resolution == "resolved"
    assert flat_by_id["event-1"].resolution == "unavailable"

    # Fact refs with equal payloads are interned within one file decode.
    assert (
        flat_by_id["event-1"].inputs[0]
        is flat_by_id["event-2"].inputs[0]
        is summary_f.returns[0]
    )
    assert flat_by_id["event-2"].inputs[1].ref == "y"


def test_cache_v3_wire_edge_decoders_are_fail_closed() -> None:
    assert cache_wire_decode._decode_wire_stat({"st": [1, 2]}) == {
        "mtime_ns": 1,
        "size": 2,
    }
    assert cache_wire_decode._decode_wire_stat({"st": [1, None]}) is None
    assert (
        cache_wire_decode._decode_profile_digest(
            ["codeclone.cache.profile.dependent.v1", "sha256", "1" * 64],
            expected_domain="codeclone.cache.profile.dependent.v1",
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_profile_digest(
            ["codeclone.cache.profile.neutral.v1", "sha256", "short"],
            expected_domain="codeclone.cache.profile.neutral.v1",
        )
        is None
    )
    assert cache_wire_decode._decode_content_binding({}) is None
    assert (
        cache_wire_decode._decode_content_binding({"cb": "1", "sd": "bad", "gb": None})
        is None
    )
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha256", "short"],
                "gb": None,
            }
        )
        is None
    )
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
                "gb": ["sha256", "0" * 64],
            }
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
                "gb": ["sha1", "short"],
            }
        )
        is None
    )
    assert cache_wire_decode._decode_optional_wire_source_stats(
        obj={"ss": [1, 2, 3, 4]}
    ) == {"lines": 1, "functions": 2, "methods": 3, "classes": 4}
    assert (
        cache_wire_decode._decode_optional_wire_source_stats(
            obj={"ss": [1, 2, "bad", 4]}
        )
        is None
    )
    assert (
        cache_wire_decode._decode_optional_wire_source_stats(obj={"ss": [1, -1, 3, 4]})
        is None
    )

    assert cache_wire_decode._decode_optional_wire_module_ints(
        obj={"x": ["m", 1]}, key="x", expected_len=2, int_indexes=(1,)
    ) == ("m", (1,))
    assert (
        cache_wire_decode._decode_optional_wire_module_ints(
            obj={"x": [None, 1]}, key="x", expected_len=2, int_indexes=(1,)
        )
        is None
    )
    assert (
        cache_wire_decode._decode_optional_wire_typing_coverage(
            obj={"tc": ["m", 1, 2, 1, 1, 1, 0]}, filepath="m.py"
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_optional_wire_docstring_coverage(
            obj={"dg": ["m", 1, 1]}, filepath="m.py"
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_optional_wire_api_surface(
            obj={"as": ["m", ["f"], [["m:f", "function", 1, 2, "name", "", []]]]},
            filepath="m.py",
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_optional_wire_api_surface(
            obj={"as": ["m", ["f"], [None]]}, filepath="m.py"
        )
        is None
    )

    assert cache_wire_decode._decode_wire_structural_findings_optional({}) == []
    structural = [["kind", "key", [["a", "b"]], [["m:f", 1, 2]]]]
    assert (
        cache_wire_decode._decode_wire_structural_findings_optional({"sf": structural})
        is not None
    )
    assert (
        cache_wire_decode._decode_wire_structural_findings_optional({"sf": [None]})
        is None
    )
    assert cache_wire_decode._decode_wire_structural_signature([["a", "b"]]) == {
        "a": "b"
    }
    assert cache_wire_decode._decode_wire_structural_signature([[None, "b"]]) is None
    assert cache_wire_decode._decode_wire_structural_occurrence(["m:f", 1, 2]) == {
        "qualname": "m:f",
        "start": 1,
        "end": 2,
    }
    assert (
        cache_wire_decode._decode_wire_structural_occurrence(["m:f", None, 2]) is None
    )


def test_cache_v3_remaining_type_guard_edges_are_explicit() -> None:
    assert not cache_validators._is_source_stats_dict([])
    assert not cache_validators._is_unit_dict([])
    assert not cache_validators._is_module_typing_coverage_dict([])
    assert not cache_validators._is_module_docstring_coverage_dict([])
    assert not cache_validators._is_api_param_spec_dict([])
    assert not cache_validators._is_public_symbol_dict([])
    assert not cache_validators._is_module_api_surface_dict([])
    assert not cache_validators._is_class_metrics_dict([])
    assert not cache_validators._is_dead_candidate_dict([])
    assert not cache_validators._has_typed_fields(
        [], string_keys=("name",), int_keys=("line",)
    )


def test_cache_v3_decoder_rejects_every_nested_lane_boundary() -> None:
    assert (
        cache_wire_decode._decode_contract_summary(
            [None, [], [], [], False], filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_semantic_facts(
            {"se": "bad", "fc": []}, filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_profile_digest(
            ["other", "sha256", "0" * 64], expected_domain="other"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
                "gb": ["sha1", None],
            }
        )
        is None
    )
    assert cache_wire_decode._decode_optional_wire_source_stats(obj={}) is None
    assert cache_wire_decode._decode_wire_name_sections(obj={"rn": [1]}) is None
    assert (
        cache_wire_decode._decode_optional_wire_api_surface(
            obj={"as": [None, [], []]}, filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_optional_wire_function_relationship_facts(
            obj={"fr": [None]}, filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_optional_wire_function_relationship_facts(
            obj={"fr": [["m:f", [None]]]}, filepath="m.py"
        )
        is None
    )
    assert (
        cache_wire_decode._decode_wire_api_surface_symbol(
            ["m:f", "function", 1, 2, "name", "", "bad"]
        )
        is None
    )
    assert (
        cache_wire_decode._decode_wire_api_surface_symbol(
            ["m:f", "function", 1, 2, "name", "", [None]]
        )
        is None
    )
    assert cache_wire_decode._decode_wire_api_param_spec(["x"]) is None
    assert (
        cache_wire_decode._decode_wire_api_param_spec(["x", "pos_or_kw", "bad", ""])
        is None
    )
    assert cache_wire_decode._decode_wire_module_dep("bad") is None

    wire = _encode_wire_file_entry(_empty_v3_entry())
    for lane, key, value in (
        ("n", "se", "bad"),
        ("n", "rn", [1]),
        ("d", "cc", "bad"),
        ("d", "rr", "bad"),
        ("d", "sf", "bad"),
    ):
        malformed = json.loads(json.dumps(wire))
        malformed[lane][key] = value
        assert _decode_wire_file_entry(malformed, "x.py") is None

    coupled = json.loads(json.dumps(wire))
    coupled["d"]["cm"] = [["m:C", 1, 2, 0, 1, 1, 0, "low", "low"]]
    coupled["d"]["cc"] = [["m:C", ["m:D"]]]
    decoded = _decode_wire_file_entry(coupled, "x.py")
    assert decoded is not None
    assert decoded.module_dependent.class_metrics[0]["coupled_classes"] == ["m:D"]


def test_cache_v3_entry_projection_and_content_miss_are_typed() -> None:
    assert cache_entries._as_security_surface_category(None) is None
    assert cache_entries._as_runtime_reachability_framework(None) is None
    assert cache_entries._as_runtime_reachability_edge_kind(None) is None
    assert cache_entries._new_optional_metrics_payload() == (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        None,
        None,
        None,
    )
    assert (
        cache_entries._unit_dict_from_model(_make_unit("x.py"), "x.py")["filepath"]
        == "x.py"
    )
    assert (
        cache_entries._block_dict_from_model(_make_block("x.py"), "x.py")["filepath"]
        == "x.py"
    )
    assert (
        cache_entries._segment_dict_from_model(_make_segment("x.py"), "x.py")[
            "filepath"
        ]
        == "x.py"
    )
    cache = Cache(Path("cache.json"), root=Path("."))
    cache.bind_module_registry(
        module_registry_context(filepath="x.py", module_name="x")[1]
    )
    decision = cache.reuse_decision(
        runtime_path="x.py",
        content=ContentIdentityVerdict(
            hit=False,
            reason="digest_miss",
            git_fallback_reason=None,
            digest_verify_cost_us=1,
            stat_fast_reject=False,
        ),
        entry=_empty_v3_entry(),
    )
    assert decision.neutral.reason == "content_miss"
    assert decision.dependent.reason == "content_miss"


def test_neutral_facts_preserve_both_complexity_metrics() -> None:
    """Save-time entry->dict conversion must carry BOTH complexity fields.

    Wave D regression pin: ``_neutral_facts`` rebuilds the unit dict
    field-by-field, and a field omitted there silently encodes as its wire
    default — the warm path then serves ``cfg_cyclomatic_complexity == 1``
    for every cached unit while cold runs report real values. Distinct values
    on the two fields also make a swap fail.
    """
    from codeclone.cache._wire_encode import _neutral_facts

    entry = replace(
        _empty_v3_entry(),
        module_neutral=replace(
            _empty_v3_entry().module_neutral,
            units=(
                CacheNeutralUnit(
                    local_name="f",
                    start_line=1,
                    end_line=2,
                    loc=2,
                    stmt_count=1,
                    fingerprint="fp",
                    loc_bucket="0-19",
                    cyclomatic_complexity=5,
                    cfg_cyclomatic_complexity=7,
                    nesting_depth=0,
                    risk="low",
                    raw_hash="raw",
                    entry_guard_count=0,
                    entry_guard_terminal_profile="none",
                    entry_guard_has_side_effect_before=False,
                    terminal_kind="fallthrough",
                    try_finally_profile="none",
                    side_effect_order_profile="none",
                ),
            ),
        ),
    )
    facts = _neutral_facts(entry)
    unit = facts["units"][0]
    assert unit["cyclomatic_complexity"] == 5
    assert unit["cfg_cyclomatic_complexity"] == 7


def test_cache_v3_neutral_qualnames_are_owned_by_current_registry() -> None:
    payload = replace(
        _empty_v3_entry().module_neutral,
        units=(
            CacheNeutralUnit(
                local_name="f",
                start_line=1,
                end_line=2,
                loc=2,
                stmt_count=1,
                fingerprint="fp",
                loc_bucket="0-19",
                cyclomatic_complexity=1,
                cfg_cyclomatic_complexity=1,
                nesting_depth=0,
                risk="low",
                raw_hash="raw",
                entry_guard_count=0,
                entry_guard_terminal_profile="none",
                entry_guard_has_side_effect_before=False,
                terminal_kind="fallthrough",
                try_finally_profile="none",
                side_effect_order_profile="none",
            ),
        ),
        blocks=(
            CacheNeutralBlock(
                local_name="f",
                start_line=1,
                end_line=2,
                size=2,
                block_hash="block",
            ),
        ),
        segments=(
            CacheNeutralSegment(
                local_name="f",
                start_line=1,
                end_line=2,
                size=2,
                segment_hash="segment",
                segment_sig="sig",
            ),
        ),
    )

    flat = rehydrate_cache_neutral(
        payload, module_name="pkg.mod", filepath="pkg/mod.py"
    )
    src = rehydrate_cache_neutral(
        payload, module_name="src_pkg.mod", filepath="src/src_pkg/mod.py"
    )

    assert flat.units[0].qualname == "pkg.mod:f"
    assert flat.blocks[0].qualname == "pkg.mod:f"
    assert flat.segments[0].qualname == "pkg.mod:f"
    assert src.units[0].qualname == "src_pkg.mod:f"
    assert src.units[0].fingerprint == flat.units[0].fingerprint


def test_cache_v3_profiles_exclude_evaluator_thresholds(tmp_path: Path) -> None:
    first = Cache(tmp_path / "first.json", root=tmp_path)
    second = Cache(tmp_path / "second.json", root=tmp_path)
    registry = module_registry_context(filepath="m.py", module_name="m")[1]
    first.bind_module_registry(registry)
    second.bind_module_registry(registry)

    evaluator_thresholds = (0, 100)
    assert evaluator_thresholds[0] != evaluator_thresholds[1]
    assert first._module_neutral_profile == second._module_neutral_profile
    assert first._module_dependent_profile == second._module_dependent_profile
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
                "gb": ["sha1", "0" * 40],
            }
        )
        is not None
    )
    assert (
        cache_wire_decode._decode_content_binding(
            {
                "cb": "1",
                "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
                "gb": ["md5", "0" * 32],
            }
        )
        is None
    )


def test_cache_v3_empty_entry_encode_decode_is_deterministic() -> None:
    entry = _empty_v3_entry()
    first = _encode_wire_file_entry(entry)
    second = _encode_wire_file_entry(entry)

    assert first == second
    assert _decode_wire_file_entry(first, "x.py") == entry


def test_cache_v3_wire_matches_golden_without_neutral_module_authority() -> None:
    wire = _encode_wire_file_entry(_empty_v3_entry())
    golden_path = Path(__file__).parent / "fixtures" / "cache_v3" / "golden_entry.json"

    assert wire == json.loads(golden_path.read_text("utf-8"))
    neutral_json = json.dumps(wire["n"], sort_keys=True)
    assert "module" not in neutral_json
    assert "filepath" not in neutral_json


def test_neutral_lane_refuses_a_moved_binding_context_by_name(tmp_path: Path) -> None:
    """The refusal has its own reason, not a generic profile mismatch.

    A moved mount and a changed floor are different failures with different
    fixes, so the lane says which one happened. Pinning the reason keeps the
    binding-context gate from being silently folded into the profile digest
    later, where it would stop being visible at all (39Y-FP section 3a).
    """

    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path)
    _store_empty_profile_entry(cache)
    loaded = Cache(cache_path, root=tmp_path)
    loaded.load()
    _bind_module_paths(loaded, "x.py")
    entry = loaded.get_file_entry("x.py")
    assert entry is not None

    same_mount = _content_hit_decision(loaded, entry)
    assert same_mount.neutral.reason == "hit"

    moved = replace(
        entry,
        binding_context_digest=binding_context_digest(
            PythonModuleIdentity(
                module="elsewhere.x",
                package="elsewhere",
                is_package=False,
                mount_path="src",
                origin="import_mount",
                node_kind="module_file",
            )
        ),
    )
    decision = _content_hit_decision(loaded, moved)
    assert decision.neutral.hit is False
    assert decision.neutral.reason == "binding_context_mismatch"


def test_cache_manifest_change_preserves_neutral_lane_only(tmp_path: Path) -> None:
    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n", "utf-8")
    cache_path = tmp_path / "cache.json"
    initial_registry = module_registry_context(filepath="a.py", module_name="a")[1]
    cache = Cache(cache_path, root=tmp_path)
    cache.bind_module_registry(initial_registry)
    cache.put_file_entry(
        str(source),
        file_stat_signature(str(source)),
        [],
        [],
        [],
        source_content_digest=_SOURCE_CONTENT_DIGEST,
    )
    entry = cache.get_file_entry(str(source))
    assert entry is not None

    (tmp_path / "b.py").write_text("VALUE = 1\n", "utf-8")
    changed_registry = module_registry_context(
        filepath="a.py",
        module_name="a",
        inventory_modules=("b",),
    )[1]
    changed_registry = replace(
        changed_registry,
        digest=DigestObject(
            domain="codeclone.module-registry.v1",
            algorithm="sha256",
            value="1" * 64,
        ),
    )
    cache.bind_module_registry(changed_registry)
    decision = cache.reuse_decision(
        # a.py's own identity is unchanged by adding b to the inventory, so the
        # neutral lane must still hit; only the manifest-keyed lane moves.
        runtime_path=str(source),
        content=ContentIdentityVerdict(
            hit=True,
            reason="digest_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        ),
        entry=entry,
    )

    assert decision.neutral.reason == "hit"
    assert decision.dependent.reason == "dependent_profile_mismatch"


def test_decode_wire_metrics_items_and_deps_roundtrip_shape() -> None:
    class_metric = _decode_wire_class_metric(
        ["pkg.mod:Service", 1, 10, 3, 2, 4, 1, "low", "medium"],
        "x.py",
    )
    assert class_metric is not None
    assert class_metric["filepath"] == "x.py"
    assert (
        _decode_wire_class_metric(
            ["pkg.mod:Service", "1", 10, 3, 2, 4, 1, "low", "medium"],
            "x.py",
        )
        is None
    )

    module_dep = _decode_wire_module_dep(["a", "b", "import", 1])
    assert module_dep is not None
    assert module_dep["source"] == "a"
    assert _decode_wire_module_dep(["a", "b", "import", "1"]) is None
    assert _decode_wire_module_dep(["a", "b", "broken", 1]) is None

    complete_dep = ModuleDep(
        source="pkg.mod",
        target="pkg.dep",
        import_type="from_import",
        line=7,
        resolution="analyzed",
        inventory_expansion=True,
        level=1,
        requested_module="dep",
        requested_names=("VALUE", "OTHER"),
        candidate_targets=("pkg.dep", "pkg.dep.VALUE"),
    )
    complete_row = cache_entries._module_dep_dict_from_model(complete_dep)
    complete_entry = replace(
        _empty_v3_entry(),
        module_dependent=replace(
            _empty_v3_entry().module_dependent,
            module_deps=(complete_row,),
        ),
    )
    decoded_entry = _decode_wire_file_entry(
        _encode_wire_file_entry(complete_entry),
        "pkg/mod.py",
    )
    assert decoded_entry is not None
    decoded_dep_row = decoded_entry.module_dependent.module_deps[0]
    assert decoded_dep_row == complete_row

    legacy_entry = replace(
        _empty_v3_entry(),
        module_dependent=replace(
            _empty_v3_entry().module_dependent,
            module_deps=(module_dep,),
        ),
    )
    decoded_legacy_entry = _decode_wire_file_entry(
        _encode_wire_file_entry(legacy_entry),
        "pkg/mod.py",
    )
    assert decoded_legacy_entry is not None
    assert decoded_legacy_entry.module_dependent.module_deps == (module_dep,)

    malformed_complete_row = [
        "pkg.mod",
        "pkg.dep",
        "from_import",
        7,
        "analyzed",
        False,
        1,
        "dep",
        ["VALUE"],
        [1],
    ]
    assert _decode_wire_module_dep(malformed_complete_row) is None
    assert (
        _decode_wire_module_dep(
            [
                "pkg.mod",
                "pkg.dep",
                "from_import",
                7,
                "broken",
                False,
                1,
                "dep",
                ["VALUE"],
                ["pkg.dep"],
            ]
        )
        is None
    )

    dead_candidate = _decode_wire_dead_candidate(
        ["pkg.mod:unused", "unused", 1, 2, "function"],
        "fallback.py",
    )
    assert dead_candidate is not None
    assert dead_candidate["filepath"] == "fallback.py"
    assert (
        _decode_wire_dead_candidate(
            ["pkg.mod:unused", "unused", "1", 2, "function"],
            "fallback.py",
        )
        is None
    )
    assert (
        _decode_wire_dead_candidate(
            ["pkg.mod:unused", "unused", 1, 2, "function", "legacy.py"],
            "fallback.py",
        )
        is None
    )
    dead_candidate_with_suppression = _decode_wire_dead_candidate(
        ["pkg.mod:unused", "unused", 1, 2, "function", ["dead-code", "dead-code"]],
        "fallback.py",
    )
    assert dead_candidate_with_suppression is not None
    assert dead_candidate_with_suppression["suppressed_rules"] == ["dead-code"]


def test_cache_type_predicates_reject_non_dict_variants() -> None:
    assert _is_class_metrics_dict([]) is False
    assert _is_module_dep_dict([]) is False
    assert _is_dead_candidate_dict([]) is False
    assert (
        _is_dead_candidate_dict(
            {
                "qualname": "pkg.mod:broken",
                "local_name": "broken",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 2,
            }
        )
        is False
    )
    assert _is_dead_candidate_dict(
        {
            "qualname": "pkg.mod:unused",
            "local_name": "unused",
            "filepath": "pkg/mod.py",
            "start_line": 1,
            "end_line": 2,
            "kind": "function",
        }
    )
    assert (
        _is_dead_candidate_dict(
            {
                "qualname": "pkg.mod:unused",
                "local_name": "unused",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 2,
                "kind": "function",
                "suppressed_rules": ["dead-code"],
            }
        )
        is True
    )
    assert (
        _is_dead_candidate_dict(
            {
                "qualname": "pkg.mod:unused",
                "local_name": "unused",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 2,
                "kind": "function",
                "suppressed_rules": [1],
            }
        )
        is False
    )
    assert (
        _is_class_metrics_dict(
            {
                "qualname": "pkg.mod:Service",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 3,
                "lcom4": 2,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "high",
            }
        )
        is True
    )
    assert (
        _is_class_metrics_dict(
            {
                "qualname": "pkg.mod:Service",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 3,
                "lcom4": 2,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "high",
                "coupled_classes": ["Alpha", "Beta"],
            }
        )
        is True
    )
    assert (
        _is_class_metrics_dict(
            {
                "qualname": "pkg.mod:Service",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 3,
                "lcom4": 2,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "high",
                "coupled_classes": [1],
            }
        )
        is False
    )
    assert _is_class_metrics_dict({"qualname": "pkg.mod:Service"}) is False
    assert (
        _is_module_dep_dict(
            {
                "source": "a",
                "target": "b",
                "import_type": "import",
                "line": 1,
            }
        )
        is True
    )
    assert (
        _is_module_dep_dict(
            {
                "source": "a",
                "target": "b",
                "import_type": "from_import",
                "line": 1,
                "resolution": "analyzed",
                "mechanism": "static",
                "inventory_expansion": False,
                "level": 1,
                "requested_module": "b",
                "requested_names": ["VALUE"],
                "candidate_targets": ["b"],
            }
        )
        is True
    )
    # The mechanism discriminator is a required member of the detail block:
    # an otherwise complete row without it is refused, and the discriminator
    # alone never rides a base row that would silently drop it.
    assert (
        _is_module_dep_dict(
            {
                "source": "a",
                "target": "b",
                "import_type": "from_import",
                "line": 1,
                "resolution": "analyzed",
                "inventory_expansion": False,
                "level": 1,
                "requested_module": "b",
                "requested_names": ["VALUE"],
                "candidate_targets": ["b"],
            }
        )
        is False
    )
    assert (
        _is_module_dep_dict(
            {
                "source": "a",
                "target": "b",
                "import_type": "import",
                "line": 1,
                "mechanism": "dynamic",
            }
        )
        is False
    )
    assert (
        _is_module_dep_dict(
            {
                "source": "a",
                "target": "b",
                "import_type": "from_import",
                "line": 1,
                "resolution": "analyzed",
            }
        )
        is False
    )
    assert _is_module_dep_dict({"source": "a"}) is False
    assert (
        _is_module_dep_dict(
            {
                "source": "a",
                "target": "b",
                "import_type": "broken",
                "line": 1,
            }
        )
        is False
    )


def test_decode_wire_int_fields_rejects_non_int_values() -> None:
    assert _decode_wire_int_fields(["x", "nope"], 1) is None


def test_decode_wire_block_rejects_missing_block_hash() -> None:
    assert (
        _decode_wire_block(
            ["pkg.mod:func", 10, 12, 4, None],
            "pkg/mod.py",
        )
        is None
    )


def test_decode_wire_segment_rejects_missing_segment_signature() -> None:
    assert (
        _decode_wire_segment(
            ["pkg.mod:func", 10, 12, 4, "seg-hash", None],
            "pkg/mod.py",
        )
        is None
    )


def test_decode_wire_dead_candidate_rejects_invalid_rows() -> None:
    assert _decode_wire_dead_candidate(object(), "pkg/mod.py") is None


def test_integrity_read_json_document_forwards_max_bytes(tmp_path: Path) -> None:
    from codeclone.cache.integrity import read_json_document

    path = tmp_path / "doc.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    assert read_json_document(path, max_bytes=64) == {"ok": True}


def test_api_signature_revision_invalidates_only_dependent_profile() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "codeclone/cache/reuse.py").read_text(encoding="utf-8")

    assert '"api_surface_signature_version": API_SURFACE_SIGNATURE_VERSION' in source
    # Candidate 2: class_metrics ride the dependent lane; the design-metrics
    # algorithm revision must gate this profile so a revision bump cannot serve
    # stale cbo/lcom4/risk off a warm hit.
    assert (
        '"design_metrics_algorithm_revision": DESIGN_METRICS_ALGORITHM_REVISION'
        in source
    )
    # Candidate 2 (follow-up): the closed detector catalogs that ride the
    # dependent lane must each version this profile, or a catalog expansion
    # serves a stale dependent-lane fact off a warm hit.
    assert "SECURITY_SURFACE_CATALOG_VERSION" in source
    assert "RUNTIME_REACHABILITY_CATALOG_VERSION" in source
    assert "STRUCTURAL_FINDINGS_CATALOG_VERSION" in source
    assert CACHE_VERSION == "4.0"


def test_wire_module_dep_row_requires_a_known_mechanism() -> None:
    valid = [
        "pkg.mod",
        "pkg.dep",
        "from_import",
        3,
        "analyzed",
        False,
        1,
        "dep",
        ["VALUE"],
        ["pkg.dep"],
        "static",
    ]
    assert _decode_wire_module_dep(list(valid)) is not None

    # A row carrying an unknown discriminator is refused outright rather than
    # silently defaulted to "static", which would invent a static edge.
    assert _decode_wire_module_dep([*valid[:10], "guessed"]) is None
    # The pre-mechanism row length no longer decodes: the version gate is what
    # invalidates old caches, not an absent-tolerant fallback here.
    assert _decode_wire_module_dep(valid[:10]) is None


def test_canonicalize_optional_string_list_narrows_shape() -> None:
    # _wire_encode re-exports the canonicalize helper it consumes; using it
    # keeps this module's import surface unchanged.
    import codeclone.cache._wire_encode as wire_encode_mod

    _normalized_optional_string_list = (
        wire_encode_mod._normalized_optional_string_list  # type: ignore[attr-defined]
    )

    assert _normalized_optional_string_list(None) is None
    assert _normalized_optional_string_list("not-a-list") is None
    assert _normalized_optional_string_list(["ok", 3]) is None
    assert _normalized_optional_string_list(["b", "a", "b"]) == ["a", "b"]


def test_cache_registry_binding_requires_root(tmp_path: Path) -> None:
    from tests._ast_metrics_helpers import module_registry_context

    rootless = Cache(tmp_path / "cache.json")
    with pytest.raises(ValueError, match="requires a project root"):
        rootless.bind_module_registry(
            module_registry_context(filepath="x.py", module_name="x")[1]
        )


def test_cache_put_file_entry_rejects_unregistered_and_foreign_names(
    tmp_path: Path,
) -> None:
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    _bind_module_paths(cache, "x.py")

    with pytest.raises(ValueError, match="absent from module registry"):
        cache.put_file_entry(
            "unbound.py",
            {"mtime_ns": 1, "size": 10},
            [],
            [],
            [],
            source_content_digest=_SOURCE_CONTENT_DIGEST,
        )

    with pytest.raises(ValueError, match="outside module"):
        cache.put_file_entry(
            "x.py",
            {"mtime_ns": 1, "size": 10},
            [_make_unit("x.py", module_name="foreign")],
            [],
            [],
            source_content_digest=_SOURCE_CONTENT_DIGEST,
        )


def test_cache_load_survives_a_transient_stat_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flaky stat costs telemetry, never the warm path.

    This replaces ``test_cache_load_retries_stat_after_transient_failure``,
    which pinned a second stat probe that existed only to feed the load-side
    size ceiling: the first failure was tolerated, then the size was re-probed
    because the ceiling had to be enforced before reading. With no ceiling to
    enforce there is no second probe and nothing to retry -- the size is now a
    span counter and nothing else.

    So the property worth pinning inverted with it. What must hold is that a
    stat failure cannot cost the cache: the load proceeds, the entries arrive,
    and only ``cache_file_bytes`` goes unreported.
    """

    cache_path = tmp_path / "cache.sqlite3"
    _save_single_cache_entry(cache_path)
    cache = Cache(cache_path, root=cache_path.parent)

    calls = {"count": 0}
    real_stat = Path.stat
    real_exists = Path.exists

    def fake_exists(self: Path, *args: Any, **kwargs: Any) -> bool:
        if self == cache_path:
            return True
        return real_exists(self, *args, **kwargs)

    def failing_stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == cache_path:
            calls["count"] += 1
            raise OSError("transient stat failure")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "stat", failing_stat)
    cache.load()
    monkeypatch.undo()

    assert calls["count"] == 1
    assert cache.load_status is CacheStatus.OK
    assert cache.get_file_entry("x.py") is not None
