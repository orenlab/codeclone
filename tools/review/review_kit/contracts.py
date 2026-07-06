"""Contract briefs read from codeclone/contracts/__init__.py."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_FINAL_RE = re.compile(
    r"^([A-Z][A-Z0-9_]+):\s*Final(?:\[[^\]]+\])?\s*=\s*(.+?)\s*(?:#.*)?$",
    re.MULTILINE,
)


def repo_root_from_policy(policy: dict[str, Any]) -> Path:
    del policy
    import subprocess

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        return Path(completed.stdout.strip())
    except (subprocess.CalledProcessError, OSError):
        return Path.cwd()


def load_contract_briefs(
    repo_root: Path,
    *,
    touched_paths: list[str],
) -> dict[str, str]:
    if not any(
        "codeclone/contracts" in path or path == "codeclone/contracts/__init__.py"
        for path in touched_paths
    ):
        return {}
    contracts_path = repo_root / "codeclone" / "contracts" / "__init__.py"
    if not contracts_path.is_file():
        return {}
    text = contracts_path.read_text(encoding="utf-8")
    briefs: dict[str, str] = {}
    for match in _FINAL_RE.finditer(text):
        name, value = match.group(1), match.group(2).strip()
        briefs[name] = value.strip('"').strip("'")
    return dict(sorted(briefs.items()))
