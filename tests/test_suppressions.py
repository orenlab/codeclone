from __future__ import annotations

from codeclone.suppressions import (
    DeclarationTarget,
    NoqaDirective,
    SuppressionBinding,
    bind_suppressions_to_declarations,
    build_suppression_index,
    extract_noqa_directives,
    suppression_target_key,
)


def test_extract_noqa_directives_supports_inline_and_leading_forms() -> None:
    source = """
# noqa: codeclone[dead-code]
def a() -> int:
    return 1

def b() -> int:  # noqa: codeclone[dead-code]
    return 2

class C:  # noqa: codeclone[dead-code]
    pass

# noqa:   codeclone [ dead-code , clone-cohort-drift ]
async def d() -> int:
    return 3
""".strip()
    directives = extract_noqa_directives(source)
    assert directives == (
        NoqaDirective(line=1, binding="leading", rules=("dead-code",)),
        NoqaDirective(line=5, binding="inline", rules=("dead-code",)),
        NoqaDirective(line=8, binding="inline", rules=("dead-code",)),
        NoqaDirective(
            line=11,
            binding="leading",
            rules=("dead-code", "clone-cohort-drift"),
        ),
    )


def test_extract_noqa_directives_ignores_unknown_and_malformed_safely() -> None:
    source = """
def a() -> int:  # noqa: codeclone[dead-code, dead-code, unknown-rule]
    return 1

def b() -> int:  # noqa: codeclone
    return 2

def c() -> int:  # noqa: CODECLONE[dead-code]
    return 3
""".strip()
    directives = extract_noqa_directives(source)
    assert directives == (
        NoqaDirective(line=1, binding="inline", rules=("dead-code",)),
    )


def test_extract_noqa_directives_ignores_empty_invalid_and_unknown_tokens() -> None:
    source = """
def a() -> int:  # noqa: codeclone[dead-code, , invalid!, unknown-rule]
    return 1

def b() -> int:  # noqa: codeclone[unknown-rule]
    return 2
""".strip()
    directives = extract_noqa_directives(source)
    assert directives == (
        NoqaDirective(line=1, binding="inline", rules=("dead-code",)),
    )


def test_extract_noqa_directives_returns_empty_on_tokenize_error() -> None:
    # Unclosed triple quote triggers tokenize.TokenError and must be ignored safely.
    source = '"""\n# noqa: codeclone[dead-code]\n'
    assert extract_noqa_directives(source) == ()


def test_bind_suppressions_applies_only_to_adjacent_declaration_line() -> None:
    source = """
# noqa: codeclone[dead-code]
def kept() -> int:
    return 1

# noqa: codeclone[dead-code]

def not_bound() -> int:
    return 2
""".strip()
    directives = extract_noqa_directives(source)
    declarations = (
        DeclarationTarget(
            filepath="pkg/mod.py",
            qualname="pkg.mod:kept",
            start_line=2,
            end_line=3,
            kind="function",
        ),
        DeclarationTarget(
            filepath="pkg/mod.py",
            qualname="pkg.mod:not_bound",
            start_line=7,
            end_line=8,
            kind="function",
        ),
    )
    bindings = bind_suppressions_to_declarations(
        directives=directives,
        declarations=declarations,
    )
    assert bindings == (
        SuppressionBinding(
            filepath="pkg/mod.py",
            qualname="pkg.mod:kept",
            start_line=2,
            end_line=3,
            kind="function",
            rules=("dead-code",),
        ),
    )


def test_bind_suppressions_does_not_propagate_class_inline_to_method() -> None:
    source = """
class Demo:  # noqa: codeclone[dead-code]
    def method(self) -> int:
        return 1
""".strip()
    directives = extract_noqa_directives(source)
    declarations = (
        DeclarationTarget(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo",
            start_line=1,
            end_line=3,
            kind="class",
        ),
        DeclarationTarget(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo.method",
            start_line=2,
            end_line=3,
            kind="method",
        ),
    )
    bindings = bind_suppressions_to_declarations(
        directives=directives,
        declarations=declarations,
    )
    assert bindings == (
        SuppressionBinding(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo",
            start_line=1,
            end_line=3,
            kind="class",
            rules=("dead-code",),
        ),
    )


def test_bind_suppressions_applies_to_method_target() -> None:
    source = """
class Demo:
    # noqa: codeclone[dead-code]
    def method(self) -> int:
        return 1
""".strip()
    directives = extract_noqa_directives(source)
    declarations = (
        DeclarationTarget(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo",
            start_line=1,
            end_line=4,
            kind="class",
        ),
        DeclarationTarget(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo.method",
            start_line=3,
            end_line=4,
            kind="method",
        ),
    )
    bindings = bind_suppressions_to_declarations(
        directives=directives,
        declarations=declarations,
    )
    assert bindings == (
        SuppressionBinding(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo.method",
            start_line=3,
            end_line=4,
            kind="method",
            rules=("dead-code",),
        ),
    )


def test_build_suppression_index_deduplicates_rules_stably() -> None:
    bindings = (
        SuppressionBinding(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo.method",
            start_line=3,
            end_line=4,
            kind="method",
            rules=("dead-code",),
        ),
        SuppressionBinding(
            filepath="pkg/mod.py",
            qualname="pkg.mod:Demo.method",
            start_line=3,
            end_line=4,
            kind="method",
            rules=("dead-code", "clone-cohort-drift"),
        ),
    )
    index = build_suppression_index(bindings)
    key = suppression_target_key(
        filepath="pkg/mod.py",
        qualname="pkg.mod:Demo.method",
        start_line=3,
        end_line=4,
        kind="method",
    )
    assert index[key] == ("dead-code", "clone-cohort-drift")
