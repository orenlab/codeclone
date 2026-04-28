# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import runpy
import sys

import pytest


def test_mcp_server_main_guard_runpy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "codeclone.surfaces.mcp", raising=False)
    monkeypatch.delitem(sys.modules, "codeclone.surfaces.mcp.__main__", raising=False)
    monkeypatch.setattr(sys, "argv", ["codeclone-mcp", "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("codeclone.surfaces.mcp", run_name="__main__")
    assert exc.value.code == 0
