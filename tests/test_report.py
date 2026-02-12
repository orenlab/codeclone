import ast
import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

import codeclone.report as report_mod
from codeclone.contracts import REPORT_SCHEMA_VERSION
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
from tests._report_fixtures import (
    REPEATED_STMT_HASH,
    repeated_block_group_key,
    write_repeated_assert_source,
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
    group_key = repeated_block_group_key()
    test_file = write_repeated_assert_source(tmp_path / "test_repeated_asserts.py")
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
    assert group["pattern_display"] == f"{REPEATED_STMT_HASH[:12]} x4"
    assert group["hint"] == "assert_only"
    assert group["hint_label"] == "Assert-only block"
    assert group["hint_confidence"] == "deterministic"
    assert group["assert_ratio"] == "100%"
    assert group["consecutive_asserts"] == "4"
    assert group["group_display_name"] == "Assert pattern block"
    assert group["group_arity"] == "1"
    assert group["instance_peer_count"] == "0"


def test_build_block_group_facts_deterministic_item_order(tmp_path: Path) -> None:
    group_key = repeated_block_group_key()
    test_file = write_repeated_assert_source(tmp_path / "test_repeated_asserts.py")
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


def test_report_output_formats(
    report_meta_factory: Callable[..., dict[str, object]],
) -> None:
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
    meta = report_meta_factory(
        codeclone_version="1.3.0",
        baseline_path="/tmp/codeclone.baseline.json",
        baseline_schema_version=1,
        cache_path="/tmp/cache.json",
    )
    json_out = to_json(groups)
    report_out = to_json_report(groups, groups, {}, meta)
    text_out = to_text_report(
        meta=meta,
        func_groups=groups,
        block_groups=groups,
        segment_groups={},
    )

    expected_json = ["group_count"]
    expected_report = [
        '"meta"',
        '"groups"',
        '"groups_split"',
        '"group_item_layout"',
        f'"report_schema_version": "{REPORT_SCHEMA_VERSION}"',
        '"baseline_schema_version": 1',
        f'"baseline_payload_sha256": "{"a" * 64}"',
        '"baseline_payload_sha256_verified": true',
        '"cache_schema_version": "1.2"',
        '"cache_status": "ok"',
        '"files_skipped_source_io": 0',
    ]
    expected_text = [
        "REPORT METADATA",
        "Report schema version: 1.1",
        "Python tag: cp313",
        "Baseline schema version: 1",
        "Baseline generator name: codeclone",
        f"Baseline payload sha256: {'a' * 64}",
        "Baseline payload verified: true",
        "Cache schema version: 1.2",
        "Cache status: ok",
        "Source IO skipped: 0",
        "FUNCTION CLONES (NEW) (groups=2)",
        "FUNCTION CLONES (KNOWN) (groups=0)",
        "Clone group #1",
    ]

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


def test_report_json_group_order_is_lexicographic() -> None:
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
    assert list(report_obj["groups"]["functions"].keys()) == ["a", "b", "c"]


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


def test_report_json_compact_v11_contract() -> None:
    groups = {
        "g1": [
            {
                "qualname": "m:a",
                "filepath": "z.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-z",
                "loc_bucket": "0-19",
            },
            {
                "qualname": "m:b",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-a",
                "loc_bucket": "0-19",
            },
        ]
    }
    payload = json.loads(to_json_report(groups, {}, {}, {"codeclone_version": "1.4.0"}))

    assert payload["meta"]["report_schema_version"] == REPORT_SCHEMA_VERSION
    assert payload["files"] == ["a.py", "z.py"]
    assert set(payload["groups"]) == {"functions", "blocks", "segments"}
    assert payload["groups_split"] == {
        "functions": {"new": ["g1"], "known": []},
        "blocks": {"new": [], "known": []},
        "segments": {"new": [], "known": []},
    }
    assert payload["meta"]["groups_counts"] == {
        "functions": {"total": 1, "new": 1, "known": 0},
        "blocks": {"total": 0, "new": 0, "known": 0},
        "segments": {"total": 0, "new": 0, "known": 0},
    }
    assert payload["group_item_layout"] == {
        "functions": [
            "file_i",
            "qualname",
            "start",
            "end",
            "loc",
            "stmt_count",
            "fingerprint",
            "loc_bucket",
        ],
        "blocks": ["file_i", "qualname", "start", "end", "size"],
        "segments": [
            "file_i",
            "qualname",
            "start",
            "end",
            "size",
            "segment_hash",
            "segment_sig",
        ],
    }
    assert "function_clones" not in payload
    assert "block_clones" not in payload
    assert "segment_clones" not in payload

    function_rows = payload["groups"]["functions"]["g1"]
    assert function_rows == [
        [0, "m:b", 1, 2, 2, 1, "fp-a", "0-19"],
        [1, "m:a", 3, 4, 2, 1, "fp-z", "0-19"],
    ]


def test_report_json_block_records_do_not_repeat_group_hash() -> None:
    block_group_key = "hash-a|hash-b|hash-c|hash-d"
    payload = json.loads(
        to_json_report(
            {},
            {
                block_group_key: [
                    {
                        "qualname": "m:f",
                        "filepath": "a.py",
                        "start_line": 10,
                        "end_line": 13,
                        "size": 4,
                    }
                ]
            },
            {},
            {"codeclone_version": "1.4.0"},
        )
    )
    rows = payload["groups"]["blocks"][block_group_key]
    assert rows == [[0, "m:f", 10, 13, 4]]


def test_report_json_includes_sorted_block_facts() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0"},
            block_facts={
                "group-b": {"z": "3", "a": "x"},
                "group-a": {"k": "v"},
            },
        )
    )
    assert payload["facts"] == {
        "blocks": {
            "group-a": {"k": "v"},
            "group-b": {"a": "x", "z": "3"},
        }
    }


