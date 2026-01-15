from codeclone.report import build_groups, build_block_groups


def test_build_function_groups():
    units = [
        {"fingerprint": "abc", "loc_bucket": "20-49", "qualname": "a"},
        {"fingerprint": "abc", "loc_bucket": "20-49", "qualname": "b"},
        {"fingerprint": "zzz", "loc_bucket": "20-49", "qualname": "c"},
    ]

    groups = build_groups(units)
    assert len(groups) == 1
    assert list(groups.values())[0][0]["fingerprint"] == "abc"


def test_block_groups_require_multiple_functions():
    blocks = [
        {"block_hash": "h1", "qualname": "f1"},
        {"block_hash": "h1", "qualname": "f1"},
        {"block_hash": "h1", "qualname": "f2"},
    ]

    groups = build_block_groups(blocks)
    assert len(groups) == 1