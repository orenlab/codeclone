# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy


class CodeCloneError(Exception):
    """Base exception for CodeClone."""


class FileProcessingError(CodeCloneError):
    """Error processing a source file."""


class ParseError(FileProcessingError):
    """AST parsing failed."""


class ValidationError(CodeCloneError):
    """Input validation failed."""


class CacheError(CodeCloneError):
    """Cache operation failed."""


class BaselineSchemaError(CodeCloneError):
    """Baseline file structure is invalid."""


class BaselineValidationError(BaselineSchemaError):
    """Baseline validation error with machine-readable status."""

    __slots__ = ("status",)

    def __init__(self, message: str, *, status: str = "invalid_type") -> None:
        super().__init__(message)
        self.status = status


__all__ = [
    "BaselineSchemaError",
    "BaselineValidationError",
    "CacheError",
    "CodeCloneError",
    "FileProcessingError",
    "ParseError",
    "ValidationError",
]
