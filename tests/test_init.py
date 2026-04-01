# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from types import ModuleType

import pytest


def test_version_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata

    def _raise(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    module = importlib.reload(importlib.import_module("codeclone"))
    assert isinstance(module, ModuleType)
    assert module.__version__ == "dev"


def test_version_from_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata

    def _fake(_name: str) -> str:
        return "1.2.3"

    monkeypatch.setattr(importlib.metadata, "version", _fake)
    module = importlib.reload(importlib.import_module("codeclone"))
    assert module.__version__ == "1.2.3"
