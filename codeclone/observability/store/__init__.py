# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Observability sqlite store: schema + bounded batched writer + (Cycle 3) reader.

Imported only on the enabled write path or the read path — never when
observability is disabled (the near-zero-overhead contract).
"""

from __future__ import annotations
