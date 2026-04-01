# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from typing import TypeVar

_FunctionDefT = TypeVar("_FunctionDefT", ast.FunctionDef, ast.AsyncFunctionDef)


def fix_missing_single_function(function_node: _FunctionDefT) -> _FunctionDefT:
    module = ast.Module(body=[function_node], type_ignores=[])
    module = ast.fix_missing_locations(module)
    node = module.body[0]
    assert isinstance(node, type(function_node))
    return node
