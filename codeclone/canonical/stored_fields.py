# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The readers and writers of one stored row's fields.

A stored row is the JSON object a model row is stored as: its fields by
name, every tuple as a JSON array, a symbol as ``[path, qualname]``.  These
are the checks every decoder of such a row applies to one field -- present,
of the declared JSON type, nothing coerced -- and the two writers that turn
a record into that row.  They are shared by the run store, which reads rows
back from SQLite, and by the canonical wire, whose comparison and evaluation
members carry the same rows (:mod:`codeclone.canonical.tier_storage`), so a
field is judged one way wherever it is read.  A refusal is the store's typed
integrity error; a reader that is not the store translates it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from codeclone.canonical.errors import StoreIntegrityError
from codeclone.canonical.identity import FileId, SymbolId


def symbol_value(symbol: SymbolId) -> list[str]:
    return [symbol.file.path, symbol.qualname]


def decode_symbol(value: object, where: str) -> SymbolId:
    if not isinstance(value, list) or len(value) != 2:
        raise StoreIntegrityError(f"{where}: stored symbol is not a [path, qualname]")
    path, qualname = value
    if not isinstance(path, str) or not isinstance(qualname, str):
        raise StoreIntegrityError(f"{where}: stored symbol is not a [path, qualname]")
    return SymbolId(FileId(path), qualname)


def storage_form(fields: Mapping[str, object]) -> dict[str, object]:
    """A record's storage row: its fields in name order, every tuple as the
    JSON array it is stored and read back as — so the row this walk yields
    is the row the decoder reads, not a look-alike."""
    return {name: listed(value) for name, value in sorted(fields.items())}


def listed(value: object) -> object:
    if isinstance(value, tuple):
        return [listed(item) for item in value]
    return value


def require_field(row: Mapping[str, object], key: str, where: str) -> object:
    if key not in row:
        raise StoreIntegrityError(f"{where}: stored row is missing {key!r}")
    return row[key]


def require_int(row: Mapping[str, object], key: str, where: str) -> int:
    value = require_field(row, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not an int")
    return value


def require_optional_str(row: Mapping[str, object], key: str, where: str) -> str | None:
    value = require_field(row, key, where)
    if value is not None and not isinstance(value, str):
        raise StoreIntegrityError(
            f"{where}: stored field {key!r} is neither a string nor null"
        )
    return value


def require_str(row: Mapping[str, object], key: str, where: str) -> str:
    value = require_field(row, key, where)
    if not isinstance(value, str):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not a string")
    return value


def require_str_list(row: Mapping[str, object], key: str, where: str) -> list[str]:
    return decode_str_list(require_field(row, key, where), key, where)


def decode_str_list(values: object, key: str, where: str) -> list[str]:
    if not isinstance(values, list):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not an array")
    items: list[str] = []
    for item in values:
        if not isinstance(item, str):
            raise StoreIntegrityError(
                f"{where}: stored field {key!r} carries a non-string"
            )
        items.append(item)
    return items


def require_bool(row: Mapping[str, object], key: str, where: str) -> bool:
    value = require_field(row, key, where)
    if not isinstance(value, bool):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not a boolean")
    return value


def require_line(row: Mapping[str, object], key: str, where: str) -> int:
    value = require_field(row, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not an int")
    return value


def row_symbol(row: Mapping[str, object], key: str, where: str) -> SymbolId:
    return decode_symbol(require_field(row, key, where), where)


def decode_stored_pairs(value: object, where: str) -> list[tuple[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StoreIntegrityError(f"{where}: stored pairs are not a list")
    pairs: list[tuple[str, object]] = []
    for item in value:
        if (
            not isinstance(item, Sequence)
            or isinstance(item, (str, bytes))
            or len(item) != 2
            or not isinstance(item[0], str)
        ):
            raise StoreIntegrityError(
                f"{where}: stored pair is not a [name, value] list"
            )
        pairs.append((item[0], item[1]))
    return pairs


def require_float(row: Mapping[str, object], key: str, where: str) -> float:
    value = require_field(row, key, where)
    if isinstance(value, bool) or not isinstance(value, float):
        raise StoreIntegrityError(f"{where}: stored field {key!r} is not a float")
    return value


def require_optional_int(row: Mapping[str, object], key: str, where: str) -> int | None:
    value = require_field(row, key, where)
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise StoreIntegrityError(
            f"{where}: stored field {key!r} is neither an int nor null"
        )
    return value
