# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from codeclone.cfg_model import CFG, Block


def test_block_hash_and_eq() -> None:
    b1 = Block(id=1)
    b2 = Block(id=1)
    b3 = Block(id=2)
    assert b1 == b2
    assert b1 != b3
    assert hash(b1) == hash(b2)


def test_cfg_create_block() -> None:
    cfg = CFG("f")
    count = len(cfg.blocks)
    b = cfg.create_block()
    assert len(cfg.blocks) == count + 1
    assert b.id == count
