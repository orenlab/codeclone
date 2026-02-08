import json
import sys
from pathlib import Path

import pytest

import codeclone.baseline as baseline_mod
from codeclone.baseline import Baseline, BaselineStatus, coerce_baseline_status
from codeclone.contracts import BASELINE_FINGERPRINT_VERSION, BASELINE_SCHEMA_VERSION
from codeclone.errors import BaselineValidationError


def _python_tag() -> str:
    impl = sys.implementation.name
    prefix = "cp" if impl == "cpython" else impl[:2]
    major, minor = sys.version_info[:2]
    return f"{prefix}{major}{minor}"


def _func_id() -> str:
    return f"{'a' * 40}|0-19"


def _block_id() -> str:
    return "|".join(["a" * 40, "b" * 40, "c" * 40, "d" * 40])


def _trusted_payload(
    *,
    functions: list[str] | None = None,
    blocks: list[str] | None = None,
    schema_version: str = BASELINE_SCHEMA_VERSION,
    fingerprint_version: str = BASELINE_FINGERPRINT_VERSION,
    python_tag: str | None = None,
    created_at: str | None = "2026-02-08T11:43:16Z",
    generator_version: str = "1.4.0",
) -> dict[str, object]:
    payload = baseline_mod._baseline_payload(
        functions=set(functions or [_func_id()]),
        blocks=set(blocks or [_block_id()]),
        generator="codeclone",
        schema_version=schema_version,
        fingerprint_version=fingerprint_version,
        python_tag=python_tag or _python_tag(),
        generator_version=generator_version,
        created_at=created_at,
    )
    return payload


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")


def test_baseline_diff() -> None:
    baseline = Baseline("dummy")
    baseline.functions = {"f1"}
    baseline.blocks = {"b1"}
    new_func, new_block = baseline.diff({"f1": [], "f2": []}, {"b1": [], "b2": []})
    assert new_func == {"f2"}
    assert new_block == {"b2"}


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        (BaselineStatus.OK, BaselineStatus.OK),
        ("ok", BaselineStatus.OK),
        ("not-a-status", BaselineStatus.INVALID_TYPE),
        (None, BaselineStatus.INVALID_TYPE),
    ],
)
def test_coerce_baseline_status(
    raw_status: str | BaselineStatus | None, expected: BaselineStatus
) -> None:
    assert coerce_baseline_status(raw_status) == expected


def test_baseline_roundtrip_v1(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline = Baseline(baseline_path)
    baseline.functions = {_func_id()}
    baseline.blocks = {_block_id()}
    baseline.save()

    payload = json.loads(baseline_path.read_text("utf-8"))
    assert set(payload.keys()) == {"meta", "clones"}
    assert set(payload["meta"].keys()) >= {
        "generator",
        "schema_version",
        "fingerprint_version",
        "python_tag",
        "created_at",
        "payload_sha256",
    }
    assert set(payload["clones"].keys()) == {"functions", "blocks"}
    assert payload["meta"]["schema_version"] == BASELINE_SCHEMA_VERSION
    assert payload["meta"]["fingerprint_version"] == BASELINE_FINGERPRINT_VERSION
    assert payload["meta"]["python_tag"] == _python_tag()
    assert isinstance(payload["meta"]["payload_sha256"], str)

    loaded = Baseline(baseline_path)
    loaded.load()
    loaded.verify_compatibility(current_python_tag=_python_tag())
    assert loaded.functions == {_func_id()}
    assert loaded.blocks == {_block_id()}


def test_baseline_save_atomic(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline = Baseline(baseline_path)
    baseline.functions = {_func_id()}
    baseline.blocks = {_block_id()}
    baseline.save()
    assert baseline_path.exists()
    assert not (tmp_path / "baseline.json.tmp").exists()


def test_baseline_load_missing(tmp_path: Path) -> None:
    baseline = Baseline(tmp_path / "missing.json")
    baseline.load()
    assert baseline.functions == set()
    assert baseline.blocks == set()


def test_baseline_load_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload())
    monkeypatch.setattr(baseline_mod, "MAX_BASELINE_SIZE_BYTES", 1)
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="too large") as exc:
        baseline.load()
    assert exc.value.status == "too_large"


def test_baseline_load_stat_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload())
    original_exists = Path.exists

    def _boom_exists(self: Path) -> bool:
        if self == baseline_path:
            raise OSError("blocked")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _boom_exists)
    baseline = Baseline(baseline_path)
    with pytest.raises(
        BaselineValidationError, match="Cannot stat baseline file"
    ) as exc:
        baseline.load()
    assert exc.value.status == "invalid_type"


