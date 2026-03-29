# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast

from codeclone.blockhash import stmt_hashes
from codeclone.normalize import NormalizationConfig


def test_stmt_hash_normalizes_names() -> None:
    cfg = NormalizationConfig()
    s1 = ast.parse("a = b + 1").body[0]
    s2 = ast.parse("x = y + 2").body[0]
    assert stmt_hashes([s1], cfg)[0] == stmt_hashes([s2], cfg)[0]
