"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("codeclone")
except PackageNotFoundError:
    __version__ = "dev"

__all__ = ["__version__"]