def test_baseline_load_invalid_json(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("{broken json", "utf-8")
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="Corrupted baseline file") as exc:
        baseline.load()
    assert exc.value.status == "invalid_json"


def test_baseline_load_non_object_payload(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text("[]", "utf-8")
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="must be an object") as exc:
        baseline.load()
    assert exc.value.status == "invalid_type"


def test_baseline_load_legacy_payload(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"functions": [], "blocks": [], "baseline_version": "1.3.0"}),
        "utf-8",
    )
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="legacy") as exc:
        baseline.load()
    assert exc.value.status == "missing_fields"


def test_baseline_load_missing_top_level_key(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, {"meta": {}})
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="missing top-level keys") as exc:
        baseline.load()
    assert exc.value.status == "missing_fields"


def test_baseline_load_extra_top_level_key(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    assert isinstance(payload, dict)
    payload["extra"] = 1
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    with pytest.raises(
        BaselineValidationError, match="unexpected top-level keys"
    ) as exc:
        baseline.load()
    assert exc.value.status == "invalid_type"


def test_baseline_load_meta_and_clones_must_be_objects(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, {"meta": [], "clones": {}})
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="'meta' must be object"):
        baseline.load()
    _write_payload(baseline_path, {"meta": {}, "clones": []})
    with pytest.raises(BaselineValidationError, match="'clones' must be object"):
        baseline.load()


def test_baseline_load_missing_required_meta_fields(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(
        baseline_path,
        {"meta": {"generator": "codeclone"}, "clones": {"functions": [], "blocks": []}},
    )
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="missing required fields") as exc:
        baseline.load()
    assert exc.value.status == "missing_fields"


def test_baseline_load_missing_required_clone_fields(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    assert isinstance(payload, dict)
    payload["clones"] = {"functions": [_func_id()]}
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="missing required fields") as exc:
        baseline.load()
    assert exc.value.status == "missing_fields"


def test_baseline_load_unexpected_clone_fields(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    assert isinstance(payload, dict)
    clones = payload["clones"]
    assert isinstance(clones, dict)
    clones["segments"] = []
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="unexpected clone keys") as exc:
        baseline.load()
    assert exc.value.status == "invalid_type"


@pytest.mark.parametrize(
    ("container", "field", "value", "error_match"),
    [
        ("meta", "generator", 1, "'generator' must be string"),
        ("meta", "schema_version", "x", "schema_version"),
        ("meta", "fingerprint_version", 1, "'fingerprint_version' must be string"),
        ("meta", "python_tag", "3.13", "python_tag"),
        ("meta", "created_at", "2026-02-08T11:43:16+00:00", "created_at"),
        ("meta", "payload_sha256", 1, "payload_sha256"),
        ("clones", "functions", "x", "functions"),
        ("clones", "blocks", "x", "blocks"),
    ],
)
def test_baseline_type_matrix(
    tmp_path: Path,
    container: str,
    field: str,
    value: object,
    error_match: str,
) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    target = payload[container]
    assert isinstance(target, dict)
    target[field] = value
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match=error_match) as exc:
        baseline.load()
    assert exc.value.status == "invalid_type"


def test_baseline_id_lists_must_be_sorted_and_unique(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    clones = payload["clones"]
    assert isinstance(clones, dict)
    clones["functions"] = [_func_id(), _func_id()]
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="sorted and unique") as exc:
        baseline.load()
    assert exc.value.status == "invalid_type"

    payload = _trusted_payload()
    clones = payload["clones"]
    assert isinstance(clones, dict)
    clones["functions"] = [f"{'b' * 40}|0-19", _func_id()]
    _write_payload(baseline_path, payload)
    with pytest.raises(BaselineValidationError, match="sorted and unique") as exc2:
        baseline.load()
    assert exc2.value.status == "invalid_type"


