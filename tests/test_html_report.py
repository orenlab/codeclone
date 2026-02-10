import importlib
import json
from pathlib import Path
from typing import Any

import pytest

from codeclone.contracts import DOCS_URL, ISSUES_URL, REPOSITORY_URL
from codeclone.errors import FileProcessingError
from codeclone.html_report import (
    _FileCache,
    _prefix_css,
    _pygments_css,
    _render_code_block,
    _try_pygments,
    pairwise,
)
from codeclone.html_report import (
    build_html_report as _core_build_html_report,
)
from codeclone.report import build_block_group_facts, to_json_report


def build_html_report(
    *,
    func_groups: dict[str, list[dict[str, Any]]],
    block_groups: dict[str, list[dict[str, Any]]],
    segment_groups: dict[str, list[dict[str, Any]]],
    block_group_facts: dict[str, dict[str, str]] | None = None,
    **kwargs: Any,
) -> str:
    resolved_block_group_facts = (
        block_group_facts
        if block_group_facts is not None
        else build_block_group_facts(block_groups)
    )
    return _core_build_html_report(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_group_facts=resolved_block_group_facts,
        **kwargs,
    )


def test_html_report_empty() -> None:
    html = build_html_report(
        func_groups={}, block_groups={}, segment_groups={}, title="Empty Report"
    )
    assert "<!doctype html>" in html
    assert "Empty Report" in html
    assert "No code clones detected" in html


def test_html_report_requires_block_group_facts_argument() -> None:
    with pytest.raises(TypeError):
        _core_build_html_report(
            func_groups={},
            block_groups={},
            segment_groups={},
        )  # type: ignore[call-arg]


def test_html_report_generation(tmp_path: Path) -> None:
    f1 = tmp_path / "a.py"
    f1.write_text("def f1():\n    pass\n", "utf-8")
    f2 = tmp_path / "b.py"
    f2.write_text("def f2():\n    pass\n", "utf-8")

    func_groups = {
        "hash1": [
            {"qualname": "f1", "filepath": str(f1), "start_line": 1, "end_line": 2},
            {"qualname": "f2", "filepath": str(f2), "start_line": 1, "end_line": 2},
        ]
    }

    html = build_html_report(
        func_groups=func_groups,
        block_groups={},
        segment_groups={},
        title="Test Report",
        context_lines=1,
        max_snippet_lines=10,
    )

    assert "Test Report" in html
    assert "f1" in html
    assert "f2" in html
    assert "codebox" in html


def test_html_report_group_and_item_metadata_attrs(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "hash1": [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title="Attrs",
    )
    assert 'data-group-key="hash1"' in html
    assert '<div class="group-name">hash1</div>' in html
    assert 'data-qualname="pkg.mod:f"' in html
    assert 'data-filepath="' in html
    assert 'data-start-line="1"' in html
    assert 'data-end-line="2"' in html


def test_html_report_block_group_includes_match_basis_and_compact_key() -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": __file__,
                    "start_line": 1,
                    "end_line": 4,
                }
            ]
        },
        segment_groups={},
    )
    assert 'data-match-rule="normalized_sliding_window"' in html
    assert 'data-block-size="4"' in html
    assert 'data-signature-kind="stmt_hash_sequence"' in html
    assert 'data-merged-regions="true"' in html
    assert 'data-pattern="repeated_stmt_hash"' in html
    assert f"{repeated[:12]} x4" in html


def test_html_report_block_group_includes_assert_only_explanation(
    tmp_path: Path,
) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        },
        segment_groups={},
    )
    assert 'data-hint="assert_only"' in html
    assert 'data-hint-confidence="deterministic"' in html
    assert 'data-assert-ratio="100%"' in html
    assert 'data-consecutive-asserts="4"' in html
    assert "Assert pattern block" in html
    assert 'data-metrics-btn="blocks-1"' in html


def test_html_report_block_group_n_way_compare_hint(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f1",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                },
                {
                    "qualname": "pkg.mod:f2",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                },
                {
                    "qualname": "pkg.mod:f3",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                },
            ]
        },
        segment_groups={},
    )
    assert "N-way group: each block matches 2 peers in this group." in html
    assert "instance 1/3 • matches 2 peers" in html
    assert "instance 2/3 • matches 2 peers" in html
    assert "instance 3/3 • matches 2 peers" in html
    assert 'data-group-arity="3"' in html


def test_html_report_uses_core_block_group_facts(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        },
        segment_groups={},
        block_group_facts={
            group_key: {
                "match_rule": "core_contract",
                "block_size": "99",
                "signature_kind": "core_signature",
                "merged_regions": "false",
                "hint": "assert_only",
                "hint_confidence": "deterministic",
                "assert_ratio": "7%",
                "consecutive_asserts": "1",
                "hint_note": "Facts are owned by core.",
            }
        },
    )
    assert 'data-match-rule="core_contract"' in html
    assert 'data-block-size="99"' in html
    assert 'data-signature-kind="core_signature"' in html
    assert 'data-merged-regions="false"' in html
    assert 'data-assert-ratio="7%"' in html
    assert 'data-consecutive-asserts="1"' in html


