# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path


def write_quality_fixture(root: Path, source: str) -> None:
    pkg = root.joinpath("pkg")
    pkg.mkdir(exist_ok=True)
    pkg.joinpath("__init__.py").write_text("", "utf-8")
    pkg.joinpath("quality.py").write_text(source, "utf-8")
