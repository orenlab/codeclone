# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("codeclone")
except PackageNotFoundError:
    __version__ = "dev"

__all__ = ["__version__"]
