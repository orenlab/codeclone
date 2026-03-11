from __future__ import annotations

from codeclone.models import (
    ClassMetrics,
    DeadItem,
    HealthScore,
    ProjectMetrics,
)
from codeclone.report import suggestions as suggestions_mod
from codeclone.report.suggestions import classify_clone_type, generate_suggestions


def _project_metrics() -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=3.5,
        complexity_max=50,
        high_risk_functions=("pkg.mod:critical",),
        coupling_avg=4.0,
        coupling_max=15,
        high_risk_classes=("pkg.mod:Service",),
        cohesion_avg=2.0,
        cohesion_max=5,
        low_cohesion_classes=("pkg.mod:Service",),
        dependency_modules=3,
        dependency_edges=2,
        dependency_edge_list=(),
        dependency_cycles=(("pkg.a", "pkg.b"),),
        dependency_max_depth=4,
        dependency_longest_chains=(("pkg.a", "pkg.b"),),
        dead_code=(
            DeadItem(
                qualname="pkg.mod:unused",
                filepath="pkg/mod.py",
                start_line=10,
                end_line=12,
                kind="function",
                confidence="high",
            ),
            DeadItem(
                qualname="pkg.mod:maybe",
                filepath="pkg/mod.py",
                start_line=20,
                end_line=22,
                kind="function",
                confidence="medium",
            ),
        ),
        health=HealthScore(total=70, grade="C", dimensions={"clones": 70}),
    )


def test_suggestion_helpers_convert_types() -> None:
    assert suggestions_mod._as_int(True) == 1
    assert suggestions_mod._as_int("42") == 42
    assert suggestions_mod._as_int("bad", default=7) == 7
    assert suggestions_mod._as_int(object(), default=9) == 9
    assert suggestions_mod._as_str("value", default="x") == "value"
    assert suggestions_mod._as_str(10, default="x") == "x"


def test_classify_clone_type_all_modes() -> None:
    assert classify_clone_type(items=(), kind="block") == "Type-4"
    assert (
        classify_clone_type(
            items=(
                {"raw_hash": "abc", "fingerprint": "f1"},
                {"raw_hash": "abc", "fingerprint": "f2"},
            ),
            kind="function",
        )
        == "Type-1"
    )
    assert (
        classify_clone_type(
            items=(
                {"fingerprint": "fp"},
                {"fingerprint": "fp"},
            ),
            kind="function",
        )
        == "Type-2"
    )
    assert (
        classify_clone_type(
            items=(
                {"fingerprint": "fp1"},
                {"fingerprint": "fp2"},
            ),
            kind="function",
        )
        == "Type-3"
    )
    assert (
        classify_clone_type(
            items=(
                {"fingerprint": ""},
                {"raw_hash": ""},
            ),
            kind="function",
        )
        == "Type-4"
    )


def test_generate_suggestions_covers_clone_metrics_and_dependency_categories() -> None:
    project_metrics = _project_metrics()
    units = (
        {
            "qualname": "pkg.mod:critical",
            "filepath": "pkg/mod.py",
            "start_line": 1,
            "end_line": 30,
            "cyclomatic_complexity": 50,
            "nesting_depth": 5,
            "risk": "high",
        },
        {
            "qualname": "pkg.mod:warning",
            "filepath": "pkg/mod.py",
            "start_line": 35,
            "end_line": 60,
            "cyclomatic_complexity": 25,
            "nesting_depth": 3,
            "risk": "medium",
        },
        {
            "qualname": "pkg.mod:ok",
            "filepath": "pkg/mod.py",
            "start_line": 70,
            "end_line": 75,
            "cyclomatic_complexity": 10,
            "nesting_depth": 1,
            "risk": "low",
        },
    )
    class_metrics = (
        ClassMetrics(
            qualname="pkg.mod:Service",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=80,
            cbo=11,
            lcom4=4,
            method_count=8,
            instance_var_count=5,
            risk_coupling="high",
            risk_cohesion="high",
        ),
    )
    func_groups = {
        "type1_group": [
            {
                "qualname": "pkg.mod:a",
                "filepath": "pkg/mod.py",
                "start_line": 5,
                "end_line": 9,
                "raw_hash": "same",
                "fingerprint": "f1",
            }
            for _ in range(4)
        ],
        "type2_group": [
            {
                "qualname": "pkg.mod:b",
                "filepath": "pkg/mod.py",
                "start_line": 15,
                "end_line": 19,
                "raw_hash": "",
                "fingerprint": "fp-shared",
            },
            {
                "qualname": "pkg.mod:c",
                "filepath": "pkg/mod.py",
                "start_line": 25,
                "end_line": 29,
                "raw_hash": "",
                "fingerprint": "fp-shared",
            },
        ],
    }
    block_groups = {
        "block-heavy": [
            {
                "qualname": "pkg.mod:block",
                "filepath": "pkg/mod.py",
                "start_line": 100,
                "end_line": 110,
            }
            for _ in range(4)
        ]
    }
    segment_groups = {
        "segment-heavy": [
            {
                "qualname": "pkg.mod:segment",
                "filepath": "pkg/mod.py",
                "start_line": 120,
                "end_line": 130,
            }
            for _ in range(4)
        ]
    }

    suggestions = generate_suggestions(
        project_metrics=project_metrics,
        units=units,
        class_metrics=class_metrics,
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
    )
    assert suggestions
    categories = {item.category for item in suggestions}
    assert categories == {
        "clone",
        "complexity",
        "coupling",
        "cohesion",
        "dead_code",
        "dependency",
    }
    assert any(item.title.endswith("(Type-1)") for item in suggestions)
    assert any(item.title.endswith("(Type-2)") for item in suggestions)
    assert any(
        item.category == "complexity"
        and item.severity == "critical"
        and item.title == "Reduce function complexity"
        for item in suggestions
    )
    assert any(
        item.category == "complexity"
        and item.severity == "warning"
        and item.title == "Reduce function complexity"
        for item in suggestions
    )
    assert any(
        item.category == "clone"
        and item.fact_kind == "Function clone group"
        and item.fact_summary == "same exact function body"
        and item.source_kind == "production"
        for item in suggestions
    )
    assert all(
        not (
            item.category == "dead_code"
            and item.location == "pkg/mod.py:20-22"
            and item.title == "Remove or explicitly keep unused code"
        )
        for item in suggestions
    )

    ordered = list(suggestions)
    assert ordered == sorted(
        ordered,
        key=lambda item: (
            -item.priority,
            item.severity,
            item.category,
            item.source_kind,
            item.location_label or item.location,
            item.title,
            item.subject_key,
        ),
    )


