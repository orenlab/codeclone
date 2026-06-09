# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Platform observability (Phase 29).

A runtime-profiling plane separate from audit truth, the analysis report, and
the memory store: operations and stage spans for CLI / MCP / projection workers.
Default OFF, bounded, deterministic shape. The write API (``runtime``) lands in
Cycle 2b; this package currently exposes the data model and the sqlite store.
"""

from __future__ import annotations
