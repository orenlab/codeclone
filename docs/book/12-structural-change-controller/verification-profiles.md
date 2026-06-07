## Verification Profiles

`check_patch_contract(mode="verify")` derives a **verification profile** from
actual changed files. The profile determines which structural checks are
applicable and whether `after_run_id` is required for verification.

### Profile classification

The classifier is a pure function with a deterministic priority chain:

| Priority | Profile                 | When                                                                                                  | `after_run` required | Structural checks |
|----------|-------------------------|-------------------------------------------------------------------------------------------------------|----------------------|-------------------|
| 1        | `state_artifact_change` | CodeClone state artifacts touched (`codeclone.baseline.json`, `.codeclone/**`, `.cache/codeclone/**`) | no (violated)        | not applicable    |
| 2        | `python_structural`     | Any `.py` / `.pyi` touched                                                                            | yes                  | all               |
| 3        | `governance_config`     | Config files only (pyproject.toml, CI…)                                                               | yes                  | not applicable    |
| 4        | `documentation_only`    | Only docs files (`.md`, `.rst`, …)                                                                    | no                   | not applicable    |
| 5        | `non_python_patch`      | Other files, no Python or docs                                                                        | no                   | not applicable    |

A single file from a higher-priority category overrides the entire patch.

### Fast path

Documentation-only and non-Python patches can verify without `after_run_id`
when `changed_files` or `diff_ref` evidence is provided. Without any diff
evidence, verify returns `unverified` to preserve backward compatibility.

### Invariants

- The profile is derived from `actual_changed_files`, never declared by the
  agent.
- Scope and forbidden checks always run before any profile-based fast return.
- Receipts use "not applicable" for skipped structural checks, never "passed".
- Claim guard warns when review text references structural verification but
  the profile says structural checks were not applicable.
- Claim guard warns and violates regression-free claims when
  `patch_health_delta < 0`.

### Public surface

| Artifact          | Path                                                   |
|-------------------|--------------------------------------------------------|
| Classifier module | `codeclone/surfaces/mcp/_verification_profile.py`      |
| Enum              | `VerificationProfile`                                  |
| Classifier        | `classify_patch(changed_files) → ClassificationResult` |
| Check matrix      | `check_matrix(profile) → CheckMatrix`                  |

### Locked by tests

- `tests/test_verification_profile.py`
- `tests/test_mcp_service.py`
