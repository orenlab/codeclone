"""Path classification helpers used across analysis stages."""

from __future__ import annotations

from pathlib import Path

_TEST_FILE_NAMES = {"conftest.py"}


def is_test_filepath(filepath: str) -> bool:
    normalized = filepath.lower().replace("\\", "/")
    if "/tests/" in normalized or "/test/" in normalized:
        return True
    filename = Path(filepath).name.lower()
    return filename in _TEST_FILE_NAMES or filename.startswith("test_")
