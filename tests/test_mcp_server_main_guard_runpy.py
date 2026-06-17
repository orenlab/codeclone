# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import pytest

from tests._runpy_guard import assert_runpy_module_help_exits_zero


def test_mcp_server_main_guard_runpy(monkeypatch: pytest.MonkeyPatch) -> None:
    assert_runpy_module_help_exits_zero(
        monkeypatch,
        module="codeclone.surfaces.mcp",
        module_cache_key="codeclone.surfaces.mcp.__main__",
        argv=["codeclone-mcp", "--help"],
    )
