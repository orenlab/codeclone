# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deferred-cycle member re-exporting lazily through module ``__getattr__``.

With defa this cycle is real but binds no edge at import time, so it must
classify as ``deferred_cycle`` (warning), never ``import_cycle``.
"""

DEFB_TOKEN = "defb"


def __getattr__(name: str) -> object:
    import defa  # type: ignore[import-not-found]

    return getattr(defa, name)