def test_generate_suggestions_covers_skip_branches_for_optional_rules() -> None:
    project_metrics = _project_metrics()
    class_metrics = (
        ClassMetrics(
            qualname="pkg.mod:OnlyCohesion",
            filepath="pkg/mod.py",
            start_line=10,
            end_line=20,
            cbo=5,
            lcom4=5,
            method_count=3,
            instance_var_count=1,
            risk_coupling="low",
            risk_cohesion="high",
        ),
        ClassMetrics(
            qualname="pkg.mod:NoWarnings",
            filepath="pkg/mod.py",
            start_line=30,
            end_line=40,
            cbo=2,
            lcom4=1,
            method_count=2,
            instance_var_count=1,
            risk_coupling="low",
            risk_cohesion="low",
        ),
    )
    suggestions = generate_suggestions(
        project_metrics=project_metrics,
        units=(),
        class_metrics=class_metrics,
        func_groups={
            "type3": [
                {"fingerprint": "a", "raw_hash": "", "filepath": "pkg/mod.py"},
                {"fingerprint": "b", "raw_hash": "", "filepath": "pkg/mod.py"},
            ]
        },
        block_groups={"small": [{"filepath": "pkg/mod.py"}]},
        segment_groups={"small": [{"filepath": "pkg/mod.py"}]},
    )
    assert any(item.category == "cohesion" for item in suggestions)
    assert not any(item.title.endswith("(Type-1)") for item in suggestions)
    assert not any(item.title.endswith("(Type-2)") for item in suggestions)


def test_generate_suggestions_uses_full_spread_for_group_location_label() -> None:
    suggestions = generate_suggestions(
        project_metrics=_project_metrics(),
        units=(),
        class_metrics=(),
        func_groups={
            "type2": [
                {
                    "qualname": "pkg.alpha:transform_alpha",
                    "filepath": "/root/tests/fixtures/alpha.py",
                    "start_line": 1,
                    "end_line": 10,
                    "fingerprint": "fp-shared",
                    "raw_hash": "",
                },
                {
                    "qualname": "pkg.beta:transform_beta",
                    "filepath": "/root/tests/fixtures/beta.py",
                    "start_line": 1,
                    "end_line": 10,
                    "fingerprint": "fp-shared",
                    "raw_hash": "",
                },
                {
                    "qualname": "pkg.gamma:transform_gamma",
                    "filepath": "/root/tests/fixtures/gamma.py",
                    "start_line": 1,
                    "end_line": 10,
                    "fingerprint": "fp-shared",
                    "raw_hash": "",
                },
                {
                    "qualname": "pkg.delta:transform_delta",
                    "filepath": "/root/tests/fixtures/delta.py",
                    "start_line": 1,
                    "end_line": 10,
                    "fingerprint": "fp-shared",
                    "raw_hash": "",
                },
            ]
        },
        block_groups={},
        segment_groups={},
        scan_root="/root",
    )
    clone_suggestion = next(
        suggestion
        for suggestion in suggestions
        if suggestion.finding_family == "clones"
    )
    assert len(clone_suggestion.representative_locations) == 3
    assert clone_suggestion.spread_files == 4
    assert clone_suggestion.spread_functions == 4
    assert (
        clone_suggestion.location_label == "4 occurrences across 4 files / 4 functions"
    )
