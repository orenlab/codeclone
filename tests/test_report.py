import ast
import json
from pathlib import Path
from typing import cast

import pytest

import codeclone.report as report_mod
from codeclone.report import (
    GroupMap,
    build_block_group_facts,
    build_block_groups,
    build_groups,
    build_segment_groups,
    prepare_block_report_groups,
    prepare_segment_report_groups,
    to_json,
    to_json_report,
    to_text_report,
)


def test_build_function_groups() -> None:
    units = [
        {"fingerprint": "abc", "loc_bucket": "20-49", "qualname": "a"},
        {"fingerprint": "abc", "loc_bucket": "20-49", "qualname": "b"},
        {"fingerprint": "zzz", "loc_bucket": "20-49", "qualname": "c"},
    ]

    groups = build_groups(units)
    assert len(groups) == 1
    assert next(iter(groups.values()))[0]["fingerprint"] == "abc"


def test_block_groups_require_multiple_functions() -> None:
    blocks = [
        {"block_hash": "h1", "qualname": "f1"},
        {"block_hash": "h1", "qualname": "f1"},
        {"block_hash": "h1", "qualname": "f2"},
    ]

    groups = build_block_groups(blocks)
    assert len(groups) == 1


def test_prepare_block_report_groups_merges_to_maximal_regions() -> None:
    groups = {
        "h": [
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 20,
                "end_line": 23,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 10,
                "end_line": 13,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 13,
                "end_line": 16,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:g",
                "start_line": 10,
                "end_line": 13,
                "size": 4,
            },
        ]
    }

    prepared = prepare_block_report_groups(groups)
    items = prepared["h"]
    assert len(items) == 3

    assert items[0]["qualname"] == "mod:f"
    assert items[0]["start_line"] == 10
    assert items[0]["end_line"] == 16
    assert items[0]["size"] == 7

    assert items[1]["qualname"] == "mod:f"
    assert items[1]["start_line"] == 20
    assert items[1]["end_line"] == 23
    assert items[1]["size"] == 4

    assert items[2]["qualname"] == "mod:g"
    assert items[2]["start_line"] == 10
    assert items[2]["end_line"] == 13
    assert items[2]["size"] == 4


def test_prepare_block_report_groups_skips_invalid_ranges() -> None:
    groups = {
        "h": [
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": "bad",
                "end_line": 13,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 30,
                "end_line": 33,
                "size": 4,
            },
        ]
    }
    prepared = prepare_block_report_groups(groups)
    assert len(prepared["h"]) == 1
    assert prepared["h"][0]["start_line"] == 30
    assert prepared["h"][0]["end_line"] == 33


def test_prepare_block_report_groups_all_invalid_ranges_fallback_sorted() -> None:
    groups: GroupMap = {
        "h": [
            {
                "block_hash": "h",
                "filepath": "b.py",
                "qualname": "mod:f",
                "start_line": "bad",
                "end_line": 13,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": None,
                "end_line": 1,
                "size": 4,
            },
        ]
    }
    prepared = prepare_block_report_groups(groups)
    items = prepared["h"]
    assert len(items) == 2
    assert items[0]["filepath"] == "a.py"
    assert items[1]["filepath"] == "b.py"


def test_prepare_block_report_groups_handles_empty_item_list() -> None:
    groups: GroupMap = {"h": []}
    prepared = prepare_block_report_groups(groups)
    assert prepared["h"] == []


def test_build_block_group_facts_assert_only(tmp_path: Path) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    test_file = tmp_path / "test_repeated_asserts.py"
    test_file.write_text(
        "def f(html):\n"
        "    assert 'a' in html\n"
        "    assert 'b' in html\n"
        "    assert 'c' in html\n"
        "    assert 'd' in html\n",
        "utf-8",
    )
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["match_rule"] == "normalized_sliding_window"
    assert group["block_size"] == "4"
    assert group["signature_kind"] == "stmt_hash_sequence"
    assert group["merged_regions"] == "true"
    assert group["pattern"] == "repeated_stmt_hash"
    assert group["pattern_display"] == f"{repeated[:12]} x4"
    assert group["hint"] == "assert_only"
    assert group["hint_confidence"] == "deterministic"
    assert group["assert_ratio"] == "100%"
    assert group["consecutive_asserts"] == "4"


def test_build_block_group_facts_deterministic_item_order(tmp_path: Path) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    test_file = tmp_path / "test_repeated_asserts.py"
    test_file.write_text(
        "def f(html):\n"
        "    assert 'a' in html\n"
        "    assert 'b' in html\n"
        "    assert 'c' in html\n"
        "    assert 'd' in html\n",
        "utf-8",
    )
    item_a = {
        "qualname": "pkg.mod:f",
        "filepath": str(test_file),
        "start_line": 2,
        "end_line": 5,
    }
    item_b = {
        "qualname": "pkg.mod:f",
        "filepath": str(test_file),
        "start_line": 2,
        "end_line": 5,
    }
    facts_a = build_block_group_facts({group_key: [item_a, item_b]})
    facts_b = build_block_group_facts({group_key: [item_b, item_a]})
    assert facts_a == facts_b


