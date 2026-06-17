# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Verification profile user-facing messages."""

from __future__ import annotations

from typing import Final

PROFILE_REASONS: Final[dict[str, str]] = {
    "state_artifact_change": "changed files include CodeClone state artifacts",
    "python_structural": "changed files include Python source",
    "governance_config": "changed files include governance or analysis configuration",
    "documentation_only": "all changed files match documentation patterns",
    "non_python_patch": (
        "changed files are outside Python source and documentation patterns"
    ),
}

EMPTY_PROFILE_REASON: Final = "no changed files detected"

PROFILE_LIMITATIONS: Final[dict[str, tuple[str, ...]]] = {
    "non_python_patch": (
        "Patch did not touch Python source files, so Python structural "
        "regressions were not checked.",
        "Changed files are not classified as documentation-only; "
        "review non-Python side effects manually.",
    ),
    "documentation_only": (),
    "governance_config": (),
    "python_structural": (),
    "state_artifact_change": (),
}

PROFILE_ACCEPTED_MESSAGES: Final[dict[str, str]] = {
    "documentation_only": (
        "Patch contract accepted. No Python source files touched; "
        "structural checks not applicable."
    ),
    "non_python_patch": (
        "Patch scope accepted. No Python source files were touched; "
        "Python structural checks were not applicable. "
        "Changed files are outside the documentation-only profile, "
        "so review limitations apply."
    ),
}

PROFILE_UNVERIFIED_MESSAGES: Final[dict[str, str]] = {
    "python_structural": (
        "Python source files were changed; after_run_id is required "
        "for structural verification."
    ),
    "governance_config": (
        "Configuration that may affect analysis or CI gates was changed; "
        "after_run_id is required for verification."
    ),
}

PROFILE_ACCEPTED_DEFAULT: Final = "Patch contract accepted."
PROFILE_UNVERIFIED_DEFAULT: Final = "after_run_id is required for verification."


def profile_accepted_message(profile: str) -> str:
    return PROFILE_ACCEPTED_MESSAGES.get(profile, PROFILE_ACCEPTED_DEFAULT)


def profile_unverified_message(profile: str) -> str:
    return PROFILE_UNVERIFIED_MESSAGES.get(profile, PROFILE_UNVERIFIED_DEFAULT)


def profile_limitations(profile: str) -> tuple[str, ...]:
    return PROFILE_LIMITATIONS.get(profile, ())
