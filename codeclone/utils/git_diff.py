# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
from typing import Final

_SAFE_GIT_DIFF_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?![-./])[A-Za-z0-9._/@{}^~+-]+$"
)


def validate_git_diff_ref(git_diff_ref: str) -> str:
    """Validate a safe, single git revision expression for `git diff`.

    CodeClone intentionally accepts a conservative subset of git revision
    syntax here: common branch names, tags, revision operators (`~`, `^`),
    reflog selectors (`@{...}`), and dotted range expressions. Whitespace,
    control characters, option-like prefixes, and unsupported punctuation are
    rejected before any subprocess call.
    """

    if git_diff_ref != git_diff_ref.strip():
        raise ValueError(
            "Invalid git diff ref "
            f"{git_diff_ref!r}: surrounding whitespace is not allowed."
        )
    if not git_diff_ref:
        raise ValueError("Invalid git diff ref '': value must not be empty.")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in git_diff_ref):
        raise ValueError(
            "Invalid git diff ref "
            f"{git_diff_ref!r}: whitespace and control characters are not allowed."
        )
    if not _SAFE_GIT_DIFF_REF_RE.fullmatch(git_diff_ref):
        raise ValueError(
            "Invalid git diff ref "
            f"{git_diff_ref!r}: expected a safe revision expression."
        )
    return git_diff_ref
