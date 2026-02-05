import runpy
import sys

import pytest


def test_cli_main_guard_runpy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "codeclone.cli", raising=False)
    monkeypatch.setattr(sys, "argv", ["codeclone", "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("codeclone.cli", run_name="__main__")
    assert exc.value.code == 0