def test_html_report_uses_core_hint_and_pattern_labels(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        },
        segment_groups={},
        block_group_facts={
            group_key: {
                "pattern": "internal_pattern_id",
                "pattern_label": "readable pattern",
                "hint": "internal_hint_id",
                "hint_label": "readable hint",
            }
        },
    )
    assert "pattern: readable pattern" in html
    assert "hint: readable hint" in html
    assert 'data-pattern-label="readable pattern"' in html
    assert 'data-hint-label="readable hint"' in html


def test_html_report_uses_core_hint_context_label(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        },
        segment_groups={},
        block_group_facts={
            group_key: {
                "hint": "assert_only",
                "hint_context_label": "Likely test boilerplate / repeated asserts",
            }
        },
    )
    assert "Likely test boilerplate / repeated asserts" in html
    assert (
        'data-hint-context-label="Likely test boilerplate / repeated asserts"' in html
    )


def test_html_report_blocks_without_explanation_meta(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        },
        segment_groups={},
        block_group_facts={},
    )
    assert '<div class="group-explain"' not in html
    assert 'data-group-arity="1"' in html


def test_html_report_respects_sparse_core_block_facts(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        },
        segment_groups={},
        report_meta={
            "baseline_path": "   ",
            "cache_path": "/",
            "baseline_status": "ok",
        },
        block_group_facts={
            group_key: {
                "match_rule": "core_sparse",
                "pattern": "repeated_stmt_hash",
                "hint": "assert_only",
                "hint_confidence": "deterministic",
            }
        },
    )
    assert 'data-match-rule="core_sparse"' in html
    assert 'data-pattern="repeated_stmt_hash"' in html
    assert 'data-block-size="' not in html
    assert 'data-signature-kind="' not in html
    assert 'data-assert-ratio="' not in html
    assert 'data-consecutive-asserts="' not in html


def test_html_report_handles_root_only_baseline_path() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"baseline_path": "/", "cache_path": "/"},
    )
    assert 'data-baseline-file=""' in html


def test_html_report_explanation_without_match_rule(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        },
        segment_groups={},
        block_group_facts={
            group_key: {
                "hint": "assert_only",
                "hint_confidence": "deterministic",
            }
        },
    )
    assert 'data-hint="assert_only"' in html
    assert "match_rule:" not in html


def test_html_report_n_way_group_without_compare_note(tmp_path: Path) -> None:
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
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f1",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                },
                {
                    "qualname": "pkg.mod:f2",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                },
                {
                    "qualname": "pkg.mod:f3",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                },
            ]
        },
        segment_groups={},
        block_group_facts={
            group_key: {
                "group_arity": "3",
                "instance_peer_count": "2",
            }
        },
    )
    assert 'data-group-arity="3"' in html
    assert '<div class="group-compare-note">' not in html


def test_html_report_command_palette_full_actions_present() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    assert "Export Report" in html
    assert "Toggle Theme" in html
    assert "Open Help" in html
    assert "Expand All" in html
    assert "Collapse All" in html
    assert "window.print();" in html
    assert "Generated by CodeClone v" in html
    assert '<span class="footer-kbd">⌘K</span>' in html
    assert '<span class="footer-kbd">⌘I</span>' in html
    assert "key === 'i'" in html
    assert 'id="help-modal"' in html


def test_html_report_help_modal_links_present() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    assert "Help & Support" in html
    assert f'href="{REPOSITORY_URL}"' in html
    assert f'href="{ISSUES_URL}"' in html
    assert f'href="{DOCS_URL}"' in html
    assert 'rel="noopener noreferrer"' in html


def test_html_report_includes_provenance_metadata(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": "f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        report_meta={
            "codeclone_version": "1.3.0",
            "python_version": "3.13",
            "baseline_path": "/repo/codeclone.baseline.json",
            "baseline_fingerprint_version": "1",
            "baseline_schema_version": 1,
            "baseline_python_version": "3.13",
            "baseline_generator_version": "1.4.0",
            "baseline_loaded": True,
            "baseline_status": "ok",
            "cache_path": "/repo/.cache/codeclone/cache.json",
            "cache_used": True,
        },
    )
    expected = [
        "Report Provenance",
        "CodeClone",
        "Baseline file",
        "Baseline path",
        "Baseline schema",
        "Baseline generator version",
        "codeclone.baseline.json",
        'data-baseline-status="ok"',
        'data-baseline-file="codeclone.baseline.json"',
        "/repo/codeclone.baseline.json",
        'data-cache-used="true"',
    ]
    for token in expected:
        assert token in html


