# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Tests for the verification profile classifier.

Covers the 10 acceptance criteria from the design:
1. Profile is computed only from actual_changed_files.
2. State artifact has highest priority.
3. Any .py/.pyi forces python_structural.
4. Governance config requires after_run; without it → unverified.
5. Documentation-only can verify without after_run.
6. Scope and forbidden checks always run before any fast return.
7. Payload includes profile, reason, performed checks, not-applicable checks.
8. Receipts use "not applicable", never "passed", for skipped structural.
9. Claim Guard allows only narrow docs-only claims.
10. Empty diff behavior is deterministic and tested.
"""

from __future__ import annotations

import pytest

from codeclone.surfaces.mcp._verification_profile import (
    CHECK_FORBIDDEN,
    CHECK_GATE_COMPARISON,
    CHECK_PROFILE_CLASSIFICATION,
    CHECK_SCOPE,
    CHECK_STRUCTURAL_DELTA,
    CHECK_WORSENED_SYMBOLS,
    VerificationProfile,
    check_matrix,
    classify_patch,
    profile_accepted_message,
    profile_limitations,
    profile_unverified_message,
)

# ═══════════════════════════════════════════════════════════════════
# Single-file classification
# ═══════════════════════════════════════════════════════════════════


def test_single_python_file() -> None:
    result = classify_patch(["src/main.py"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL
    assert result.python_source_touched is True


def test_single_pyi_file() -> None:
    result = classify_patch(["codeclone/types.pyi"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL
    assert result.python_source_touched is True


def test_single_markdown_file() -> None:
    result = classify_patch(["README.md"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY
    assert result.python_source_touched is False


def test_single_rst_file() -> None:
    result = classify_patch(["docs/guide.rst"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_single_txt_file() -> None:
    result = classify_patch(["notes.txt"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_single_adoc_file() -> None:
    result = classify_patch(["guide.adoc"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_single_textile_file() -> None:
    result = classify_patch(["notes.textile"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_single_pyproject_toml() -> None:
    result = classify_patch(["pyproject.toml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG
    assert result.governance_config_touched is True


def test_single_pre_commit_config() -> None:
    result = classify_patch([".pre-commit-config.yaml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_single_github_workflow() -> None:
    result = classify_patch([".github/workflows/tests.yml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_single_github_action() -> None:
    result = classify_patch([".github/actions/codeclone/action.yml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_single_dockerfile() -> None:
    result = classify_patch(["Dockerfile"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_single_docker_compose() -> None:
    result = classify_patch(["docker-compose.yml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_single_baseline_json() -> None:
    result = classify_patch(["codeclone.baseline.json"])
    assert result.profile == VerificationProfile.STATE_ARTIFACT_CHANGE
    assert result.state_artifact_touched is True


def test_single_cache_file() -> None:
    result = classify_patch([".codeclone/report.json"])
    assert result.profile == VerificationProfile.STATE_ARTIFACT_CHANGE


def test_single_unknown_file() -> None:
    result = classify_patch(["data/fixtures.json"])
    assert result.profile == VerificationProfile.NON_PYTHON_PATCH
    assert result.python_source_touched is False


def test_single_image_file() -> None:
    result = classify_patch(["assets/logo.png"])
    assert result.profile == VerificationProfile.NON_PYTHON_PATCH


def test_py_typed_marker() -> None:
    result = classify_patch(["py.typed"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_ruff_toml() -> None:
    result = classify_patch(["ruff.toml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_mypy_ini() -> None:
    result = classify_patch(["mypy.ini"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_makefile() -> None:
    result = classify_patch(["Makefile"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_setup_cfg() -> None:
    result = classify_patch(["setup.cfg"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_coveragerc() -> None:
    result = classify_patch([".coveragerc"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


# ═══════════════════════════════════════════════════════════════════
# Priority chain — mixed files
# ═══════════════════════════════════════════════════════════════════


def test_state_artifact_overrides_python() -> None:
    """State artifact has highest priority, even with Python files."""
    result = classify_patch(["src/main.py", "codeclone.baseline.json"])
    assert result.profile == VerificationProfile.STATE_ARTIFACT_CHANGE
    assert result.state_artifact_touched is True
    assert result.python_source_touched is True


def test_state_artifact_overrides_docs() -> None:
    result = classify_patch(["README.md", ".codeclone/report.json"])
    assert result.profile == VerificationProfile.STATE_ARTIFACT_CHANGE


def test_python_overrides_governance() -> None:
    result = classify_patch(["src/engine.py", "pyproject.toml"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL


def test_python_overrides_docs() -> None:
    result = classify_patch(["src/main.py", "README.md"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL


def test_governance_overrides_docs() -> None:
    result = classify_patch(["README.md", "pyproject.toml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_governance_overrides_non_python() -> None:
    result = classify_patch(["data/config.json", ".pre-commit-config.yaml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_docs_only_multiple_doc_files() -> None:
    result = classify_patch(["README.md", "CHANGELOG.md", "docs/guide.rst"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_docs_plus_unknown_is_non_python() -> None:
    """Docs + unknown file is not docs-only."""
    result = classify_patch(["README.md", "data/fixtures.json"])
    assert result.profile == VerificationProfile.NON_PYTHON_PATCH


def test_setup_py_is_python_structural() -> None:
    """setup.py is a Python file, so it triggers python_structural."""
    result = classify_patch(["setup.py"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL


def test_noxfile_is_python_structural() -> None:
    """noxfile.py is Python source, not governance config."""
    result = classify_patch(["noxfile.py"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL


def test_conftest_is_python_structural() -> None:
    result = classify_patch(["tests/conftest.py"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL


# ═══════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════


def test_empty_changed_files() -> None:
    """Empty list → deterministic non_python_patch with dedicated reason."""
    result = classify_patch([])
    assert result.profile == VerificationProfile.NON_PYTHON_PATCH
    assert result.reason == "no changed files detected"
    assert result.python_source_touched is False
    assert result.state_artifact_touched is False
    assert result.governance_config_touched is False


def test_docs_nested_in_docs_dir() -> None:
    result = classify_patch(["docs/book/chapter.md"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_license_is_docs() -> None:
    result = classify_patch(["LICENSE"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_contributing_is_docs() -> None:
    result = classify_patch(["CONTRIBUTING.md"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_changelog_without_extension() -> None:
    result = classify_patch(["CHANGELOG"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_doc_dir_is_docs() -> None:
    result = classify_patch(["doc/tutorial.html"])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


@pytest.mark.parametrize(
    "filename",
    [
        "CHANGES",
        "CHANGES.md",
        "HISTORY.rst",
        "NEWS",
        "LICENCE",
        "COPYING",
        "NOTICE",
        "CONTRIBUTORS.md",
        "CREDITS",
        "MAINTAINERS",
        "THANKS",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
    ],
    ids=lambda f: f.replace(".", "_"),
)
def test_expanded_documentation_patterns(filename: str) -> None:
    result = classify_patch([filename])
    assert result.profile == VerificationProfile.DOCUMENTATION_ONLY


def test_windows_path_normalization() -> None:
    result = classify_patch(["src\\main.py"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL


def test_dotslash_prefix_normalization() -> None:
    result = classify_patch(["./src/main.py"])
    assert result.profile == VerificationProfile.PYTHON_STRUCTURAL


def test_deeply_nested_workflow() -> None:
    result = classify_patch([".github/workflows/deploy/staging.yml"])
    assert result.profile == VerificationProfile.GOVERNANCE_CONFIG


def test_deeply_nested_cache() -> None:
    result = classify_patch([".codeclone/intents/some-intent.json"])
    assert result.profile == VerificationProfile.STATE_ARTIFACT_CHANGE


# ═══════════════════════════════════════════════════════════════════
# ClassificationResult payload
# ═══════════════════════════════════════════════════════════════════


def test_payload_has_required_fields() -> None:
    result = classify_patch(["README.md"])
    payload = result.to_payload()
    assert payload["verification_profile"] == "documentation_only"
    assert isinstance(payload["profile_reason"], str)
    assert payload["python_source_touched"] is False
    assert isinstance(payload["after_run_required"], bool)
    assert isinstance(payload["checks_performed"], list)
    assert isinstance(payload["checks_not_applicable"], list)


def test_python_structural_payload() -> None:
    result = classify_patch(["src/main.py"])
    payload = result.to_payload()
    assert payload["verification_profile"] == "python_structural"
    assert payload["after_run_required"] is True
    performed = payload["checks_performed"]
    assert isinstance(performed, list)
    assert CHECK_STRUCTURAL_DELTA in performed
    assert CHECK_GATE_COMPARISON in performed
    assert CHECK_WORSENED_SYMBOLS in performed
    assert payload["checks_not_applicable"] == []


def test_docs_only_payload_structural_not_applicable() -> None:
    result = classify_patch(["docs/guide.md"])
    payload = result.to_payload()
    assert payload["verification_profile"] == "documentation_only"
    assert payload["after_run_required"] is False
    not_applicable = payload["checks_not_applicable"]
    assert isinstance(not_applicable, list)
    assert CHECK_STRUCTURAL_DELTA in not_applicable
    assert CHECK_GATE_COMPARISON in not_applicable
    assert CHECK_WORSENED_SYMBOLS in not_applicable


def test_governance_config_requires_after_run() -> None:
    result = classify_patch(["pyproject.toml"])
    payload = result.to_payload()
    assert payload["after_run_required"] is True
    not_applicable = payload["checks_not_applicable"]
    assert isinstance(not_applicable, list)
    assert CHECK_STRUCTURAL_DELTA in not_applicable


def test_profile_classification_always_in_checks_performed() -> None:
    """verification_profile_classification is in checks_performed."""
    for files, expected_profile in (
        (["src/main.py"], VerificationProfile.PYTHON_STRUCTURAL),
        (["README.md"], VerificationProfile.DOCUMENTATION_ONLY),
        (["pyproject.toml"], VerificationProfile.GOVERNANCE_CONFIG),
        (["data.json"], VerificationProfile.NON_PYTHON_PATCH),
    ):
        result = classify_patch(files)
        assert result.profile == expected_profile
        performed = result.to_payload()["checks_performed"]
        assert isinstance(performed, list)
        assert CHECK_PROFILE_CLASSIFICATION in performed
        assert CHECK_SCOPE in performed
        assert CHECK_FORBIDDEN in performed


# ═══════════════════════════════════════════════════════════════════
# CheckMatrix
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "profile, after_run_required, structural",
    [
        (VerificationProfile.PYTHON_STRUCTURAL, True, True),
        (VerificationProfile.GOVERNANCE_CONFIG, True, False),
        (VerificationProfile.DOCUMENTATION_ONLY, False, False),
        (VerificationProfile.NON_PYTHON_PATCH, False, False),
        (VerificationProfile.STATE_ARTIFACT_CHANGE, False, False),
    ],
    ids=[
        "python_structural",
        "governance_config",
        "documentation_only",
        "non_python_patch",
        "state_artifact_change",
    ],
)
def test_check_matrix_exhaustive(
    profile: VerificationProfile,
    after_run_required: bool,
    structural: bool,
) -> None:
    matrix = check_matrix(profile)
    assert matrix.profile == profile
    assert matrix.after_run_required == after_run_required
    assert matrix.structural_checks_applicable == structural


def test_check_matrix_structural_includes_all_checks() -> None:
    matrix = check_matrix(VerificationProfile.PYTHON_STRUCTURAL)
    performed = matrix.checks_performed
    assert CHECK_STRUCTURAL_DELTA in performed
    assert CHECK_GATE_COMPARISON in performed
    assert CHECK_WORSENED_SYMBOLS in performed
    assert matrix.checks_not_applicable == ()


def test_check_matrix_docs_excludes_structural() -> None:
    matrix = check_matrix(VerificationProfile.DOCUMENTATION_ONLY)
    not_applicable = matrix.checks_not_applicable
    assert CHECK_STRUCTURAL_DELTA in not_applicable
    assert CHECK_GATE_COMPARISON in not_applicable
    assert CHECK_WORSENED_SYMBOLS in not_applicable


# ═══════════════════════════════════════════════════════════════════
# Limitations and messages
# ═══════════════════════════════════════════════════════════════════


def test_non_python_patch_has_limitations() -> None:
    limitations = profile_limitations(VerificationProfile.NON_PYTHON_PATCH)
    assert len(limitations) == 2
    assert any("Python structural" in lim for lim in limitations)
    assert any("documentation-only" in lim for lim in limitations)


def test_documentation_only_no_limitations() -> None:
    assert profile_limitations(VerificationProfile.DOCUMENTATION_ONLY) == ()


def test_accepted_message_docs() -> None:
    msg = profile_accepted_message(VerificationProfile.DOCUMENTATION_ONLY)
    assert "not applicable" in msg


def test_accepted_message_non_python() -> None:
    msg = profile_accepted_message(VerificationProfile.NON_PYTHON_PATCH)
    assert "limitations" in msg


def test_unverified_message_python() -> None:
    msg = profile_unverified_message(VerificationProfile.PYTHON_STRUCTURAL)
    assert "after_run_id" in msg


def test_unverified_message_governance() -> None:
    msg = profile_unverified_message(VerificationProfile.GOVERNANCE_CONFIG)
    assert "after_run_id" in msg
    assert "configuration" in msg.lower() or "CI" in msg


# ═══════════════════════════════════════════════════════════════════
# Determinism
# ═══════════════════════════════════════════════════════════════════


def test_classify_is_pure() -> None:
    """Same input always yields the same result."""
    files = ["src/main.py", "README.md", "pyproject.toml"]
    result_a = classify_patch(files)
    result_b = classify_patch(files)
    assert result_a.profile == result_b.profile
    assert result_a.reason == result_b.reason
    assert result_a.python_source_touched == result_b.python_source_touched


def test_classify_order_independent() -> None:
    """File order does not change the result."""
    files_a = ["README.md", "src/main.py"]
    files_b = ["src/main.py", "README.md"]
    assert classify_patch(files_a).profile == classify_patch(files_b).profile


# ═══════════════════════════════════════════════════════════════════
# Profile reason stability
# ═══════════════════════════════════════════════════════════════════


def test_reason_stable_for_docs() -> None:
    result = classify_patch(["README.md", "docs/guide.rst"])
    assert result.reason == "all changed files match documentation patterns"


def test_reason_stable_for_governance() -> None:
    result = classify_patch(["pyproject.toml"])
    assert "governance or analysis configuration" in result.reason


def test_reason_stable_for_python() -> None:
    result = classify_patch(["src/main.py"])
    assert "Python source" in result.reason


def test_reason_stable_for_state_artifact() -> None:
    result = classify_patch(["codeclone.baseline.json"])
    assert "state artifacts" in result.reason


def test_reason_stable_for_empty() -> None:
    result = classify_patch([])
    assert result.reason == "no changed files detected"


def test_reason_stable_for_non_python() -> None:
    result = classify_patch(["assets/logo.png"])
    assert "documentation" in result.reason or "outside" in result.reason
