import os
import tempfile
from unittest.mock import patch

import pytest

from codeclone.cli import MAX_FILE_SIZE, process_file
from codeclone.errors import ValidationError
from codeclone.normalize import NormalizationConfig
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
