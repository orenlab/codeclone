# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Typed decoder refusals of canonical JSON vNext (F-3 §7.7).

Every refusal code is exercised by an input that demonstrably reaches its
guard: a canonical document corrupted surgically at the byte level. Each
needle is asserted to occur exactly once, so a drifted fixture fails loudly
instead of corrupting a different byte.  ``W11`` was deleted by sanction
(2026-08-13) and is pinned absent.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from typing import Any

import pytest

from codeclone.canonical import (
    CanonicalModel,
    CanonicalModelError,
    ContractRow,
    FileId,
    SymbolId,
    WireDecodeError,
    canonical_float_lexeme,
    canonical_string_lexeme,
    decode_canonical_json,
    encode_canonical_json,
)
from codeclone.canonical import codec as codec_module
from tests.test_canonical_roundtrip import analysis_facts, fixture_model


@pytest.fixture(scope="module")
def canonical_bytes() -> bytes:
    return encode_canonical_json(fixture_model())


def _replaced(data: bytes, needle: str, replacement: str) -> bytes:
    text = data.decode("utf-8")
    assert text.count(needle) == 1, f"needle not unique: {needle!r}"
    return text.replace(needle, replacement).encode("utf-8")


def _resealed(data: bytes, needle: str, replacement: str) -> bytes:
    """Corrupt the body and reseal integrity so only W24 can refuse."""
    text = data.decode("utf-8")
    marker = ',"integrity":'
    body, _, _tail = text.partition(marker)
    assert body.count(needle) == 1, f"needle not unique in body: {needle!r}"
    new_body = body.replace(needle, replacement)[1:]
    digest = hashlib.sha256(
        codec_module._INTEGRITY_DOMAIN + new_body.encode("utf-8")
    ).hexdigest()
    return (
        "{" + new_body + f',"integrity":{{"algorithm":"sha256","value":"{digest}"}}}}'
    ).encode("utf-8")


_SEG_FORMAT = '"format":{"name":"codeclone-canonical","wire":"0"}'
_SEG_REVISIONS = (
    '"revisions":{"authority_analysis":"1","canonical_model":"1",'
    '"contract_ir":"1","module_identity":"2"}'
)