def test_html_report_escapes_meta_and_title(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": "f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title='<img src=x onerror="alert(1)">',
        report_meta={
            "baseline_path": '"/><script>alert(1)</script>',
            "cache_path": 'x" onmouseover="alert(1)',
            "baseline_status": "ok",
        },
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert (
        'data-baseline-path="&quot;/&gt;&lt;script&gt;alert(1)&lt;/script&gt;"' in html
    )
    assert 'data-cache-path="x&quot; onmouseover=&quot;alert(1)"' in html


def test_html_report_escapes_script_breakout_payload(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    payload = "</script><script>alert(1)</script>"
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": payload,
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        report_meta={"baseline_path": payload},
        title=payload,
    )
    assert "</script><script>" not in html
    assert "&lt;/script&gt;&lt;script&gt;" in html


def test_html_report_deterministic_group_order(tmp_path: Path) -> None:
    a_file = tmp_path / "a.py"
    b_file = tmp_path / "b.py"
    a_file.write_text("def a():\n    return 1\n", "utf-8")
    b_file.write_text("def b():\n    return 2\n", "utf-8")
    func_groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": str(b_file),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": str(a_file),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
    }
    html = build_html_report(
        func_groups=func_groups,
        block_groups={},
        segment_groups={},
    )
    a_idx = html.find('data-group-key="a"')
    b_idx = html.find('data-group-key="b"')
    assert a_idx != -1
    assert b_idx != -1
    assert a_idx < b_idx


def test_html_and_json_group_order_consistent(tmp_path: Path) -> None:
    a_file = tmp_path / "a.py"
    b_file = tmp_path / "b.py"
    c_file = tmp_path / "c.py"
    a_file.write_text("def a():\n    return 1\n", "utf-8")
    b_file.write_text("def b():\n    return 1\n", "utf-8")
    c_file.write_text("def c():\n    return 1\n", "utf-8")
    groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": str(b_file),
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": str(a_file),
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "c": [
            {
                "qualname": "c1",
                "filepath": str(c_file),
                "start_line": 1,
                "end_line": 2,
            },
            {
                "qualname": "c2",
                "filepath": str(c_file),
                "start_line": 1,
                "end_line": 2,
            },
        ],
    }
    html = build_html_report(func_groups=groups, block_groups={}, segment_groups={})
    json_report = json.loads(to_json_report(groups, {}, {}))
    json_keys = list(json_report["function_clones"].keys())
    assert json_keys == ["c", "a", "b"]
    assert html.find('data-group-key="c"') < html.find('data-group-key="a"')
    assert html.find('data-group-key="a"') < html.find('data-group-key="b"')


def test_html_report_escapes_control_chars_in_payload(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    qualname = "q`</div>\u2028\u2029"
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": qualname,
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
    )
    assert "&lt;/div&gt;" in html
    assert "&#96;" in html
    assert "&#8232;" in html
    assert "&#8233;" in html


