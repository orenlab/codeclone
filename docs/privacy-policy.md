# Privacy Policy

This page describes the privacy behavior of CodeClone's local integration
surfaces, including the Claude Desktop bundle.

## CodeClone local privacy model

CodeClone itself is a local analysis tool.

For the CLI, MCP server, VS Code extension, and Claude Desktop bundle:

- CodeClone does not run its own telemetry service
- CodeClone does not send repository contents to an external CodeClone backend
- CodeClone reads local repository files, local git state, baselines, and cache
  only to perform the requested structural analysis
- the Claude Desktop bundle is only a local wrapper around `codeclone-mcp`

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
