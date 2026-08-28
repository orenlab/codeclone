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
4. **Authority edge.** A configuration key is enforced only if a structural
   path exists from its canonical config owner to the production decision it
   claims to control. Validation, documentation, reporting, or a field on a
   policy object are not enforcement witnesses. The vacuum must therefore take
   its governed population *from* :class:`MemoryRetentionPolicy`, not restate
   one of its own.

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
- The authority edge is pinned by *substituting the owner*, not by reading
  source text and not by watching a private helper. It was measured that
  reverting the vacuum loop to a literal ``("draft", "rejected", "archived")``
  leaves every public-API observation byte-identical — same delete calls, same
  commit, same ``VacuumReport`` — because a withheld status contributes
  nothing downstream by construction. While ``VacuumReport`` is fixed no
  public-API pin for this axis can exist, so the discriminating witness is the
  edge itself: hand the vacuum a policy governing a population no inlined list
  could restate, and require the vacuum to follow it.
- That formulation survives legitimate renaming. It couples only to the
  declared owner and the two questions the vacuum may ask it, never to the
  spelling of a loop or the name of a private helper, and it fails only when
  the edge is severed.
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


class _RecordingPolicy:
    """Stand-in retention owner that records what the vacuum asked it.

    Its population is deliberately disjoint from the ratified statuses, so a
    consumer that restates a population of its own cannot accidentally agree
    with it.
    """

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.enforced: tuple[str, ...] = ("active", "superseded")
        self.withheld: tuple[str, ...] = ("historical",)

    @property
    def governed_statuses(self) -> tuple[str, ...]:
        return (*self.enforced, *self.withheld)

    def deletion_days(self, status: str) -> int | None:
        self.asked.append(status)
        return 0 if status in self.enforced else None


def test_governed_population_is_derived_from_the_config_keys(
    aggressive: MemoryApplicationContext,
) -> None:
    """The config edge: the owner governs exactly the keys config declares."""
    policy = vacuum_module.MemoryRetentionPolicy.from_config(aggressive.config)

    assert not set(policy.enforced) & set(policy.withheld), (
        "a status cannot be both ratified and withheld"
    )

    configured = {
        status
        for status in MEMORY_STATUS_VALUES
        if f"{status}_retention_days" in _memory_config_field_names(aggressive)
    }
    assert set(policy.governed_statuses) == configured


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


def test_owner_declines_every_withheld_status(
    aggressive: MemoryApplicationContext,
) -> None:
    """Withheld statuses resolve to no permitted deletion age."""
    policy = vacuum_module.MemoryRetentionPolicy.from_config(aggressive.config)
    withheld = sorted(policy.withheld)
    assert withheld, "nothing is withheld; the decision would be vacuous"

    resolved = {status: policy.deletion_days(status) for status in withheld}
    assert resolved == dict.fromkeys(withheld, None)


def test_owner_permits_every_ratified_status(
    aggressive: MemoryApplicationContext,
) -> None:
    """The same decision must not swallow the statuses whose policy is set."""
    policy = vacuum_module.MemoryRetentionPolicy.from_config(aggressive.config)
    ratified = sorted(policy.enforced)
    assert ratified, "nothing is ratified; the vacuum would be inert"

    resolved = {status: policy.deletion_days(status) for status in ratified}
    assert resolved == dict.fromkeys(ratified, 0)


def test_governed_status_without_a_configured_key_has_no_retention() -> None:
    """A status the policy governs but configuration does not carry.

    Keeps the "no configured value" arm of the owner reachable: without an
    input that lands on it, the arm would be unreachable prose rather than a
    rule, which is the same defect class this module exists to catch.
    """
    policy = vacuum_module.MemoryRetentionPolicy(
        enforced=("draft",),
        withheld=("historical",),
        days_by_status={"draft": 5},
    )

    assert policy.configured_days("historical") is None
    assert policy.deletion_days("historical") is None
    assert policy.withheld_days() == {}
    assert policy.deletion_days("draft") == 5


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


def test_vacuum_takes_its_population_from_the_policy_owner(
    aggressive: MemoryApplicationContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authority edge: change the owner and the vacuum must follow.

    The owner is replaced by one governing statuses that appear in no ratified
    list. A vacuum that reads its population from the owner asks about exactly
    those and deletes exactly the owner's ratified subset. A vacuum that
    restates a population of its own keeps deleting the same rows in
    production — observably identical — yet cannot follow the substitution,
    and fails here.
    """
    probe = _RecordingPolicy()
    monkeypatch.setattr(
        vacuum_module.MemoryRetentionPolicy,
        "from_config",
        classmethod(lambda cls, config: probe),
    )
    store = _RecordingStore()

    vacuum_module.run_memory_vacuum(store, aggressive.config, commit=True)  # type: ignore[arg-type]

    assert tuple(probe.asked) == probe.governed_statuses, (
        "the vacuum did not take its population from the policy owner: the "
        "authority edge config -> retention policy -> vacuum is severed"
    )
    assert store.deleted_statuses == list(probe.enforced)


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
