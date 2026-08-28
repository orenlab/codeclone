# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Declared memory config keys must not out-promise what the code enforces.

``[tool.codeclone.memory]`` keys are a public contract: they are declared in
``codeclone/config/memory_defaults.py``, validated by
``codeclone/config/memory_specs.py``, materialized onto ``MemoryConfig``, and
documented in ``docs/reference/configuration.md``. Declaration and validation
alone make a key *accepted*, not *enforced* — a user who writes an accepted
but unowned key into ``pyproject.toml`` gets silence, not an error, and
nothing changes.

Measured on this tree: 7 of 30 ``MemoryConfig`` fields had no reader at all
outside ``codeclone/config/`` while the reference page described every one of
them as working.

Three failure classes are guarded here:

1. **Owner reachability.** ``memory.active_retention_days`` and
   ``memory.stale_retention_days`` must reach the retention owner in
   ``codeclone/memory/vacuum.py`` on the real vacuum path — not sit in a
   dataclass no caller consults.
2. **Withheld destructive policy.** Reaching the owner must not mean being
   applied. Age alone is not a ratified reason to delete live knowledge, so
   the owner must decline ``active``/``stale`` on every run. This is a
   standing regression guard: it is green today and stays green only while
   nothing wires an age-triggered DELETE onto those two statuses.
3. **Documentation honesty.** The reference page must mark exactly the
   unenforced keys as unenforced. The expected set is *re-derived* — from
   ``vacuum``'s own status tuples for retention, and from a mechanical AST
   scan for readers everywhere else — never restated as a literal list here,
   because a hand-maintained list is the drift it is meant to catch.

Deliberate design notes:

- The doc predicate is a union of two sources because "referenced" and
  "enforced" stopped being the same question once the retention keys gained
  a named owner that declines them. An AST-reader scan alone would call
  ``active_retention_days`` live the moment ``vacuum`` names it, and the doc
  would silently start over-promising again.
- The resolved config arrives through ``memory_fixtures`` rather than a direct
  ``codeclone.config.memory`` import: this module's subject is ring r2p, which
  may not reach into the r2 configuration package, and the fixture seam exists
  for exactly that reason.
- The vacuum probe uses a recording fake store rather than a round trip
  through SQLite: the claim under test is "no DELETE is *issued* for these
  statuses", and observing the issued calls pins that directly, without
  depending on which rows a fixture happened to contain.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from dataclasses import replace
from pathlib import Path
from typing import Final

import pytest

from codeclone.memory import vacuum as vacuum_module
from codeclone.memory.application import MemoryApplicationContext
from codeclone.memory.enums import MEMORY_STATUS_VALUES

from .memory_fixtures import memory_application_context

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_CONFIG_DOC: Final = _REPO_ROOT / "docs" / "reference" / "configuration.md"
_PACKAGE: Final = _REPO_ROOT / "codeclone"
_CONFIG_PACKAGE_PREFIX: Final = "codeclone/config/"

#: Marker the reference page must carry on a key nothing enforces.
_UNENFORCED_MARKER: Final = "**Not enforced.**"

_MEMORY_ROW_RE: Final = re.compile(r"^\|\s*`memory\.([a-z0-9_]+)`\s*\|(.*)\|\s*$")


class _RecordingStore:
    """Vacuum store double that records every issued delete."""

    def __init__(self) -> None:
        self.deleted_statuses: list[str] = []
        self.committed = False

    def delete_records_older_than(
        self,
        *,
        status: str,
        updated_before_utc: str,
        commit: bool,
    ) -> int:
        del updated_before_utc, commit
        self.deleted_statuses.append(status)
        return 0

    def commit(self) -> None:
        self.committed = True


@pytest.fixture(name="aggressive")
def _aggressive(tmp_path: Path) -> MemoryApplicationContext:
    """Every retention set to 0 days: the most destructive legal setting."""
    context = memory_application_context(tmp_path)
    return replace(
        context,
        config=replace(
            context.config,
            active_retention_days=0,
            stale_retention_days=0,
            draft_retention_days=0,
            rejected_retention_days=0,
            archived_retention_days=0,
        ),
    )


def _memory_config_field_names(context: MemoryApplicationContext) -> frozenset[str]:
    return frozenset(field.name for field in dataclasses.fields(context.config))


