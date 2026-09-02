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


class DiagnosedUserError(CodeCloneError):
    """A condition CodeClone diagnosed precisely and the user can fix.

    The distinction this marker draws is between two things one ``except``
    clause used to conflate: a fault CodeClone did not anticipate, and a
    configuration CodeClone validated and rejected by name. The first is a
    bug report; the second is a sentence telling the user which key is
    wrong. Rendering the second as the first was measured on 2026-09-01 --
    ``CODECLONE_OBSERVABILITY_PROFILE=1`` without the ``perf`` extra printed
    "Unexpected exception", offered a traceback for a message it had just
    produced itself, and asked for a bug report against a documented option
    used without its extra.

    It is a MARKER on the class and not a check on the instance, because the
    envelope must not carry a list: an envelope that named one exception
    would misreport every sibling raised from the same kind of validation,
    which is how the defect arrived in the first place.

    ``remediation`` is the one step that resolves the condition, when such a
    step exists and is not already the message. It is optional and it is
    never invented: a next step that cannot help is the other half of what
    was wrong with the internal envelope here, so an error with nothing
    useful to add carries nothing.
    """

    __slots__ = ("remediation",)

    def __init__(self, *args: object, remediation: str = "") -> None:
        super().__init__(*args)
        self.remediation = remediation


class ContractInvariantError(CodeCloneError):
    """A shipped contract constant violates the invariant it is published with.

    Not user input and not a runtime accident: the value is a literal in
    ``codeclone.contracts``, so this can only be reached through a build whose
    constants were edited past their declared rule, or through a caller that
    substituted one at runtime. Refusing is the point -- the alternative is a
    number that looks ordinary and is not.
    """


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
    "ContractInvariantError",
    "DiagnosedUserError",
    "FileProcessingError",
    "ParseError",
    "ValidationError",
]
