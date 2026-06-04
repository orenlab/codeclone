<!-- doc-scope: TERMS OF USE — legal content.
     owns: terms of use text.
     does-not-own: MCP read-only contract (→ book/25), security model (→ book/21).
     rule: cross-link to contracts, do not restate them. -->
# Terms of Use

These terms describe the intended operational and integration boundaries of
CodeClone and its local integration surfaces, including the MCP server,
VS Code extension, Codex plugin, and Claude Desktop bundle.

## Local-first execution model

CodeClone is distributed as a local structural review and analysis tool.

Analysis executes against repositories available to the local process or
explicitly configured execution environment. CodeClone does not provide a
hosted SaaS analysis backend and does not transmit repository contents to
external services unless the surrounding client, transport, or deployment
explicitly does so.

CodeClone source code is licensed under MPL-2.0.
Documentation content and the published docs site are licensed under MIT.

## Integration boundaries

CodeClone integrations are local control surfaces over the same canonical
analysis pipeline.

Integrations:

- inherit the repository and filesystem access already granted to the local
  execution environment
- do not elevate privileges or bypass operating-system, editor, repository,
  or host-application security controls
- do not grant additional repository permissions beyond those already available
  to the executing process or connected client

CodeClone integrations do not modify or replace the security, account,
privacy, or usage policies of third-party host applications such as
Claude Desktop, Codex, VS Code, Anthropic services, or OpenAI services.

Those platforms remain governed by their own applicable terms and policies.

## MCP and automation surfaces

The MCP interface is read-only by contract with respect to source files,
baselines, analysis cache, and canonical report artifacts.

CodeClone MCP integrations are intended for deterministic structural analysis,
review, and triage workflows. They expose canonical findings, metrics, and
review data, but do not mutate:

- source files
- git history
- baselines
- analysis cache or canonical report artifacts
- CI configuration

Ephemeral controller coordination (workspace intent registry: file backend under
`.cache/codeclone/intents/`, or SQLite under `.cache/codeclone/db/intents.sqlite3`
when configured) and optional audit trail
(`.cache/codeclone/db/audit.sqlite3` when `audit_enabled=true`) are the only
allowed repo-local writes.

Remote, shared, or network-exposed MCP deployments are the responsibility of
the operator securing and governing those environments.

## Intended usage

CodeClone is intended for:

- structural review and architectural analysis
- baseline-aware CI governance
- deterministic review workflows
- local IDE, CI, and AI-agent integrations

Hosted, unattended, multi-tenant, or internet-exposed deployments may require
additional operational controls, sandboxing, authentication, and access
restrictions outside the scope of the default local integrations.

## Compatibility and evolution

The `2.x` release line evolves under documented compatibility contracts.

Canonical schemas, exit codes, report structures, and interface guarantees are
defined by the published documentation and locked regression tests.

## Support

Questions, issues, and false-positive reports can be submitted at:

- <https://github.com/orenlab/codeclone/issues>
