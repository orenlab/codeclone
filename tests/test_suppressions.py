# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import pytest

from codeclone.analysis.suppressions import (
    DeclarationTarget,
    SuppressionBinding,
    SuppressionDirective,
    bind_suppressions_to_declarations,
    build_suppression_index,
    extract_suppression_directives,
    suppression_target_key,
)


def test_extract_suppression_directives_supports_inline_and_leading_forms() -> None:
    source = """
# codeclone: ignore[dead-code]
def a() -> int:
    return 1

def b() -> int:  # codeclone: ignore[dead-code]
    return 2

class C:  # codeclone: ignore[dead-code]
    pass

# codeclone:   ignore [ dead-code , clone-cohort-drift ]
async def d() -> int:
    return 3
""".strip()
    directives = extract_suppression_directives(source)
    assert directives == (
        SuppressionDirective(line=1, binding="leading", rules=("dead-code",)),
        SuppressionDirective(line=5, binding="inline", rules=("dead-code",)),
        SuppressionDirective(line=8, binding="inline", rules=("dead-code",)),
        SuppressionDirective(
            line=11,
            binding="leading",
            rules=("dead-code", "clone-cohort-drift"),
        ),
    )


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
def a() -> int:  # codeclone: ignore[dead-code, dead-code, unknown-rule]
    return 1

def b() -> int:  # codeclone: ignore
    return 2

def c() -> int:  # codeclone: IGNORE[dead-code]
    return 3

def d() -> int:  # codeclone ignore[dead-code]
    return 4
""".strip(),
            id="unknown_and_malformed",
        ),
        pytest.param(
            """
def a() -> int:  # codeclone: ignore[dead-code, , invalid!, unknown-rule]
    return 1

def b() -> int:  # codeclone: ignore[unknown-rule]
    return 2
""".strip(),
            id="invalid_rule_tokens",
        ),
    ],
)
def test_extract_suppression_directives_ignores_invalid_forms(source: str) -> None:
    directives = extract_suppression_directives(source)
    assert directives == (
        SuppressionDirective(line=1, binding="inline", rules=("dead-code",)),
    )


def test_extract_suppression_directives_returns_empty_on_tokenize_error() -> None:
    # Unclosed triple quote triggers tokenize.TokenError and must be ignored safely.
    source = '"""\n# codeclone: ignore[dead-code]\n'
    assert extract_suppression_directives(source) == ()


@pytest.mark.parametrize(
    ("source", "declarations", "expected_bindings"),
    [
        pytest.param(
            """
# codeclone: ignore[dead-code]
def kept() -> int:
    return 1

# codeclone: ignore[dead-code]

def not_bound() -> int:
    return 2
""".strip(),
            (
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
            ),
            (
                SuppressionBinding(
                    filepath="pkg/mod.py",
                    qualname="pkg.mod:kept",
                    start_line=2,
                    end_line=3,
                    kind="function",
                    rules=("dead-code",),
                ),
            ),
            id="adjacent_leading_only",
        ),
        pytest.param(
            """
class Demo:  # codeclone: ignore[dead-code]
    def method(self) -> int:
        return 1
""".strip(),
            (
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
            ),
            (
                SuppressionBinding(
                    filepath="pkg/mod.py",
                    qualname="pkg.mod:Demo",
                    start_line=1,
                    end_line=3,
                    kind="class",
                    rules=("dead-code",),
                ),
            ),
            id="class_inline_does_not_propagate",
        ),
        pytest.param(
            """
class Demo:
    # codeclone: ignore[dead-code]
    def method(self) -> int:
        return 1
""".strip(),
            (
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
            ),
            (
                SuppressionBinding(
                    filepath="pkg/mod.py",
                    qualname="pkg.mod:Demo.method",
                    start_line=3,
                    end_line=4,
                    kind="method",
                    rules=("dead-code",),
                ),
            ),
            id="method_target",
        ),
    ],
)
def test_bind_suppressions_targets_expected_declaration_scope(
    source: str,
    declarations: tuple[DeclarationTarget, ...],
    expected_bindings: tuple[SuppressionBinding, ...],
) -> None:
    directives = extract_suppression_directives(source)
    bindings = bind_suppressions_to_declarations(
        directives=directives,
        declarations=declarations,
    )
    assert bindings == expected_bindings