_REFUSALS: list[tuple[str, str, str, str]] = [
    ("W01", "root key set", ',"scope":{"analyzed_files":[0,2]}', ""),
    (
        "W02",
        "root member order",
        f"{_SEG_FORMAT},{_SEG_REVISIONS}",
        f"{_SEG_REVISIONS},{_SEG_FORMAT}",
    ),
    (
        "W02",
        "column order",
        '"file":[0,0,1,2,2],"qualname":["A.run","A.stop","run","helper","zz"]',
        '"qualname":["A.run","A.stop","run","helper","zz"],"file":[0,0,1,2,2]',
    ),
    (
        "W02",
        "sparse positions order",
        '{"1":"W2","2":"Writer","3":"Z"}',
        '{"2":"Writer","1":"W2","3":"Z"}',
    ),
    (
        "W03",
        "duplicate object key",
        '{"name":"codeclone-canonical","wire":"0"}',
        '{"name":"codeclone-canonical","name":"codeclone-canonical","wire":"0"}',
    ),
    ("W05", "lone surrogate escape", '"zz"', '"z\\ud800z"'),
    ("W06", "NaN literal", '"file":[0,0,1,2,2]', '"file":[NaN,0,1,2,2]'),
    (
        "W07",
        "fraction in an integer slot",
        '"file":[0,0,1,2,2]',
        '"file":[0.5,0,1,2,2]',
    ),
    (
        "W07",
        "integer above 2**31-1",
        '"file":[0,0,1,2,2]',
        '"file":[2147483648,0,1,2,2]',
    ),
    (
        "W08",
        "unknown root family tag",
        '"family":["effect",',
        '"family":["banana",',
    ),
    ("W08", "unknown head tag", '["opaque","x.y"]', '["banana","x.y"]'),
    (
        "W09",
        "domain not admitted for the slot",
        '"2":["module",0]',
        '"2":["symbol",0]',
    ),
    ("W10", "ordinal beyond its table", '"file":[0,0,1,2,2]', '"file":[0,0,1,2,9]'),
    (
        "W08",
        "unknown occurrence dependency_type tag",
        '"type_checking"],"dependency_type":["from_import"',
        '"type_checking"],"dependency_type":["banana"',
    ),
    (
        "W08",
        "unknown relation dependency_type tag",
        '"dependency_relations":{"dependency_type":["from_import"',
        '"dependency_relations":{"dependency_type":["banana"',
    ),
    (
        "W08",
        "unknown dependency binding tag",
        '"binding":["lazy_syntax","deferred_function","import_time","type_checking"]',
        '"binding":["banana","deferred_function","import_time","type_checking"]',
    ),
    (
        "W08",
        "endpoint tag unknown",
        '"source":[["file",2],["module",0],["module",0],["module",0]]',
        '"source":[["banana",2],["module",0],["module",0],["module",0]]',
    ),
    (
        "W09",
        "endpoint tag not admitted",
        '"source":[["file",2],["module",0],["module",0],["module",0]]',
        '"source":[["symbol",2],["module",0],["module",0],["module",0]]',
    ),
    (
        "W12",
        "occurrences out of producer-key order",
        '"line":[2,4,4,9]',
        '"line":[2,4,9,4]',
    ),
    (
        "W13",
        "duplicate occurrence producer key",
        '"line":[2,4,4,9]',
        '"line":[2,4,4,4]',
    ),
    (
        "W12",
        "relations out of canonical key order",
        '"dependency_relations":{"dependency_type":'
        '["from_import","from_import","import","import"]',
        '"dependency_relations":{"dependency_type":'
        '["from_import","import","from_import","import"]',
    ),
    (
        "W13",
        "duplicate relation key",
        '"dependency_relations":{"dependency_type":'
        '["from_import","from_import","import","import"]',
        '"dependency_relations":{"dependency_type":'
        '["from_import","import","import","import"]',
    ),
    (
        "W26",
        "occurrence names a relation the table does not carry",
        '"dependency_relations":{"dependency_type":["from_import","from_import"',
        '"dependency_relations":{"dependency_type":["import","from_import"',
    ),
    (
        "W10",
        "lazy position beyond the rows",
        '"is_lazy":[0,3]',
        '"is_lazy":[0,9]',
    ),
    (
        "W14",
        "lazy positions not increasing",
        '"is_lazy":[0,3]',
        '"is_lazy":[3,0]',
    ),
    (
        "W08",
        "unknown coupling dimension tag",
        '"dimension":["cbo","lcom4"',
        '"dimension":["banana","lcom4"',
    ),
    (
        "W07",
        "coupling numerator below the family floor",
        '"numerator":[3,1,3,2,1]',
        '"numerator":[0,1,3,2,1]',
    ),
    (
        "W12",
        "coupling rows out of key order",
        '"dimension":["cbo","lcom4"',
        '"dimension":["lcom4","cbo"',
    ),
    (
        "W13",
        "duplicate coupling key",
        '"dimension":["cbo","lcom4"',
        '"dimension":["cbo","cbo"',
    ),
    (
        "W08",
        "unknown violation kind tag",
        '"kind":["owner_bypass","shadow_projection"]',
        '"kind":["banana","shadow_projection"]',
    ),
    (
        "W16",
        "violation sink without the FUNCTION role",
        '"sink_identity":[0,0]',
        '"sink_identity":[4,0]',
    ),
    (
        "W18",
        "empty violation contract_id",
        '"contract_id":["governance.report_write","governance.report_write"]',
        '"contract_id":["","governance.report_write"]',
    ),
    (
        "W10",
        "suppressed position beyond the rows",
        '"suppressed":[1]',
        '"suppressed":[9]',
    ),
    (
        "W12",
        "identity table out of canonical order",
        '"path":["pkg/a.py","pkg/a.py.d","tools/b.py"]',
        '"path":["pkg/a.py.d","pkg/a.py","tools/b.py"]',
    ),
    (
        "W13",
        "duplicate canonical key",
        '"path":["pkg/a.py","pkg/a.py.d","tools/b.py"]',
        '"path":["pkg/a.py","pkg/a.py","tools/b.py"]',
    ),
    (
        "W13",
        "parallel semantic edge (simple-graph pin)",
        '"source":[0,1,3],"target":[3,4,1]',
        '"source":[0,1,1],"target":[3,4,4]',
    ),
    ("W14", "set elements unsorted", "[4,5]", "[5,4]"),
    ("W14", "set element repeated", "[4,5]", "[4,4]"),
    (
        "W15",
        "diverging column lengths",
        '"qualname":["A.run","A.stop","run","helper","zz"]',
        '"qualname":["A.run","A.stop","run","helper"]',
    ),
    (
        "W16",
        "producer without the FUNCTION role",
        '"producer_sets":[[0,1],[0,3]]',
        '"producer_sets":[[0,1],[0,4]]',
    ),
    ("W17", "absolute FILE path", '"path":["pkg/a.py",', '"path":["/pkg/a.py",'),
    (
        "W18",
        "null where forbidden",
        '"module":["pkg.a","tools.helper"]',
        '"module":[null,"tools.helper"]',
    ),
    (
        "W18",
        "boolean in an integer slot",
        '"analyzed_files":[0,2]',
        '"analyzed_files":[true,2]',
    ),
    (
        "W19",
        "non-canonical sparse key",
        '{"1":"canonical_operation"',
        '{"01":"canonical_operation"',
    ),
    ("W19", "sparse position beyond rows", '"target":{"4":0}', '"target":{"9":0}'),
    (
        "W20",
        "mandatory variant slot missing",
        '"label":{"0":"os.replace"},',
        "",
    ),
    (
        "W20",
        "variant slot on a foreign family",
        '"target":{"4":0}',
        '"target":{"3":0}',
    ),
    (
        "W08",
        "unknown api symbol kind tag",
        '"symbol_kind":["method"',
        '"symbol_kind":["banana"',
    ),
    (
        "W08",
        "unknown api visibility tag",
        '"visibility":["name","all","all","name","name"]',
        '"visibility":["banana","all","all","name","name"]',
    ),
    (
        "W08",
        "unknown api parameter kind tag",
        '["self","pos_only",0]',
        '["self","banana",0]',
    ),
    (
        "W18",
        "api default marker outside 0/1",
        '["self","pos_only",0]',
        '["self","pos_only",7]',
    ),
    (
        "W18",
        "api parameter cell of a wrong arity",
        '["self","pos_only",0]',
        '["self","pos_only"]',
    ),
    (
        "W18",
        "empty api parameter name",
        '["self","pos_only",0]',
        '["","pos_only",0]',
    ),
    (
        "W18",
        "empty api annotation digest",
        '["extra","kw_only",1,'
        '"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"]',
        '["extra","kw_only",1,""]',
    ),
    (
        "W25",
        "api signature variant does not match its formula owner",
        '"90dec1a3883d07ad11a7e7119810ab7316456cd9388c20076f0d28b02a222416"',
        '"00dec1a3883d07ad11a7e7119810ab7316456cd9388c20076f0d28b02a222416"',
    ),
    (
        "W12",
        "api symbol rows out of key order",
        '"symbol":[0,1,2,3,3],"symbol_kind"',
        '"symbol":[0,1,2,3,2],"symbol_kind"',
    ),
    (
        "W18",
        "api parameters cell is not an array",
        ',[],[],[["value"',
        ',7,[],[["value"',
    ),
    (
        "W21",
        "incompatible revision value",
        '"canonical_model":"1"',
        '"canonical_model":"9"',
    ),
    ("W21", "incomplete revisions", '"contract_ir":"1",', ""),
    (
        "W21",
        "foreign format name",
        '"name":"codeclone-canonical"',
        '"name":"codeclone-legacy"',
    ),
]


