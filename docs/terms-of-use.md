# Terms of Use

These terms describe the intended use of CodeClone's local integration surfaces,
including the Codex plugin and Claude Desktop bundle.

## Local tool scope

CodeClone is distributed as a local analysis tool and local integration layer.

That means:

- CodeClone is provided as-is under the repository license terms
- local integrations are wrappers over local CodeClone execution, not hosted
  managed services
- users are responsible for reviewing the commands, configuration, and
  repository access they enable on their own machines

## Integration boundaries

CodeClone local integrations:

- do not grant additional repository permissions beyond what the local client
  and local process already have
- do not override the security or account terms of Claude Desktop, Codex, or
  other host applications
- do not change Anthropic or OpenAI platform terms for those host applications

## Intended usage

CodeClone integrations are intended for:

- local structural analysis and review
- local CI and developer workflows
- read-only MCP-based inspection of repository state

They are not intended to operate as unattended hosted analysis services unless
you build and secure that deployment separately.

## Support and updates

CodeClone integrations may evolve during the `2.0.x` beta line. Published docs,
tests, and changelog entries define the intended contract surface for each
release.

Questions or issues can be reported at:

- <https://github.com/orenlab/codeclone/issues>
