# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast


def ast_node_start_line(node: ast.AST) -> int | None:
    line = getattr(node, "lineno", None)
    if isinstance(line, int) and line > 0:
        return line
    return None


def ast_node_end_line(node: ast.AST) -> int:
    start_line = ast_node_start_line(node)
    if start_line is None:
        return 0
    end_line = getattr(node, "end_lineno", None)
    return (
        end_line if isinstance(end_line, int) and end_line >= start_line else start_line
    )