@pytest.mark.parametrize(
    ("code", "label", "needle", "replacement"),
    _REFUSALS,
    ids=[f"{code}-{label}".replace(" ", "-") for code, label, *_ in _REFUSALS],
)
def test_typed_refusals_fire_on_reaching_inputs(
    canonical_bytes: bytes, code: str, label: str, needle: str, replacement: str
) -> None:
    corrupted = _replaced(canonical_bytes, needle, replacement)
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(corrupted)
    assert caught.value.code == code, caught.value


def test_w01_refuses_a_non_object_document() -> None:
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(b"[1,2]")
    assert caught.value.code == "W01"


def test_w04_refuses_bytes_after_the_document(canonical_bytes: bytes) -> None:
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(canonical_bytes + b"{}")
    assert caught.value.code == "W04"


def test_w05_refuses_non_utf8_bytes(canonical_bytes: bytes) -> None:
    corrupted = canonical_bytes.replace(b'"helper"', b'"hel\xffper"')
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(corrupted)
    assert caught.value.code == "W05"


def test_w23_refuses_a_tampered_integrity_digest(canonical_bytes: bytes) -> None:
    text = canonical_bytes.decode("utf-8")
    head, _, digest_tail = text.rpartition('"value":"')
    flipped = ("0" if digest_tail[0] != "0" else "1") + digest_tail[1:]
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json((head + '"value":"' + flipped).encode("utf-8"))
    assert caught.value.code == "W23"


