from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import codeclone.metrics_baseline as mb_mod
from codeclone.errors import BaselineValidationError
from codeclone.metrics_baseline import MetricsBaseline, MetricsBaselineStatus
from codeclone.models import (
    DeadItem,
    HealthScore,
    MetricsSnapshot,
    ProjectMetrics,
)


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


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), "utf-8")


def _valid_payload(
    *,
    schema_version: str = mb_mod.METRICS_BASELINE_SCHEMA_VERSION,
    python_tag: str | None = None,
) -> dict[str, object]:
    return mb_mod._build_payload(
        snapshot=_snapshot(),
        schema_version=schema_version,
        python_tag=python_tag or mb_mod.current_python_tag(),
        generator_name=mb_mod.METRICS_BASELINE_GENERATOR,
        generator_version="2.0.0",
        created_at="2026-03-06T00:00:00Z",
    )


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
    baseline = MetricsBaseline(tmp_path / "metrics-baseline.json")
    baseline.snapshot = _snapshot()
    baseline.payload_sha256 = mb_mod._compute_payload_sha256(_snapshot())
    baseline.generator_name = "other"
    baseline.schema_version = mb_mod.METRICS_BASELINE_SCHEMA_VERSION
    baseline.python_tag = mb_mod.current_python_tag()
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


def test_snapshot_from_project_metrics_and_from_project_metrics_factory(
    tmp_path: Path,
) -> None:
    snapshot = mb_mod.snapshot_from_project_metrics(_project_metrics())
    assert snapshot.high_risk_functions == ("pkg.mod:hot",)
    assert snapshot.high_coupling_classes == ("pkg.mod:Service",)
    assert snapshot.low_cohesion_classes == ("pkg.mod:Service",)
    assert snapshot.dependency_cycles == (("pkg.a", "pkg.b"),)
    assert snapshot.dead_code_items == ("pkg.mod:unused",)

    baseline = MetricsBaseline.from_project_metrics(
        project_metrics=_project_metrics(),
        path=tmp_path / "metrics-baseline.json",
        generator_version="2.0.0",
    )
    assert baseline.generator_name == "codeclone"
    assert baseline.generator_version == "2.0.0"
    assert baseline.schema_version == mb_mod.METRICS_BASELINE_SCHEMA_VERSION
    assert baseline.snapshot is not None
    assert isinstance(baseline.payload_sha256, str)


