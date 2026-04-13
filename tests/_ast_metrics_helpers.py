# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast

from codeclone import extractor
from codeclone.qualnames import QualnameCollector


def tree_collector_and_imports(
    source: str,
    *,
    module_name: str,
) -> tuple[ast.Module, QualnameCollector, frozenset[str]]:
    tree = ast.parse(source)
    collector = QualnameCollector()
    collector.visit(tree)
    walk = extractor._collect_module_walk_data(
        tree=tree,
        module_name=module_name,
        collector=collector,
        collect_referenced_names=True,
    )
    return tree, collector, walk.import_names
