# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP payload token budget estimation (optional leaf module).

Requires the ``codeclone[token-bench]`` extra for exact BPE counts.
Falls back to character-based approximation when ``tiktoken`` is absent.

This module must not import from ``codeclone.surfaces`` or
``codeclone.audit``.  Dependency direction: ``audit -> budget``.
"""

from __future__ import annotations
