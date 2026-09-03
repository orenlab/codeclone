from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.surfaces.mcp import _session_helpers as _helpers
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.mapping_paths import section

from ._report_fixtures import (
    GATE_POLICY_GENERATED_AT,
    build_gate_policy_disagreement_pair,
    build_gate_policy_report_document,
)

_GENERATED_AT_LATER = "2026-08-13T11:00:00Z"


def _digest(document: Mapping[str, object], tier: str) -> str:
    value = section(document, f"integrity.digests.{tier}").get("value")
    assert isinstance(value, str) and value
    return value


def test_run_identity_moves_when_the_gate_verdict_moves() -> None:
    """Same tree, different thresholds, different verdicts -- different ids.

    The run store is keyed by ``(root, run_id)``, so two runs sharing an id
    are one record: the second registration replaces the first, and the
    evidence that the two disagreed is gone. Taking the id from the comparison
    tier -- facts and baseline, no policy -- produced exactly that, because
    the thresholds and the outcome live one tier above it.

    The fixture owner makes an accidental pass impossible: it asserts that the
    two runs share every tier below ``evaluation`` (same tree, same baseline)
    and that they disagree on the verdict, with the strict run carrying a real
    gate reason rather than a silent refusal. That arrangement is shared with
    the CLI's identity pin and lives in ``_report_fixtures`` for both.
    """

    lenient, strict = build_gate_policy_disagreement_pair()

    assert _helpers._report_digest(lenient) != _helpers._report_digest(strict)


def test_run_identity_holds_still_when_only_the_clock_moves() -> None:
    """Re-measuring an unchanged tree must not mint a new identity.

    ``meta.runtime.report_generated_at_utc`` is the document's only time-like
    field, and only the envelope tier seals it. An identity taken from the
    envelope would be new on every run, which reads as honest and is not: it
    would leave ``after_run_not_new`` permanently unable to fire, so a cycle
    that never re-analysed anything would verify as if it had.
    """

    first = build_gate_policy_report_document()
    second = build_gate_policy_report_document(
        report_generated_at_utc=_GENERATED_AT_LATER
    )

    assert (
        section(first, "meta.runtime").get("report_generated_at_utc")
        == GATE_POLICY_GENERATED_AT
    )
    assert (
        section(second, "meta.runtime").get("report_generated_at_utc")
        == _GENERATED_AT_LATER
    )
    assert _digest(first, "envelope") != _digest(second, "envelope")

    assert _helpers._report_digest(first) == _helpers._report_digest(second)


# ---------------------------------------------------------------------------
# End-to-end acceptance on the live MCP surface (RULING-2026-09-02).
#
# Near-miss is the causal witness of identity incompleteness: a report-only
# tier that reaches no baseline lane and no gate.  The order of the assertions
# is the contract -- first prove that the OUTPUTS differ while every other
# owner of the identity is unchanged, and only then that the identity differs.
# A pin that only shows "the near-miss flag reached the hash" proves nothing
# about outputs.
# ---------------------------------------------------------------------------


_PAIRS_FIXTURE = Path(__file__).parent / "fixtures" / "clone_tiers" / "pairs.py"
_NEAR_MISS_PYPROJECT = (
    '[project]\nname = "pairs"\nversion = "0.1.0"\n'
    "\n[tool.codeclone]\nnear_miss = true\n"
)
# The near-miss pair (active_customer_value, active_customer_value_clamped)
# sits at distance one.  Replacing one statement inside the clamped twin --
# a different method, same line count -- moves it to distance two and out of
# the tier without adding a line or touching any other producer's input.
_PAIR_STATEMENT = "        accepted.append(customer.identifier)\n"
_PAIR_STATEMENT_REPLACED = "        accepted.insert(0, customer.identifier)\n"
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@e.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@e.com",
}


def _near_miss_repo(root: Path, *, second_module: bool = False) -> None:
    package = root / "pkg"
    package.mkdir(parents=True, exist_ok=True)
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    text = _PAIRS_FIXTURE.read_text(encoding="utf-8")
    package.joinpath("pairs.py").write_text(text, encoding="utf-8")
    if second_module:
        # Every function again under another name: cross-file exact clone
        # groups, so that ordering between files reaches every clone family.
        renamed = re.sub(r"^def (\w+)\(", r"def \1_b(", text, flags=re.MULTILINE)
        package.joinpath("pairs_b.py").write_text(renamed, encoding="utf-8")
    root.joinpath("pyproject.toml").write_text(_NEAR_MISS_PYPROJECT, encoding="utf-8")
    root.joinpath(".gitignore").write_text(".codeclone/\n", encoding="utf-8")
    for args in (("init",), ("add", "-A"), ("commit", "-m", "init")):
        subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, env=_GIT_ENV
        )


