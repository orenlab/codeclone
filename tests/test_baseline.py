import json
from pathlib import Path

import pytest

import codeclone.baseline as baseline_mod
from codeclone.baseline import Baseline
from codeclone.errors import BaselineSchemaError


def test_baseline_diff() -> None:
    baseline = Baseline("dummy")
    baseline.functions = {"f1"}
    baseline.blocks = {"b1"}

    func_groups: dict[str, object] = {"f1": [], "f2": []}
    block_groups: dict[str, object] = {"b1": [], "b2": []}

    new_func, new_block = baseline.diff(func_groups, block_groups)

    assert new_func == {"f2"}
    assert new_block == {"b2"}


def test_baseline_io(tmp_path: Path) -> None:
    f = tmp_path / "baseline.json"
    bl = Baseline(f)
    bl.functions = {"f1", "f2"}
    bl.blocks = {"b1"}
    bl.save()

    assert f.exists()
    content = json.loads(f.read_text("utf-8"))
    assert content["functions"] == ["f1", "f2"]
    assert content["blocks"] == ["b1"]
    assert "python_version" not in content
    assert "baseline_version" in content
    assert "schema_version" in content
    assert content["generator"] == "codeclone"
    assert isinstance(content["payload_sha256"], str)
    assert isinstance(content["created_at"], str)

    bl2 = Baseline(f)
    bl2.load()
    bl2.verify_integrity()
    assert bl2.functions == {"f1", "f2"}
    assert bl2.blocks == {"b1"}
    assert isinstance(bl2.baseline_version, str)
    assert bl2.schema_version == 1


def test_baseline_load_missing(tmp_path: Path) -> None:
    f = tmp_path / "non_existent.json"
    bl = Baseline(f)
    bl.load()
    assert bl.functions == set()
    assert bl.blocks == set()


def test_baseline_load_corrupted(tmp_path: Path) -> None:
    f = tmp_path / "corrupt.json"
    f.write_text("{invalid json", "utf-8")
    bl = Baseline(f)
    with pytest.raises(BaselineSchemaError, match="Corrupted baseline file"):
        bl.load()


def test_baseline_load_non_object_payload(tmp_path: Path) -> None:
    f = tmp_path / "not_object.json"
    f.write_text("[]", "utf-8")
    bl = Baseline(f)
    with pytest.raises(BaselineSchemaError, match="must be an object"):
        bl.load()


def test_baseline_load_stat_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "baseline.json"
    f.write_text(json.dumps({"functions": [], "blocks": []}), "utf-8")
    original_exists = Path.exists
    original_stat = Path.stat

    def _exists(self: Path) -> bool:
        if self == f:
            return True
        return original_exists(self)

    def _boom(self: Path, *args: object, **kwargs: object) -> object:
        if self == f:
            raise OSError("blocked")
        return original_stat(self)

    monkeypatch.setattr(Path, "exists", _exists)
    monkeypatch.setattr(Path, "stat", _boom)
    bl = Baseline(f)
    with pytest.raises(BaselineSchemaError, match="Cannot stat baseline file"):
        bl.load()


def test_baseline_load_invalid_schema(tmp_path: Path) -> None:
    f = tmp_path / "invalid.json"
    f.write_text(
        json.dumps({"functions": ["f1"], "blocks": [1], "schema_version": 1}),
        "utf-8",
    )
    bl = Baseline(f)
    with pytest.raises(BaselineSchemaError, match="Invalid baseline schema"):
        bl.load()


def test_baseline_load_invalid_created_at_type(tmp_path: Path) -> None:
    f = tmp_path / "invalid_created_at.json"
    f.write_text(
        json.dumps(
            {
                "functions": [],
                "blocks": [],
                "baseline_version": "1.3.0",
                "schema_version": 1,
                "created_at": 123,
            }
        ),
        "utf-8",
    )
    bl = Baseline(f)
    with pytest.raises(BaselineSchemaError, match="'created_at' must be string"):
        bl.load()


def test_baseline_load_invalid_schema_version_type(tmp_path: Path) -> None:
    f = tmp_path / "invalid_schema_version.json"
    f.write_text(
        json.dumps(
            {
                "functions": [],
                "blocks": [],
                "baseline_version": "1.3.0",
                "schema_version": "1",
            }
        ),
        "utf-8",
    )
    bl = Baseline(f)
    with pytest.raises(BaselineSchemaError, match="'schema_version' must be integer"):
        bl.load()


def test_baseline_load_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "large.json"
    f.write_text(json.dumps({"functions": [], "blocks": []}), "utf-8")
    monkeypatch.setattr(baseline_mod, "MAX_BASELINE_SIZE_BYTES", 1)
    bl = Baseline(f)
    with pytest.raises(BaselineSchemaError, match="too large"):
        bl.load()


