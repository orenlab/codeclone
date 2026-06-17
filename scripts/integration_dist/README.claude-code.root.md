# CodeClone for Claude Code

This repository is the public Claude Code marketplace for the CodeClone plugin.
It is synchronized from
[orenlab/codeclone](https://github.com/orenlab/codeclone); see
`SYNC_MANIFEST.json` for the exact source commit and package version.

## Install

Add the marketplace, then install the plugin:

```bash
claude plugin marketplace add orenlab/codeclone-claude-code
claude plugin install codeclone@orenlab-codeclone
```

The equivalent commands inside an interactive Claude Code session are:

```text
/plugin marketplace add orenlab/codeclone-claude-code
/plugin install codeclone@orenlab-codeclone
```

The plugin does not bundle the Python MCP server. Install `codeclone[mcp]` in
the workspace or on `PATH`:

```bash
uv tool install "codeclone[mcp]"
codeclone-mcp --help
```

See the [plugin guide](plugins/codeclone/README.md) for skills, runtime
resolution, and trust boundaries.

## Documentation

- [Claude Code setup](https://orenlab.github.io/codeclone/guide/integrations/claude-code/setup/)
- [MCP usage guide](https://orenlab.github.io/codeclone/guide/mcp/)
- [Claude Code plugin contract](https://orenlab.github.io/codeclone/book/integrations/claude-code-plugin/)
