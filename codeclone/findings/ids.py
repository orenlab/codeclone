# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterable


def clone_group_id(kind: str, group_key: str) -> str:
    return f"clone:{kind}:{group_key}"


def structural_group_id(finding_kind: str, finding_key: str) -> str:
    return f"structural:{finding_kind}:{finding_key}"


def dead_code_group_id(subject_key: str) -> str:
    return f"dead_code:{subject_key}"


def design_group_id(category: str, subject_key: str) -> str:
    return f"design:{category}:{subject_key}"


def authority_group_id(contract_id: str, violation_id: str) -> str:
    return f"authority:{contract_id}:{violation_id}"


def dependency_cycle_subject_key(modules: Iterable[str]) -> str:
    """The identity a dependency cycle is compared and addressed under.

    The producer of the per-entity novelty facts, the design dependency group
    and the canonical projection must all spell one cycle the same way; this
    is the one spelling, and ``design_group_id("dependency", …)`` takes it as
    the subject.
    """
    return " -> ".join(str(module) for module in modules)


__all__ = [
    "authority_group_id",
    "clone_group_id",
    "dead_code_group_id",
    "dependency_cycle_subject_key",
    "design_group_id",
    "structural_group_id",
]
