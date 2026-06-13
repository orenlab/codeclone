# CodeClone for Codex — distribution repository

This repository is the **public marketplace mirror** for the Codex plugin. It is
synced from [orenlab/codeclone](https://github.com/orenlab/codeclone); see
`SYNC_MANIFEST.json` for the exact source commit and package version.

## Layout

| Path | Role |
|------|------|
| `.agents/plugins/marketplace.json` | Codex marketplace catalog (`codex plugin marketplace add orenlab/codeclone-codex`) |
| `plugins/codeclone/` | Plugin root (manifest, skills, MCP launcher, assets) |
| `plugins/codeclone/README.md` | **Full** install and usage guide for the plugin tree |

The file you are reading is the **repository** README for GitHub and browsing.
Codex loads the plugin from `./plugins/codeclone`; do not move the plugin to the
repo root.

## Install

```bash
codex plugin marketplace add orenlab/codeclone-codex
codex plugin add codeclone@orenlab-codeclone
```

Install `codeclone[mcp]` in your workspace or on `PATH` so the bundled launcher
can resolve `codeclone-mcp`. Step-by-step setup, skills, and boundaries:

**[plugins/codeclone/README.md](plugins/codeclone/README.md)**

## Documentation

- [Codex plugin guide](https://orenlab.github.io/codeclone/guide/integrations/codex/setup/)
- [MCP interface](https://orenlab.github.io/codeclone/guide/mcp/)
- [Publishing / sync](https://github.com/orenlab/codeclone/blob/main/docs/publishing.md)