def test_report_output_formats() -> None:
    groups = {
        "k1": [
            {
                "qualname": "f1",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
        "k2": [
            {
                "qualname": "f2",
                "filepath": "b.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
            },
            {
                "qualname": "f3",
                "filepath": "c.py",
                "start_line": 5,
                "end_line": 6,
                "loc": 2,
            },
        ],
    }
    meta = {
        "codeclone_version": "1.3.0",
        "python_version": "3.13",
        "baseline_path": "/tmp/codeclone.baseline.json",
        "baseline_fingerprint_version": "1",
        "baseline_schema_version": 1,
        "baseline_python_version": "3.13",
        "baseline_generator_version": "1.4.0",
        "baseline_loaded": True,
        "baseline_status": "ok",
        "cache_path": "/tmp/cache.json",
        "cache_used": True,
    }
    json_out = to_json(groups)
    report_out = to_json_report(groups, groups, {}, meta)
    text_out = to_text_report(
        meta=meta,
        func_groups=groups,
        block_groups=groups,
        segment_groups={},
    )

    expected_json = ["group_count"]
    expected_report = ['"meta"', '"function_clones"', '"baseline_schema_version": 1']
    expected_text = ["REPORT METADATA", "Baseline schema version: 1", "Clone group #1"]

    for token in expected_json:
        assert token in json_out
    for token in expected_report:
        assert token in report_out
    for token in expected_text:
        assert token in text_out


def test_report_json_deterministic_group_order() -> None:
    groups_a = {
        "b": [
            {
                "qualname": "b",
                "filepath": "b.py",
                "start_line": 2,
                "end_line": 3,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
    }
    groups_b = {"a": groups_a["a"], "b": groups_a["b"]}
    meta = {"codeclone_version": "1.3.0"}
    out_a = to_json_report(groups_a, groups_a, groups_a, meta)
    out_b = to_json_report(groups_b, groups_b, groups_b, meta)
    assert out_a == out_b


def test_report_json_group_order_prefers_size_then_key() -> None:
    groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": "b.py",
                "start_line": 2,
                "end_line": 3,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
        "c": [
            {
                "qualname": "c1",
                "filepath": "c.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            },
            {
                "qualname": "c2",
                "filepath": "c.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
            },
        ],
    }
    payload = to_json_report(groups, {}, {}, {"codeclone_version": "1.3.0"})
    report_obj = json.loads(payload)
    assert list(report_obj["function_clones"].keys()) == ["c", "a", "b"]


def test_report_json_deterministic_with_shuffled_units() -> None:
    units_a = [
        {
            "fingerprint": "abc",
            "loc_bucket": "0-19",
            "qualname": "b",
            "filepath": "b.py",
            "start_line": 2,
            "end_line": 3,
            "loc": 2,
        },
        {
            "fingerprint": "abc",
            "loc_bucket": "0-19",
            "qualname": "a",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 2,
            "loc": 2,
        },
    ]
    units_b = list(reversed(units_a))
    groups_a = build_groups(units_a)
    groups_b = build_groups(units_b)
    meta = {"codeclone_version": "1.3.0"}
    out_a = to_json_report(groups_a, {}, {}, meta)
    out_b = to_json_report(groups_b, {}, {}, meta)
    assert out_a == out_b


def test_text_report_deterministic_group_order() -> None:
    groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": "b.py",
                "start_line": 2,
                "end_line": 3,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
    }
    text = report_mod.to_text(groups)
    first_idx = text.find("Clone group #1")
    a_idx = text.find("a.py")
    b_idx = text.find("b.py")
    assert first_idx != -1
    assert a_idx != -1
    assert b_idx != -1
    assert a_idx < b_idx


def test_to_text_report_handles_missing_meta_fields() -> None:
    text_out = to_text_report(
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    assert "CodeClone version: n/a" in text_out
    assert "Baseline status: n/a" in text_out
    assert "Cache path:" not in text_out
    assert "Cache used:" not in text_out
    assert "FUNCTION CLONES\n(none)" in text_out
    assert "BLOCK CLONES\n(none)" in text_out
    assert "SEGMENT CLONES\n(none)" in text_out


def test_segment_groups_internal_only() -> None:
    segments = [
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 4,
            "size": 4,
        },
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 10,
            "end_line": 13,
            "size": 4,
        },
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:g",
            "filepath": "b.py",
            "start_line": 1,
            "end_line": 4,
            "size": 4,
        },
    ]

    groups = build_segment_groups(segments)
    assert len(groups) == 1
    group_items = next(iter(groups.values()))
    assert all(item["qualname"] == "mod:f" for item in group_items)


def test_segment_groups_filters_small_candidates() -> None:
    segments = [
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 2,
            "size": 2,
        }
    ]
    groups = build_segment_groups(segments)
    assert groups == {}


