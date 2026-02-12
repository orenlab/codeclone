from __future__ import annotations

from pathlib import Path

REPEATED_STMT_HASH = "0e8579f84e518d186950d012c9944a40cb872332"

REPEATED_ASSERT_SOURCE = (
    "def f(html):\n"
    "    assert 'a' in html\n"
    "    assert 'b' in html\n"
    "    assert 'c' in html\n"
    "    assert 'd' in html\n"
)


def repeated_block_group_key(*, block_size: int = 4) -> str:
    return "|".join([REPEATED_STMT_HASH] * block_size)


def write_repeated_assert_source(path: Path) -> Path:
    path.write_text(REPEATED_ASSERT_SOURCE, "utf-8")
    return path
