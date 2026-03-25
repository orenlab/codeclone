# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("codeclone")
except PackageNotFoundError:
    __version__ = "dev"

__all__ = ["__version__"]