@pytest.mark.parametrize(
    ("label", "needle", "replacement"),
    [
        ("inserted whitespace", '"wire":"0"}', '"wire":"0" }'),
        ("non-canonical escape", '"x.y"', '"\\u0078.y"'),
        (
            "non-canonical float lexeme",
            '"analyzed_files":[0,2]',
            '"analyzed_files":[0,2E0]',
        ),
        # a present-but-empty sparse boolean column decodes as "no trues"
        # but is not the canonical encoding of that model (omission is)
        ("present empty sparse column", '"suppressed":[1],', '"suppressed":[],'),
    ],
)
def test_w24_refuses_non_canonical_byte_encodings(
    canonical_bytes: bytes, label: str, needle: str, replacement: str
) -> None:
    corrupted = _resealed(canonical_bytes, needle, replacement)
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(corrupted)
    assert caught.value.code == "W24", label


def test_w11_stays_deleted_by_sanction() -> None:
    source = inspect.getsource(codec_module)
    assert '"W11"' not in source
    assert "W12" in source and "W10" in source


def test_encoder_refuses_a_lone_surrogate_in_content() -> None:
    model = CanonicalModel(
        facts=analysis_facts(
            contracts=frozenset(
                {
                    ContractRow(
                        SymbolId(FileId("a.py"), "bad\ud800name"),
                        "sig",
                        frozenset(),
                    )
                }
            )
        )
    )
    with pytest.raises(CanonicalModelError, match="surrogate"):
        encode_canonical_json(model)


def test_canonical_string_lexeme_escapes_only_what_json_requires() -> None:
    assert canonical_string_lexeme('a"b\\c') == '"a\\"b\\\\c"'
    assert canonical_string_lexeme("a\nb\tc") == '"a\\nb\\tc"'
    assert canonical_string_lexeme("a\x01b") == '"a\\u0001b"'
    assert canonical_string_lexeme("Å…é") == '"Å…é"'


@pytest.mark.parametrize(
    ("value", "lexeme"),
    [(1.0, "1.0"), (0.1, "0.1"), (1e-05, "1e-05"), (-0.0, "-0.0")],
)
def test_canonical_float_lexeme_is_single_valued(value: float, lexeme: str) -> None:
    assert canonical_float_lexeme(value) == lexeme


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_refused_never_substituted(value: float) -> None:
    with pytest.raises(CanonicalModelError):
        canonical_float_lexeme(value)


@pytest.mark.parametrize("value", [True, -1, 2**31, object(), {"unordered": 1}])
def test_writer_fails_closed_on_undeclared_value_shapes(value: object) -> None:
    with pytest.raises(CanonicalModelError):
        codec_module._write(value)


_SECONDARY_REFUSALS: list[tuple[str, str, str, str]] = [
    (
        "W18",
        "non-string in a string column",
        '"level":["exact","exact"]',
        '"level":[7,"exact"]',
    ),
    (
        "W18",
        "null in an ordinal column",
        '"producer_set":[0,1]',
        '"producer_set":[null,1]',
    ),
    (
        "W18",
        "string in an integer column",
        '"function":[0,1,2,3]',
        '"function":["0",1,2,3]',
    ),
    (
        "W18",
        "scalar where an array is declared",
        '"analyzed_files":[0,2]',
        '"analyzed_files":7',
    ),
    ("W18", "scalar where a sparse map is declared", '"target":{"4":0}', '"target":7'),
    (
        "W18",
        "head is not a pair",
        '"2":["module",0]',
        '"2":["module",0,1]',
    ),
    (
        "W18",
        "endpoint is not a pair",
        '"source":[["file",2],["module",0],["module",0],["module",0]]',
        '"source":[["file",2,1],["module",0],["module",0],["module",0]]',
    ),
    ("W18", "empty opaque head", '["opaque","x.y"]', '["opaque",""]'),
    (
        "W08",
        "unknown operation_kind",
        '{"1":"canonical_operation"',
        '{"1":"banana"',
    ),
    ("W18", "empty local name", '"local_name":{"1":"W2"', '"local_name":{"1":""'),
    (
        "W18",
        "empty module name",
        '"module":["pkg.a","tools.helper"]',
        '"module":["","tools.helper"]',
    ),
    (
        "W08",
        "unknown effect_kind",
        '"effect_kind":{"0":"artifact_write"}',
        '"effect_kind":{"0":"banana"}',
    ),
    ("W18", "empty effect label", '"label":{"0":"os.replace"}', '"label":{"0":""}'),
    ("W18", "empty qualname", '"qualname":["A.run"', '"qualname":[""'),
    (
        "W15",
        "facts columns diverge",
        '"level":["exact","exact"]',
        '"level":["exact"]',
    ),
    (
        "W23",
        "foreign integrity algorithm",
        '"algorithm":"sha256"',
        '"algorithm":"sha512"',
    ),
    (
        "W24",
        "integrity member not in canonical byte form",
        ',"integrity":{"algorithm"',
        ', "integrity":{"algorithm"',
    ),
]


