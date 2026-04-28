# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations


def clone_group_id(kind: str, group_key: str) -> str:
    return f"clone:{kind}:{group_key}"


def structural_group_id(finding_kind: str, finding_key: str) -> str:
    return f"structural:{finding_kind}:{finding_key}"


def dead_code_group_id(subject_key: str) -> str:
    return f"dead_code:{subject_key}"


def design_group_id(category: str, subject_key: str) -> str:
    return f"design:{category}:{subject_key}"


__all__ = [
    "clone_group_id",
    "dead_code_group_id",
    "design_group_id",
    "structural_group_id",
]
