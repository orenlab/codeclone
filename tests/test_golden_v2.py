from __future__ import annotations

import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import pytest

import codeclone.pipeline as pipeline
from codeclone import cli
from codeclone.baseline import current_python_tag
from codeclone.extractor import extract_units_and_stats_from_source
from codeclone.grouping import build_block_groups, build_groups, build_segment_groups
from codeclone.models import ClassMetrics, DeadCandidate, ModuleDep
from codeclone.normalize import NormalizationConfig
from codeclone.pipeline import compute_project_metrics
from codeclone.scanner import iter_py_files, module_name_from_path
from codeclone.structural_findings import build_clone_cohort_structural_findings

_GOLDEN_V2_ROOT = Path("tests/fixtures/golden_v2").resolve()


@dataclass(slots=True)
class _DummyFuture:
    value: object

    def result(self) -> object:
        return self.value


class _DummyExecutor:
    def __init__(self, max_workers: int | None = None) -> None:
        self.max_workers = max_workers

    def __enter__(self) -> _DummyExecutor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> Literal[False]:
        return False

    def submit(
        self,
        fn: object,
        *args: object,
        **kwargs: object,
    ) -> _DummyFuture:
        assert callable(fn)
        return _DummyFuture(fn(*args, **kwargs))


def _patch_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", _DummyExecutor)
    monkeypatch.setattr(pipeline, "as_completed", lambda futures: futures)


