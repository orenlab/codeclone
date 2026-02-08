from pathlib import Path

from codeclone._report_explain import build_block_group_facts


def test_build_block_group_facts_handles_missing_file() -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": "/definitely/missing/file.py",
                    "start_line": 10,
                    "end_line": 20,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["match_rule"] == "normalized_sliding_window"
    assert group["pattern"] == "repeated_stmt_hash"
    assert "hint" not in group
    assert "assert_ratio" not in group


def test_build_block_group_facts_handles_syntax_error_file(tmp_path: Path) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    broken = tmp_path / "broken.py"
    broken.write_text("def f(:\n    pass\n", "utf-8")
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(broken),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        }
    )
    assert "hint" not in facts[group_key]


def test_build_block_group_facts_assert_detection_with_calls(tmp_path: Path) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    test_file = tmp_path / "test_calls.py"
    test_file.write_text(
        "def f(checker):\n"
        '    "doc"\n'
        "    assert_ok(checker)\n"
        "    checker.assert_ready(checker)\n",
        "utf-8",
    )
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "tests.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 4,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["hint"] == "assert_only"
    assert group["assert_ratio"] == "100%"
    assert group["consecutive_asserts"] == "3"


def test_build_block_group_facts_non_assert_breaks_hint(tmp_path: Path) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    test_file = tmp_path / "test_mixed.py"
    test_file.write_text(
        "def f(html):\n"
        "    assert 'a' in html\n"
        "    check(html)\n"
        "    assert 'b' in html\n",
        "utf-8",
    )
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "tests.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 4,
                }
            ]
        }
    )
    group = facts[group_key]
    assert "hint" not in group
    assert group["assert_ratio"] == "67%"
    assert group["consecutive_asserts"] == "1"


def test_build_block_group_facts_non_repeated_signature_has_no_pattern() -> None:
    group_key = (
        "0e8579f84e518d186950d012c9944a40cb872332|"
        "1e8579f84e518d186950d012c9944a40cb872332|"
        "2e8579f84e518d186950d012c9944a40cb872332|"
        "3e8579f84e518d186950d012c9944a40cb872332"
    )
    facts = build_block_group_facts({group_key: []})
    group = facts[group_key]
    assert group["block_size"] == "4"
    assert "pattern" not in group


def test_build_block_group_facts_handles_empty_stmt_range(tmp_path: Path) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    test_file = tmp_path / "module.py"
    test_file.write_text("def f():\n    return 1\n", "utf-8")
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "mod:f",
                    "filepath": str(test_file),
                    "start_line": 100,
                    "end_line": 200,
                }
            ]
        }
    )
    group = facts[group_key]
    assert "assert_ratio" not in group
    assert "hint" not in group


def test_build_block_group_facts_non_assert_call_shapes(tmp_path: Path) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    test_file = tmp_path / "module.py"
    test_file.write_text(
        "def f(checker, x):\n    checker.validate(x)\n    (lambda y: y)(x)\n    x\n",
        "utf-8",
    )
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 4,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["assert_ratio"] == "0%"
    assert group["consecutive_asserts"] == "0"
    assert "hint" not in group


def test_build_block_group_facts_invalid_item_disables_assert_hint() -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "mod:f",
                    "filepath": "",
                    "start_line": 0,
                    "end_line": 0,
                }
            ]
        }
    )
    group = facts[group_key]
    assert "hint" not in group
    assert "assert_ratio" not in group


def test_build_block_group_facts_assert_only_without_test_context(
    tmp_path: Path,
) -> None:
    repeated = "0e8579f84e518d186950d012c9944a40cb872332"
    group_key = "|".join([repeated] * 4)
    prod_file = tmp_path / "module.py"
    prod_file.write_text(
        "def f(html):\n"
        "    assert 'a' in html\n"
        "    assert 'b' in html\n"
        "    assert 'c' in html\n"
        "    assert 'd' in html\n",
        "utf-8",
    )
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(prod_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["hint"] == "assert_only"
    assert "hint_context" not in group