@pytest.mark.parametrize(
    ("code", "label", "needle", "replacement"),
    _SECONDARY_REFUSALS,
    ids=[
        f"{code}-{label}".replace(" ", "-") for code, label, *_ in _SECONDARY_REFUSALS
    ],
)
def test_secondary_refusal_branches_are_reachable(
    canonical_bytes: bytes, code: str, label: str, needle: str, replacement: str
) -> None:
    corrupted = _replaced(canonical_bytes, needle, replacement)
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(corrupted)
    assert caught.value.code == code, caught.value


def _structurally_corrupted(
    data: bytes, mutate: Callable[[dict[str, Any]], None]
) -> bytes:
    """Re-serialize with one structural corruption; canonical byte checks sit
    behind the structural refusal under test, so re-spacing is immaterial."""
    document = json.loads(data.decode("utf-8"))
    mutate(document)
    return json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _reordered(mapping: dict[str, Any], first_keys: list[str]) -> dict[str, Any]:
    remaining = [key for key in mapping if key not in first_keys]
    return {key: mapping[key] for key in first_keys + remaining}


@pytest.mark.parametrize(
    ("code", "label", "mutate"),
    [
        (
            "W01",
            "effect_roots is not an object",
            lambda doc: doc["domains"].__setitem__("effect_roots", 7),
        ),
        (
            "W02",
            "family is not the first column",
            lambda doc: doc["domains"].__setitem__(
                "effect_roots",
                _reordered(doc["domains"]["effect_roots"], ["effect_kind"]),
            ),
        ),
        (
            "W01",
            "unknown effect_roots column",
            lambda doc: doc["domains"]["effect_roots"].__setitem__("zzz", {}),
        ),
        (
            "W02",
            "variant columns not sorted",
            lambda doc: doc["domains"].__setitem__(
                "effect_roots",
                _reordered(doc["domains"]["effect_roots"], ["family", "head"]),
            ),
        ),
        (
            "W21",
            "revisions is not an object",
            lambda doc: doc.__setitem__("revisions", 7),
        ),
        (
            "W01",
            "facts table with an unknown column",
            lambda doc: doc["facts"]["candidates"].__setitem__("zzz", []),
        ),
        (
            "W01",
            "facts table missing a mandatory column",
            lambda doc: doc["facts"]["candidates"].__delitem__("level"),
        ),
        (
            "W02",
            "facts table columns out of canonical order",
            lambda doc: doc["facts"].__setitem__(
                "candidates", _reordered(doc["facts"]["candidates"], ["level"])
            ),
        ),
        (
            "W01",
            "facts table is not an object",
            lambda doc: doc["facts"].__setitem__("dependency_relations", 7),
        ),
    ],
    ids=[
        "W01-effect-roots-not-object",
        "W02-family-not-first",
        "W01-unknown-variant-column",
        "W02-variant-columns-unsorted",
        "W21-revisions-not-object",
        "W01-facts-unknown-column",
        "W01-facts-missing-column",
        "W02-facts-columns-unsorted",
        "W01-facts-table-not-object",
    ],
)
def test_structural_refusals_on_reserialized_documents(
    canonical_bytes: bytes,
    code: str,
    label: str,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    corrupted = _structurally_corrupted(canonical_bytes, mutate)
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(corrupted)
    assert caught.value.code == code, caught.value


def test_w01_refuses_unparseable_bytes() -> None:
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(b"{not json")
    assert caught.value.code == "W01"


def test_string_lexeme_refuses_a_lone_surrogate_directly() -> None:
    with pytest.raises(CanonicalModelError, match="surrogate"):
        canonical_string_lexeme("a\ud800b")


def test_writer_emits_the_canonical_float_lexeme() -> None:
    assert codec_module._write(1.5) == "1.5"
