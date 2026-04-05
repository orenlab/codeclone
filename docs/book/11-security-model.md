# 11. Security Model

## Purpose

Describe implemented protections and explicit security boundaries.

## Public surface

- Scanner path validation: `codeclone/scanner.py:iter_py_files`
- File read limits and parser limits: `codeclone/cli.py:process_file`, `codeclone/extractor.py:_parse_limits`
- Baseline/cache validation: `codeclone/baseline.py`, `codeclone/cache.py`
- HTML escaping: `codeclone/_html_escape.py`, `codeclone/html_report.py`
- MCP read-only enforcement: `codeclone/mcp_service.py`, `codeclone/mcp_server.py`

## Data model

Security-relevant input classes:

- filesystem paths (root/source/baseline/cache/report)
- untrusted JSON files (baseline/cache)
- untrusted source snippets and metadata rendered into HTML

## Contracts

- CodeClone parses source text; it does not execute repository Python code.
- Sensitive root directories are blocked by scanner policy.
- Symlink traversal outside root is skipped.
- HTML report escapes text and attribute contexts before embedding.
- MCP server is read-only by design: no tool mutates source files, baselines,
  cache, or report artifacts.
- `--allow-remote` guard must be passed explicitly for non-local transports;
  default is local-only (`stdio`).
- `cache_policy=refresh` is rejected — MCP cannot trigger cache invalidation.
- Review markers (`mark_finding_reviewed`) are session-local in-memory state;
  they are never persisted to disk or leaked into baselines/reports.
- `git_diff_ref` parameter is validated against a strict regex to prevent
  command injection via shell-interpreted git arguments.
- Run history is bounded by `--history-limit` (default 10) to prevent
  unbounded memory growth.

Refs:

- `codeclone/extractor.py:_parse_with_limits`
- `codeclone/scanner.py:SENSITIVE_DIRS`
- `codeclone/scanner.py:iter_py_files`
- `codeclone/_html_escape.py:_escape_html`

## Invariants (MUST)

- Baseline and cache integrity checks use constant-time comparison.
- Size guards are enforced before parsing baseline/cache JSON.
- Cache failures degrade safely (warning + ignore), baseline trust failures follow trust model.

Refs:

- `codeclone/baseline.py:Baseline.verify_integrity`
- `codeclone/cache.py:Cache.load`
- `codeclone/cli.py:_main_impl`

## Failure modes

| Condition                                | Security behavior  |
|------------------------------------------|--------------------|
| Symlink points outside root              | File skipped       |
| Root under sensitive dirs                | Validation error   |
| Oversized baseline                       | Baseline rejected  |
| Oversized cache                          | Cache ignored      |
| HTML-injected payload in metadata/source | Escaped output     |
| `--allow-remote` not passed for HTTP     | Transport rejected |
| `cache_policy=refresh` requested         | Policy rejected    |
| `git_diff_ref` fails regex               | Parameter rejected |

## Determinism / canonicalization

- Canonical JSON hashing for baseline/cache prevents formatting-only drift.
- Security failures map to explicit statuses (baseline/cache enums).

Refs:

- `codeclone/baseline.py:_compute_payload_sha256`
- `codeclone/cache.py:_canonical_json`
- `codeclone/baseline.py:BaselineStatus`
- `codeclone/cache.py:CacheStatus`

## Locked by tests

- `tests/test_security.py::test_scanner_path_traversal`
- `tests/test_scanner_extra.py::test_iter_py_files_symlink_loop_does_not_traverse`
- `tests/test_security.py::test_html_report_escapes_user_content`
- `tests/test_html_report.py::test_html_report_escapes_script_breakout_payload`
- `tests/test_cache.py::test_cache_too_large_warns`
- `tests/test_mcp_service.py::test_cache_policy_refresh_rejected`
- `tests/test_mcp_server.py::test_allow_remote_guard`

## Non-guarantees

- Baseline/cache integrity is tamper-evident at file-content level; it is not cryptographic attestation against a
  privileged attacker.
