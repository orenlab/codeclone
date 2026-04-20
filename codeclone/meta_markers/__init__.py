# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

# Contains `:` characters, so it cannot be produced by valid Python identifiers
# from parsed source code. It is only emitted programmatically by CFG builder.
CFG_META_PREFIX = "__CC_META__::"