def _break_one_near_miss_pair(root: Path) -> None:
    text = root.joinpath("pkg", "pairs.py").read_text(encoding="utf-8")
    head, first, tail = text.partition(_PAIR_STATEMENT)
    assert first and _PAIR_STATEMENT in tail, "the pairs fixture moved"
    # The first occurrence belongs to active_customer_value and stays; the
    # second is the clamped twin's.
    tail = tail.replace(_PAIR_STATEMENT, _PAIR_STATEMENT_REPLACED, 1)
    root.joinpath("pkg", "pairs.py").write_text(head + first + tail, encoding="utf-8")


def _analyze_document(
    service: CodeCloneMCPService, root: Path, *, processes: int | None = None
) -> tuple[str, Mapping[str, object]]:
    payload = service.analyze_repository(
        MCPAnalysisRequest(root=str(root), min_loc=6, min_stmt=4, processes=processes)
    )
    run_id = str(payload["run_id"])
    record = service._runs.get_for_root(run_id, root=root)
    return run_id, record.report_document


def _moved_families(
    before: Mapping[str, object], after: Mapping[str, object]
) -> set[str]:
    digests_before = section(before, "integrity.semantic.family_digests")
    digests_after = section(after, "integrity.semantic.family_digests")
    moved: set[str] = set()
    for domain in sorted({*digests_before, *digests_after}):
        families_before = digests_before.get(domain)
        families_after = digests_after.get(domain)
        assert isinstance(families_before, Mapping)
        assert isinstance(families_after, Mapping)
        assert set(families_before) == set(families_after), domain
        moved.update(
            f"{domain}.{family}"
            for family in families_before
            if families_before[family] != families_after[family]
        )
    return moved


def test_near_miss_output_moves_the_identity_and_nothing_else_moves(
    tmp_path: Path,
) -> None:
    """Outputs first: the pair set shrinks while every other owner holds still.

    Only then the identity: the run id must move, and it must move for that
    one reason -- the observation digest, the population, every realized
    contract and every other family digest are byte-equal across the edit.
    Near-miss reaches the MCP surface through repository configuration
    (``[tool.codeclone] near_miss``), not through a request field.
    """

    _near_miss_repo(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    run_before, before = _analyze_document(service, tmp_path)
    _break_one_near_miss_pair(tmp_path)
    run_after, after = _analyze_document(service, tmp_path)

    tier_before = section(before, "findings.groups.near_miss")
    tier_after = section(after, "findings.groups.near_miss")
    # The producer ran both times: a count is only a measurement when it did.
    assert tier_before.get("state") == "complete"
    assert tier_after.get("state") == "complete"
    count_before = tier_before.get("count")
    count_after = tier_after.get("count")
    assert isinstance(count_before, int) and isinstance(count_after, int)
    # 1. The outputs differ ...
    assert count_before > count_after > 0
    # ... while every other owner is unchanged.
    assert _digest(before, "observation") == _digest(after, "observation")
    assert section(before, "integrity.semantic.population") == section(
        after, "integrity.semantic.population"
    )
    assert section(before, "integrity.semantic.realized_contracts") == section(
        after, "integrity.semantic.realized_contracts"
    )
    assert _moved_families(before, after) == {"analysis.near_miss"}
    # 2. The semantic identity differs -- and it is what the surface serves.
    assert _helpers._report_digest(before) != _helpers._report_digest(after)
    assert run_before != run_after


def test_run_identity_is_invariant_to_process_count_and_discovery_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A digest that moves with ``--processes`` or with file order is a defect.

    Three cold executions of one tree: one worker, two workers, and one worker
    fed the discovered files in reverse.  Every run is proven cold (nothing
    served from the cache) so that the pool and the accept order are actually
    exercised, and every run must mint the same run id.
    """

    import codeclone.surfaces.mcp.session as session_mod

    _near_miss_repo(tmp_path, second_module=True)
    service = CodeCloneMCPService(history_limit=6)

    def cold_run(processes: int) -> tuple[str, Mapping[str, object]]:
        shutil.rmtree(tmp_path / ".codeclone", ignore_errors=True)
        run_id, document = _analyze_document(service, tmp_path, processes=processes)
        files = section(document, "inventory.files")
        cached, analyzed = files.get("cached"), files.get("analyzed")
        assert isinstance(cached, int) and isinstance(analyzed, int), files
        assert cached == 0 and analyzed >= 3, files
        return run_id, document

    one_worker, document = cold_run(1)
    pairs = section(document, "findings.groups.near_miss").get("count")
    assert isinstance(pairs, int) and pairs > 0
    two_workers, _ = cold_run(2)
    assert two_workers == one_worker

    original_discover = session_mod.discover  # type: ignore[attr-defined]

    def reversed_discover(**kwargs: object) -> object:
        result = original_discover(**kwargs)  # type: ignore[arg-type]
        return replace(
            result, files_to_process=tuple(reversed(result.files_to_process))
        )

    monkeypatch.setattr(session_mod, "discover", reversed_discover)
    reversed_order, _ = cold_run(1)
    assert reversed_order == one_worker
