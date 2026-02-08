import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from codeclone.cli import MAX_FILE_SIZE, process_file
from codeclone.errors import ValidationError
from codeclone.html_report import build_html_report
from codeclone.normalize import NormalizationConfig
from codeclone.report import build_block_group_facts
from codeclone.scanner import iter_py_files


def test_scanner_path_traversal() -> None:
    """Test that scanner rejects paths outside root or sensitive paths."""
    with pytest.raises(ValidationError):
        list(iter_py_files("/etc"))

    with pytest.raises(ValidationError):
        list(iter_py_files("/etc/passwd"))


def test_process_file_size_limit() -> None:
    """Test that process_file rejects large files."""
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp.write(b"print('hello')")
        tmp_path = tmp.name

    try:
        cfg = NormalizationConfig()

        # Mock os.path.getsize to return huge size
        with patch("os.path.getsize", return_value=MAX_FILE_SIZE + 1):
            result = process_file(tmp_path, os.path.dirname(tmp_path), cfg, 0, 0)
            assert result.success is False
            assert result.error is not None
            assert "File too large" in result.error

        # Normal size should pass
        with patch("os.path.getsize", return_value=10):
            result = process_file(tmp_path, os.path.dirname(tmp_path), cfg, 0, 0)
            assert result.success is True

    finally:
        os.remove(tmp_path)


def test_html_report_escapes_user_content(tmp_path: Path) -> None:
    bad_path = tmp_path / 'x" onmouseover="alert(1).py'
    good_path = tmp_path / "y.py"
    bad_path.write_text("def f():\n    return 1\n", "utf-8")
    good_path.write_text("def g():\n    return 2\n", "utf-8")
    func_groups = {
        "k": [
            {
                "qualname": "<script>alert(1)</script>",
                "filepath": str(bad_path),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            },
            {
                "qualname": "ok",
                "filepath": str(good_path),
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
            },
        ]
    }
    html = build_html_report(
        func_groups=func_groups,
        block_groups={},
        segment_groups={},
        block_group_facts=build_block_group_facts({}),
        title="Security",
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert 'onmouseover="alert(1)' not in html
    assert 'data-qualname="&lt;script&gt;alert(1)&lt;/script&gt;"' in html
    assert "&quot; onmouseover=&quot;alert(1).py" in html
