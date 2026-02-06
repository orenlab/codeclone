import importlib
from pathlib import Path

import pytest

from codeclone.errors import FileProcessingError
from codeclone.html_report import (
    _FileCache,
    _prefix_css,
    _pygments_css,
    _try_pygments,
    build_html_report,
    pairwise,
)


def test_html_report_empty() -> None:
    html = build_html_report(
        func_groups={}, block_groups={}, segment_groups={}, title="Empty Report"
    )
    assert "<!doctype html>" in html
    assert "Empty Report" in html
    assert "No code clones detected" in html


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
    assert '<code class="gkey" title="hash1">hash1</code>' in html
    assert 'data-qualname="pkg.mod:f"' in html
    assert 'data-filepath="' in html
    assert 'data-start-line="1"' in html
    assert 'data-end-line="2"' in html


def test_html_report_command_palette_full_actions_present() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    assert "Export as PDF" in html
    assert "window.print();" in html
    assert "No matching commands" in html
    assert "ArrowDown" in html
    assert "ArrowUp" in html
    assert "Chart feature coming soon" not in html
    assert "Clone Group Distribution" in html
    assert 'id="stats-dashboard" style="display: none;"' in html


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
            "baseline_version": "1.3.0",
            "baseline_schema_version": 1,
            "baseline_python_version": "3.13",
            "baseline_loaded": True,
            "baseline_status": "ok",
            "cache_path": "/repo/.cache/codeclone/cache.json",
            "cache_used": True,
        },
    )
    assert "Report Provenance" in html
    assert "CodeClone" in html
    assert "Baseline schema" in html
    assert 'data-baseline-status="ok"' in html
    assert "/repo/codeclone.baseline.json" in html
    assert 'data-cache-used="true"' in html


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
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

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
