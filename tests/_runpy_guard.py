# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import runpy
import sys

import pytest


def assert_runpy_module_help_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: str,
    module_cache_key: str,
    argv: list[str],
) -> None:
    monkeypatch.delitem(sys.modules, module_cache_key, raising=False)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        runpy.run_module(module, run_name="__main__")
    assert exc.value.code == 0