def test_file_cache_reads_ranges(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text("\n".join([f"line{i}" for i in range(1, 21)]), "utf-8")

    cache = _FileCache(maxsize=4)
    lines = cache.get_lines_range(str(f), 5, 8)

    assert lines == ("line5", "line6", "line7", "line8")
    assert cache.cache_info().hits == 0
    lines2 = cache.get_lines_range(str(f), 5, 8)
    assert lines2 == lines
    assert cache.cache_info().hits == 1


def test_file_cache_missing_file(tmp_path: Path) -> None:
    cache = _FileCache(maxsize=2)
    missing = tmp_path / "missing.py"
    with pytest.raises(FileProcessingError):
        cache.get_lines_range(str(missing), 1, 2)


def test_html_report_missing_source_snippet_fallback(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": "f",
                    "filepath": str(missing),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title="Missing Source",
    )
    assert "Missing Source" in html
    assert "Source file unavailable" in html


def test_file_cache_unicode_fallback(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_bytes(b"\xff\xfe\xff\n")
    cache = _FileCache(maxsize=2)
    lines = cache.get_lines_range(str(f), 1, 2)
    assert len(lines) == 1


def test_file_cache_range_bounds(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", "utf-8")
    cache = _FileCache(maxsize=2)
    lines = cache.get_lines_range(str(f), 0, 0)
    assert lines == ()
    lines2 = cache.get_lines_range(str(f), -3, 1)
    assert len(lines2) == 1


def test_render_code_block_truncate(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("\n".join([f"line{i}" for i in range(1, 50)]), "utf-8")
    html = build_html_report(
        func_groups={
            "h": [
                {
                    "qualname": "f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 40,
                    "loc": 40,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title="Truncate",
        context_lines=10,
        max_snippet_lines=5,
    )
    assert "Truncate" in html


def test_prefix_css() -> None:
    css = "/* c */\n\n.a{color:red}\nplain\n.b { color: blue; }\n"
    prefixed = _prefix_css(css, ".wrap")
    assert ".wrap .a" in prefixed
    assert ".wrap .b" in prefixed
    assert "/* c */" in prefixed


def test_prefix_css_empty_selector_passthrough() -> None:
    css = "   { color: red; }\n"
    prefixed = _prefix_css(css, ".wrap")
    assert "{ color: red; }" in prefixed


def test_pygments_css() -> None:
    css = _pygments_css("default")
    assert ".codebox" in css or css == ""


def test_pygments_css_invalid_style() -> None:
    css = _pygments_css("no-such-style")
    assert isinstance(css, str)


def test_pygments_css_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr(importlib, "import_module", _boom)
    assert _pygments_css("default") == ""


def test_try_pygments_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr(importlib, "import_module", _boom)
    assert _try_pygments("x = 1") is None


def test_try_pygments_ok() -> None:
    result = _try_pygments("x = 1")
    assert result is None or isinstance(result, str)


def test_render_code_block_without_pygments_uses_escaped_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import codeclone._html_snippets as snippets

    src = tmp_path / "a.py"
    src.write_text("x = '<tag>'\n", "utf-8")
    monkeypatch.setattr(snippets, "_try_pygments", lambda _raw: None)
    snippet = _render_code_block(
        filepath=str(src),
        start_line=1,
        end_line=1,
        file_cache=_FileCache(),
        context=0,
        max_lines=10,
    )
    assert "&lt;tag&gt;" in snippet.code_html
    assert 'class="hitline"' in snippet.code_html


def test_html_report_with_blocks(tmp_path: Path) -> None:
    f1 = tmp_path / "a.py"
    f1.write_text("def f1():\n    pass\n", "utf-8")
    f2 = tmp_path / "b.py"
    f2.write_text("def f2():\n    pass\n", "utf-8")

    block_groups = {
        "h1": [
            {
                "qualname": "f1",
                "filepath": str(f1),
                "start_line": 1,
                "end_line": 2,
                "size": 4,
            },
            {
                "qualname": "f2",
                "filepath": str(f2),
                "start_line": 1,
                "end_line": 2,
                "size": 4,
            },
        ]
    }
    html = build_html_report(
        func_groups={},
        block_groups=block_groups,
        segment_groups={},
        title="Blocks",
    )
    assert "Block clones" in html


def test_html_report_pygments_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import codeclone.html_report as hr

    def _fake_css(name: str) -> str:
        if name in ("github-dark", "github-light"):
            return ""
        return "x"

    monkeypatch.setattr(hr, "_pygments_css", _fake_css)
    html = build_html_report(
        func_groups={}, block_groups={}, segment_groups={}, title="Pygments"
    )
    assert "Pygments" in html


def test_html_report_segments_section(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    x = 1\n    y = 2\n", "utf-8")
    segment_groups = {
        "s1|mod:f": [
            {
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            },
            {
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
        ]
    }
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups=segment_groups,
        title="Segments",
    )
    assert "Segment clones" in html


def test_html_report_single_item_group(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    x = 1\n", "utf-8")
    segment_groups = {
        "s1|mod:f": [
            {
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ]
    }
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups=segment_groups,
        title="Segments",
    )
    assert f"{f}:1-2" in html


def test_pairwise_helper() -> None:
    assert list(pairwise([1, 2, 3])) == [(1, 2), (2, 3)]


def test_render_code_block_truncates_and_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "a.py"
    f.write_text("\n".join([f"line{i}" for i in range(1, 30)]), "utf-8")

    import codeclone.html_report as hr

    monkeypatch.setattr(hr, "_try_pygments", lambda _text: None)
    cache = _FileCache(maxsize=2)
    snippet = hr._render_code_block(
        filepath=str(f),
        start_line=1,
        end_line=20,
        file_cache=cache,
        context=5,
        max_lines=5,
    )
    assert "codebox" in snippet.code_html


def test_pygments_css_get_style_defs_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Fmt:
        def get_style_defs(self, _selector: str) -> str:
            raise RuntimeError("nope")

    class _Mod:
        HtmlFormatter = _Fmt

    monkeypatch.setattr(importlib, "import_module", lambda _name: _Mod)
    assert _pygments_css("default") == ""


def test_pygments_css_formatter_init_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Fmt:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("nope")

    class _Mod:
        HtmlFormatter = _Fmt

    monkeypatch.setattr(importlib, "import_module", lambda _name: _Mod)
    assert _pygments_css("default") == ""
