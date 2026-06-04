<!-- doc-scope: SECURITY MODEL AND THREAT BOUNDARIES.
     owns: trust boundaries, read-only invariant, allowed writes, transport security.
     does-not-own: MCP tool surface (→ 25), change controller (→ 12). -->
# 11. Security Model

## Purpose

Describe implemented protections and explicit security boundaries.

## Public surface

- Scanner path validation: `codeclone/scanner/__init__.py:iter_py_files`
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
- MCP is read-only with respect to source files, baselines, analysis cache
  (`cache.json`), and canonical report artifacts.
- Allowed repo-local writes are limited to ephemeral controller coordination
  (workspace intent registry: file backend under `.codeclone/intents/`,
  or SQLite under `.codeclone/db/intents.sqlite3` when configured) and
  optional audit trail (`.codeclone/db/audit.sqlite3` when
  `audit_enabled=true`).
- Session-local review markers and in-memory run history do not survive
  process restart.
- Five session/coordination tools are marked `destructiveHint` in MCP metadata
  (`manage_change_intent`, `start_controlled_change`,
  `finish_controlled_change`, `mark_finding_reviewed`, `clear_session_runs`).
- `--allow-remote` is required for non-local transports. It is an explicit
  operator opt-in, not authentication. A remote MCP endpoint remains an
  unauthenticated local-trust surface unless wrapped by external access control.
- MCP accepts cache policies `reuse` and `off`; `refresh` is rejected at
  runtime with a contract error.
- `git_diff_ref` is validated as a safe single revision expression before any `git diff` subprocess call.
- MCP `processes` is capped to `min(requested, os.cpu_count() or 4, 64)`.
  This is a resource ceiling only; it does not change analysis results.

## Trust boundaries (explicit)

These are documented limits, not hidden guarantees.

### MCP optional artifact paths

`_resolve_optional_path` resolves `baseline_path`, `metrics_baseline_path`,
`cache_path`, and `coverage_xml` relative to the repository root, but also
accepts absolute paths anywhere on the host filesystem. That behavior is
intentional for monorepo and shared-artifact workflows, but it is a trust
boundary: the MCP client and operator must treat these parameters as privileged
inputs. Blind containment would break valid external artifact paths; any future
containment must be opt-in and contract-versioned.

Refs:

- `codeclone/surfaces/mcp/_session_helpers.py:_resolve_optional_path`

### Cache checksum semantics

Cache signatures detect corruption and accidental mutation of the canonical
cache payload. They are not adversarial authentication against a privileged
local attacker who can rewrite `.codeclone/cache.json` directly.

Refs:

- `codeclone/cache/integrity.py:sign_cache_payload`
- `codeclone/cache/integrity.py:verify_cache_payload_signature`

### Workspace change intents

The workspace intent registry coordinates concurrent edits between processes
running as the same local UID on the same host (file backend:
`.codeclone/intents/`; SQLite backend: `.codeclone/db/intents.sqlite3`
when configured). Records are advisory, TTL-bound (default 1 hour, lease 5
minutes), gitignored, and integrity-checked (SHA-256 over canonical JSON) but not
cryptographically authenticated. A same-UID process with repository write access
can forge or delete intent records; that UID can already modify source files and
baselines directly. Treat intents as coordination hints, not proof of agent
identity.

The Cursor plugin may enforce `preToolUse` by **reading** this registry through
`codeclone.workspace_intent` (read-only; no lazy-close or writes). That reduces
accidental edits without intent; it does not stop a hostile same-UID process.

Refs:

- `codeclone/workspace_intent/gate.py`
- `codeclone/surfaces/mcp/_workspace_intents.py`
- `codeclone/surfaces/mcp/_session_workflow_mixin.py`

### Remote MCP transport

Loopback binding is the default. `--allow-remote` removes the loopback-only
transport guard so HTTP MCP can bind on non-local interfaces. CodeClone does
not implement TLS, tokens, or session authentication for MCP. Operators must
place remote MCP behind a trusted network boundary or external auth proxy.

Refs:

- `codeclone/surfaces/mcp/server.py`
- `tests/test_mcp_server.py::test_mcp_server_main_rejects_non_loopback_host_without_opt_in`

Refs:

- `codeclone/analysis/parser.py:_parse_with_limits`
- `codeclone/scanner/__init__.py:SENSITIVE_DIRS`
- `codeclone/scanner/__init__.py:iter_py_files`
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
| Invalid `cache_policy` requested in MCP  | Policy rejected    |
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
- `tests/test_mcp_service.py::test_mcp_service_caps_process_count_from_request_and_config`
- `tests/test_mcp_server.py::test_mcp_server_main_rejects_non_loopback_host_without_opt_in`

## Non-guarantees

- Baseline/cache integrity is tamper-evident at file-content level; it is not cryptographic attestation against a
  privileged attacker.
- Baseline `payload_sha256` and cache signatures protect against accidental corruption and unsynchronized edits; they
  do not authenticate files against a hostile same-UID writer.
- Workspace intent files are not signed and must not be treated as proof of which agent declared a change.
- MCP optional absolute artifact paths are caller-controlled; CodeClone does not sandbox them to the scan root.
- Remote MCP with `--allow-remote` is not a hardened multi-tenant network service.
