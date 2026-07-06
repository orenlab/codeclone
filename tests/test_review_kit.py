"""Contract tests for tools/review review kit."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from review_kit.coverage import unmapped_tracked_paths
from review_kit.decompose import (
    _command_applies_to_unit,
    build_review_units,
    format_diff_command,
)
from review_kit.git_evidence import resolve_target
from review_kit.packet import build_packet
from review_kit.policy import KIT_ROOT, load_policy
from review_kit.validate import validate_packet
from review_kit.verification import (
    command_is_approved,
    parse_safe_argv,
    run_verification_plan,
)

REVIEW_ROOT = KIT_ROOT


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    return load_policy(REVIEW_ROOT / "policy.yaml")


def test_policy_version_is_v3(policy: dict[str, Any]) -> None:
    assert policy["version"] == "3"
    assert policy["docs_review"]["mode"] == "transitional"
    jetbrains = policy["surface_catalog"]["integrations_jetbrains"]
    assert jetbrains.get("status") == "disabled"


def test_command_applies_to_unit_uses_trigger_field() -> None:
    entry = {
        "command": "uv run pytest -q",
        "reason": "python",
        "trigger": "python_change",
    }
    assert _command_applies_to_unit(entry, ["codeclone/main.py"], "engine_entry")
    assert not _command_applies_to_unit(entry, ["README.md"], "repo_governance")


def test_build_packet_v3_shape() -> None:
    packet = build_packet(
        "commit", "HEAD", policy=load_policy(REVIEW_ROOT / "policy.yaml")
    )
    assert packet["packet_version"] == "3"
    assert packet["routing"]["profile"] in {"economy", "balanced", "thorough"}
    assert "cost_estimate" in packet
    assert "incremental" in packet
    assert packet["incremental"]["enabled"] is False
    errors = validate_packet(packet)
    assert errors == []


def test_range_decomposition_is_deterministic() -> None:
    policy = load_policy(REVIEW_ROOT / "policy.yaml")
    packet_a = build_packet("range", "0dd0b26^..d88c17f0", policy=policy)
    packet_b = build_packet("range", "0dd0b26^..d88c17f0", policy=policy)
    assert packet_a == packet_b
    if packet_a["routing"]["decomposed"]:
        units = packet_a["review_units"]
        assert units
        assert units[0]["unit_id"] == "R-001"
        assert all(unit["unit_id"].startswith("R-") for unit in units)


def test_review_units_receive_verification_commands(policy: dict[str, Any]) -> None:
    head_packet = build_packet("commit", "HEAD", policy=policy)
    base_sha = head_packet["target"]["base_sha"]
    head_sha = head_packet["target"]["head_sha"]
    units = build_review_units(
        policy=policy,
        base_sha=base_sha,
        head_sha=head_sha,
        surface_hints={"mcp_controller": ["codeclone/surfaces/mcp/service.py"]},
        files=[{"status": "M", "path": "codeclone/surfaces/mcp/service.py"}],
        classification={"python": True, "public_surface": True},
        profile="balanced",
        repo_root=Path(__file__).resolve().parents[1],
        contract_briefs={},
        verification_plan=[
            {
                "command": "uv run pytest -q tests/test_mcp_service.py",
                "reason": "mcp",
                "trigger": "codeclone/surfaces/mcp/**",
            }
        ],
    )
    commands = units[0]["unit_brief"]["mandatory_commands"]
    assert commands
    assert commands[0]["trigger"] == "codeclone/surfaces/mcp/**"


def test_surface_coverage_allows_tools_review(policy: dict[str, Any]) -> None:
    unknown = unmapped_tracked_paths(policy)
    review_paths = [path for path in unknown if path.startswith("tools/review")]
    assert review_paths == []


def test_v3_agents_exist() -> None:
    # The review-change skill lives untracked under .claude/skills/review-change/
    # (it has no tracked source under tools/review), so it is not asserted here.
    root = REVIEW_ROOT
    for agent in (
        "review-coordinator",
        "review-scout",
        "surface-reviewer",
        "critical-reviewer",
    ):
        assert (root / "agents" / f"{agent}.md").is_file()


def test_packet_json_roundtrip() -> None:
    packet = build_packet(
        "commit", "HEAD", policy=load_policy(REVIEW_ROOT / "policy.yaml")
    )
    encoded = json.dumps(packet, sort_keys=True)
    decoded = json.loads(encoded)
    assert decoded == packet


def test_parse_safe_argv_rejects_shell_metacharacters() -> None:
    assert parse_safe_argv("uv run pytest -q tests/test_architecture.py") is not None
    assert parse_safe_argv("uv run pytest; rm -rf /") is None
    assert parse_safe_argv("uv run pytest && echo pwned") is None


def test_command_is_approved_uses_policy_prefixes(policy: dict[str, Any]) -> None:
    approved = policy["approved_read_only_commands"]
    assert command_is_approved("uv lock --check", approved)
    assert command_is_approved(
        "uv run pytest -q tests/test_mcp_service.py",
        approved,
    )
    assert not command_is_approved("curl https://example.com", approved)


def test_run_verification_plan_rejects_unapproved_commands(
    policy: dict[str, Any],
) -> None:
    results = run_verification_plan(
        [{"command": "curl https://example.com", "reason": "x", "trigger": "y"}],
        execute=True,
        approved_commands=policy["approved_read_only_commands"],
    )
    assert results[0]["status"] == "rejected"


def test_run_verification_plan_uses_argv_not_shell(
    monkeypatch: pytest.MonkeyPatch,
    policy: dict[str, Any],
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: object, **kwargs: object) -> object:
        captured["argv"] = argv
        captured["shell"] = kwargs.get("shell")

        class _Result:
            returncode = 0
            stdout = "ok"
            stderr = ""

        return _Result()

    monkeypatch.setattr("review_kit.verification.subprocess.run", fake_run)
    run_verification_plan(
        [{"command": "uv lock --check", "reason": "x", "trigger": "y"}],
        execute=True,
        approved_commands=policy["approved_read_only_commands"],
    )
    assert captured["argv"] == ["uv", "lock", "--check"]
    assert captured["shell"] is False


def test_format_diff_command_quotes_paths_with_spaces() -> None:
    command = format_diff_command(
        "abc123",
        "def456",
        ["tools/review/foo bar.py", "plain.py"],
    )
    assert "'tools/review/foo bar.py'" in command
    assert " plain.py" in command


def test_resolve_target_rejects_dash_prefixed_ref() -> None:
    with pytest.raises(SystemExit, match="Invalid git ref"):
        resolve_target("commit", "--show-toplevel")


def test_cli_module_entrypoint_writes_packet(tmp_path: Path) -> None:
    """python -m review_kit.cli must invoke main(), not only import cli.py."""

    repo_root = Path(__file__).resolve().parents[1]
    out = tmp_path / "packet.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "tools" / "review")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "review_kit.cli",
            "build-packet",
            "range",
            "HEAD~1..HEAD",
            "--out",
            str(out),
        ],
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["packet_version"] == "3"
    assert payload["target"]["base_sha"]
    assert payload["target"]["head_sha"]
