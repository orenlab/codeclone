# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.baseline as baseline_mod
import codeclone.baseline._metrics_baseline_payload as mb_payload
import codeclone.baseline._metrics_baseline_validation as mb_validate
import codeclone.baseline.metrics_baseline as mb_mod
from codeclone.baseline.metrics_baseline import (
    MetricsBaseline,
    MetricsBaselineStatus,
)
from codeclone.contracts.errors import BaselineValidationError
from codeclone.models import (
    ApiParamSpec,
    ApiSurfaceSnapshot,
    DeadItem,
    HealthScore,
    MetricsSnapshot,
    ModuleApiSurface,
    ProjectMetrics,
    PublicSymbol,
)
from tests._assertions import assert_missing_keys


def _snapshot() -> MetricsSnapshot:
    return MetricsSnapshot(
        max_complexity=50,
        high_risk_functions=("pkg.mod:hot",),
        max_coupling=10,
        high_coupling_classes=("pkg.mod:Service",),
        max_cohesion=4,
        low_cohesion_classes=("pkg.mod:Service",),
        dependency_cycles=(("pkg.a", "pkg.b"),),
        dependency_max_depth=6,
        dead_code_items=("pkg.mod:unused",),
        health_score=70,
        health_grade="C",
    )


def _project_metrics() -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=3.2,
        complexity_max=50,
        high_risk_functions=("pkg.mod:hot", "pkg.mod:hot"),
        coupling_avg=2.0,
        coupling_max=10,
        high_risk_classes=("pkg.mod:Service", "pkg.mod:Service"),
        cohesion_avg=1.8,
        cohesion_max=4,
        low_cohesion_classes=("pkg.mod:Service", "pkg.mod:Service"),
        dependency_modules=2,
        dependency_edges=2,
        dependency_edge_list=(),
        dependency_cycles=(("pkg.a", "pkg.b"), ("pkg.a", "pkg.b")),
        dependency_max_depth=6,
        dependency_longest_chains=(("pkg.a", "pkg.b"),),
        dead_code=(
            DeadItem(
                qualname="pkg.mod:unused",
                filepath="pkg/mod.py",
                start_line=1,
                end_line=2,
                kind="function",
                confidence="high",
            ),
            DeadItem(
                qualname="pkg.mod:unused",
                filepath="pkg/mod.py",
                start_line=1,
                end_line=2,
                kind="function",
                confidence="high",
            ),
        ),
        health=HealthScore(total=70, grade="C", dimensions={"health": 70}),
    )


def _api_surface_snapshot(*, include_added: bool = False) -> ApiSurfaceSnapshot:
    symbols = [
        PublicSymbol(
            qualname="pkg.mod:run",
            kind="function",
            start_line=10,
            end_line=14,
            params=(
                ApiParamSpec(
                    name="value",
                    kind="pos_or_kw",
                    has_default=False,
                ),
            ),
        ),
        PublicSymbol(
            qualname="pkg.mod:stable",
            kind="function",
            start_line=20,
            end_line=22,
        ),
    ]
    if include_added:
        symbols.append(
            PublicSymbol(
                qualname="pkg.mod:added",
                kind="function",
                start_line=30,
                end_line=32,
            )
        )
    return ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module="pkg.mod",
                filepath="pkg/mod.py",
                symbols=tuple(symbols),
            ),
        )
    )


def _api_surface_snapshot_with_filepath(filepath: str) -> ApiSurfaceSnapshot:
    snapshot = _api_surface_snapshot(include_added=True)
    module = snapshot.modules[0]
    return ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module=module.module,
                filepath=filepath,
                symbols=module.symbols,
                all_declared=module.all_declared,
            ),
        )
    )


def _assert_metrics_baseline_reload_state(
    baseline: MetricsBaseline,
    *,
    embedded: bool,
    has_adoption: bool,
    has_api_surface: bool,
) -> None:
    assert baseline.is_embedded_in_clone_baseline is embedded
    assert baseline.has_coverage_adoption_snapshot is has_adoption
    if has_api_surface:
        assert baseline.api_surface_snapshot is not None
    else:
        assert baseline.api_surface_snapshot is None


def _save_metrics_baseline_with_api_surface(
    path: Path,
    *,
    api_surface: ApiSurfaceSnapshot,
) -> dict[str, object]:
    baseline = MetricsBaseline.from_project_metrics(
        project_metrics=_project_metrics_with_adoption_and_api(
            api_surface=api_surface,
        ),
        path=path,
    )
    baseline.save()
    return cast(dict[str, object], json.loads(path.read_text("utf-8")))


def _repo_metrics_baseline_path_and_abs_filepath(tmp_path: Path) -> tuple[Path, str]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    path = repo_root / "metrics-baseline.json"
    absolute_filepath = str((repo_root / "pkg" / "mod.py").resolve())
    return path, absolute_filepath