def _fields_read_outside_config_package(
    context: MemoryApplicationContext,
) -> frozenset[str]:
    """Mechanically inventory which MemoryConfig fields anything reads.

    Attribute name matching over the AST, not grep over text: the question is
    "does any module read this field", and a name-based AST walk answers it
    without a hand-maintained inventory of call sites.
    """
    field_names = _memory_config_field_names(context)
    seen: set[str] = set()
    for path in sorted(_PACKAGE.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith(_CONFIG_PACKAGE_PREFIX):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in field_names:
                seen.add(node.attr)
    return frozenset(seen)


def _expected_unenforced_keys(context: MemoryApplicationContext) -> frozenset[str]:
    """Re-derive the unenforced key set from code, never from a literal list."""
    withheld_retention = {
        f"{status}_retention_days"
        for status in getattr(vacuum_module, "RETENTION_UNENFORCED_STATUSES", ())
    }
    unread = _memory_config_field_names(context) - _fields_read_outside_config_package(
        context
    )
    return frozenset(withheld_retention | unread)


def _documented_memory_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in _CONFIG_DOC.read_text(encoding="utf-8").splitlines():
        match = _MEMORY_ROW_RE.match(line.strip())
        if match is not None:
            rows[match.group(1)] = match.group(2)
    return rows


def test_retention_status_tuples_partition_every_configured_retention_key(
    aggressive: MemoryApplicationContext,
) -> None:
    """Owner coverage is exhaustive: no configured retention silently absent.

    Pins the derivation rule rather than a literal roster, so adding a
    ``<status>_retention_days`` key without giving it an owner fails here.
    """
    enforced = set(vacuum_module.RETENTION_ENFORCED_STATUSES)
    unenforced = set(vacuum_module.RETENTION_UNENFORCED_STATUSES)

    assert not enforced & unenforced, "a status cannot be both enforced and not"

    configured = {
        status
        for status in MEMORY_STATUS_VALUES
        if f"{status}_retention_days" in _memory_config_field_names(aggressive)
    }
    assert enforced | unenforced == configured


def test_configured_retention_reaches_the_owner_for_withheld_statuses(
    aggressive: MemoryApplicationContext,
) -> None:
    """The value arrives at its owner even though no policy applies it."""
    config = replace(
        aggressive.config,
        active_retention_days=30,
        stale_retention_days=45,
    )

    assert vacuum_module.unenforced_retention_days(config) == {
        "active": 30,
        "stale": 45,
    }


def test_negative_retention_is_absent_rather_than_reported_as_withheld(
    aggressive: MemoryApplicationContext,
) -> None:
    """``-1`` means "keep forever", which is not a withheld policy."""
    config = replace(
        aggressive.config,
        active_retention_days=-1,
        stale_retention_days=7,
    )

    assert vacuum_module.unenforced_retention_days(config) == {"stale": 7}


def test_owner_declines_every_unratified_status(
    aggressive: MemoryApplicationContext,
) -> None:
    """The gate sits on the resolution path and fires for withheld statuses."""
    withheld = sorted(vacuum_module.RETENTION_UNENFORCED_STATUSES)
    assert withheld, "no status is withheld; the gate would be unreachable"

    resolved = {
        status: vacuum_module._retention_days_for_status(status, aggressive.config)
        for status in withheld
    }
    assert resolved == dict.fromkeys(withheld, None)


def test_owner_resolves_every_ratified_status(
    aggressive: MemoryApplicationContext,
) -> None:
    """The same gate must not swallow statuses whose policy is ratified."""
    ratified = sorted(vacuum_module.RETENTION_ENFORCED_STATUSES)
    assert ratified, "no status is enforced; the vacuum would be inert"

    resolved = {
        status: vacuum_module._retention_days_for_status(status, aggressive.config)
        for status in ratified
    }
    assert resolved == dict.fromkeys(ratified, 0)


def test_vacuum_issues_no_delete_for_active_or_stale(
    aggressive: MemoryApplicationContext,
) -> None:
    """Standing guard: age alone must never delete live or stale knowledge.

    Runs with every retention at its most destructive legal value, so a
    surviving ``active``/``stale`` delete cannot be blamed on configuration.
    """
    store = _RecordingStore()

    vacuum_module.run_memory_vacuum(store, aggressive.config, commit=True)  # type: ignore[arg-type]

    assert store.committed is True
    withheld = set(vacuum_module.RETENTION_UNENFORCED_STATUSES)
    assert not withheld & set(store.deleted_statuses)
    assert set(store.deleted_statuses) == set(vacuum_module.RETENTION_ENFORCED_STATUSES)


def test_configuration_doc_marks_exactly_the_unenforced_memory_keys(
    aggressive: MemoryApplicationContext,
) -> None:
    """The reference page must not promise a key that nothing enforces."""
    rows = _documented_memory_rows()
    expected = _expected_unenforced_keys(aggressive)
    assert expected, "nothing derived as unenforced; the pin would be vacuous"

    undocumented = sorted(expected - rows.keys())
    assert not undocumented, (
        "unenforced keys missing from the configuration reference table: "
        f"{undocumented}"
    )

    marked = {key for key, cell in rows.items() if _UNENFORCED_MARKER in cell}
    over_promised = sorted(expected - marked)
    assert not over_promised, (
        "configuration.md describes these keys as working, but nothing "
        f"enforces them: {over_promised}"
    )
    under_promised = sorted(marked - expected)
    assert not under_promised, (
        "configuration.md marks these keys unenforced, but code does enforce "
        f"them: {under_promised}"
    )
