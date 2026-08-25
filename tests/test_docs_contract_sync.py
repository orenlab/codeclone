# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Governance docs must not drift from the versioned contracts.

Two failure classes are guarded:

1. Symbol existence: when AGENTS.md or docs/internal claims that a
   backticked ``_UPPER_SNAKE`` identifier lives in a specific ``*.py``
   module, that module must exist and define/mention the identifier.
   (This caught AGENTS.md describing a nonexistent
   ``_BASELINE_SCHEMA_MAX_MINOR_BY_MAJOR`` in ``codeclone/baseline/trust.py``.)
2. Version-literal sync: when those docs quote a value next to the name
   of a version constant from ``codeclone/contracts/__init__.py``, the
   quoted value must equal the live constant.

Design constraints, deliberately conservative:

- Claims are compared against the live ``codeclone.contracts`` module —
  a hand-maintained inventory would itself drift.
- Only ``*VERSION*`` constants participate in value sync; ``DEFAULT_*``
  thresholds and digest domains are excluded because docs legitimately
  discuss them in non-current contexts.
- Subsystem-local wire constants (owned outside ``codeclone/contracts``)
  are covered by the symbol-existence check only; syncing their values
  would require an inventory of owning modules, which would drift.
- Symbol existence is scoped to AGENTS.md + docs/internal/**.
- Version-literal sync additionally covers docs/reference/**, because the
  matcher only fires on a claim that *names* the constant, and a public
  reference page naming `REPORT_SCHEMA_VERSION` is quoting the schema, not
  a package release. (This caught docs/reference/json-output.md quoting
  `REPORT_SCHEMA_VERSION: 3.1` after the contract moved to 3.2.)
- CHANGELOG and the remaining public docs are not scanned: CHANGELOG
  entries are historical by design, and narrative pages carry
  package-release versions this matcher must not reinterpret as schema
  versions.
- The matcher recognizes only explicit claim shapes (``NAME=value``,
  ``NAME: value``, ``NAME ("value")``, the appositive ``NAME, currently
  value`` / ``NAME (currently value)``, and table rows naming exactly one
  constant). Prose like "schema v3.0" without a constant name is out of
  scope: fewer claims checked reliably beats false positives.

The appositive shape was added after it was measured walking through.
json-output.md carried the *same* stale version twice — the colon form on
line 11 and the appositive on line 46 — and one edit repaired both, so a
mutation that reverted only the colon form still died and the guard looked
whole. A page can state a constant more than once; a claim shape this
matcher cannot see is not absent, only unmeasured.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

import codeclone.contracts as contracts
from codeclone.report.document._common import _clone_novelty
from codeclone.report.document._findings_groups import (
    build_near_miss_payload,
    build_renamed_structure_payload,
)

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_AGENTS_DOC: Final = _REPO_ROOT / "AGENTS.md"
_DOCS_INTERNAL: Final = _REPO_ROOT / "docs" / "internal"
_DOCS_REFERENCE: Final = _REPO_ROOT / "docs" / "reference"
_JSON_OUTPUT_DOC: Final = _DOCS_REFERENCE / "json-output.md"

pytestmark = pytest.mark.skipif(
    not _AGENTS_DOC.is_file() or not _DOCS_INTERNAL.is_dir(),
    reason="repo docs source tree is not present",
)

_UPPER_SNAKE_RE: Final = re.compile(r"\b(_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")
# Explicit, minimal exclusions from version-literal sync. Each entry is
# (doc path, constant name, quoted value) with a justification:
# - memory-schema.md quotes a hypothetical FUTURE bump of
#   ENGINEERING_MEMORY_SCHEMA_VERSION to "1.8" inside a failure-mode
#   narrative ("Code bumps ... adds column X via migration"); it is a
#   what-if example, not a claim about the current value.
_VERSION_CLAIM_EXCLUSIONS: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        (
            "docs/internal/contracts/memory-schema.md",
            "ENGINEERING_MEMORY_SCHEMA_VERSION",
            "1.8",
        ),
    }
)
_SYMBOL_IN_MODULE_RE: Final = re.compile(
    r"`(_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`\s+(?:in|from)\s+`([^`]+\.py)`"
)
_TABLE_SYMBOL_RE: Final = re.compile(r"`(_?[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)`")
_TABLE_MODULE_RE: Final = re.compile(r"`([A-Za-z0-9_./-]+\.py)`")
# X or X.Y version literals; two-dot tokens (package releases like
# 2.1.0a1) never match, which keeps release versions out of schema sync.
_WHOLE_CELL_VERSION_RE: Final = re.compile(r"\d+(?:\.\d+)?|[a-z]+-v\d+")
_DOTTED_TOKEN_RE: Final = re.compile(r"\d+\.\d+")


def _governance_doc_paths() -> tuple[Path, ...]:
    return (_AGENTS_DOC, *sorted(_DOCS_INTERNAL.rglob("*.md")))


def _version_claim_doc_paths() -> tuple[Path, ...]:
    """Governance docs plus the public reference pages.

    A reference page that names a contract constant is quoting the contract,
    so it drifts exactly like an internal one. Narrative public pages stay
    out: they quote release versions this matcher must not reinterpret.
    """

    reference = () if not _DOCS_REFERENCE.is_dir() else _DOCS_REFERENCE.rglob("*.md")
    return (*_governance_doc_paths(), *sorted(reference))


def _contract_versions() -> dict[str, str]:
    """Live version constants, read from the single source of truth."""

    values: dict[str, str] = {}
    for name in contracts.__all__:
        if "VERSION" not in name or not name.isupper():
            continue
        value = getattr(contracts, name)
        if isinstance(value, (str, int)):
            values[name] = str(value)
    return values


def _strip_cell_decorations(cell: str) -> str:
    return cell.strip().strip("`").strip('"').strip("'").strip("*").strip()


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _cell_version_token(cell: str) -> str | None:
    stripped = _strip_cell_decorations(cell)
    if _WHOLE_CELL_VERSION_RE.fullmatch(stripped):
        return stripped
    for token in stripped.split():
        candidate = token.strip("`\"'()")
        if _DOTTED_TOKEN_RE.fullmatch(candidate):
            return candidate
    return None


def _claimed_versions_in_line(
    line: str, names: frozenset[str]
) -> list[tuple[str, str]]:
    present = [
        match.group(1)
        for match in _UPPER_SNAKE_RE.finditer(line)
        if match.group(1) in names
    ]
    claims: list[tuple[str, str]] = []
    for name in sorted(set(present)):
        assign_re = re.compile(
            rf"{name}[`\"]?\s*[=:]\s*[`\"]?([A-Za-z0-9][A-Za-z0-9._-]*)"
        )
        claims.extend(
            (name, match.group(1).rstrip('`"')) for match in assign_re.finditer(line)
        )
        paren_re = re.compile(rf"{name}`?\s*\(\"([^\"]+)\"\)")
        claims.extend((name, match.group(1)) for match in paren_re.finditer(line))
        # Appositive: the value trails the name in prose instead of sitting
        # behind `=` or `:`. One optional separator covers both spellings,
        # `NAME, currently V` and `NAME (currently V)`.
        currently_re = re.compile(
            rf"{name}[`\"]?\s*[,(]?\s*currently\s+[`\"]?"
            rf"([A-Za-z0-9][A-Za-z0-9._-]*)",
            re.IGNORECASE,
        )
        claims.extend(
            (name, match.group(1).rstrip('`"')) for match in currently_re.finditer(line)
        )
    if line.lstrip().startswith("|") and len(set(present)) == 1:
        name = present[0]
        for cell in _table_cells(line):
            if name in cell:
                continue
            token = _cell_version_token(cell)
            if token is not None:
                claims.append((name, token))
    return claims


def _symbol_module_claims_in_line(line: str) -> list[tuple[str, str]]:
    claims = [
        (match.group(1), match.group(2))
        for match in _SYMBOL_IN_MODULE_RE.finditer(line)
    ]
    if line.lstrip().startswith("|"):
        symbols = sorted({match.group(1) for match in _TABLE_SYMBOL_RE.finditer(line)})
        modules = sorted({match.group(1) for match in _TABLE_MODULE_RE.finditer(line)})
        if len(symbols) == 1 and len(modules) == 1:
            claims.append((symbols[0], modules[0]))
    return sorted(set(claims))


def test_documented_module_symbols_exist() -> None:
    """A doc that binds a symbol to a module must describe real code."""

    violations: list[str] = []
    for doc_path in _governance_doc_paths():
        rel_doc = doc_path.relative_to(_REPO_ROOT).as_posix()
        for line_no, line in enumerate(
            doc_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for symbol, module in _symbol_module_claims_in_line(line):
                module_path = _REPO_ROOT / module
                if not module_path.is_file():
                    violations.append(
                        f"{rel_doc}:{line_no}: `{symbol}` claimed in "
                        f"`{module}`, but that module does not exist"
                    )
                    continue
                module_text = module_path.read_text(encoding="utf-8")
                if re.search(rf"\b{re.escape(symbol)}\b", module_text) is None:
                    violations.append(
                        f"{rel_doc}:{line_no}: `{symbol}` claimed in "
                        f"`{module}`, but the module does not mention it"
                    )
    assert not violations, "docs claim nonexistent symbols:\n" + "\n".join(violations)


def test_documented_version_literals_match_contracts() -> None:
    """A doc that quotes a versioned constant must quote the live value."""

    versions = _contract_versions()
    names = frozenset(versions)
    violations: list[str] = []
    for doc_path in _version_claim_doc_paths():
        rel_doc = doc_path.relative_to(_REPO_ROOT).as_posix()
        for line_no, line in enumerate(
            doc_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for name, quoted in _claimed_versions_in_line(line, names):
                if (rel_doc, name, quoted) in _VERSION_CLAIM_EXCLUSIONS:
                    continue
                if quoted != versions[name]:
                    violations.append(
                        f"{rel_doc}:{line_no}: {name} quoted as "
                        f"{quoted!r}, live value is {versions[name]!r}"
                    )
    assert not violations, "docs quote stale contract versions:\n" + "\n".join(
        violations
    )


def test_json_output_doc_states_every_novelty_word_the_producers_emit() -> None:
    """The JSON reference must not narrow `novelty` to `new` / `known`.

    Three producers own the word, and two of them cannot say `new` or
    `known` at all: the near-miss and renamed-structure containers reach no
    baseline lane, so they emit `untracked`, and a clone lane that was not
    compared emits `unavailable` rather than guessing. A reference page that
    lists only `new` / `known` tells a reader to filter on a vocabulary the
    report does not use — the same reader who then reads an absent
    comparison as "nothing new".

    The vocabulary is re-derived from the producers here rather than
    restated, so adding a fourth novelty word reds this test instead of
    silently leaving the page a word short.
    """

    emitted = {
        str(build_near_miss_payload([], scan_root=".")["novelty"]),
        str(build_renamed_structure_payload([], scan_root=".")["novelty"]),
        _clone_novelty(group_key="k", lane_trusted=False, new_keys=None)[0],
        _clone_novelty(group_key="k", lane_trusted=True, new_keys=None)[0],
        _clone_novelty(group_key="k", lane_trusted=True, new_keys=["k"])[0],
        _clone_novelty(group_key="k", lane_trusted=True, new_keys=[])[0],
    }
    # The producers really do speak more than the two words the page listed.
    assert emitted == {"untracked", "unavailable", "new", "known"}

    doc_text = _JSON_OUTPUT_DOC.read_text(encoding="utf-8")
    missing = sorted(word for word in emitted if f"`{word}`" not in doc_text)
    assert not missing, (
        f"docs/reference/json-output.md omits novelty words the report emits: {missing}"
    )
