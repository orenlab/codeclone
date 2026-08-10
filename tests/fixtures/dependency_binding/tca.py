# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Typing-only link: this edge exists solely under TYPE_CHECKING.

With tcb's eager back-edge the pair would look circular — but the typing
guard never runs, so no runtime cycle exists and none may be reported.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tcb  # type: ignore[import-not-found] # noqa: F401 — the typing-only edge IS the fixture's point

TCA_TOKEN = "tca"


def tca_value() -> str:
    return TCA_TOKEN