def test_report_json_groups_split_trusted_baseline() -> None:
    func_groups = {
        "func-known": [
            {
                "qualname": "m:fk",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-k",
                "loc_bucket": "0-19",
            }
        ],
        "func-new": [
            {
                "qualname": "m:fn",
                "filepath": "b.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-n",
                "loc_bucket": "0-19",
            }
        ],
    }
    block_groups = {
        "block-known": [
            {
                "qualname": "m:bk",
                "filepath": "a.py",
                "start_line": 10,
                "end_line": 13,
                "size": 4,
            }
        ],
        "block-new": [
            {
                "qualname": "m:bn",
                "filepath": "b.py",
                "start_line": 20,
                "end_line": 23,
                "size": 4,
            }
        ],
    }
    segment_groups = {
        "segment-new": [
            {
                "qualname": "m:sn",
                "filepath": "b.py",
                "start_line": 30,
                "end_line": 35,
                "size": 6,
                "segment_hash": "seg-h",
                "segment_sig": "seg-s",
            }
        ]
    }
    payload = json.loads(
        to_json_report(
            func_groups,
            block_groups,
            segment_groups,
            {"baseline_loaded": True, "baseline_status": "ok"},
            new_function_group_keys={"func-new"},
            new_block_group_keys={"block-new"},
            new_segment_group_keys={"segment-new"},
        )
    )
    split = payload["groups_split"]
    assert split["functions"] == {"new": ["func-new"], "known": ["func-known"]}
    assert split["blocks"] == {"new": ["block-new"], "known": ["block-known"]}
    assert split["segments"] == {"new": ["segment-new"], "known": []}
    for section_name in ("functions", "blocks", "segments"):
        new_keys = set(split[section_name]["new"])
        known_keys = set(split[section_name]["known"])
        group_keys = set(payload["groups"][section_name].keys())
        assert new_keys.isdisjoint(known_keys)
        assert new_keys | known_keys == group_keys
        counts = payload["meta"]["groups_counts"][section_name]
        assert counts["total"] == len(group_keys)
        assert counts["new"] == len(new_keys)
        assert counts["known"] == len(known_keys)


