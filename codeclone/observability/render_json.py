# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""JSON renderer for the observability ``TraceView``.

Deterministic: sorted keys, stable indentation. The read model is the source of
truth; this is a faithful projection of it.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from .views import TraceView


def render_trace_json(trace: TraceView) -> str:
    """Render a ``TraceView`` as canonical, human-readable JSON."""
    return json.dumps(asdict(trace), sort_keys=True, indent=2, ensure_ascii=False)


__all__ = ["render_trace_json"]
