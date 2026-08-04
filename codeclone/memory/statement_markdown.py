# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic Markdown-subset validation for memory statements.

Statements may carry a safe Markdown subset (one ``## `` title line, inline
code spans, bold/italic, depth-1 lists, compact tables, blockquotes, bare
URLs). The validator is hand-rolled line/regex rules — deterministic and
total: every input classifies, no input crashes. It is not a CommonMark
parser; security rules deliberately over-approximate what renderers treat
as active markup (fail-closed), and backtick code spans are the sanctioned
escape for literal markup fragments.

Records written through :func:`codeclone.memory.governance.record_candidate`
are stamped ``statement_format="md-v1"`` in the record payload; the absence
of the marker means plain text and renderers must not markdown-render it.
This marker rides the free-form payload JSON — no store schema change.
On the wire the marker is resolved per statement body through
:func:`resolve_statement_format`, which also derives md-v1 for unstamped
records carrying a leading validated ``## `` title — the stamp alone cannot
cover rows written by a server process that predated the stamping code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from ..models import StatementMarkdownIssue, StatementMarkdownReport

STATEMENT_FORMAT_MD: Final = "md-v1"
STATEMENT_FORMAT_PLAIN: Final = "plain"
STATEMENT_FORMAT_PAYLOAD_KEY: Final = "statement_format"

_HELP_MENTION: Final = 'help(topic="engineering_memory")'

STATEMENT_MD_REJECT_CODES: Final[tuple[str, ...]] = (
    "memory_md_heading_structure",
    "memory_md_html",
    "memory_md_image",
    "memory_md_link",
)
STATEMENT_MD_WARN_CODES: Final[tuple[str, ...]] = (
    "memory_md_heading_level",
    "memory_md_list_nesting",
)

_REJECT_MESSAGES: Final[dict[str, str]] = {
    "memory_md_image": (
        "memory_md_image: image syntax is not allowed in memory statements — "
        "a rendered image pings its URL (exfiltration channel). "
        "next_step: remove the image and cite evidence as a bare URL or a "
        "backtick code span, then retry "
        "manage_engineering_memory(action=record_candidate). "
        f"See {_HELP_MENTION}."
    ),
    "memory_md_html": (
        "memory_md_html: raw HTML is not allowed in memory statements — it "
        "injects into webview render surfaces. "
        "next_step: wrap literal markup in a backtick code span (`<tag>`) or "
        "rewrite it as text, then retry "
        "manage_engineering_memory(action=record_candidate). "
        f"See {_HELP_MENTION}."
    ),
    "memory_md_link": (
        "memory_md_link: [text](target) and reference-style links mask the "
        "target in rendered UI; bare URLs only (renderers autolink them). "
        "next_step: replace the link with its bare URL, then retry "
        "manage_engineering_memory(action=record_candidate). "
        f"See {_HELP_MENTION}."
    ),
    "memory_md_heading_structure": (
        "memory_md_heading_structure: a memory note carries at most one "
        "'## ' title and it must be the first content line. "
        "next_step: keep one leading '## ' title; split additional facts "
        "into separate manage_engineering_memory(action=record_candidate) "
        "calls. "
        f"See {_HELP_MENTION}."
    ),
}

_WARN_MESSAGES: Final[dict[str, str]] = {
    "memory_md_heading_level": (
        "memory_md_heading_level: use '## ' for the single title line — one "
        "card-level heading, no document hierarchy inside a memory note."
    ),
    "memory_md_list_nesting": (
        "memory_md_list_nesting: keep list nesting depth <= 1 (indent under "
        "6 spaces); flatten deeper structure or split the note."
    ),
}


_BACKTICK_RUN = re.compile(r"`+")

# Security class. Over-approximation is intentional: if a CommonMark renderer
# could treat the text as active markup, the write is refused (fail-closed).
_IMAGE = re.compile(r"!\[[^\]]*\]\s*[(\[]")
_INLINE_LINK = re.compile(r"\[[^\]]*\]\(")
_REFERENCE_LINK = re.compile(r"\[[^\]]+\]\[[^\]]*\]")
_LINK_DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:\s+\S")
_RAW_HTML = re.compile(
    r"<(?:[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>|/[A-Za-z][A-Za-z0-9-]*\s*>|!|\?)"
)

# Discipline class.
_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:\s|$)")
_SETEXT_H1_UNDERLINE = re.compile(r"^ {0,3}=+\s*$")
_LIST_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d{1,9}[.)])\s+")
_LIST_NESTING_WARN_INDENT: Final = 6


def _mask_code_spans(text: str) -> str:
    """Blank inline code-span content so literal markup never trips a rule.

    CommonMark pairing: a run of N backticks closes with the next run of
    exactly N. Unmatched runs stay literal. Newlines are preserved so line
    structure survives masking.
    """
    runs = [(match.start(), match.end()) for match in _BACKTICK_RUN.finditer(text)]
    chars = list(text)
    index = 0
    while index < len(runs):
        start, _end = runs[index]
        width = runs[index][1] - start
        for probe in range(index + 1, len(runs)):
            probe_start, probe_end = runs[probe]
            if probe_end - probe_start == width:
                for position in range(start, probe_end):
                    if chars[position] != "\n":
                        chars[position] = " "
                index = probe
                break
        index += 1
    return "".join(chars)


