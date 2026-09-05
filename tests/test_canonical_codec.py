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
from codeclone.contracts import CANONICAL_WIRE_REVISION
from tests.test_canonical_roundtrip import analysis_facts, fixture_model


@pytest.fixture(scope="module")
def canonical_bytes() -> bytes:
    return encode_canonical_json(fixture_model())


def _replaced(data: bytes, needle: str, replacement: str) -> bytes:
    text = data.decode("utf-8")
    assert text.count(needle) == 1, f"needle not unique: {needle!r}"
    return text.replace(needle, replacement).encode("utf-8")


# The inner seal's domain, spelled HERE and by hand.  A helper that imported
# the codec's own constant would follow it wherever it went and stay green --
# which is exactly how a second, undetected spelling of the generation
# survived in production.  These literals are third-party witnesses.
_GENERATION_0_DOMAIN = b"cc-canonical-wire:0\x00"
_GENERATION_1_DOMAIN = b"cc-canonical-wire:1\x00"


def _resealed(data: bytes, needle: str, replacement: str) -> bytes:
    """Corrupt the body and reseal integrity so only W24 can refuse."""
    text = data.decode("utf-8")
    marker = ',"integrity":'
    body, _, _tail = text.partition(marker)
    assert body.count(needle) == 1, f"needle not unique in body: {needle!r}"
    new_body = body.replace(needle, replacement)[1:]
    digest = hashlib.sha256(_GENERATION_0_DOMAIN + new_body.encode("utf-8")).hexdigest()
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
        '"file":[0,0,0,1,1,2,2,2],"qualname":["A.maybe","A.run","A.stop","dead_probe","run","clone_only","helper","zz"]',
        '"qualname":["A.maybe","A.run","A.stop","dead_probe","run","clone_only","helper","zz"],"file":[0,0,0,1,1,2,2,2]',
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
    ("W06", "NaN literal", '"file":[0,0,0,1,1,2,2,2]', '"file":[NaN,0,0,1,1,2,2,2]'),
    (
        "W07",
        "fraction in an integer slot",
        '"file":[0,0,0,1,1,2,2,2]',
        '"file":[0.5,0,0,1,1,2,2,2]',
    ),
    (
        "W07",
        "integer above 2**31-1",
        '"file":[0,0,0,1,1,2,2,2]',
        '"file":[2147483648,0,0,1,1,2,2,2]',
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
        '"2":["module",1]',
        '"2":["symbol",1]',
    ),
    (
        "W10",
        "ordinal beyond its table",
        '"file":[0,0,0,1,1,2,2,2]',
        '"file":[0,0,0,1,1,2,2,9]',
    ),
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
        '"source":[["file",2],["module",1],["module",1],["module",2]]',
        '"source":[["banana",2],["module",1],["module",1],["module",2]]',
    ),
    (
        "W09",
        "endpoint tag not admitted",
        '"source":[["file",2],["module",1],["module",1],["module",2]]',
        '"source":[["symbol",2],["module",1],["module",1],["module",2]]',
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
        "unknown dependency cycle kind tag",
        '"dependency_cycles":{"kind":["import_cycle"',
        '"dependency_cycles":{"kind":["banana"',
    ),
    (
        "W13",
        "duplicate cycle module set (classified-once law in-band)",
        '"modules":[[1,2],[1,2,3]]',
        '"modules":[[1,2],[1,2]]',
    ),
    (
        "W12",
        "cycle rows out of module-set order",
        '"modules":[[1,2],[1,2,3]]',
        '"modules":[[1,2,3],[1,2]]',
    ),
    (
        "W14",
        "cycle members not strictly increasing",
        '"modules":[[1,2],[1,2,3]]',
        '"modules":[[2,1],[1,2,3]]',
    ),
    (
        "W18",
        "cycle with fewer than two modules",
        '"modules":[[1,2],[1,2,3]]',
        '"modules":[[1],[1,2,3]]',
    ),
    (
        "W10",
        "cycle module ordinal beyond the table",
        '"modules":[[1,2],[1,2,3]]',
        '"modules":[[1,2],[1,2,9]]',
    ),
    (
        "W08",
        "unknown clone kind tag",
        '"clone_groups":{"clone_kind":["block"',
        '"clone_groups":{"clone_kind":["banana"',
    ),
    (
        "W13",
        "duplicate clone group key",
        '"clone_kind":["block","function","segment"]',
        '"clone_kind":["block","function","function"]',
    ),
    (
        "W12",
        "clone groups out of kind-key order",
        '"clone_kind":["block","function","segment"]',
        '"clone_kind":["block","segment","function"]',
    ),
    (
        "W18",
        "empty clone group key",
        '"group_key":["bb22|bb22|bb22|bb22","aa11|0-19","aa11|0-19"]',
        '"group_key":["","aa11|0-19","aa11|0-19"]',
    ),
    (
        "W18",
        "clone group with fewer than two items",
        "[[1,4,16],[4,19,31]]",
        "[[1,4,16]]",
    ),
    (
        "W13",
        "duplicate clone item cell",
        "[[1,4,16],[4,19,31]]",
        "[[1,4,16],[1,4,16]]",
    ),
    (
        "W12",
        "clone item cells out of order",
        "[[1,4,16],[4,19,31]]",
        "[[4,19,31],[1,4,16]]",
    ),
    (
        "W07",
        "clone item start below the span floor",
        "[[1,4,16],[4,19,31]]",
        "[[1,0,16],[4,19,31]]",
    ),
    (
        "W18",
        "clone item end precedes its start",
        "[[1,4,16],[4,19,31]]",
        "[[1,4,3],[4,19,31]]",
    ),
    (
        "W18",
        "clone item cell of a wrong arity",
        "[[1,4,16],[4,19,31]]",
        "[[1,4],[4,19,31]]",
    ),
    (
        "W10",
        "clone item symbol ordinal beyond the table",
        "[[1,4,16],[4,19,31]]",
        "[[1,4,16],[9,19,31]]",
    ),
    (
        "W08",
        "unknown dead-code observation kind tag",
        '"observation_kind":["symbol","unreachable_statement"',
        '"observation_kind":["banana","unreachable_statement"',
    ),
    (
        "W08",
        "unknown dead-code candidate kind tag",
        '"candidate_kind":["method","function","import","method","function"]',
        '"candidate_kind":["banana","function","import","method","function"]',
    ),
    (
        "W08",
        "unknown live root reason tag",
        '"live_root_reason":["export_root","","external_decorator","",""]',
        '"live_root_reason":["banana","","external_decorator","",""]',
    ),
    (
        "W08",
        "unknown dead-code entity tag",
        '"entity":[["module",0,"Exported.helper"]',
        '"entity":[["banana",0,"Exported.helper"]',
    ),
    (
        "W09",
        "entity tag not admitted for a dead-code entity",
        '"entity":[["module",0,"Exported.helper"]',
        '"entity":[["file",0,"Exported.helper"]',
    ),
    (
        "W10",
        "dead-code module ordinal beyond the table",
        '"entity":[["module",0,"Exported.helper"]',
        '"entity":[["module",9,"Exported.helper"]',
    ),
    (
        "W18",
        "dead-code symbol slot of a wrong arity",
        '["symbol",0],["symbol",3]',
        '["symbol",0,0],["symbol",3]',
    ),
    (
        "W20",
        "abstained row carrying a live root",
        '"live_root_reason":["export_root","","external_decorator","",""]',
        '"live_root_reason":["export_root","","external_decorator","export_root",""]',
    ),
    (
        "W12",
        "dead-code rows out of entity-kind order",
        '"observation_kind":["symbol","unreachable_statement"',
        '"observation_kind":["unreachable_statement","symbol"',
    ),
    (
        "W13",
        "duplicate dead-code key",
        '"observation_kind":["symbol","unreachable_statement"',
        '"observation_kind":["symbol","symbol"',
    ),
    (
        "W12",
        "dead-code markers out of order",
        '[["aa","bb"],["cc","dd"]]',
        '[["cc","dd"],["aa","bb"]]',
    ),
    (
        "W13",
        "duplicate dead-code marker",
        '[["aa","bb"],["cc","dd"]]',
        '[["aa","bb"],["aa","bb"]]',
    ),
    (
        "W18",
        "dead-code marker not a pair",
        '[["aa","bb"],["cc","dd"]]',
        '[["aa"],["cc","dd"]]',
    ),
    (
        "W18",
        "dead-code marker with an empty member",
        '[["aa","bb"],["cc","dd"]]',
        '[["","bb"],["cc","dd"]]',
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
        "unknown risk dimension tag",
        '"risk_observations":{"dimension":["cyclomatic_complexity",',
        '"risk_observations":{"dimension":["banana",',
    ),
    (
        "W07",
        "risk numerator below the family floor",
        '"numerator":[7,7,2,1]',
        '"numerator":[0,7,2,1]',
    ),
    (
        "W07",
        "risk declaration site below the family floor",
        '"start_line":[10,40,10,1]',
        '"start_line":[0,40,10,1]',
    ),
    (
        "W12",
        "risk rows out of declaration-key order",
        '"start_line":[10,40,10,1]',
        '"start_line":[40,10,10,1]',
    ),
    (
        "W13",
        "duplicate risk declaration key",
        '"start_line":[10,40,10,1]',
        '"start_line":[10,10,10,1]',
    ),
    (
        "W08",
        "unknown adoption feature tag",
        '"feature":["typing.parameters","docstrings.public_symbols"',
        '"feature":["banana","docstrings.public_symbols"',
    ),
    (
        "W07",
        "adoption denominator below the family floor",
        '"denominator":[1,3,9,9,5]',
        '"denominator":[0,3,9,9,5]',
    ),
    (
        "W18",
        "adoption numerator above its denominator",
        '"denominator":[1,3,9,9,5],"feature"',
        '"denominator":[1,1,9,9,5],"feature"',
    ),
    (
        "W08",
        "adoption scope tag unknown",
        '"scope":[["file",2],["module",1]',
        '"scope":[["banana",2],["module",1]',
    ),
    (
        "W09",
        "adoption scope tag not admitted",
        '"scope":[["file",2],["module",1]',
        '"scope":[["symbol",2],["module",1]',
    ),
    (
        "W12",
        "adoption rows out of scope-key order",
        '"feature":["typing.parameters","docstrings.public_symbols",'
        '"typing.parameters","typing.returns","typing.returns"]',
        '"feature":["typing.parameters","typing.parameters",'
        '"docstrings.public_symbols","typing.returns","typing.returns"]',
    ),
    (
        "W13",
        "duplicate adoption key",
        '"feature":["typing.parameters","docstrings.public_symbols",'
        '"typing.parameters","typing.returns","typing.returns"]',
        '"feature":["typing.parameters","typing.parameters",'
        '"typing.parameters","typing.returns","typing.returns"]',
    ),
    (
        "W08",
        "unknown surface source kind tag",
        '"source_kind":["production","production","production","production","tests","production"]',
        '"source_kind":["banana","production","production","production","tests","production"]',
    ),
    (
        "W08",
        "unknown surface category tag",
        '"category":["dynamic_execution","dynamic_execution"',
        '"category":["banana","dynamic_execution"',
    ),
    (
        "W18",
        "empty surface evidence symbol",
        '"evidence_symbol":["compile","eval"',
        '"evidence_symbol":["","eval"',
    ),
    (
        "W10",
        "surface file ordinal beyond the table",
        '"file":[0,0,0,0,1,2]',
        '"file":[0,0,0,0,1,9]',
    ),
    (
        "W18",
        "empty surface capability",
        '"capability":["dynamic_compile"',
        '"capability":[""',
    ),
    (
        "W18",
        "surface end line precedes its start",
        '"end_line":[22,22,27,27,3,16]',
        '"end_line":[21,22,27,27,3,16]',
    ),
    (
        "W07",
        "surface start line below the span floor",
        '"start_line":[22,22,26,27,3,16]',
        '"start_line":[0,22,26,27,3,16]',
    ),
    (
        "W20",
        "module-scope surface with a local name",
        '"qualname":["run_dynamic","run_dynamic","decode_blob","ShellHelper","probe",""]',
        '"qualname":["run_dynamic","run_dynamic","decode_blob","ShellHelper","probe","ghost"]',
    ),
    (
        "W20",
        "callable-scope surface without a local name",
        '"qualname":["run_dynamic","run_dynamic","decode_blob","ShellHelper","probe",""]',
        '"qualname":["","run_dynamic","decode_blob","ShellHelper","probe",""]',
    ),
    (
        "W12",
        "surface rows out of evidence-key order",
        '"evidence_symbol":["compile","eval","pickle.loads","pickle.loads","subprocess.call","subprocess"]',
        '"evidence_symbol":["eval","compile","pickle.loads","pickle.loads","subprocess.call","subprocess"]',
    ),
    (
        "W13",
        "duplicate surface evidence key",
        '"evidence_symbol":["compile","eval","pickle.loads","pickle.loads","subprocess.call","subprocess"]',
        '"evidence_symbol":["compile","compile","pickle.loads","pickle.loads","subprocess.call","subprocess"]',
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
        '"sink_identity":[1,1]',
        '"sink_identity":[0,1]',
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
        '"source":[1,2,6],"target":[6,7,2]',
        '"source":[1,2,2],"target":[6,7,7]',
    ),
    ("W14", "set elements unsorted", "[4,5]", "[5,4]"),
    ("W14", "set element repeated", "[4,5]", "[4,4]"),
    (
        "W15",
        "diverging column lengths",
        '"qualname":["A.maybe","A.run","A.stop","dead_probe","run","clone_only","helper","zz"]',
        '"qualname":["A.maybe","A.run","A.stop","dead_probe","run","clone_only","helper"]',
    ),
    (
        "W16",
        "producer without the FUNCTION role",
        '"producer_sets":[[1,2],[1,6]]',
        '"producer_sets":[[1,2],[1,3]]',
    ),
    ("W17", "absolute FILE path", '"path":["pkg/a.py",', '"path":["/pkg/a.py",'),
    (
        "W18",
        "null where forbidden",
        '"module":["dead.only","pkg.a","tools.helper","zz.top","zzz.adoption.only"]',
        '"module":[null,"pkg.a","tools.helper","zz.top","zzz.adoption.only"]',
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
    ("W19", "sparse position beyond rows", '"target":{"4":1}', '"target":{"9":1}'),
    (
        "W20",
        "mandatory variant slot missing",
        '"label":{"0":"os.replace"},',
        "",
    ),
    (
        "W20",
        "variant slot on a foreign family",
        '"target":{"4":1}',
        '"target":{"3":1}',
    ),
    (
        # The needle above MOVES the producer's slot, so the mandatory-slot
        # loop refuses it too and the foreign-slot branch is never the reason.
        # This one ADDS a slot to a foreign family and leaves every mandatory
        # slot in place, so only the foreign-slot branch can refuse it.
        "W20",
        "foreign variant slot added beside every mandatory one",
        '"target":{"4":1}',
        '"target":{"3":1,"4":1}',
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
        '"symbol":[1,2,4,6,6],"symbol_kind"',
        '"symbol":[1,2,4,6,2],"symbol_kind"',
    ),
    (
        "W18",
        "api parameters cell is not an array",
        ',[],[],[["value"',
        ',7,[],[["value"',
    ),
    (
        "W01",
        "run_scalars record missing a scalar",
        '"run_scalars":{"classes":7,',
        '"run_scalars":{',
    ),
    (
        "W02",
        "run_scalars keys out of canonical order",
        '"run_scalars":{"classes":7,"files_analyzed":2,',
        '"run_scalars":{"files_analyzed":2,"classes":7,',
    ),
    (
        "W18",
        "run_scalars boolean scalar",
        '"run_scalars":{"classes":7,',
        '"run_scalars":{"classes":true,',
    ),
    (
        "W07",
        "run_scalars scalar out of wire range",
        '"files_skipped":0,"functions":41,',
        '"files_skipped":-1,"functions":41,',
    ),
    (
        "W01",
        "analysis_population record missing a member",
        '"analysis_population":{"analysis_mode":"full",',
        '"analysis_population":{',
    ),
    (
        "W02",
        "analysis_population keys out of canonical order",
        '{"analysis_mode":"full","analysis_profile":[["min_loc",6],["min_stmt",4]],',
        '{"analysis_profile":[["min_loc",6],["min_stmt",4]],"analysis_mode":"full",',
    ),
    (
        "W18",
        "analysis_population empty mode",
        '"analysis_mode":"full"',
        '"analysis_mode":""',
    ),
    (
        "W01",
        "analysis_population profile pair is not a pair",
        '[["min_loc",6],',
        '[["min_loc",6,6],',
    ),
    (
        "W18",
        "analysis_population profile value is not an int",
        '[["min_loc",6],["min_stmt",4]]',
        '[["min_loc","6"],["min_stmt",4]]',
    ),
    (
        "W02",
        "analysis_population profile pairs unsorted",
        '[["min_loc",6],["min_stmt",4]]',
        '[["min_stmt",4],["min_loc",6]]',
    ),
    (
        "W18",
        "analysis_population state pair member is not a string",
        '["complexity","complete"]',
        '["complexity",7]',
    ),
    (
        "W18",
        "analysis_population state pair is not an array",
        '[["complexity","complete"],',
        "[7,",
    ),
    (
        "W08",
        "analysis_population unknown execution state",
        '"not_executed"',
        '"paused"',
    ),
    (
        "W02",
        "analysis_population producer families unsorted",
        '[["complexity","complete"],["near_miss","not_executed"]',
        '[["near_miss","not_executed"],["complexity","complete"]',
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
        # the C0 escape the encoder would have spelled in lowercase: this is
        # the only input that separates the lowercase clause from its
        # uppercase twin, because W24 refuses exactly what the encoder would
        # not itself emit -- an encoder mutated to {code:04X} accepts it.
        ("uppercase C0 escape", '"x.y"', '"\\u001B.y"'),
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
    [
        ("a\x1bb", '"a\\u001bb"'),
        ("a\x0bb", '"a\\u000bb"'),
        ("a\x1fb", '"a\\u001fb"'),
        ("a\x01b", '"a\\u0001b"'),
    ],
)
def test_c0_escapes_are_lowercase_hex(value: str, lexeme: str) -> None:
    """SS7.9: lowercase ``\\u00xx`` for the C0 characters JSON gives no short
    form. ``\\x01`` -- the only C0 character the rest of the suite spells --
    has no hex letters, so it cannot tell the two cases apart; every value
    here carries a letter in its low nibble and dies on ``{code:04X}``."""
    assert canonical_string_lexeme(value) == lexeme


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
        '"function":[1,2,4,6]',
        '"function":["1",2,4,6]',
    ),
    (
        "W18",
        "scalar where an array is declared",
        '"analyzed_files":[0,2]',
        '"analyzed_files":7',
    ),
    ("W18", "scalar where a sparse map is declared", '"target":{"4":1}', '"target":7'),
    (
        "W18",
        "head is not a pair",
        '"2":["module",1]',
        '"2":["module",1,1]',
    ),
    (
        "W18",
        "endpoint is not a pair",
        '"source":[["file",2],["module",1],["module",1],["module",2]]',
        '"source":[["file",2,1],["module",1],["module",1],["module",2]]',
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
        '"module":["dead.only","pkg.a","tools.helper","zz.top","zzz.adoption.only"]',
        '"module":["","pkg.a","tools.helper","zz.top","zzz.adoption.only"]',
    ),
    (
        "W08",
        "unknown effect_kind",
        '"effect_kind":{"0":"artifact_write"}',
        '"effect_kind":{"0":"banana"}',
    ),
    ("W18", "empty effect label", '"label":{"0":"os.replace"}', '"label":{"0":""}'),
    ("W18", "empty qualname", '"qualname":["A.maybe"', '"qualname":[""'),
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
        (
            "W01",
            "run_scalars member is not an object",
            lambda doc: doc["facts"].__setitem__("run_scalars", 7),
        ),
        (
            "W01",
            "analysis_population member is not an object",
            lambda doc: doc["facts"].__setitem__("analysis_population", 7),
        ),
        (
            # The facts CONTAINER's own member order, not the columns inside
            # one family. Nothing else reorders facts members, so without
            # this the decoder's declared-order check for `facts` is vacuous
            # and a reordered document is refused only by the integrity seal.
            "W02",
            "facts families out of the declared order",
            lambda doc: doc.__setitem__(
                "facts", _reordered(doc["facts"], ["candidates"])
            ),
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
        "W01-run-scalars-not-object",
        "W01-analysis-population-not-object",
        "W02-facts-families-unordered",
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


def test_absent_analysis_population_is_the_empty_member_decoding_none() -> None:
    """RULING-2026-08-31 §3 absence law on the wire: a run with no
    execution witness emits the EMPTY record member and decodes back to
    the typed absence — never a fabricated record, never a refusal.
    Found by mutation: dropping the decoder's empty-member branch
    survived the whole codec home, so this pin is the input that
    reaches it."""
    import dataclasses

    model = fixture_model()
    stripped = dataclasses.replace(
        model,
        facts=dataclasses.replace(
            model.facts,
            analysis=dataclasses.replace(
                model.facts.analysis, analysis_population=None
            ),
        ),
    )
    payload = encode_canonical_json(stripped)
    assert b'"analysis_population":{}' in payload
    decoded = decode_canonical_json(payload)
    assert decoded.facts.analysis.analysis_population is None


# ---------------------------------------------------------------------------
# The inner seal's domain is DERIVED from the wire revision, not respelled.
#
# The OUTER seal already closes this class by construction
# (``canonical.export.artifact_domain`` builds its domain from the revision).
# The inner seal did not: its domain was an independent byte literal that
# merely agreed with ``CANONICAL_WIRE_REVISION`` today.  The first bump would
# have declared ``format.wire = "1"`` and sealed under the generation-0
# domain -- the separator defeated at the exact moment it first matters.
# ---------------------------------------------------------------------------


def _sealed_under(body: str, domain: bytes) -> bytes:
    """Seal one document body under an EXPLICITLY GIVEN domain.

    The domain is a parameter and never read from production, so a document
    sealed under a generation this build does not use can be built at all.
    """
    digest = hashlib.sha256(domain + body.encode("utf-8")).hexdigest()
    return (
        "{" + body + f',"integrity":{{"algorithm":"sha256","value":"{digest}"}}}}'
    ).encode("utf-8")


def _body_of(document: bytes) -> str:
    """The sealed body: the bytes the seal covers, brace and tail excluded."""
    return document.decode("utf-8").partition(',"integrity":')[0][1:]


def test_the_seal_domain_is_derived_from_the_wire_revision() -> None:
    """Pin 1: derivation, not coincidence.

    The literals here are written by hand; production computes them.  The
    third assertion binds today's authority to today's domain, so a real
    generation bump has to walk through this pin deliberately instead of
    silently leaving the seal a generation behind.
    """
    assert codec_module._wire_integrity_domain("0") == _GENERATION_0_DOMAIN
    assert codec_module._wire_integrity_domain("1") == _GENERATION_1_DOMAIN
    assert (
        codec_module._wire_integrity_domain(CANONICAL_WIRE_REVISION)
        == _GENERATION_0_DOMAIN
    )


def test_the_domain_prefix_has_exactly_one_spelling_in_the_codec() -> None:
    """The defect itself, pinned at the source: one owner, one spelling.

    The prefix may appear ONCE in the codec -- inside the constructor.  Any
    other occurrence is a second spelling of the generation, free to drift
    from the revision it claims to name.
    """
    source = inspect.getsource(codec_module)
    assert source.count("cc-canonical-wire:") == 1


def test_the_naive_cross_generation_pin_cannot_reach_the_seal() -> None:
    """Reachability accounting for the pin below -- not a proof of the fix.

    The obvious spelling ("a body sealed under domain 0 must not validate as
    generation 1") is a guard no input can reach: a foreign generation is
    refused at the revision fence, long before the seal is recomputed.
    Written that way the pin is green in every configuration, defect or
    repair, and proves nothing.  This test holds that fact in place.
    """
    native = encode_canonical_json(fixture_model())
    forged = _sealed_under(
        _body_of(native).replace('"wire":"0"', '"wire":"1"', 1), _GENERATION_0_DOMAIN
    )
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(forged)
    assert caught.value.code == "W21"


def test_a_document_declaring_the_next_generation_is_refused_by_this_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin 3: the defect's own signature, in the only form that can fire.

    A generation-1 build is simulated by moving the wire authority alone --
    every derivation from it must follow, which is the whole claim.  The
    document then DECLARES generation 1, passes the revision fence, and
    lands precisely on the seal check.

    Both boundaries die here: the forged case catches a domain hard-coded in
    both writer and reader, and the positive control above it catches either
    half alone -- derive the writer but not the reader, or the reverse, and
    what this build seals it can no longer verify.
    """
    monkeypatch.setattr(codec_module, "CANONICAL_WIRE_REVISION", "1")
    native = encode_canonical_json(fixture_model())
    assert b'"wire":"1"' in native

    # Positive control, same causal path: what this build seals, it verifies.
    decode_canonical_json(native)

    forged = _sealed_under(_body_of(native), _GENERATION_0_DOMAIN)
    assert _body_of(forged) == _body_of(native), "only the seal may differ"
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(forged)
    assert caught.value.code == "W23"
    assert "does not seal" in str(caught.value)


_GENERATION_9_DOMAIN = b"cc-canonical-wire:9\x00"


def test_the_seal_is_checked_under_this_build_never_under_the_declared_one() -> None:
    """The domain comes from THIS process, never from the document.

    Through :func:`decode_canonical_json` the distinction cannot arise: the
    revision fence refuses a foreign ``format.wire`` (``W21``) some seventy
    lines before the seal is recomputed, so the declared revision and the
    process revision are always equal by the time integrity is checked.  A
    pin written at that door would be green in every configuration and would
    prove nothing.

    The door it CAN be reached through is the one an external verifier uses
    and the one a future reordering would open: :func:`_check_integrity`
    itself.  A document that declares generation 9 and is sealed under
    generation 9's domain must still be refused by a generation-0 build --
    a forgery does not get to choose the domain it is checked under.
    """

    body = _body_of(encode_canonical_json(fixture_model()))
    body_nine = body.replace('"wire":"0"', '"wire":"9"', 1)
    assert body_nine != body, "the declared revision must actually differ"

    forged = _sealed_under(body_nine, _GENERATION_9_DOMAIN)
    root = codec_module._parse_document(forged)
    with pytest.raises(WireDecodeError) as caught:
        codec_module._check_integrity(forged, root)
    assert caught.value.code == "W23"
    assert "does not seal" in str(caught.value)

    # Positive control on the same function: what this build seals, this
    # build verifies -- so the refusal above is the domain, not the door.
    honest = _sealed_under(body, _GENERATION_0_DOMAIN)
    codec_module._check_integrity(honest, codec_module._parse_document(honest))
