import ast

from codeclone.blockhash import stmt_hash
from codeclone.normalize import NormalizationConfig


def test_stmt_hash_normalizes_names() -> None:
    cfg = NormalizationConfig()
    s1 = ast.parse("a = b + 1").body[0]
    s2 = ast.parse("x = y + 2").body[0]
    assert stmt_hash(s1, cfg) == stmt_hash(s2, cfg)
