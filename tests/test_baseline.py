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