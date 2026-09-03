# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from collections.abc import Sequence


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

    ``remediation`` is the steps that resolve the condition, when such steps
    exist and are not already the message. It is optional and it is never
    invented: a next step that cannot help is the other half of what was
    wrong with the internal envelope here, so an error with nothing useful
    to add carries nothing.

    It is a sequence and not one string because a diagnosis usually has more
    than one way out, and they are not interchangeable: the user who cannot
    write to the environment CodeClone runs from still owns the flag that
    asked for the feature. Folding both into a single line would put them
    under one bullet of a heading that already says "steps".

    It is also the only field of this class that is read on the user's own
    terminal and nowhere else -- ``fmt_diagnosed_user_error`` is its one
    reader, and ``main`` its one caller. That is what makes it the place for
    a local detail like an interpreter path: ``args`` travels into MCP
    responses, logs, and pasted bug reports, and this does not.

    That last sentence is enforced, not merely asserted: a second reader
    anywhere under ``codeclone/`` fails
    ``test_no_production_code_reads_the_steps_outside_the_diagnosed_renderer``
    by name. Before adding one, check it cannot reach a public surface.
    """

    __slots__ = ("remediation",)

    def __init__(self, *args: object, remediation: str | Sequence[str] = ()) -> None:
        super().__init__(*args)
        steps = (remediation,) if isinstance(remediation, str) else tuple(remediation)
        self.remediation: tuple[str, ...] = tuple(step for step in steps if step)


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
