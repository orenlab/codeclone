<!-- doc-scope: PRIVACY POLICY — legal content.
     owns: privacy policy text.
     does-not-own: MCP read-only contract (→ book/25, book/21).
     rule: cross-link to contracts, do not restate them. -->

# Privacy Policy

This page describes the privacy behavior of CodeClone's local integration
surfaces, including the VS Code extension, Cursor plugin, Claude Code plugin,
Codex plugin, and Claude Desktop bundle.

## CodeClone local privacy model

CodeClone itself is a local analysis tool.

For the CLI, MCP server, VS Code extension, Cursor plugin, Claude Code plugin,
Codex plugin, and Claude Desktop bundle:

- CodeClone does not run its own telemetry service
- CodeClone does not send repository contents to an external CodeClone backend
- CodeClone reads local repository files, local git state, baselines, and cache
  only to perform the requested structural analysis
- Engineering Memory, trajectory/Experience projections, Controller audit, and
  Platform Observability are optional local SQLite state under `.codeclone/`
- Platform Observability records bounded metadata, counters, timings, and
  literal-free SQL fingerprints; it does not store raw prompts or payload bodies
- the Claude Desktop bundle is only a local wrapper around `codeclone-mcp`

CodeClone does not provide a remote telemetry exporter. Automatic pruning of
the Platform Observability database is not currently enforced; users who enable
persistence control that local file's lifecycle. See
[Platform Observability](book/26-platform-observability.md) and
[Plans and Retention](plans-and-retention.md).

## Claude Desktop bundle specifics

The bundle in `extensions/claude-desktop-codeclone/`:

- runs locally on the user's machine
- launches `codeclone-mcp` via local `stdio`
- does not expose a remote listener
- does not upload repository contents on its own
- stores no bundle-specific cloud account, token, or analytics state

The bundle may read:

- the configured launcher command
- optional advanced launcher arguments
- the local repository content that CodeClone MCP analyzes on request

## Third-party platform note

When you use CodeClone through Claude Desktop, your conversation and tool use
still happen inside Claude Desktop. Anthropic's own product terms and privacy
policies apply to the Claude Desktop client and your account with Anthropic.

This CodeClone bundle does not change that relationship and does not operate a
separate hosted service.

## Support

Questions or issues about the CodeClone bundle can be reported at:

- <https://github.com/orenlab/codeclone/issues>
