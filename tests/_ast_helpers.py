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
