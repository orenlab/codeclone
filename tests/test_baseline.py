from pathlib import Path
import json
import pytest
from codeclone.baseline import Baseline


def test_baseline_diff():
    baseline = Baseline("dummy")
    baseline.functions = {"f1"}
    baseline.blocks = {"b1"}

    func_groups = {"f1": [], "f2": []}
    block_groups = {"b1": [], "b2": []}

    new_func, new_block = baseline.diff(func_groups, block_groups)

    assert new_func == {"f2"}
    assert new_block == {"b2"}


def test_baseline_io(tmp_path):
    f = tmp_path / "baseline.json"
    bl = Baseline(f)
    bl.functions = {"f1", "f2"}
    bl.blocks = {"b1"}
    bl.save()

    assert f.exists()
    content = json.loads(f.read_text("utf-8"))
    assert content["functions"] == ["f1", "f2"]
    assert content["blocks"] == ["b1"]

    bl2 = Baseline(f)
    bl2.load()
    assert bl2.functions == {"f1", "f2"}
    assert bl2.blocks == {"b1"}


def test_baseline_load_missing(tmp_path):
    f = tmp_path / "non_existent.json"
    bl = Baseline(f)
    bl.load()
    assert bl.functions == set()
    assert bl.blocks == set()


def test_baseline_load_corrupted(tmp_path):
    f = tmp_path / "corrupt.json"
    f.write_text("{invalid json", "utf-8")
    bl = Baseline(f)
    with pytest.raises(ValueError, match="Corrupted baseline file"):
        bl.load()


def test_baseline_from_groups():
    func_groups = {"f1": [], "f2": []}
    block_groups = {"b1": []}
    bl = Baseline.from_groups(func_groups, block_groups, path="custom.json")

    assert bl.functions == {"f1", "f2"}
    assert bl.blocks == {"b1"}
    assert bl.path == Path("custom.json")