def test_metrics_baseline_json_and_structure_validators(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    path.write_text("[]", "utf-8")
    with pytest.raises(BaselineValidationError, match="must be an object"):
        mb_mod._load_json_object(path)

    mb_mod._validate_top_level_structure(_valid_payload(), path=path)
    with pytest.raises(BaselineValidationError, match="unexpected top-level keys"):
        mb_mod._validate_top_level_structure(
            {**_valid_payload(), "extra": 1},
            path=path,
        )
    with pytest.raises(BaselineValidationError, match="missing required fields"):
        mb_mod._validate_required_keys(
            {"only": "one"}, frozenset({"required"}), path=path
        )
    with pytest.raises(BaselineValidationError, match="unexpected fields"):
        mb_mod._validate_exact_keys({"a": 1, "b": 2}, frozenset({"a"}), path=path)


def test_metrics_baseline_field_parsers_and_cycle_parser(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"

    with pytest.raises(BaselineValidationError, match="'name' must be str"):
        mb_mod._require_str({"name": 1}, "name", path=path)
    assert (
        mb_mod._extract_metrics_payload_sha256({"payload_sha256": "x"}, path=path)
        == "x"
    )
    assert (
        mb_mod._extract_metrics_payload_sha256(
            {"metrics_payload_sha256": "y", "payload_sha256": "x"},
            path=path,
        )
        == "y"
    )

    with pytest.raises(BaselineValidationError, match="must be int"):
        mb_mod._require_int({"value": True}, "value", path=path)
    with pytest.raises(BaselineValidationError, match="must be int"):
        mb_mod._require_int({"value": "1"}, "value", path=path)

    with pytest.raises(BaselineValidationError, match="must be list\\[str\\]"):
        mb_mod._require_str_list({"items": "bad"}, "items", path=path)
    with pytest.raises(BaselineValidationError, match="must be list\\[str\\]"):
        mb_mod._require_str_list({"items": [1]}, "items", path=path)

    with pytest.raises(BaselineValidationError, match="must be list"):
        mb_mod._parse_cycles(
            {"dependency_cycles": "bad"}, key="dependency_cycles", path=path
        )
    with pytest.raises(
        BaselineValidationError, match="cycle item must be list\\[str\\]"
    ):
        mb_mod._parse_cycles(
            {"dependency_cycles": ["bad"]},
            key="dependency_cycles",
            path=path,
        )
    with pytest.raises(
        BaselineValidationError, match="cycle item must be list\\[str\\]"
    ):
        mb_mod._parse_cycles(
            {"dependency_cycles": [[1]]},
            key="dependency_cycles",
            path=path,
        )
    assert mb_mod._parse_cycles(
        {"dependency_cycles": [["b", "a"], ["a", "b"], ["b", "a"]]},
        key="dependency_cycles",
        path=path,
    ) == (("a", "b"), ("b", "a"))


def test_metrics_baseline_parse_generator_variants(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    assert mb_mod._parse_generator({"generator": "codeclone"}, path=path) == (
        "codeclone",
        None,
    )
    assert mb_mod._parse_generator(
        {"generator": "codeclone", "codeclone_version": "1.0.0"},
        path=path,
    ) == ("codeclone", "1.0.0")
    with pytest.raises(BaselineValidationError, match="generator_version must be str"):
        mb_mod._parse_generator(
            {"generator": "codeclone", "generator_version": 1},
            path=path,
        )

    assert mb_mod._parse_generator(
        {"generator": {"name": "codeclone", "version": "2.0.0"}},
        path=path,
    ) == ("codeclone", "2.0.0")
    with pytest.raises(BaselineValidationError, match="unexpected generator keys"):
        mb_mod._parse_generator(
            {"generator": {"name": "codeclone", "extra": 1}},
            path=path,
        )
    with pytest.raises(BaselineValidationError, match=r"generator\.name must be str"):
        mb_mod._parse_generator(
            {"generator": {"name": 1, "version": "2.0.0"}},
            path=path,
        )
    with pytest.raises(
        BaselineValidationError,
        match=r"generator\.version must be str",
    ):
        mb_mod._parse_generator(
            {"generator": {"name": "codeclone", "version": 2}},
            path=path,
        )
    with pytest.raises(
        BaselineValidationError, match="generator must be object or str"
    ):
        mb_mod._parse_generator({"generator": 1}, path=path)


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
    meta_obj, clones_obj = mb_mod._require_embedded_clone_baseline_payload(
        valid_embedded, path=path
    )
    assert "schema_version" in meta_obj
    assert "functions" in clones_obj
    assert (
        mb_mod._resolve_embedded_schema_version(meta_obj, path=path)
        == mb_mod.BASELINE_SCHEMA_VERSION
    )
    assert (
        mb_mod._resolve_embedded_schema_version(
            {**meta_obj, "schema_version": "2.1"},
            path=path,
        )
        == "2.1"
    )

    with pytest.raises(BaselineValidationError, match="'meta' must be object"):
        mb_mod._require_embedded_clone_baseline_payload(
            {"meta": [], "clones": {}},
            path=path,
        )
    with pytest.raises(BaselineValidationError, match="'clones' must be object"):
        mb_mod._require_embedded_clone_baseline_payload(
            {"meta": {}, "clones": []},
            path=path,
        )
    with pytest.raises(
        BaselineValidationError,
        match=r"'clones\.functions' must be list\[str\]",
    ):
        mb_mod._require_embedded_clone_baseline_payload(
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
        mb_mod._require_embedded_clone_baseline_payload(
            {
                "meta": valid_embedded["meta"],
                "clones": {"functions": [], "blocks": [1]},
            },
            path=path,
        )
    with pytest.raises(BaselineValidationError, match="must be semver string"):
        mb_mod._resolve_embedded_schema_version(
            {**meta_obj, "schema_version": "broken"},
            path=path,
        )


def test_metrics_baseline_parse_snapshot_grade_validation(tmp_path: Path) -> None:
    path = tmp_path / "metrics-baseline.json"
    payload = mb_mod._snapshot_payload(_snapshot())
    payload["health_grade"] = "Z"
    with pytest.raises(BaselineValidationError, match="must be one of A/B/C/D/F"):
        mb_mod._parse_snapshot(payload, path=path)


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
        mb_mod._load_json_object(path)
