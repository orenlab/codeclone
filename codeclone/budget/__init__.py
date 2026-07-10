# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Surface-neutral budget policies and optional payload token estimation.

Patch-contract budgets live in :mod:`codeclone.budget.patch_contract`. Payload
token estimation stays isolated in :mod:`codeclone.budget.estimator`, which
requires the ``codeclone[token-bench]`` extra for exact BPE counts and falls
back to character-based approximation when ``tiktoken`` is absent.

This module must not import from ``codeclone.surfaces`` or
``codeclone.audit``.  Dependency direction: ``audit -> budget``.
"""

from __future__ import annotations