def test_bind_suppressions_ignores_inline_comment_on_middle_signature_line() -> None:
    source = """
def keep(
    arg: int,  # codeclone: ignore[dead-code]
) -> int:
    return arg
""".strip()
    directives = extract_suppression_directives(source)
    declarations = (
        DeclarationTarget(
            filepath="pkg/mod.py",
            qualname="pkg.mod:keep",
            start_line=1,
            end_line=4,
            kind="function",
            declaration_end_line=3,
        ),
    )
    assert (
        bind_suppressions_to_declarations(
            directives=directives,
            declarations=declarations,
        )
        == ()
    )


@pytest.mark.parametrize(
    ("source", "declaration"),
    [
        pytest.param(
            """
@decorator
def keep(
    arg: int,
) -> int:  # codeclone: ignore[dead-code]
    return arg
""".strip(),
            DeclarationTarget(
                filepath="pkg/mod.py",
                qualname="pkg.mod:keep",
                start_line=2,
                end_line=5,
                kind="function",
                declaration_end_line=4,
            ),
            id="decorated_function_end_line",
        ),
        pytest.param(
            """
@decorator
def keep(  # codeclone: ignore[dead-code]
    arg: int,
) -> int:
    return arg
""".strip(),
            DeclarationTarget(
                filepath="pkg/mod.py",
                qualname="pkg.mod:keep",
                start_line=2,
                end_line=5,
                kind="function",
                declaration_end_line=4,
            ),
            id="decorated_function_start_line",
        ),
        pytest.param(
            """
async def keep_async(  # codeclone: ignore[dead-code]
    arg: int,
) -> int:
    return arg
""".strip(),
            DeclarationTarget(
                filepath="pkg/mod.py",
                qualname="pkg.mod:keep_async",
                start_line=1,
                end_line=4,
                kind="function",
                declaration_end_line=3,
            ),
            id="async_function_start_line",
        ),
        pytest.param(
            """
async def keep_async(
    arg: int,
) -> int:  # codeclone: ignore[dead-code]
    return arg
""".strip(),
            DeclarationTarget(
                filepath="pkg/mod.py",
                qualname="pkg.mod:keep_async",
                start_line=1,
                end_line=4,
                kind="function",
                declaration_end_line=3,
            ),
            id="async_function_end_line",
        ),
        pytest.param(
            """
class Demo(  # codeclone: ignore[dead-code]
    Base,
):
    pass
""".strip(),
            DeclarationTarget(
                filepath="pkg/mod.py",
                qualname="pkg.mod:Demo",
                start_line=1,
                end_line=4,
                kind="class",
                declaration_end_line=3,
            ),
            id="class_start_line",
        ),
        pytest.param(
            """
class Demo(
    Base,
):  # codeclone: ignore[dead-code]
    pass
""".strip(),
            DeclarationTarget(
                filepath="pkg/mod.py",
                qualname="pkg.mod:Demo",
                start_line=1,
                end_line=4,
                kind="class",
                declaration_end_line=3,
            ),
            id="class_end_line",
        ),
    ],
)
def test_bind_suppressions_supports_multiline_inline_on_supported_boundaries(
    source: str,
    declaration: DeclarationTarget,
) -> None:
    directives = extract_suppression_directives(source)
    bindings = bind_suppressions_to_declarations(
        directives=directives,
        declarations=(declaration,),
    )
    assert bindings == (
        SuppressionBinding(
            filepath=declaration.filepath,
            qualname=declaration.qualname,
            start_line=declaration.start_line,
            end_line=declaration.end_line,
            kind=declaration.kind,
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
