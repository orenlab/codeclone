import json
from pathlib import Path

import pytest

from codeclone.baseline import Baseline


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

    bl2 = Baseline(f)
    bl2.load()
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
    with pytest.raises(ValueError, match="Corrupted baseline file"):
        bl.load()


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