def _relative_to_root(path: str, root: Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return str(candidate).replace("\\", "/")
    return str(candidate.resolve().relative_to(root))


def _collect_analysis_snapshot(project_root: Path) -> dict[str, object]:
    cfg = NormalizationConfig()
    units: list[dict[str, object]] = []
    blocks: list[dict[str, object]] = []
    segments: list[dict[str, object]] = []
    class_metrics: list[ClassMetrics] = []
    module_deps: list[ModuleDep] = []
    dead_candidates: list[DeadCandidate] = []
    referenced_names: set[str] = set()
    referenced_qualnames: set[str] = set()

    files = tuple(iter_py_files(str(project_root)))
    lines_total = 0
    functions_total = 0
    methods_total = 0
    classes_total = 0

    for filepath in files:
        source = Path(filepath).read_text("utf-8")
        module_name = module_name_from_path(str(project_root), filepath)
        relative_filepath = str(Path(filepath).resolve().relative_to(project_root))
        (
            file_units,
            file_blocks,
            file_segments,
            source_stats,
            file_metrics,
            _sf,
        ) = extract_units_and_stats_from_source(
            source=source,
            filepath=relative_filepath,
            module_name=module_name,
            cfg=cfg,
            min_loc=1,
            min_stmt=1,
        )
        units.extend(asdict(unit) for unit in file_units)
        blocks.extend(asdict(block) for block in file_blocks)
        segments.extend(asdict(segment) for segment in file_segments)
        class_metrics.extend(file_metrics.class_metrics)
        module_deps.extend(file_metrics.module_deps)
        dead_candidates.extend(file_metrics.dead_candidates)
        referenced_names.update(file_metrics.referenced_names)
        referenced_qualnames.update(file_metrics.referenced_qualnames)

        lines_total += source_stats.lines
        functions_total += source_stats.functions
        methods_total += source_stats.methods
        classes_total += source_stats.classes

    function_groups = build_groups(units)
    block_groups = build_block_groups(blocks)
    segment_groups = build_segment_groups(segments)
    cohort_structural_groups = build_clone_cohort_structural_findings(
        func_groups=function_groups,
    )

    project_metrics, dep_graph, dead_items = compute_project_metrics(
        units=tuple(units),
        class_metrics=tuple(class_metrics),
        module_deps=tuple(module_deps),
        dead_candidates=tuple(dead_candidates),
        referenced_names=frozenset(referenced_names),
        referenced_qualnames=frozenset(referenced_qualnames),
        files_found=len(files),
        files_analyzed_or_cached=len(files),
        function_clone_groups=len(function_groups),
        block_clone_groups=len(block_groups),
        skip_dependencies=False,
        skip_dead_code=False,
    )
    guarded_functions = 0
    for unit in units:
        guard_count = unit.get("entry_guard_count", 0)
        if isinstance(guard_count, bool):
            guard_count = int(guard_count)
        if isinstance(guard_count, int) and guard_count > 0:
            guarded_functions += 1

    return {
        "meta": {"python_tag": current_python_tag()},
        "files": {
            "count": len(files),
            "lines": lines_total,
            "functions": functions_total,
            "methods": methods_total,
            "classes": classes_total,
        },
        "groups": {
            "function_keys": sorted(function_groups.keys()),
            "block_keys": sorted(block_groups.keys()),
            "segment_keys": sorted(segment_groups.keys()),
        },
        "stable_structure": {
            "terminal_kinds": sorted({str(unit["terminal_kind"]) for unit in units}),
            "guard_terminal_profiles": sorted(
                {str(unit["entry_guard_terminal_profile"]) for unit in units},
            ),
            "try_finally_profiles": sorted(
                {str(unit["try_finally_profile"]) for unit in units},
            ),
            "side_effect_order_profiles": sorted(
                {str(unit["side_effect_order_profile"]) for unit in units},
            ),
            "guarded_functions": guarded_functions,
        },
        "cohort_structural_findings": {
            "count": len(cohort_structural_groups),
            "kinds": [
                group.finding_kind
                for group in sorted(
                    cohort_structural_groups,
                    key=lambda group: (group.finding_kind, group.finding_key),
                )
            ],
            "keys": [
                group.finding_key
                for group in sorted(
                    cohort_structural_groups,
                    key=lambda group: (group.finding_kind, group.finding_key),
                )
            ],
        },
        "metrics": {
            "complexity_max": project_metrics.complexity_max,
            "high_risk_functions": list(project_metrics.high_risk_functions),
            "coupling_max": project_metrics.coupling_max,
            "high_risk_classes": list(project_metrics.high_risk_classes),
            "cohesion_max": project_metrics.cohesion_max,
            "low_cohesion_classes": list(project_metrics.low_cohesion_classes),
            "dependency_cycles": [list(cycle) for cycle in dep_graph.cycles],
            "dependency_max_depth": dep_graph.max_depth,
            "dead_items": [
                {
                    "qualname": item.qualname,
                    "filepath": _relative_to_root(item.filepath, project_root),
                    "kind": item.kind,
                    "confidence": item.confidence,
                }
                for item in dead_items
            ],
            "health": {
                "total": project_metrics.health.total,
                "grade": project_metrics.health.grade,
            },
        },
    }


@pytest.mark.parametrize(
    "fixture_name",
    ("test_only_usage", "clone_metrics_cycle"),
)
def test_golden_v2_analysis_contracts(fixture_name: str) -> None:
    fixture_root = _GOLDEN_V2_ROOT / fixture_name
    expected_path = fixture_root / "golden_expected_snapshot.json"
    expected = json.loads(expected_path.read_text("utf-8"))

    expected_meta = expected.get("meta", {})
    assert isinstance(expected_meta, dict)
    expected_python_tag = expected_meta.get("python_tag")
    assert isinstance(expected_python_tag, str)

    runtime_tag = current_python_tag()
    if runtime_tag != expected_python_tag:
        pytest.skip(
            "Golden detector fixture is canonicalized for "
            f"{expected_python_tag}; runtime is {runtime_tag}."
        )

    snapshot = _collect_analysis_snapshot(fixture_root)
    assert snapshot == expected


def _run_cli(args: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    _patch_parallel(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["codeclone", *args])
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        if code is None:
            return 0
        try:
            return int(code)
        except (TypeError, ValueError):
            return 1
    return 0


def _collect_cli_snapshot(
    *,
    fixture_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    project_root = tmp_path / fixture_root.name
    shutil.copytree(fixture_root, project_root)
    report_path = project_root / "report.json"
    baseline_path = project_root / "codeclone.baseline.json"
    cache_path = project_root / ".cache" / "codeclone" / "cache.json"

    exit_code = _run_cli(
        [
            str(project_root),
            "--json",
            str(report_path),
            "--baseline",
            str(baseline_path),
            "--metrics-baseline",
            str(baseline_path),
            "--cache-path",
            str(cache_path),
            "--no-progress",
            "--quiet",
        ],
        monkeypatch,
    )
    assert exit_code == 0

    payload = json.loads(report_path.read_text("utf-8"))
    meta = payload["meta"]
    findings = payload["findings"]
    clone_groups = findings["groups"]["clones"]
    structural_groups = findings["groups"]["structural"]["groups"]
    return {
        "meta": {"python_tag": current_python_tag()},
        "report_schema_version": payload["report_schema_version"],
        "project_name": meta["project_name"],
        "scan_root": meta["scan_root"],
        "baseline_status": meta["baseline"]["status"],
        "baseline_loaded": meta["baseline"]["loaded"],
        "cache_used": meta["cache"]["used"],
        "findings_summary": findings["summary"],
        "function_group_ids": [group["id"] for group in clone_groups["functions"]],
        "block_group_ids": [group["id"] for group in clone_groups["blocks"]],
        "segment_group_ids": [group["id"] for group in clone_groups["segments"]],
        "structural_group_ids": [group["id"] for group in structural_groups],
        "structural_group_kinds": [group["kind"] for group in structural_groups],
    }


def test_golden_v2_cli_pyproject_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_root = _GOLDEN_V2_ROOT / "pyproject_defaults"
    expected_path = fixture_root / "golden_expected_cli_snapshot.json"
    expected = json.loads(expected_path.read_text("utf-8"))

    expected_meta = expected.get("meta", {})
    assert isinstance(expected_meta, dict)
    expected_python_tag = expected_meta.get("python_tag")
    assert isinstance(expected_python_tag, str)

    runtime_tag = current_python_tag()
    if runtime_tag != expected_python_tag:
        pytest.skip(
            "Golden detector fixture is canonicalized for "
            f"{expected_python_tag}; runtime is {runtime_tag}."
        )

    snapshot = _collect_cli_snapshot(
        fixture_root=fixture_root,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    assert snapshot == expected