def _project_metrics_with_adoption_and_api(
    *,
    typing_param_annotated: int = 3,
    typing_return_annotated: int = 2,
    docstring_public_documented: int = 2,
    api_surface: ApiSurfaceSnapshot | None = None,
) -> ProjectMetrics:
    return replace(
        _project_metrics(),
        typing_param_total=4,
        typing_param_annotated=typing_param_annotated,
        typing_return_total=2,
        typing_return_annotated=typing_return_annotated,
        typing_any_count=1,
        docstring_public_total=3,
        docstring_public_documented=docstring_public_documented,
        api_surface=api_surface,
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")


def _load_written_metrics_baseline(path: Path, payload: object) -> MetricsBaseline:
    _write_json(path, payload)
    baseline = MetricsBaseline(path)
    baseline.load()
    return baseline


def _valid_payload(
    *,
    schema_version: str = mb_mod.METRICS_BASELINE_SCHEMA_VERSION,
    python_tag: str | None = None,
) -> dict[str, object]:
    return mb_payload._build_payload(
        snapshot=_snapshot(),
        schema_version=schema_version,
        python_tag=python_tag or mb_mod.current_python_tag(),
        generator_name=mb_mod.METRICS_BASELINE_GENERATOR,
        generator_version="2.0.0",
        created_at="2026-03-06T00:00:00Z",
    )


def _ready_metrics_baseline(
    path: Path,
    *,
    schema_version: str,
    generator_name: str = mb_mod.METRICS_BASELINE_GENERATOR,
    python_tag: str | None = None,
    embedded: bool = False,
    has_adoption: bool = True,
) -> MetricsBaseline:
    baseline = MetricsBaseline(path)
    baseline.snapshot = _snapshot()
    baseline.payload_sha256 = mb_payload._compute_payload_sha256(_snapshot())
    baseline.has_coverage_adoption_snapshot = has_adoption
    baseline.generator_name = generator_name
    baseline.schema_version = schema_version
    baseline.python_tag = python_tag or mb_mod.current_python_tag()
    baseline.is_embedded_in_clone_baseline = embedded
    return baseline


def test_coerce_metrics_baseline_status_variants() -> None:
    assert (
        mb_mod.coerce_metrics_baseline_status(MetricsBaselineStatus.OK)
        == MetricsBaselineStatus.OK
    )
    assert mb_mod.coerce_metrics_baseline_status("ok") == MetricsBaselineStatus.OK
    assert (
        mb_mod.coerce_metrics_baseline_status("not-a-status")
        == MetricsBaselineStatus.INVALID_TYPE
    )
    assert (
        mb_mod.coerce_metrics_baseline_status(None)
        == MetricsBaselineStatus.INVALID_TYPE
    )


def test_metrics_baseline_load_missing_file_is_noop(tmp_path: Path) -> None:
    baseline = MetricsBaseline(tmp_path / "missing.json")
    baseline.load()
    assert baseline.snapshot is None


def test_metrics_baseline_load_stat_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "metrics-baseline.json"
    _write_json(path, _valid_payload())
    baseline = MetricsBaseline(path)

    original_exists = Path.exists

    def _boom_exists(self: Path) -> bool:
        if self == path:
            raise OSError("exists failed")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _boom_exists)
    with pytest.raises(
        BaselineValidationError, match="Cannot stat metrics baseline file"
    ):
        baseline.load()

    monkeypatch.setattr(Path, "exists", original_exists)
    original_stat = Path.stat

    def _boom_stat(
        self: Path,
        *,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if self == path:
            raise OSError("stat failed")
        try:
            return original_stat(self, follow_symlinks=follow_symlinks)
        except TypeError:
            return original_stat(self)

    monkeypatch.setattr(Path, "stat", _boom_stat)
    with pytest.raises(
        BaselineValidationError, match="Cannot stat metrics baseline file"
    ):
        baseline.load()


def test_metrics_baseline_load_size_and_shape_validation(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    _write_json(path, _valid_payload())

    baseline = MetricsBaseline(path)
    with pytest.raises(BaselineValidationError, match="too large"):
        baseline.load(max_size_bytes=1)

    _write_json(path, {"meta": [], "metrics": {}})
    with pytest.raises(BaselineValidationError, match="'meta' must be object"):
        baseline.load()

    _write_json(path, {"meta": {}, "metrics": []})
    with pytest.raises(BaselineValidationError, match="'metrics' must be object"):
        baseline.load()


def test_metrics_baseline_load_rejects_non_object_preloaded_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    _write_json(path, _valid_payload())
    baseline = MetricsBaseline(path)

    with pytest.raises(BaselineValidationError, match="must be an object") as exc:
        baseline.load(preloaded_payload=cast(Any, []))
    assert exc.value.status == MetricsBaselineStatus.INVALID_TYPE


def test_metrics_baseline_load_stat_error_after_exists_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "metrics-baseline.json"
    _write_json(path, _valid_payload())
    baseline = MetricsBaseline(path)

    monkeypatch.setattr(Path, "exists", lambda self: self == path)
    original_stat = Path.stat

    def _boom_stat(
        self: Path,
        *,
        follow_symlinks: bool = True,
    ) -> os.stat_result:
        if self == path:
            raise OSError("stat failed")
        try:
            return original_stat(self, follow_symlinks=follow_symlinks)
        except TypeError:
            return original_stat(self)

    monkeypatch.setattr(Path, "stat", _boom_stat)
    with pytest.raises(
        BaselineValidationError, match="Cannot stat metrics baseline file"
    ):
        baseline.load()


def test_metrics_baseline_save_requires_snapshot(tmp_path: Path) -> None:
    baseline = MetricsBaseline(tmp_path / "metrics-baseline.json")
    with pytest.raises(BaselineValidationError, match="snapshot is missing"):
        baseline.save()


def test_metrics_baseline_save_standalone_payload_sets_metadata(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    baseline = MetricsBaseline(path)
    baseline.snapshot = _snapshot()
    baseline.schema_version = mb_mod.METRICS_BASELINE_SCHEMA_VERSION
    baseline.python_tag = mb_mod.current_python_tag()
    baseline.generator_name = mb_mod.METRICS_BASELINE_GENERATOR
    baseline.generator_version = "2.0.0"
    baseline.created_at = "2026-03-06T00:00:00Z"
    baseline.save()

    payload = json.loads(path.read_text("utf-8"))
    assert set(payload.keys()) == {"meta", "metrics"}
    assert baseline.is_embedded_in_clone_baseline is False
    assert baseline.schema_version == mb_mod.METRICS_BASELINE_SCHEMA_VERSION
    assert baseline.python_tag == mb_mod.current_python_tag()
    assert baseline.created_at == "2026-03-06T00:00:00Z"
    assert isinstance(baseline.payload_sha256, str)


def test_metrics_baseline_save_writes_compact_api_surface_local_names(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    payload = _save_metrics_baseline_with_api_surface(
        path,
        api_surface=_api_surface_snapshot(include_added=True),
    )
    api_surface = cast(dict[str, object], payload["api_surface"])
    modules = cast(list[dict[str, object]], api_surface["modules"])
    symbols = cast(list[dict[str, object]], modules[0]["symbols"])

    assert "local_name" in symbols[0]
    assert "qualname" not in symbols[0]
    assert symbols[0]["local_name"] == "added"
    assert symbols[1]["local_name"] == "run"
    assert symbols[2]["local_name"] == "stable"


def test_metrics_baseline_save_relativizes_api_surface_filepaths(
    tmp_path: Path,
) -> None:
    path, absolute_filepath = _repo_metrics_baseline_path_and_abs_filepath(tmp_path)
    payload = _save_metrics_baseline_with_api_surface(
        path,
        api_surface=_api_surface_snapshot_with_filepath(absolute_filepath),
    )
    api_surface = cast(dict[str, object], payload["api_surface"])
    modules = cast(list[dict[str, object]], api_surface["modules"])
    assert modules[0]["filepath"] == "pkg/mod.py"

    reloaded = MetricsBaseline(path)
    reloaded.load()
    assert reloaded.api_surface_snapshot is not None
    assert reloaded.api_surface_snapshot.modules[0].filepath == absolute_filepath


def test_api_surface_payload_hashes_are_order_independent() -> None:
    symbols = _api_surface_snapshot(include_added=True).modules[0].symbols
    reordered = ApiSurfaceSnapshot(
        modules=(
            ModuleApiSurface(
                module="pkg.mod",
                filepath="pkg/mod.py",
                symbols=(symbols[2], symbols[0], symbols[1]),
            ),
        )
    )

    assert mb_payload._compute_api_surface_payload_sha256(
        reordered
    ) == mb_payload._compute_api_surface_payload_sha256(
        _api_surface_snapshot(include_added=True)
    )
    assert mb_payload._compute_legacy_api_surface_payload_sha256(
        reordered
    ) == mb_payload._compute_legacy_api_surface_payload_sha256(
        _api_surface_snapshot(include_added=True)
    )


def test_metrics_baseline_save_with_existing_plain_payload_rewrites_plain(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    _write_json(path, _valid_payload())
    baseline = MetricsBaseline(path)
    baseline.snapshot = _snapshot()
    baseline.save()
    payload = json.loads(path.read_text("utf-8"))
    assert "clones" not in payload
    assert baseline.is_embedded_in_clone_baseline is False


def test_metrics_baseline_atomic_write_json_cleans_up_temp_file_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    payload = _valid_payload()
    temp_holder: dict[str, Path] = {}

    def _boom_replace(src: str | Path, dst: str | Path) -> None:
        temp_holder["path"] = Path(src)
        raise OSError("replace failed")

    monkeypatch.setattr("codeclone.utils.json_io.os.replace", _boom_replace)

    with pytest.raises(OSError, match="replace failed"):
        mb_validate._atomic_write_json(path, payload)

    assert temp_holder["path"].exists() is False


def test_metrics_baseline_save_rejects_corrupted_existing_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    path.write_text("{broken", "utf-8")
    baseline = MetricsBaseline(path)
    baseline.snapshot = _snapshot()
    with pytest.raises(
        BaselineValidationError, match="Cannot read existing baseline file"
    ):
        baseline.save()


def test_metrics_baseline_verify_compatibility_and_integrity_failures(
    tmp_path: Path,
) -> None:
    baseline = _ready_metrics_baseline(
        tmp_path / "metrics-baseline.json",
        schema_version=mb_mod.METRICS_BASELINE_SCHEMA_VERSION,
        generator_name="other",
    )
    with pytest.raises(BaselineValidationError, match="generator mismatch"):
        baseline.verify_compatibility(runtime_python_tag=mb_mod.current_python_tag())

    baseline.generator_name = mb_mod.METRICS_BASELINE_GENERATOR
    baseline.schema_version = "9.9"
    with pytest.raises(BaselineValidationError, match="schema version mismatch"):
        baseline.verify_compatibility(runtime_python_tag=mb_mod.current_python_tag())

    baseline.schema_version = mb_mod.METRICS_BASELINE_SCHEMA_VERSION
    baseline.python_tag = "cp310"
    with pytest.raises(BaselineValidationError, match="python tag mismatch"):
        baseline.verify_compatibility(runtime_python_tag="cp313")

    baseline.python_tag = mb_mod.current_python_tag()
    baseline.snapshot = None
    with pytest.raises(BaselineValidationError, match="snapshot is missing"):
        baseline.verify_integrity()

    baseline.snapshot = _snapshot()
    baseline.payload_sha256 = None
    with pytest.raises(BaselineValidationError, match="payload hash is missing"):
        baseline.verify_integrity()

    baseline.payload_sha256 = "abc"
    with pytest.raises(BaselineValidationError, match="payload hash is missing"):
        baseline.verify_integrity()

    baseline.payload_sha256 = "a" * 64
    with pytest.raises(BaselineValidationError, match="integrity check failed"):
        baseline.verify_integrity()


def test_metrics_baseline_verify_accepts_previous_minor_versions(
    tmp_path: Path,
) -> None:
    standalone = _ready_metrics_baseline(
        tmp_path / "metrics-baseline.json",
        schema_version="1.1",
    )
    standalone.verify_compatibility(runtime_python_tag=mb_mod.current_python_tag())

    embedded = _ready_metrics_baseline(
        tmp_path / "codeclone.baseline.json",
        schema_version="2.0",
        embedded=True,
    )
    embedded.verify_compatibility(runtime_python_tag=mb_mod.current_python_tag())


def test_metrics_baseline_diff_without_snapshot_uses_default_snapshot(
    tmp_path: Path,
) -> None:
    baseline = MetricsBaseline(tmp_path / "metrics-baseline.json")
    diff = baseline.diff(_project_metrics())
    assert diff.new_high_risk_functions == ("pkg.mod:hot",)
    assert diff.new_high_coupling_classes == ("pkg.mod:Service",)
    assert diff.new_cycles == (("pkg.a", "pkg.b"),)
    assert diff.new_dead_code == ("pkg.mod:unused",)
    assert diff.health_delta == 70


def test_metrics_baseline_diff_tracks_adoption_and_api_surface_deltas(
    tmp_path: Path,
) -> None:
    baseline = MetricsBaseline.from_project_metrics(
        project_metrics=_project_metrics_with_adoption_and_api(
            typing_param_annotated=2,
            typing_return_annotated=1,
            docstring_public_documented=1,
            api_surface=_api_surface_snapshot(include_added=False),
        ),
        path=tmp_path / "metrics-baseline.json",
    )

    current = _project_metrics_with_adoption_and_api(
        typing_param_annotated=3,
        typing_return_annotated=2,
        docstring_public_documented=2,
        api_surface=ApiSurfaceSnapshot(
            modules=(
                ModuleApiSurface(
                    module="pkg.mod",
                    filepath="pkg/mod.py",
                    symbols=(
                        PublicSymbol(
                            qualname="pkg.mod:run",
                            kind="function",
                            start_line=10,
                            end_line=14,
                            params=(
                                ApiParamSpec(
                                    name="renamed",
                                    kind="pos_or_kw",
                                    has_default=False,
                                ),
                            ),
                        ),
                        PublicSymbol(
                            qualname="pkg.mod:added",
                            kind="function",
                            start_line=30,
                            end_line=32,
                        ),
                    ),
                ),
            )
        ),
    )

    diff = baseline.diff(current)
    assert diff.typing_param_permille_delta == 250
    assert diff.typing_return_permille_delta == 500
    assert diff.docstring_permille_delta == 334
    assert diff.new_api_symbols == ("pkg.mod:added",)
    assert [
        (item.qualname, item.change_kind) for item in diff.new_api_breaking_changes
    ] == [
        ("pkg.mod:run", "signature_break"),
        ("pkg.mod:stable", "removed"),
    ]


def test_snapshot_from_project_metrics_and_from_project_metrics_factory(
    tmp_path: Path,
) -> None:
    snapshot = mb_mod.snapshot_from_project_metrics(
        _project_metrics_with_adoption_and_api(
            api_surface=_api_surface_snapshot(include_added=False),
        )
    )
    assert snapshot.high_risk_functions == ("pkg.mod:hot",)
    assert snapshot.high_coupling_classes == ("pkg.mod:Service",)
    assert snapshot.low_cohesion_classes == ("pkg.mod:Service",)
    assert snapshot.dependency_cycles == (("pkg.a", "pkg.b"),)
    assert snapshot.dead_code_items == ("pkg.mod:unused",)
    assert snapshot.typing_param_permille == 750
    assert snapshot.typing_return_permille == 1000
    assert snapshot.docstring_permille == 667
    assert snapshot.typing_any_count == 1

    baseline = MetricsBaseline.from_project_metrics(
        project_metrics=_project_metrics_with_adoption_and_api(
            api_surface=_api_surface_snapshot(include_added=False),
        ),
        path=tmp_path / "metrics-baseline.json",
        generator_version="2.0.0",
    )
    assert baseline.generator_name == "codeclone"
    assert baseline.generator_version == "2.0.0"
    assert baseline.schema_version == mb_mod.METRICS_BASELINE_SCHEMA_VERSION
    assert baseline.snapshot is not None
    assert baseline.has_coverage_adoption_snapshot is True
    assert isinstance(baseline.payload_sha256, str)
    assert isinstance(baseline.api_surface_payload_sha256, str)
    assert baseline.api_surface_snapshot is not None


def test_metrics_baseline_load_tracks_adoption_snapshot_presence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    payload = _valid_payload()
    meta = cast(dict[str, object], payload["meta"])
    metrics = cast(dict[str, object], payload["metrics"])
    metrics.pop("typing_param_permille")
    metrics.pop("typing_return_permille")
    metrics.pop("docstring_permille")
    metrics.pop("typing_any_count")
    meta["payload_sha256"] = mb_payload._compute_payload_sha256(
        _snapshot(),
        include_adoption=False,
    )
    baseline = _load_written_metrics_baseline(path, payload)

    assert baseline.snapshot is not None
    assert baseline.has_coverage_adoption_snapshot is False
    baseline.verify_integrity()


def test_metrics_baseline_from_project_metrics_can_omit_optional_surfaces(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    baseline = MetricsBaseline.from_project_metrics(
        project_metrics=_project_metrics_with_adoption_and_api(
            api_surface=_api_surface_snapshot(include_added=True),
        ),
        path=path,
        include_adoption=False,
        include_api_surface=False,
    )

    assert baseline.has_coverage_adoption_snapshot is False
    assert baseline.api_surface_snapshot is None
    assert baseline.api_surface_payload_sha256 is None

    baseline.save()

    payload = json.loads(path.read_text("utf-8"))
    meta = cast(dict[str, object], payload["meta"])
    metrics = cast(dict[str, object], payload["metrics"])
    assert_missing_keys(
        metrics,
        "typing_param_permille",
        "typing_return_permille",
        "docstring_permille",
        "typing_any_count",
    )
    assert_missing_keys(payload, "api_surface")
    assert_missing_keys(meta, "api_surface_payload_sha256")

    reloaded = MetricsBaseline(path)
    reloaded.load()
    _assert_metrics_baseline_reload_state(
        reloaded,
        embedded=False,
        has_adoption=False,
        has_api_surface=False,
    )
    reloaded.verify_integrity()


def test_metrics_baseline_save_embedded_clone_baseline_preserves_api_surface(
    tmp_path: Path,
) -> None:
    path = tmp_path / "codeclone.baseline.json"
    baseline_mod.Baseline.from_groups({}, {}, path=path).save()

    baseline = MetricsBaseline.from_project_metrics(
        project_metrics=_project_metrics_with_adoption_and_api(
            api_surface=_api_surface_snapshot(include_added=True),
        ),
        path=path,
    )
    baseline.save()

    payload = json.loads(path.read_text("utf-8"))
    meta = cast(dict[str, object], payload["meta"])
    assert "api_surface" in payload
    assert "api_surface_payload_sha256" in meta

    reloaded = MetricsBaseline(path)
    reloaded.load()
    _assert_metrics_baseline_reload_state(
        reloaded,
        embedded=True,
        has_adoption=True,
        has_api_surface=True,
    )


def test_metrics_baseline_load_accepts_legacy_api_surface_qualnames(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"
    snapshot = _snapshot()
    api_surface_snapshot = _api_surface_snapshot(include_added=True)
    payload = mb_payload._build_payload(
        snapshot=snapshot,
        schema_version=mb_mod.METRICS_BASELINE_SCHEMA_VERSION,
        python_tag=mb_mod.current_python_tag(),
        generator_name=mb_mod.METRICS_BASELINE_GENERATOR,
        generator_version="2.0.0",
        created_at="2026-03-06T00:00:00Z",
        api_surface_snapshot=api_surface_snapshot,
    )
    api_surface = cast(dict[str, object], payload["api_surface"])
    modules = cast(list[dict[str, object]], api_surface["modules"])
    symbols = cast(list[dict[str, object]], modules[0]["symbols"])
    for symbol in symbols:
        local_name = cast(str, symbol.pop("local_name"))
        symbol["qualname"] = f"pkg.mod:{local_name}"
    meta = cast(dict[str, object], payload["meta"])
    meta["api_surface_payload_sha256"] = (
        mb_payload._compute_legacy_api_surface_payload_sha256(
            api_surface_snapshot,
            root=path.parent,
        )
    )
    baseline = _load_written_metrics_baseline(path, payload)

    assert baseline.api_surface_snapshot is not None
    assert [
        item.qualname for item in baseline.api_surface_snapshot.modules[0].symbols
    ] == [
        "pkg.mod:added",
        "pkg.mod:run",
        "pkg.mod:stable",
    ]
    baseline.verify_integrity()


def test_metrics_baseline_load_accepts_absolute_api_surface_filepaths(
    tmp_path: Path,
) -> None:
    path, absolute_filepath = _repo_metrics_baseline_path_and_abs_filepath(tmp_path)
    snapshot = _snapshot()
    api_surface_snapshot = _api_surface_snapshot_with_filepath(absolute_filepath)
    payload = mb_payload._build_payload(
        snapshot=snapshot,
        schema_version=mb_mod.METRICS_BASELINE_SCHEMA_VERSION,
        python_tag=mb_mod.current_python_tag(),
        generator_name=mb_mod.METRICS_BASELINE_GENERATOR,
        generator_version="2.0.0",
        created_at="2026-03-06T00:00:00Z",
        api_surface_snapshot=api_surface_snapshot,
        api_surface_root=path.parent,
    )
    api_surface = cast(dict[str, object], payload["api_surface"])
    modules = cast(list[dict[str, object]], api_surface["modules"])
    modules[0]["filepath"] = absolute_filepath
    meta = cast(dict[str, object], payload["meta"])
    meta["api_surface_payload_sha256"] = mb_payload._compute_api_surface_payload_sha256(
        api_surface_snapshot
    )
    baseline = _load_written_metrics_baseline(path, payload)

    assert baseline.api_surface_snapshot is not None
    assert baseline.api_surface_snapshot.modules[0].filepath == absolute_filepath
    baseline.verify_integrity()


def test_metrics_baseline_json_and_structure_validators(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    path.write_text("[]", "utf-8")
    with pytest.raises(BaselineValidationError, match="must be an object"):
        mb_validate._load_json_object(path)

    mb_validate._validate_top_level_structure(_valid_payload(), path=path)
    with pytest.raises(BaselineValidationError, match="unexpected top-level keys"):
        mb_validate._validate_top_level_structure(
            {**_valid_payload(), "extra": 1},
            path=path,
        )
    with pytest.raises(BaselineValidationError, match="missing required fields"):
        mb_validate._validate_required_keys(
            {"only": "one"}, frozenset({"required"}), path=path
        )
    with pytest.raises(BaselineValidationError, match="unexpected fields"):
        mb_validate._validate_exact_keys(
            {"a": 1, "b": 2},
            frozenset({"a"}),
            path=path,
        )


def test_metrics_baseline_field_parsers_and_cycle_parser(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"

    with pytest.raises(BaselineValidationError, match="'name' must be str"):
        mb_validate._require_str({"name": 1}, "name", path=path)
    assert (
        mb_validate._extract_metrics_payload_sha256(
            {"payload_sha256": "x"},
            path=path,
        )
        == "x"
    )
    assert (
        mb_validate._extract_metrics_payload_sha256(
            {"metrics_payload_sha256": "y", "payload_sha256": "x"},
            path=path,
        )
        == "y"
    )

    with pytest.raises(BaselineValidationError, match="must be int"):
        mb_validate._require_int({"value": True}, "value", path=path)
    with pytest.raises(BaselineValidationError, match="must be int"):
        mb_validate._require_int({"value": "1"}, "value", path=path)

    with pytest.raises(BaselineValidationError, match="must be list\\[str\\]"):
        mb_validate._require_str_list({"items": "bad"}, "items", path=path)
    with pytest.raises(BaselineValidationError, match="must be list\\[str\\]"):
        mb_validate._require_str_list({"items": [1]}, "items", path=path)

    with pytest.raises(BaselineValidationError, match="must be list"):
        mb_validate._parse_cycles(
            {"dependency_cycles": "bad"}, key="dependency_cycles", path=path
        )
    with pytest.raises(
        BaselineValidationError, match="cycle item must be list\\[str\\]"
    ):
        mb_validate._parse_cycles(
            {"dependency_cycles": ["bad"]},
            key="dependency_cycles",
            path=path,
        )
    with pytest.raises(
        BaselineValidationError, match="cycle item must be list\\[str\\]"
    ):
        mb_validate._parse_cycles(
            {"dependency_cycles": [[1]]},
            key="dependency_cycles",
            path=path,
        )
    assert mb_validate._parse_cycles(
        {"dependency_cycles": [["b", "a"], ["a", "b"], ["b", "a"]]},
        key="dependency_cycles",
        path=path,
    ) == (("a", "b"), ("b", "a"))


def test_metrics_baseline_parse_generator_variants(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    assert mb_validate._parse_generator({"generator": "codeclone"}, path=path) == (
        "codeclone",
        None,
    )
    assert mb_validate._parse_generator(
        {"generator": "codeclone", "codeclone_version": "1.0.0"},
        path=path,
    ) == ("codeclone", "1.0.0")
    with pytest.raises(BaselineValidationError, match="generator_version must be str"):
        mb_validate._parse_generator(
            {"generator": "codeclone", "generator_version": 1},
            path=path,
        )

    assert mb_validate._parse_generator(
        {"generator": {"name": "codeclone", "version": "2.0.0"}},
        path=path,
    ) == ("codeclone", "2.0.0")
    with pytest.raises(BaselineValidationError, match="unexpected generator keys"):
        mb_validate._parse_generator(
            {"generator": {"name": "codeclone", "extra": 1}},
            path=path,
        )
    with pytest.raises(BaselineValidationError, match=r"generator\.name must be str"):
        mb_validate._parse_generator(
            {"generator": {"name": 1, "version": "2.0.0"}},
            path=path,
        )
    with pytest.raises(
        BaselineValidationError,
        match=r"generator\.version must be str",
    ):
        mb_validate._parse_generator(
            {"generator": {"name": "codeclone", "version": 2}},
            path=path,
        )
    with pytest.raises(
        BaselineValidationError, match="generator must be object or str"
    ):
        mb_validate._parse_generator({"generator": 1}, path=path)


def test_metrics_baseline_embedded_clone_payload_and_schema_resolution(
    tmp_path: Path,
) -> None:
    path = tmp_path / "baseline.json"
    valid_embedded = {
        "meta": {
            "generator": {"name": "codeclone", "version": "2.0.0"},
            "schema_version": "1.0",
            "python_tag": mb_mod.current_python_tag(),
            "created_at": "2026-03-06T00:00:00Z",
            "payload_sha256": "a" * 64,
        },
        "clones": {
            "functions": ["a" * 40 + "|0-19"],
            "blocks": ["|".join(["a" * 40, "b" * 40, "c" * 40, "d" * 40])],
        },
    }
    meta_obj, clones_obj = mb_validate._require_embedded_clone_baseline_payload(
        valid_embedded, path=path
    )
    assert "schema_version" in meta_obj
    assert "functions" in clones_obj
    assert (
        mb_validate._resolve_embedded_schema_version(meta_obj, path=path)
        == mb_mod.BASELINE_SCHEMA_VERSION
    )
    assert (
        mb_validate._resolve_embedded_schema_version(
            {**meta_obj, "schema_version": "2.1"},
            path=path,
        )
        == "2.1"
    )

    with pytest.raises(BaselineValidationError, match="'meta' must be object"):
        mb_validate._require_embedded_clone_baseline_payload(
            {"meta": [], "clones": {}},
            path=path,
        )
    with pytest.raises(BaselineValidationError, match="'clones' must be object"):
        mb_validate._require_embedded_clone_baseline_payload(
            {"meta": {}, "clones": []},
            path=path,
        )
    with pytest.raises(
        BaselineValidationError,
        match=r"'clones\.functions' must be list\[str\]",
    ):
        mb_validate._require_embedded_clone_baseline_payload(
            {
                "meta": valid_embedded["meta"],
                "clones": {"functions": [1], "blocks": []},
            },
            path=path,
        )
    with pytest.raises(
        BaselineValidationError,
        match=r"'clones\.blocks' must be list\[str\]",
    ):
        mb_validate._require_embedded_clone_baseline_payload(
            {
                "meta": valid_embedded["meta"],
                "clones": {"functions": [], "blocks": [1]},
            },
            path=path,
        )
    with pytest.raises(BaselineValidationError, match="must be semver string"):
        mb_validate._resolve_embedded_schema_version(
            {**meta_obj, "schema_version": "broken"},
            path=path,
        )


def test_metrics_baseline_parse_snapshot_grade_validation(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    payload = mb_payload._snapshot_payload(_snapshot())
    payload["health_grade"] = "Z"
    with pytest.raises(BaselineValidationError, match="must be one of A/B/C/D/F"):
        mb_validate._parse_snapshot(payload, path=path)


def test_metrics_baseline_version_and_optional_string_helpers(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"

    assert (
        mb_validate._is_compatible_metrics_schema(
            baseline_version="1.1",
            expected_version="1.2",
        )
        is True
    )
    assert (
        mb_validate._is_compatible_metrics_schema(
            baseline_version=None,
            expected_version="1.2",
        )
        is False
    )
    assert (
        mb_validate._is_compatible_metrics_schema(
            baseline_version="broken",
            expected_version="1.2",
        )
        is False
    )
    assert mb_validate._parse_major_minor("1") is None
    assert mb_validate._parse_major_minor("1.x") is None
    assert mb_validate._require_str_list_or_none({}, "missing", path=path) is None

    with pytest.raises(BaselineValidationError, match="'qualname' must be str"):
        mb_validate._optional_require_str({"qualname": 1}, "qualname", path=path)


def test_metrics_baseline_enum_validation_helpers_cover_all_supported_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"

    for grade in ("A", "B", "C", "D", "F"):
        assert mb_validate._require_health_grade(grade, path=path) == grade
    with pytest.raises(BaselineValidationError, match="must be one of A/B/C/D/F"):
        mb_validate._require_health_grade("Z", path=path)

    for kind in ("pos_only", "pos_or_kw", "vararg", "kw_only", "kwarg"):
        assert mb_validate._require_api_param_kind(kind, path=path) == kind
    with pytest.raises(BaselineValidationError, match="api param 'kind' is invalid"):
        mb_validate._require_api_param_kind("bad", path=path)

    for kind in ("function", "class", "method", "constant"):
        assert mb_validate._require_public_symbol_kind(kind, path=path) == kind
    with pytest.raises(
        BaselineValidationError,
        match="public symbol 'kind' is invalid",
    ):
        mb_validate._require_public_symbol_kind("bad", path=path)

    assert mb_validate._require_exported_via("all", path=path) == "all"
    assert mb_validate._require_exported_via("name", path=path) == "name"
    with pytest.raises(
        BaselineValidationError,
        match="public symbol 'exported_via' is invalid",
    ):
        mb_validate._require_exported_via("bad", path=path)


def test_metrics_baseline_parse_api_surface_snapshot_validation_edges(
    tmp_path: Path,
) -> None:
    path = tmp_path / "metrics-baseline.json"

    with pytest.raises(BaselineValidationError, match="'api_surface' must be object"):
        mb_validate._parse_api_surface_snapshot([], path=path)

    with pytest.raises(
        BaselineValidationError,
        match=r"'api_surface\.modules' must be list",
    ):
        mb_validate._parse_api_surface_snapshot({"modules": "bad"}, path=path)

    with pytest.raises(
        BaselineValidationError, match="api surface module must be object"
    ):
        mb_validate._parse_api_surface_snapshot({"modules": ["bad"]}, path=path)

    with pytest.raises(
        BaselineValidationError, match="api surface symbols must be list"
    ):
        mb_validate._parse_api_surface_snapshot(
            {
                "modules": [
                    {
                        "module": "pkg.mod",
                        "filepath": "pkg/mod.py",
                        "symbols": "bad",
                    }
                ]
            },
            path=path,
        )

    with pytest.raises(
        BaselineValidationError, match="api surface symbol must be object"
    ):
        mb_validate._parse_api_surface_snapshot(
            {
                "modules": [
                    {
                        "module": "pkg.mod",
                        "filepath": "pkg/mod.py",
                        "symbols": ["bad"],
                    }
                ]
            },
            path=path,
        )

    with pytest.raises(
        BaselineValidationError,
        match="api surface symbol requires 'local_name' or 'qualname'",
    ):
        mb_validate._parse_api_surface_snapshot(
            {
                "modules": [
                    {
                        "module": "pkg.mod",
                        "filepath": "pkg/mod.py",
                        "symbols": [{"kind": "function", "exported_via": "name"}],
                    }
                ]
            },
            path=path,
        )

    with pytest.raises(
        BaselineValidationError, match="api surface params must be list"
    ):
        mb_validate._parse_api_surface_snapshot(
            {
                "modules": [
                    {
                        "module": "pkg.mod",
                        "filepath": "pkg/mod.py",
                        "symbols": [
                            {
                                "local_name": "run",
                                "kind": "function",
                                "exported_via": "name",
                                "params": "bad",
                            }
                        ],
                    }
                ]
            },
            path=path,
        )

    with pytest.raises(BaselineValidationError, match="api param must be object"):
        mb_validate._parse_api_surface_snapshot(
            {
                "modules": [
                    {
                        "module": "pkg.mod",
                        "filepath": "pkg/mod.py",
                        "symbols": [
                            {
                                "local_name": "run",
                                "kind": "function",
                                "exported_via": "name",
                                "params": ["bad"],
                            }
                        ],
                    }
                ]
            },
            path=path,
        )

    with pytest.raises(
        BaselineValidationError, match="api param 'has_default' must be bool"
    ):
        mb_validate._parse_api_surface_snapshot(
            {
                "modules": [
                    {
                        "module": "pkg.mod",
                        "filepath": "pkg/mod.py",
                        "symbols": [
                            {
                                "local_name": "run",
                                "kind": "function",
                                "exported_via": "name",
                                "params": [
                                    {
                                        "name": "value",
                                        "kind": "pos_or_kw",
                                        "has_default": "bad",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
            path=path,
        )


def test_metrics_baseline_load_json_read_oserror_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "metrics-baseline.json"
    path.write_text("{}", "utf-8")

    def _boom_read(_self: Path, _encoding: str) -> str:
        raise OSError("read failed")

    monkeypatch.setattr(Path, "read_text", _boom_read)
    with pytest.raises(
        BaselineValidationError, match="Cannot read metrics baseline file"
    ):
        mb_validate._load_json_object(path)
