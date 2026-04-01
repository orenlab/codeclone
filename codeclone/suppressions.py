# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

DEAD_CODE_RULE_ID: Final[str] = "dead-code"
SUPPORTED_RULE_IDS: Final[frozenset[str]] = frozenset(
    {
        DEAD_CODE_RULE_ID,
        "clone-cohort-drift",
        "clone-guard-exit-divergence",
    }
)

DirectiveBindingKind = Literal["inline", "leading"]
DeclarationKind = Literal["function", "method", "class"]
SuppressionSource = Literal["inline_codeclone"]
INLINE_CODECLONE_SUPPRESSION_SOURCE: Final[SuppressionSource] = "inline_codeclone"
SuppressionTargetKey = tuple[str, str, int, int, DeclarationKind]

_SUPPRESSION_DIRECTIVE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^\s*#\s*codeclone\s*:\s*ignore\s*\[(?P<rules>[^\]]+)\]\s*$"
)
_RULE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]*$")

__all__ = [
    "DEAD_CODE_RULE_ID",
    "INLINE_CODECLONE_SUPPRESSION_SOURCE",
    "SUPPORTED_RULE_IDS",
    "DeclarationKind",
    "DeclarationTarget",
    "DirectiveBindingKind",
    "SuppressionBinding",
    "SuppressionDirective",
    "SuppressionTargetKey",
    "bind_suppressions_to_declarations",
    "build_suppression_index",
    "extract_suppression_directives",
    "suppression_target_key",
]


@dataclass(frozen=True, slots=True)
class SuppressionDirective:
    line: int
    binding: DirectiveBindingKind
    rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeclarationTarget:
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    kind: DeclarationKind
    declaration_end_line: int | None = None


@dataclass(frozen=True, slots=True)
class SuppressionBinding:
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    kind: DeclarationKind
    rules: tuple[str, ...]
    source: SuppressionSource = "inline_codeclone"


def _merge_rules(
    base: tuple[str, ...],
    incoming: Sequence[str],
) -> tuple[str, ...]:
    if not incoming:
        return base
    seen = set(base)
    merged = list(base)
    for rule_id in incoming:
        if rule_id in seen:
            continue
        seen.add(rule_id)
        merged.append(rule_id)
    return tuple(merged)


def _parse_rule_ids(
    raw: str,
    *,
    supported_rules: frozenset[str],
) -> tuple[str, ...]:
    parsed: tuple[str, ...] = ()
    for token in raw.split(","):
        rule_id = token.strip()
        if not rule_id:
            continue
        if _RULE_ID_PATTERN.fullmatch(rule_id) is None:
            continue
        if rule_id not in supported_rules:
            continue
        parsed = _merge_rules(parsed, (rule_id,))
    return parsed


def extract_suppression_directives(
    source: str,
    *,
    supported_rules: frozenset[str] = SUPPORTED_RULE_IDS,
) -> tuple[SuppressionDirective, ...]:
    # Fast-path: skip tokenization when no directive marker exists.
    # Every valid directive contains the literal "codeclone:" — if absent,
    # no comment can match _SUPPRESSION_DIRECTIVE_PATTERN.
    if "codeclone:" not in source:
        return ()
    lines = source.splitlines()
    directives: list[SuppressionDirective] = []

    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            match = _SUPPRESSION_DIRECTIVE_PATTERN.fullmatch(token.string)
            if match is None:
                continue
            parsed_rules = _parse_rule_ids(
                match.group("rules"),
                supported_rules=supported_rules,
            )
            if not parsed_rules:
                continue

            line_no = token.start[0]
            col_no = token.start[1]
            line_text = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
            binding: DirectiveBindingKind = (
                "inline" if line_text[:col_no].strip() else "leading"
            )
            directives.append(
                SuppressionDirective(
                    line=line_no,
                    binding=binding,
                    rules=parsed_rules,
                )
            )
    except tokenize.TokenError:
        return ()

    return tuple(
        sorted(
            directives,
            key=lambda item: (item.line, item.binding, item.rules),
        )
    )


def _declaration_inline_lines(target: DeclarationTarget) -> tuple[int, ...]:
    end_line = target.declaration_end_line or target.start_line
    if end_line <= 0 or end_line == target.start_line:
        return (target.start_line,)
    return (target.start_line, end_line)


def _bound_inline_rules(
    *,
    target: DeclarationTarget,
    inline_rules_by_line: Mapping[int, tuple[str, ...]],
) -> tuple[str, ...]:
    rules: tuple[str, ...] = ()
    for line_no in _declaration_inline_lines(target):
        rules = _merge_rules(rules, inline_rules_by_line.get(line_no, ()))
    return rules


def bind_suppressions_to_declarations(
    *,
    directives: Sequence[SuppressionDirective],
    declarations: Sequence[DeclarationTarget],
) -> tuple[SuppressionBinding, ...]:
    leading_rules_by_line: dict[int, tuple[str, ...]] = {}
    inline_rules_by_line: dict[int, tuple[str, ...]] = {}

    for directive in directives:
        target_map = (
            inline_rules_by_line
            if directive.binding == "inline"
            else leading_rules_by_line
        )
        existing = target_map.get(directive.line, ())
        target_map[directive.line] = _merge_rules(existing, directive.rules)

    bindings: list[SuppressionBinding] = []
    for target in declarations:
        bound_rules = _merge_rules(
            leading_rules_by_line.get(target.start_line - 1, ()),
            _bound_inline_rules(
                target=target,
                inline_rules_by_line=inline_rules_by_line,
            ),
        )
        if not bound_rules:
            continue
        bindings.append(
            SuppressionBinding(
                filepath=target.filepath,
                qualname=target.qualname,
                start_line=target.start_line,
                end_line=target.end_line,
                kind=target.kind,
                rules=bound_rules,
            )
        )

    return tuple(
        sorted(
            bindings,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.kind,
                item.rules,
            ),
        )
    )


def suppression_target_key(
    *,
    filepath: str,
    qualname: str,
    start_line: int,
    end_line: int,
    kind: DeclarationKind,
) -> SuppressionTargetKey:
    return (filepath, qualname, start_line, end_line, kind)


def build_suppression_index(
    bindings: Sequence[SuppressionBinding],
) -> Mapping[SuppressionTargetKey, tuple[str, ...]]:
    index: dict[SuppressionTargetKey, tuple[str, ...]] = {}
    for binding in bindings:
        key = suppression_target_key(
            filepath=binding.filepath,
            qualname=binding.qualname,
            start_line=binding.start_line,
            end_line=binding.end_line,
            kind=binding.kind,
        )
        existing = index.get(key, ())
        index[key] = _merge_rules(existing, binding.rules)
    return index
