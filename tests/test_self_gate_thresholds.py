# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""This repository's own CodeClone gate thresholds must stay satisfiable.

Phase 39Y made two honest metric-population changes that cost self-measured
health: Y5 (a metric fact per defined function, -8 points) and Y6 (the CBO
imported-domain edge lane, -8 points). Neither is suppressible — the findings
are real — so the maintainer lowered ``fail_health`` to the measured value
instead of hiding the measurement.

This module is the owning assertion for that decision. It is deliberately
cheap: it reads the committed configuration rather than re-analyzing 913 files,
because the satisfiability of the gate against a live tree is what
``codeclone . --ci`` proves at landing.
"""

from __future__ import annotations

from pathlib import Path

from codeclone.config.pyproject_loader import load_pyproject_config

REPO_ROOT = Path(__file__).parent.parent

# Cold self-measure of this worktree, worktree CLI, 39Y after Addition 1:
#   ./.venv/bin/codeclone . --cache-path <fresh>
#   -> Health 92/100 (A)
#      929 files analyzed · 10570 callables · 922 classes
#      CC       avg 2.2 · max 34 · 6 high-risk
#      Coupling avg 1.4 · max 27
#      Cohesion avg 1.1 · max 3 · cycles clean · dead code clean
#
# Measured IN-PROCESS against this source tree. A long-lived MCP server reports
# PRE-NORM complexity (it still says max 20 and zero high-risk), so its numbers
# are not evidence for this constant.
#
# The jump from the previous record (73) is two corrections, not new work:
#   * the previous line's own figures were stale — it recorded coupling avg 2.5
#     / max 61 and 10352 callables, none of which this tree measures;
#   * the complexity dimension was recalibrated (39Y Addition 1). Under the old
#     unbounded formula the post-norm distribution scored 12 because one
#     34-complexity function spent 40.8 points; the bounded terms score it in
#     the eighties, which is the same codebase measured honestly rather than a
#     codebase that improved.
#
# Re-measure with that command and update this constant *together with* any
# increase of fail_health. Raising the gate without a fresh measurement is the
# failure this test exists to catch. The fail_health VALUE itself is the
# maintainer's landing decision and is not set from here.
MEASURED_SELF_HEALTH = 92


def _self_fail_health() -> int:
    """Return this repository's effective ``fail_health``.

    Read through the production loader rather than raw TOML, so the assertion
    covers the value the CLI actually gates on.
    """

    config = load_pyproject_config(REPO_ROOT)
    assert "fail_health" in config, (
        "pyproject [tool.codeclone] no longer declares fail_health; the health "
        "gate would fall back to the CLI default and stop being governed here."
    )
    return int(str(config["fail_health"]))


def test_fail_health_gate_is_satisfiable_by_measured_health() -> None:
    """The configured health floor must not exceed what the repo measures."""

    fail_health = _self_fail_health()

    assert fail_health <= MEASURED_SELF_HEALTH, (
        f"fail_health={fail_health} exceeds the recorded self-measure "
        f"{MEASURED_SELF_HEALTH}: `codeclone . --ci` cannot pass on this "
        f"repository. Either improve health and re-measure (updating "
        f"MEASURED_SELF_HEALTH), or lower the gate deliberately."
    )


def test_health_gate_stays_enabled() -> None:
    """Lowering the floor must not become a way to switch the gate off.

    -1 disables a CodeClone threshold gate; 0 would accept any health. The
    39Y decision was to lower the floor to the honest measurement, not to stop
    gating on health at all.
    """

    fail_health = _self_fail_health()

    assert fail_health > 0, (
        f"fail_health={fail_health} disables the health gate; 39Y lowered the "
        f"floor to the measured value, it did not remove the gate."
    )