def test_baseline_integrity_missing_payload(tmp_path: Path) -> None:
    f = tmp_path / "missing_payload.json"
    f.write_text(
        json.dumps(
            {
                "functions": ["f1"],
                "blocks": ["b1"],
                "baseline_version": "1.3.0",
                "schema_version": 1,
                "generator": "codeclone",
            }
        ),
        "utf-8",
    )
    bl = Baseline(f)
    bl.load()
    with pytest.raises(BaselineSchemaError, match="payload hash is missing"):
        bl.verify_integrity()


def test_baseline_integrity_generator_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "generator_mismatch.json"
    bl = Baseline(f)
    bl.functions = {"f1"}
    bl.blocks = {"b1"}
    bl.save()
    payload = json.loads(f.read_text("utf-8"))
    payload["generator"] = "evil"
    f.write_text(json.dumps(payload), "utf-8")
    bl2 = Baseline(f)
    bl2.load()
    with pytest.raises(BaselineSchemaError, match="generator mismatch"):
        bl2.verify_integrity()


def test_baseline_integrity_generator_wrong_type(tmp_path: Path) -> None:
    f = tmp_path / "generator_wrong_type.json"
    bl = Baseline(f)
    bl.functions = {"f1"}
    bl.blocks = {"b1"}
    bl.save()
    payload = json.loads(f.read_text("utf-8"))
    payload["generator"] = 123
    f.write_text(json.dumps(payload), "utf-8")
    bl2 = Baseline(f)
    bl2.load()
    with pytest.raises(BaselineSchemaError, match="generator mismatch"):
        bl2.verify_integrity()


def test_baseline_integrity_payload_mismatch(tmp_path: Path) -> None:
    f = tmp_path / "tampered.json"
    bl = Baseline(f)
    bl.functions = {"f1"}
    bl.blocks = {"b1"}
    bl.save()
    payload = json.loads(f.read_text("utf-8"))
    payload["functions"] = ["tampered"]
    f.write_text(json.dumps(payload), "utf-8")
    bl2 = Baseline(f)
    bl2.load()
    with pytest.raises(BaselineSchemaError, match="payload_sha256 mismatch"):
        bl2.verify_integrity()


def test_baseline_integrity_payload_wrong_type(tmp_path: Path) -> None:
    f = tmp_path / "payload_wrong_type.json"
    bl = Baseline(f)
    bl.functions = {"f1"}
    bl.blocks = {"b1"}
    bl.save()
    payload = json.loads(f.read_text("utf-8"))
    payload["payload_sha256"] = 1
    f.write_text(json.dumps(payload), "utf-8")
    bl2 = Baseline(f)
    bl2.load()
    with pytest.raises(BaselineSchemaError, match="payload hash is missing"):
        bl2.verify_integrity()


def test_baseline_verify_integrity_skips_legacy(tmp_path: Path) -> None:
    f = tmp_path / "legacy.json"
    f.write_text(json.dumps({"functions": [], "blocks": []}), "utf-8")
    bl = Baseline(f)
    bl.load()
    bl.verify_integrity()


def test_baseline_from_groups() -> None:
    func_groups: dict[str, object] = {"f1": [], "f2": []}
    block_groups: dict[str, object] = {"b1": []}
    bl = Baseline.from_groups(
        func_groups,
        block_groups,
        path="custom.json",
        baseline_version="1.3.0",
        schema_version=1,
    )

    assert bl.functions == {"f1", "f2"}
    assert bl.blocks == {"b1"}
    assert bl.path == Path("custom.json")
    assert bl.baseline_version == "1.3.0"
    assert bl.schema_version == 1


def test_baseline_python_version_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "baseline.json"
    bl = Baseline(f)
    bl.functions = {"f1"}
    bl.blocks = {"b1"}
    bl.python_version = "3.13"
    bl.save()

    content = json.loads(f.read_text("utf-8"))
    assert content["python_version"] == "3.13"
    assert "baseline_version" in content
    assert content["schema_version"] == 1

    bl2 = Baseline(f)
    bl2.load()
    assert bl2.python_version == "3.13"
    assert isinstance(bl2.baseline_version, str)
    assert bl2.schema_version == 1


def test_baseline_payload_without_created_at() -> None:
    payload = baseline_mod._baseline_payload(
        {"f1"},
        {"b1"},
        python_version=None,
        baseline_version="1.3.0",
        schema_version=1,
        generator="codeclone",
        created_at=None,
    )
    assert "created_at" not in payload
