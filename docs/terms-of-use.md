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

The MCP interface is read-only by contract.

CodeClone MCP integrations are intended for deterministic structural analysis,
review, and triage workflows. They expose canonical findings, metrics, and
review data, but do not mutate:

- source files
- git history
- baselines
- repository state
- CI configuration

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

## Commercial hosted usage

The default open-source distribution of CodeClone is intended for local,
team, and self-managed use.

Providing CodeClone as a hosted service, managed analysis platform,
multi-tenant SaaS/PaaS offering, or externally operated commercial review
service may require separate commercial licensing or written authorization,
depending on the deployment model and redistribution scope.

This includes, but is not limited to:

- hosted structural analysis platforms
- commercial CI review services built on top of CodeClone
- externally managed multi-tenant deployments
- paid analysis or governance services exposing CodeClone functionality
  to third parties

For commercial licensing or deployment questions, contact:

- <mailto:sudo@secuapp.ru>

## Compatibility and evolution

The `2.x` release line evolves under documented compatibility contracts.

Canonical schemas, exit codes, report structures, and interface guarantees are
defined by the published documentation and locked regression tests.

## Support

Questions, issues, and false-positive reports can be submitted at:

- <https://github.com/orenlab/codeclone/issues>
