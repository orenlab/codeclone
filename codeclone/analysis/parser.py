# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import io
import math
import os
import signal
import tokenize
from contextlib import contextmanager
from typing import TYPE_CHECKING

from ..contracts.errors import ParseError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

PARSE_TIMEOUT_SECONDS = 5


class _ParseTimeoutError(Exception):
    pass


_DeclarationTokenIndexKey = tuple[int, int, str]
_DECLARATION_TOKEN_STRINGS = frozenset({"def", "async", "class"})


def _consumed_cpu_seconds(resource_module: object) -> float:
    """Return consumed CPU seconds for the current process."""
    try:
        usage = resource_module.getrusage(  # type: ignore[attr-defined]
            resource_module.RUSAGE_SELF  # type: ignore[attr-defined]
        )
        return float(usage.ru_utime) + float(usage.ru_stime)
    except Exception:
        return 0.0


@contextmanager
def _parse_limits(timeout_s: int) -> Iterator[None]:
    if os.name != "posix" or timeout_s <= 0:
        yield
        return

    old_handler = signal.getsignal(signal.SIGALRM)

    def _timeout_handler(_signum: int, _frame: object) -> None:
        raise _ParseTimeoutError("AST parsing timeout")

    old_limits: tuple[int, int] | None = None
    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)

        try:
            import resource

            old_limits = resource.getrlimit(resource.RLIMIT_CPU)
            soft, hard = old_limits
            consumed_cpu_s = _consumed_cpu_seconds(resource)
            desired_soft = max(1, timeout_s + math.ceil(consumed_cpu_s))
            if soft == resource.RLIM_INFINITY:
                candidate_soft = desired_soft
            else:
                # Never reduce finite soft limits and avoid immediate SIGXCPU
                # when the process already consumed more CPU than timeout_s.
                candidate_soft = max(soft, desired_soft)
            if hard == resource.RLIM_INFINITY:
                new_soft = candidate_soft
            else:
                new_soft = min(max(1, hard), candidate_soft)
            # Never lower hard limit: raising it back may be disallowed for
            # unprivileged processes and can lead to process termination later.
            resource.setrlimit(resource.RLIMIT_CPU, (new_soft, hard))
        except Exception:
            # If resource is unavailable or cannot be set, rely on alarm only.
            pass

        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_limits is not None:
            try:
                import resource

                resource.setrlimit(resource.RLIMIT_CPU, old_limits)
            except Exception:
                pass


_PARSE_LIMITS_IMPL = _parse_limits


def _parse_with_limits(source: str, timeout_s: int) -> ast.AST:
    try:
        with _parse_limits(timeout_s):
            return ast.parse(source)
    except _ParseTimeoutError as e:
        raise ParseError(str(e)) from e


_PARSE_WITH_LIMITS_IMPL = _parse_with_limits


def _source_tokens(source: str) -> tuple[tokenize.TokenInfo, ...]:
    try:
        return tuple(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return ()


_SOURCE_TOKENS_IMPL = _source_tokens


def _declaration_token_name(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async"
    return "def"


def _declaration_token_index(
    *,
    source_tokens: tuple[tokenize.TokenInfo, ...],
    start_line: int,
    start_col: int,
    declaration_token: str,
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None,
) -> int | None:
    if source_token_index is not None:
        return source_token_index.get((start_line, start_col, declaration_token))
    for idx, token in enumerate(source_tokens):
        if token.start != (start_line, start_col):
            continue
        if token.type == tokenize.NAME and token.string == declaration_token:
            return idx
    return None


def _build_declaration_token_index(
    source_tokens: tuple[tokenize.TokenInfo, ...],
) -> Mapping[_DeclarationTokenIndexKey, int]:
    indexed: dict[_DeclarationTokenIndexKey, int] = {}
    for idx, token in enumerate(source_tokens):
        if token.type == tokenize.NAME and token.string in _DECLARATION_TOKEN_STRINGS:
            indexed[(token.start[0], token.start[1], token.string)] = idx
    return indexed


def _scan_declaration_colon_line(
    *,
    source_tokens: tuple[tokenize.TokenInfo, ...],
    start_index: int,
) -> int | None:
    nesting = 0
    for token in source_tokens[start_index + 1 :]:
        if token.type == tokenize.OP:
            if token.string in "([{":
                nesting += 1
                continue
            if token.string in ")]}":
                if nesting > 0:
                    nesting -= 1
                continue
            if token.string == ":" and nesting == 0:
                return token.start[0]
        if token.type == tokenize.NEWLINE and nesting == 0:
            return None
    return None


def _fallback_declaration_end_line(node: ast.AST, *, start_line: int) -> int:
    body = getattr(node, "body", None)
    if not isinstance(body, list) or not body:
        return start_line

    first_body_line = int(getattr(body[0], "lineno", 0))
    if first_body_line <= 0 or first_body_line == start_line:
        return start_line
    return max(start_line, first_body_line - 1)


def _declaration_end_line(
    node: ast.AST,
    *,
    source_tokens: tuple[tokenize.TokenInfo, ...],
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None,
) -> int:
    start_line = int(getattr(node, "lineno", 0))
    start_col = int(getattr(node, "col_offset", 0))
    if start_line <= 0:
        return 0

    declaration_token = _declaration_token_name(node)
    start_index = _declaration_token_index(
        source_tokens=source_tokens,
        start_line=start_line,
        start_col=start_col,
        declaration_token=declaration_token,
        source_token_index=source_token_index,
    )
    if start_index is None:
        return _fallback_declaration_end_line(node, start_line=start_line)

    colon_line = _scan_declaration_colon_line(
        source_tokens=source_tokens,
        start_index=start_index,
    )
    if colon_line is not None:
        return colon_line
    return _fallback_declaration_end_line(node, start_line=start_line)
