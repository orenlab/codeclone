# 11. Security Model

## Purpose

Describe implemented protections and explicit security boundaries.

## Public surface

- Scanner path validation: `codeclone/scanner.py:iter_py_files`
- File read and parser limits: `codeclone/core/worker.py:process_file`,
  `codeclone/analysis/parser.py:_parse_limits`
- Baseline/cache validation: `codeclone/baseline/*`, `codeclone/cache/*`
- HTML escaping: `codeclone/report/html/primitives/escape.py`,
  `codeclone/report/html/assemble.py`
- MCP read-only enforcement: `codeclone/surfaces/mcp/*`

## Data model

Security-relevant input classes:

- filesystem paths (root/source/baseline/cache/report)
- untrusted JSON files (baseline/cache)
- untrusted source snippets and metadata rendered into HTML
- MCP request parameters (`root`, filters, diff refs, cache policy)

## Contracts

- CodeClone parses source text; it does not execute repository Python code.
- Sensitive root directories are blocked by scanner policy.
- Symlink traversal outside the root is skipped.
- HTML escapes text and attribute contexts before embedding.
- MCP is read-only by design:
  no tool mutates source files, baselines, cache, or report artifacts.
- `--allow-remote` is required for non-local transports.
- `cache_policy=refresh` is rejected by MCP.
- Review markers are session-local in-memory state only.
- `git_diff_ref` is validated as a safe single revision expression before any `git diff` subprocess call.

Refs:

- `codeclone/analysis/parser.py:_parse_with_limits`
- `codeclone/scanner.py:SENSITIVE_DIRS`
- `codeclone/scanner.py:iter_py_files`
- `codeclone/report/html/primitives/escape.py:_escape_html`

## Invariants (MUST)

- Baseline and cache integrity checks use constant-time comparison.
- Size guards are enforced before parsing baseline/cache JSON.
- Cache failures degrade safely; baseline trust failures follow the explicit trust model.

Refs:

- `codeclone/baseline/clone_baseline.py:Baseline.verify_integrity`
- `codeclone/cache/store.py:Cache.load`
- `codeclone/surfaces/cli/workflow.py:_main_impl`

## Failure modes

| Condition                                | Security behavior  |
|------------------------------------------|--------------------|
| Symlink points outside root              | File skipped       |
| Root under sensitive dirs                | Validation error   |
| Oversized baseline                       | Baseline rejected  |
| Oversized cache                          | Cache ignored      |
| HTML-injected payload in metadata/source | Escaped output     |
| `--allow-remote` not passed for HTTP     | Transport rejected |
| `cache_policy=refresh` requested in MCP  | Policy rejected    |
| `git_diff_ref` fails validation          | Parameter rejected |

## Determinism / canonicalization

- Canonical JSON hashing for baseline/cache prevents formatting-only drift.
- Security failures map to explicit statuses rather than silent mutation.

Refs:

- `codeclone/baseline/trust.py:_compute_payload_sha256`
- `codeclone/cache/integrity.py:canonical_json`
- `codeclone/baseline/trust.py:BaselineStatus`
- `codeclone/cache/versioning.py:CacheStatus`

## Locked by tests

- `tests/test_security.py::test_scanner_path_traversal`
- `tests/test_scanner_extra.py::test_iter_py_files_symlink_loop_does_not_traverse`
- `tests/test_security.py::test_html_report_escapes_user_content`
- `tests/test_html_report.py::test_html_report_escapes_script_breakout_payload`
- `tests/test_cache.py::test_cache_too_large_warns`
- `tests/test_mcp_service.py::test_mcp_service_rejects_refresh_cache_policy_in_read_only_mode`
- `tests/test_mcp_server.py::test_mcp_server_main_rejects_non_loopback_host_without_opt_in`

## Non-guarantees

- Baseline/cache integrity is tamper-evident at file-content level; it is not cryptographic attestation against a
  privileged attacker.