def test_report_json_groups_split_untrusted_baseline() -> None:
    func_groups = {
        "func-a": [
            {
                "qualname": "m:f",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-a",
                "loc_bucket": "0-19",
            }
        ]
    }
    payload = json.loads(
        to_json_report(
            func_groups,
            {},
            {},
            {"baseline_loaded": False, "baseline_status": "integrity_failed"},
            new_function_group_keys=set(),
        )
    )
    split = payload["groups_split"]
    assert split["functions"] == {"new": ["func-a"], "known": []}
    assert split["blocks"] == {"new": [], "known": []}
    assert split["segments"] == {"new": [], "known": []}


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
    assert "Report schema version: (none)" in text_out
    assert "CodeClone version: (none)" in text_out
    assert "Baseline status: (none)" in text_out
    assert "Cache path: (none)" in text_out
    assert "Cache used: (none)" in text_out
    assert "Note: baseline is untrusted; all groups are treated as NEW." in text_out
    assert "FUNCTION CLONES (NEW) (groups=0)\n(none)" in text_out
    assert "FUNCTION CLONES (KNOWN) (groups=0)\n(none)" in text_out
    assert "BLOCK CLONES (NEW) (groups=0)\n(none)" in text_out
    assert "BLOCK CLONES (KNOWN) (groups=0)\n(none)" in text_out
    assert "SEGMENT CLONES (NEW) (groups=0)\n(none)" in text_out
    assert "SEGMENT CLONES (KNOWN) (groups=0)\n(none)" in text_out


def test_to_text_report_uses_section_specific_metric_labels() -> None:
    text_out = to_text_report(
        meta={"codeclone_version": "1.4.0"},
        func_groups={
            "f": [
                {
                    "qualname": "pkg:f",
                    "filepath": "a.py",
                    "start_line": 1,
                    "end_line": 10,
                    "loc": 11,
                }
            ]
        },
        block_groups={
            "b": [
                {
                    "qualname": "pkg:b",
                    "filepath": "b.py",
                    "start_line": 20,
                    "end_line": 23,
                    "size": 4,
                }
            ]
        },
        segment_groups={
            "s": [
                {
                    "qualname": "pkg:s",
                    "filepath": "c.py",
                    "start_line": 30,
                    "end_line": 35,
                    "size": 6,
                }
            ]
        },
    )
    assert "loc=11" in text_out
    assert "size=4" in text_out
    assert "size=6" in text_out


def test_to_text_report_trusted_baseline_split_sections() -> None:
    text_out = to_text_report(
        meta={"baseline_loaded": True, "baseline_status": "ok"},
        func_groups={
            "func-known": [
                {
                    "qualname": "pkg:known",
                    "filepath": "a.py",
                    "start_line": 1,
                    "end_line": 2,
                    "loc": 2,
                }
            ],
            "func-new": [
                {
                    "qualname": "pkg:new",
                    "filepath": "b.py",
                    "start_line": 3,
                    "end_line": 4,
                    "loc": 2,
                }
            ],
        },
        block_groups={},
        segment_groups={},
        new_function_group_keys={"func-new"},
    )
    assert "Note: baseline is untrusted" not in text_out
    assert "FUNCTION CLONES (NEW) (groups=1)" in text_out
    assert "FUNCTION CLONES (KNOWN) (groups=1)" in text_out
    assert "pkg:new b.py:3-4 loc=2" in text_out
    assert "pkg:known a.py:1-2 loc=2" in text_out


def test_to_text_report_untrusted_baseline_known_sections_empty() -> None:
    text_out = to_text_report(
        meta={"baseline_loaded": False, "baseline_status": "mismatch_schema_version"},
        func_groups={
            "func-a": [
                {
                    "qualname": "pkg:a",
                    "filepath": "a.py",
                    "start_line": 1,
                    "end_line": 2,
                    "loc": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
    )
    assert "Note: baseline is untrusted; all groups are treated as NEW." in text_out
    assert "FUNCTION CLONES (NEW) (groups=1)" in text_out
    assert "FUNCTION CLONES (KNOWN) (groups=0)\n(none)" in text_out


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
