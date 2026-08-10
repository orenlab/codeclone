# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Eager half of the typing-only pair: a one-way runtime edge, no cycle."""

import tca  # type: ignore[import-not-found]

TCB_TOKEN = "tcb"


def tcb_value() -> str:
    return f"{TCB_TOKEN}:{tca.TCA_TOKEN}"
