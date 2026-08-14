#!/usr/bin/env python
"""Policy lint for the AGENTS.md authority model (AUTH2).

AUTH1 states that every obligation belongs to exactly one owning rule block, that
only text inside such a block is normative, and that obligations are expressed with
RFC-2119 uppercase modality. Until this lint runs, that property is asserted by hand.

The lint reds on four conditions, one per guarantee AUTH2 declares:

    modal_outside_block     an RFC-2119 uppercase modal outside any owning block
    duplicate_owner         one rule id opening two disjoint blocks
    block_without_modal     an owning block that states no obligation
    undefined_id_citation   a cited rule id that no block defines

A block opens on a line of the form ``**ID — title.**`` or ``**ID** — title`` and runs
until the next block opening, the next Markdown heading, or end of file.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

RULE_ID = r"[A-Z]{1,6}[0-9]{1,2}"

_BLOCK_OPENING = re.compile(rf"^\*\*(?P<rule_id>{RULE_ID})(?:\*\*)?\s*[—-]")
_HEADING = re.compile(r"^#{1,6}\s")
_MODAL = re.compile(r"\b(MUST NOT|MUST|MAY)\b")
_CITATION = re.compile(
    rf"(?:`(?P<backticked>{RULE_ID}(?:\.[0-9]+)?)`|\((?P<parenthesized>{RULE_ID}(?:\.[0-9]+)?)\))"
)


class ViolationKind(str, Enum):
    """The four conditions AUTH2 requires the lint to red on."""

    MODAL_OUTSIDE_BLOCK = "modal_outside_block"
    DUPLICATE_OWNER = "duplicate_owner"
    BLOCK_WITHOUT_MODAL = "block_without_modal"
    UNDEFINED_ID_CITATION = "undefined_id_citation"


@dataclass(frozen=True)
class Violation:
    """One authority-model defect, located at a one-based line."""

    kind: ViolationKind
    line: int
    detail: str
    rule_id: str | None = None
    modal: str | None = None


@dataclass(frozen=True)
class _Block:
    rule_id: str
    start: int
    end: int


def _find_blocks(lines: Sequence[str]) -> list[_Block]:
    """Locate every owning block and the extent of text it governs."""
    openings: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _BLOCK_OPENING.match(line)
        if match is not None:
            openings.append((index, match.group("rule_id")))

    boundaries = {index for index, _ in openings}
    boundaries.update(index for index, line in enumerate(lines) if _HEADING.match(line))

    blocks: list[_Block] = []
    for start, rule_id in openings:
        following = [index for index in boundaries if index > start]
        end = min(following) if following else len(lines)
        blocks.append(_Block(rule_id=rule_id, start=start, end=end))
    return blocks


def _owned_lines(blocks: Sequence[_Block]) -> set[int]:
    owned: set[int] = set()
    for block in blocks:
        owned.update(range(block.start, block.end))
    return owned


def _modal_violations(lines: Sequence[str], owned: set[int]) -> list[Violation]:
    violations: list[Violation] = []
    for index, line in enumerate(lines):
        if index in owned:
            continue
        match = _MODAL.search(line)
        if match is None:
            continue
        modal = match.group(1)
        violations.append(
            Violation(
                kind=ViolationKind.MODAL_OUTSIDE_BLOCK,
                line=index + 1,
                detail=f"obligation '{modal}' stated outside any owning rule block",
                modal=modal,
            )
        )
    return violations


def _duplicate_owner_violations(blocks: Sequence[_Block]) -> list[Violation]:
    seen: dict[str, int] = {}
    violations: list[Violation] = []
    for block in blocks:
        first = seen.get(block.rule_id)
        if first is None:
            seen[block.rule_id] = block.start
            continue
        violations.append(
            Violation(
                kind=ViolationKind.DUPLICATE_OWNER,
                line=block.start + 1,
                detail=(
                    f"rule id '{block.rule_id}' already opens a block "
                    f"at line {first + 1}"
                ),
                rule_id=block.rule_id,
            )
        )
    return violations


def _empty_block_violations(
    lines: Sequence[str], blocks: Sequence[_Block]
) -> list[Violation]:
    violations: list[Violation] = []
    for block in blocks:
        body = lines[block.start : block.end]
        if any(_MODAL.search(line) for line in body):
            continue
        violations.append(
            Violation(
                kind=ViolationKind.BLOCK_WITHOUT_MODAL,
                line=block.start + 1,
                detail=(
                    f"block '{block.rule_id}' declares an owner "
                    "but states no obligation"
                ),
                rule_id=block.rule_id,
            )
        )
    return violations


def _citation_violations(
    lines: Sequence[str], blocks: Sequence[_Block]
) -> list[Violation]:
    defined = {block.rule_id for block in blocks}
    opening_lines = {block.start for block in blocks}
    violations: list[Violation] = []
    for index, line in enumerate(lines):
        if index in opening_lines:
            continue
        for match in _CITATION.finditer(line):
            cited = match.group("backticked") or match.group("parenthesized")
            if cited.split(".", 1)[0] not in defined:
                violations.append(
                    Violation(
                        kind=ViolationKind.UNDEFINED_ID_CITATION,
                        line=index + 1,
                        detail=f"cited rule id '{cited}' has no defining block",
                        rule_id=cited,
                    )
                )
    return violations


def lint_text(text: str) -> list[Violation]:
    """Return every authority-model violation in ``text``, ordered by location."""
    lines = text.splitlines()
    blocks = _find_blocks(lines)
    owned = _owned_lines(blocks)

    violations = [
        *_modal_violations(lines, owned),
        *_duplicate_owner_violations(blocks),
        *_empty_block_violations(lines, blocks),
        *_citation_violations(lines, blocks),
    ]
    return sorted(
        violations, key=lambda violation: (violation.line, violation.kind.value)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Lint each named file; return 1 when any violation was found."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    arguments = parser.parse_args(argv)

    total = 0
    for path in sorted(arguments.paths):
        violations = lint_text(path.read_text(encoding="utf-8"))
        total += len(violations)
        for violation in violations:
            print(
                f"{path}:{violation.line}: {violation.kind.value}: {violation.detail}"
            )

    if total:
        print(f"\n{total} authority-model violation(s); see AUTH1/AUTH2 in AGENTS.md")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
