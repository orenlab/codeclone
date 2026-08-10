# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Eager member of the import-time cycle: both edges bind at import."""

import eag_two  # type: ignore[import-not-found]

EAG_ONE_TOKEN = "eag_one"


def eag_one_value() -> str:
    return f"{EAG_ONE_TOKEN}:{eag_two.EAG_TWO_TOKEN}"
