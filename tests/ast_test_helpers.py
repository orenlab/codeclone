# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import TypeVar

_T = TypeVar("_T", bound=ast.AST)


def parse_class_first_member(
    source: str, member_type: type[_T]
) -> tuple[ast.ClassDef, _T]:
    class_node = ast.parse(source).body[0]
    assert isinstance(class_node, ast.ClassDef)
    member = class_node.body[0]
    assert isinstance(member, member_type)
    return class_node, member
