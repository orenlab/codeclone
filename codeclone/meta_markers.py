# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

# Contains `:` characters, so it cannot be produced by valid Python identifiers
# from parsed source code. It is only emitted programmatically by CFG builder.
CFG_META_PREFIX = "__CC_META__::"
