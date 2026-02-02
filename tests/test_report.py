from codeclone.report import (
    build_block_groups,
    build_groups,
    to_json,
    to_json_report,
    to_text,
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
    json_out = to_json(groups)
    report_out = to_json_report(groups, groups)
    text_out = to_text(groups)

    assert "group_count" in json_out
    assert '"functions"' in report_out
    assert "Clone group #1" in text_out
