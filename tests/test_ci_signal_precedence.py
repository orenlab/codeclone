# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Who wins, the explicit setting or the detected CI: one table per consumer.

The launchers now carry CI into the MCP process, so every consumer of
``codeclone.utils.ci.is_ci_environment`` sees it there too. The consumers
resolve the conflict differently, and these tables pin each rule as it
stands -- every row written out, none derived -- so a change to any of them
is a decision someone makes, not a drift. ``CI=false`` is a CI marker: the
owner treats any non-empty value as CI. The projection-job rule lives in
``test_ci_signal_precedence_projection_jobs.py`` (another architecture ring).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.observability import resolve_observability_config
from codeclone.core.canonical_snapshot import resolve_run_store_config

_UNSET = None

# (ENABLED, CI, FORCE) -> enabled.  The run store: CI switches an enabled
# store off; FORCE keeps it on in CI and enables nothing by itself.
_RUN_STORE_TABLE = (
    (_UNSET, _UNSET, _UNSET, False),
    (_UNSET, _UNSET, "1", False),
    (_UNSET, "true", _UNSET, False),
    (_UNSET, "true", "1", False),
    (_UNSET, "false", _UNSET, False),
    (_UNSET, "false", "1", False),
    ("1", _UNSET, _UNSET, True),
    ("1", _UNSET, "1", True),
    ("1", "true", _UNSET, False),
    ("1", "true", "1", True),
    ("1", "false", _UNSET, False),
    ("1", "false", "1", True),
    ("0", _UNSET, _UNSET, False),
    ("0", _UNSET, "1", False),
    ("0", "true", _UNSET, False),
    ("0", "true", "1", False),
    ("0", "false", _UNSET, False),
    ("0", "false", "1", False),
)

# (ENABLED, CI, FORCE) -> enabled.  Observability: the explicit switch
# decides alone; neither CI nor FORCE changes the outcome of any row.
_OBSERVABILITY_TABLE = (
    (_UNSET, _UNSET, _UNSET, False),
    (_UNSET, _UNSET, "1", False),
    (_UNSET, "true", _UNSET, False),
    (_UNSET, "true", "1", False),
    (_UNSET, "false", _UNSET, False),
    (_UNSET, "false", "1", False),
    ("1", _UNSET, _UNSET, True),
    ("1", _UNSET, "1", True),
    ("1", "true", _UNSET, True),
    ("1", "true", "1", True),
    ("1", "false", _UNSET, True),
    ("1", "false", "1", True),
    ("0", _UNSET, _UNSET, False),
    ("0", _UNSET, "1", False),
    ("0", "true", _UNSET, False),
    ("0", "true", "1", False),
    ("0", "false", _UNSET, False),
    ("0", "false", "1", False),
)


def _environ(
    prefix: str, row: tuple[str | None, str | None, str | None]
) -> dict[str, str]:
    enabled, ci, force = row
    pairs = (
        (f"CODECLONE_{prefix}_ENABLED", enabled),
        ("CI", ci),
        (f"CODECLONE_{prefix}_FORCE", force),
    )
    return {key: value for key, value in pairs if value is not None}


@pytest.mark.parametrize(("enabled", "ci", "force", "expected"), _RUN_STORE_TABLE)
def test_run_store_precedence_table(
    tmp_path: Path,
    enabled: str | None,
    ci: str | None,
    force: str | None,
    expected: bool,
) -> None:
    environ = _environ("RUN_STORE", (enabled, ci, force))
    config = resolve_run_store_config(root=tmp_path, environ=environ)
    assert config.enabled is expected


@pytest.mark.parametrize(("enabled", "ci", "force", "expected"), _OBSERVABILITY_TABLE)
def test_observability_precedence_table(
    enabled: str | None,
    ci: str | None,
    force: str | None,
    expected: bool,
) -> None:
    environ = _environ("OBSERVABILITY", (enabled, ci, force))
    assert resolve_observability_config(environ=environ).enabled is expected
