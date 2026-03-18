from __future__ import annotations

from collections.abc import Mapping, Sequence

from codeclone import _coerce


def test_as_int_handles_bool_int_str_and_default() -> None:
    assert _coerce.as_int(True) == 1
    assert _coerce.as_int(False) == 0
    assert _coerce.as_int(7) == 7
    assert _coerce.as_int("12") == 12
    assert _coerce.as_int("bad", 9) == 9
    assert _coerce.as_int(object(), 11) == 11


def test_as_float_handles_bool_number_str_and_default() -> None:
    assert _coerce.as_float(True) == 1.0
    assert _coerce.as_float(False) == 0.0
    assert _coerce.as_float(3) == 3.0
    assert _coerce.as_float(2.5) == 2.5
    assert _coerce.as_float("2.75") == 2.75
    assert _coerce.as_float("bad", 1.25) == 1.25
    assert _coerce.as_float(object(), 4.5) == 4.5


def test_as_str_returns_only_string_instances() -> None:
    assert _coerce.as_str("x") == "x"
    assert _coerce.as_str(1) == ""
    assert _coerce.as_str(None, "fallback") == "fallback"


def test_as_mapping_preserves_mapping_and_rejects_other_values() -> None:
    source: Mapping[str, object] = {"a": 1}
    assert _coerce.as_mapping(source) is source
    assert _coerce.as_mapping("x") == {}
    assert _coerce.as_mapping(3.14) == {}


def test_as_sequence_preserves_sequence_except_text_and_bytes() -> None:
    as_list = _coerce.as_sequence([1, 2])
    as_tuple = _coerce.as_sequence((1, 2))
    as_str = _coerce.as_sequence("abc")
    as_bytes = _coerce.as_sequence(b"abc")
    as_bytearray = _coerce.as_sequence(bytearray(b"abc"))

    assert isinstance(as_list, Sequence)
    assert isinstance(as_tuple, Sequence)
    assert tuple(as_list) == (1, 2)
    assert tuple(as_tuple) == (1, 2)
    assert as_str == ()
    assert as_bytes == ()
    assert as_bytearray == ()