def test_segment_groups_merge_overlaps(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    if True:",
            "        x = 1",
            "    y = 2",
            "    z = 3",
            "    w = 4",
            "    t = 5",
            "    u = 6",
            "    v = 7",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 4,
                "end_line": 6,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 8,
                "end_line": 9,
                "size": 2,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    items = filtered["seg|mod:f"]
    assert len(items) == 2
    assert items[0]["start_line"] == 2
    assert items[0]["end_line"] == 6
    assert items[1]["start_line"] == 8
    assert items[1]["end_line"] == 9


def test_segment_groups_suppress_boilerplate(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.a = 1",
            "    self.b = 2",
            "    self.c = 3",
            "    self.d = factory()",
            "    self.e = 5",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 6,
                "size": 5,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 6,
                "size": 5,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert filtered == {}
    assert suppressed == 1


def test_segment_groups_keep_call_statement(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.x = 1",
            "    init()",
            "    self.y = 2",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_groups_suppress_rhs_call_assigns(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.x = init()",
            "    self.y = factory()",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert filtered == {}
    assert suppressed == 1


def test_segment_groups_keep_control_flow(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.a = 1",
            "    if flag:",
            "        self.b = 2",
            "    self.c = 3",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 5,
                "size": 4,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 5,
                "size": 4,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_groups_keep_min_unique_types(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.a = 1",
            "    x += 1",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_groups_deterministic(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    if flag:",
            "        x = 1",
            "    y = 2",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
        ]
    }
    first = prepare_segment_report_groups(group)
    second = prepare_segment_report_groups(group)
    assert first == second


def test_segment_helpers_cover_edge_cases(tmp_path: Path) -> None:
    # _merge_segment_items empty
    assert report_mod._merge_segment_items([]) == []

    # _merge_segment_items skips invalid lines and still appends trailing current
    merged = report_mod._merge_segment_items(
        [
            {"start_line": 0, "end_line": 0},
            {"start_line": 2, "end_line": 3, "filepath": "x", "qualname": "q"},
        ]
    )
    assert len(merged) == 1

    # _assign_targets_attribute_only
    assign_attr = ast.parse("self.x = 1").body[0]
    assert report_mod._assign_targets_attribute_only(assign_attr)
    annassign_attr = ast.parse("self.y: int = 2").body[0]
    assert report_mod._assign_targets_attribute_only(annassign_attr)
    assign_name = ast.parse("x = 1").body[0]
    assert not report_mod._assign_targets_attribute_only(assign_name)
    expr_stmt = ast.parse("pass").body[0]
    assert not report_mod._assign_targets_attribute_only(expr_stmt)

    # _analyze_segment_statements empty
    assert report_mod._analyze_segment_statements([]) is None

    # _segment_statements handles non-list body and missing lineno
    class Dummy:
        body = None

    dummy = cast(ast.FunctionDef, cast(object, Dummy()))
    assert report_mod._segment_statements(dummy, 1, 2) == []

    func = ast.parse("def f():\n    x = 1\n").body[0]
    assert isinstance(func, ast.FunctionDef)
    stmt = func.body[0]
    delattr(stmt, "lineno")
    assert report_mod._segment_statements(func, 1, 2) == []


def test_segment_prepare_unknown_paths(tmp_path: Path) -> None:
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "",
                "filepath": "missing.py",
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_prepare_empty_merge() -> None:
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": "x.py",
                "start_line": 0,
                "end_line": 0,
                "size": 0,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert filtered == {}


def test_segment_prepare_missing_file(tmp_path: Path) -> None:
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(tmp_path / "missing.py"),
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


@pytest.mark.parametrize(
    ("case", "start_line", "end_line"),
    [
        ("syntax_error", 1, 2),
        ("missing_function", 1, 2),
        ("empty_range", 10, 12),
    ],
)
def test_segment_prepare_unresolvable_cases(
    tmp_path: Path, case: str, start_line: int, end_line: int
) -> None:
    if case == "syntax_error":
        f = tmp_path / "bad.py"
        f.write_text("def f(:\n    pass\n", "utf-8")
    elif case == "missing_function":
        f = tmp_path / "a.py"
        f.write_text("def g():\n    return 1\n", "utf-8")
    else:
        f = tmp_path / "a.py"
        f.write_text("def f():\n    x = 1\n", "utf-8")

    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": start_line,
                "end_line": end_line,
                "size": 2,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_collect_file_functions_class_and_async(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "class C:",
            "    async def a(self):",
            "        return 1",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    funcs = report_mod._collect_file_functions(str(f))
    assert funcs is not None
    assert "C.a" in funcs

    segments = [
        {
            "segment_sig": "sig2",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 2,
            "size": 2,
        },
        {
            "segment_sig": "sig2",
            "segment_hash": "h2",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 3,
            "end_line": 4,
            "size": 2,
        },
    ]
    groups = build_segment_groups(segments)
    assert groups == {}