def _reject(code: str) -> StatementMarkdownIssue:
    return StatementMarkdownIssue(
        code=code,
        severity="reject",
        message=_REJECT_MESSAGES[code],
    )


def _warn(code: str) -> StatementMarkdownIssue:
    return StatementMarkdownIssue(
        code=code,
        severity="warn",
        message=_WARN_MESSAGES[code],
    )


def _security_issues(masked: str) -> list[StatementMarkdownIssue]:
    issues: list[StatementMarkdownIssue] = []
    if _IMAGE.search(masked):
        issues.append(_reject("memory_md_image"))
    without_images = _IMAGE.sub(lambda match: " " * len(match.group(0)), masked)
    if (
        _INLINE_LINK.search(without_images)
        or _REFERENCE_LINK.search(without_images)
        or any(_LINK_DEFINITION.match(line) for line in without_images.split("\n"))
    ):
        issues.append(_reject("memory_md_link"))
    if _RAW_HTML.search(masked):
        issues.append(_reject("memory_md_html"))
    return issues


def _heading_and_list_issues(masked: str) -> list[StatementMarkdownIssue]:
    lines = masked.split("\n")
    atx_headings: list[tuple[int, int]] = []
    setext_underline = False
    nested_list = False
    first_content_index: int | None = None
    for index, line in enumerate(lines):
        if first_content_index is None and line.strip():
            first_content_index = index
        atx = _ATX_HEADING.match(line)
        if atx:
            atx_headings.append((index, len(atx.group(1))))
            continue
        if (
            index > 0
            and _SETEXT_H1_UNDERLINE.match(line)
            and lines[index - 1].strip()
            and not _ATX_HEADING.match(lines[index - 1])
            and not _LIST_ITEM.match(lines[index - 1])
            and not lines[index - 1].lstrip().startswith(">")
            and "|" not in lines[index - 1]
        ):
            setext_underline = True
            continue
        list_item = _LIST_ITEM.match(line)
        if list_item:
            indent = len(list_item.group(1).expandtabs(4))
            if indent >= _LIST_NESTING_WARN_INDENT:
                nested_list = True
    issues: list[StatementMarkdownIssue] = []
    if len(atx_headings) > 1 or (
        len(atx_headings) == 1 and atx_headings[0][0] != first_content_index
    ):
        issues.append(_reject("memory_md_heading_structure"))
    if setext_underline or any(level != 2 for _, level in atx_headings):
        issues.append(_warn("memory_md_heading_level"))
    if nested_list:
        issues.append(_warn("memory_md_list_nesting"))
    return issues


def validate_statement_markdown(statement: str) -> StatementMarkdownReport:
    """Classify a statement against the allowed Markdown subset.

    Deterministic and total: fixed rule order, at most one issue per code,
    pure regex/line scanning over any ``str`` input.
    """
    masked = _mask_code_spans(statement)
    issues = _security_issues(masked)
    issues.extend(_heading_and_list_issues(masked))
    return StatementMarkdownReport(issues=tuple(issues))


def markdown_reject_error(report: StatementMarkdownReport) -> str:
    """Compose the typed contract-error text for a rejecting report."""
    return " | ".join(issue.message for issue in report.rejects)


def resolve_statement_format(
    statement: str,
    payload: Mapping[str, object] | None = None,
) -> str | None:
    """Decide the wire ``statement_format`` marker for one statement body.

    Returns ``"md-v1"`` or ``None`` (= plain: emit no key). Two honest
    sources, in order:

    1. The write-time payload stamp — authorship truth recorded by
       :func:`codeclone.memory.governance.record_candidate`.
    2. Structural derivation — a leading ``## `` title line on a statement
       the validator accepts is the md-v1 signature by construction. This
       heals records whose writer predated the stamp: a wave's memory notes
       are recorded through a server process older than the wave's own code,
       so the stamp alone can never cover the store.

    Statements without the leading title never derive: there is no
    unambiguous markdown-authorship signal, and legacy plain text must not
    be force-rendered. Rejecting reports (images, raw HTML, masked links,
    broken heading structure) stay plain, so the render-surface security
    bans hold for legacy rows too.
    """
    if (
        isinstance(payload, Mapping)
        and payload.get(STATEMENT_FORMAT_PAYLOAD_KEY) == STATEMENT_FORMAT_MD
    ):
        return STATEMENT_FORMAT_MD
    if (
        statement.startswith("## ")
        and not validate_statement_markdown(statement).rejects
    ):
        return STATEMENT_FORMAT_MD
    return None


__all__ = [
    "STATEMENT_FORMAT_MD",
    "STATEMENT_FORMAT_PAYLOAD_KEY",
    "STATEMENT_FORMAT_PLAIN",
    "STATEMENT_MD_REJECT_CODES",
    "STATEMENT_MD_WARN_CODES",
    "StatementMarkdownIssue",
    "StatementMarkdownReport",
    "markdown_reject_error",
    "resolve_statement_format",
    "validate_statement_markdown",
]