def test_baseline_id_format_validation(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload(functions=["bad-id"])
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    with pytest.raises(BaselineValidationError, match="invalid id format") as exc:
        baseline.load()
    assert exc.value.status == "invalid_type"

    payload = _trusted_payload(blocks=["bad-block-id"])
    _write_payload(baseline_path, payload)
    with pytest.raises(BaselineValidationError, match="invalid id format") as exc2:
        baseline.load()
    assert exc2.value.status == "invalid_type"


def test_baseline_verify_generator_mismatch(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    assert isinstance(payload, dict)
    meta = payload["meta"]
    assert isinstance(meta, dict)
    meta["generator"] = "eviltool"
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    baseline.load()
    with pytest.raises(BaselineValidationError, match="generator mismatch") as exc:
        baseline.verify_compatibility(current_python_tag=_python_tag())
    assert exc.value.status == "generator_mismatch"


def test_baseline_verify_schema_too_new(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload(schema_version="1.1"))
    baseline = Baseline(baseline_path)
    baseline.load()
    with pytest.raises(BaselineValidationError, match="newer than supported") as exc:
        baseline.verify_compatibility(current_python_tag=_python_tag())
    assert exc.value.status == "mismatch_schema_version"


def test_baseline_verify_fingerprint_mismatch(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload(fingerprint_version="2"))
    baseline = Baseline(baseline_path)
    baseline.load()
    with pytest.raises(
        BaselineValidationError, match="fingerprint version mismatch"
    ) as exc:
        baseline.verify_compatibility(current_python_tag=_python_tag())
    assert exc.value.status == "mismatch_fingerprint_version"


def test_baseline_verify_python_tag_mismatch(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload(python_tag="cp999"))
    baseline = Baseline(baseline_path)
    baseline.load()
    with pytest.raises(BaselineValidationError, match="python tag mismatch") as exc:
        baseline.verify_compatibility(current_python_tag=_python_tag())
    assert exc.value.status == "mismatch_python_version"


def test_baseline_verify_integrity_missing(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    assert isinstance(payload, dict)
    meta = payload["meta"]
    assert isinstance(meta, dict)
    meta["payload_sha256"] = "zz"
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    baseline.load()
    with pytest.raises(BaselineValidationError, match="payload hash is missing") as exc:
        baseline.verify_integrity()
    assert exc.value.status == "integrity_missing"


def test_baseline_verify_integrity_mismatch(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload()
    assert isinstance(payload, dict)
    clones = payload["clones"]
    assert isinstance(clones, dict)
    clones["functions"] = [_func_id(), f"{'b' * 40}|0-19"]
    _write_payload(baseline_path, payload)
    baseline = Baseline(baseline_path)
    baseline.load()
    with pytest.raises(BaselineValidationError, match="payload_sha256 mismatch") as exc:
        baseline.verify_integrity()
    assert exc.value.status == "integrity_failed"


def test_baseline_hash_canonical_determinism() -> None:
    hash_a = baseline_mod._compute_payload_sha256(
        functions={"a" * 40 + "|0-19", "b" * 40 + "|0-19"},
        blocks={_block_id()},
        schema_version="1.0",
        fingerprint_version="1",
        python_tag="cp313",
    )
    hash_b = baseline_mod._compute_payload_sha256(
        functions={"b" * 40 + "|0-19", "a" * 40 + "|0-19"},
        blocks={_block_id()},
        schema_version="1.0",
        fingerprint_version="1",
        python_tag="cp313",
    )
    assert hash_a == hash_b


def test_baseline_from_groups_defaults() -> None:
    baseline = Baseline.from_groups(
        {"a" * 40 + "|0-19": []},
        {_block_id(): []},
        path="baseline.json",
    )
    assert baseline.path == Path("baseline.json")
    assert baseline.schema_version == BASELINE_SCHEMA_VERSION
    assert baseline.fingerprint_version == BASELINE_FINGERPRINT_VERSION
    assert baseline.python_tag == _python_tag()
    assert baseline.generator == "codeclone"


def test_baseline_verify_schema_major_mismatch(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload(schema_version="2.0"))
    baseline = Baseline(baseline_path)
    baseline.load()
    with pytest.raises(BaselineValidationError, match="schema version mismatch") as exc:
        baseline.verify_compatibility(current_python_tag=_python_tag())
    assert exc.value.status == "mismatch_schema_version"


@pytest.mark.parametrize(
    ("attr", "match_text"),
    [
        ("schema_version", "schema version is missing"),
        ("fingerprint_version", "fingerprint version is missing"),
        ("python_tag", "python_tag is missing"),
    ],
)
def test_baseline_verify_compatibility_missing_fields(
    tmp_path: Path, attr: str, match_text: str
) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload())
    baseline = Baseline(baseline_path)
    baseline.load()
    setattr(baseline, attr, None)
    with pytest.raises(BaselineValidationError, match=match_text) as exc:
        baseline.verify_compatibility(current_python_tag=_python_tag())
    assert exc.value.status == "missing_fields"


def test_baseline_verify_integrity_payload_not_string(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload())
    baseline = Baseline(baseline_path)
    baseline.load()
    baseline.payload_sha256 = None
    with pytest.raises(BaselineValidationError, match="payload hash is missing") as exc:
        baseline.verify_integrity()
    assert exc.value.status == "integrity_missing"


def test_baseline_verify_integrity_payload_non_hex(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload())
    baseline = Baseline(baseline_path)
    baseline.load()
    baseline.payload_sha256 = "g" * 64
    with pytest.raises(BaselineValidationError, match="payload hash is missing") as exc:
        baseline.verify_integrity()
    assert exc.value.status == "integrity_missing"


@pytest.mark.parametrize(
    ("attr", "match_text"),
    [
        ("schema_version", "schema version is missing for integrity"),
        ("fingerprint_version", "fingerprint version is missing for integrity"),
        ("python_tag", "python_tag is missing for integrity"),
    ],
)
def test_baseline_verify_integrity_missing_context_fields(
    tmp_path: Path, attr: str, match_text: str
) -> None:
    baseline_path = tmp_path / "baseline.json"
    _write_payload(baseline_path, _trusted_payload())
    baseline = Baseline(baseline_path)
    baseline.load()
    setattr(baseline, attr, None)
    with pytest.raises(BaselineValidationError, match=match_text) as exc:
        baseline.verify_integrity()
    assert exc.value.status == "missing_fields"


def test_baseline_safe_stat_size_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "baseline.json"

    def _boom_stat(self: Path) -> object:
        if self == path:
            raise OSError("blocked")
        return object()

    monkeypatch.setattr(Path, "stat", _boom_stat)
    with pytest.raises(
        BaselineValidationError, match="Cannot stat baseline file"
    ) as exc:
        baseline_mod._safe_stat_size(path)
    assert exc.value.status == "invalid_type"


def test_baseline_load_json_read_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("{}", "utf-8")

    def _boom_read(self: Path, *_args: object, **_kwargs: object) -> str:
        if self == path:
            raise OSError("blocked")
        return "{}"

    monkeypatch.setattr(Path, "read_text", _boom_read)
    with pytest.raises(
        BaselineValidationError, match="Cannot read baseline file"
    ) as exc:
        baseline_mod._load_json_object(path)
    assert exc.value.status == "invalid_json"


def test_baseline_optional_str_paths(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    assert baseline_mod._optional_str({}, "generator_version", path=path) is None
    with pytest.raises(
        BaselineValidationError,
        match="'generator_version' must be string",
    ) as exc:
        baseline_mod._optional_str(
            {"generator_version": 1},
            "generator_version",
            path=path,
        )
    assert exc.value.status == "invalid_type"


def test_baseline_load_legacy_codeclone_version_alias(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    payload = _trusted_payload(generator_version="1.4.0")
    meta = payload["meta"]
    assert isinstance(meta, dict)
    generator = meta.get("generator")
    assert isinstance(generator, dict)
    # Simulate pre-rename baseline metadata key.
    meta["codeclone_version"] = generator.pop("version")
    _write_payload(baseline_path, payload)

    baseline = Baseline(baseline_path)
    baseline.load()
    assert baseline.generator_version == "1.4.0"


def test_parse_generator_meta_string_legacy_alias(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    name, version = baseline_mod._parse_generator_meta(
        {
            "generator": "codeclone",
            "codeclone_version": "1.4.0",
        },
        path=path,
    )
    assert name == "codeclone"
    assert version == "1.4.0"


def test_parse_generator_meta_string_prefers_generator_version(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    name, version = baseline_mod._parse_generator_meta(
        {
            "generator": "codeclone",
            "generator_version": "1.4.2",
            "codeclone_version": "1.4.0",
        },
        path=path,
    )
    assert name == "codeclone"
    assert version == "1.4.2"


def test_parse_generator_meta_object_top_level_fallback(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    name, version = baseline_mod._parse_generator_meta(
        {
            "generator": {"name": "codeclone"},
            "generator_version": "1.4.1",
        },
        path=path,
    )
    assert name == "codeclone"
    assert version == "1.4.1"


def test_parse_generator_meta_rejects_extra_generator_keys(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    with pytest.raises(
        BaselineValidationError, match="unexpected generator keys"
    ) as exc:
        baseline_mod._parse_generator_meta(
            {"generator": {"name": "codeclone", "version": "1.4.0", "extra": "x"}},
            path=path,
        )
    assert exc.value.status == "invalid_type"


def test_baseline_parse_semver_three_parts(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    assert baseline_mod._parse_semver("1.2.3", key="schema_version", path=path) == (
        1,
        2,
        3,
    )


def test_baseline_require_sorted_unique_ids_non_string(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    with pytest.raises(
        BaselineValidationError,
        match="'functions' must be list\\[str\\]",
    ) as exc:
        baseline_mod._require_sorted_unique_ids(
            {"functions": [1]},
            "functions",
            pattern=baseline_mod._FUNCTION_ID_RE,
            path=path,
        )
    assert exc.value.status == "invalid_type"
