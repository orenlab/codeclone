# 22. Claude Desktop Bundle

## Purpose

Document the current contract and behavior of the Claude Desktop bundle shipped
in `extensions/claude-desktop-codeclone/`.

This chapter describes the bundle as a local install and launcher layer over
existing CodeClone MCP contracts. It does not define a second analysis truth
model.

## Position in the platform

The Claude Desktop bundle is:

- a local `.mcpb` install surface for Claude Desktop
- a small Node wrapper around `codeclone-mcp`
- read-only with respect to repository state
- local-stdio-only by design
- configuration-aware only for launcher resolution

The bundle exists to make local setup easier, not to reinterpret CodeClone
analysis.

## Source of truth

The bundle delegates to the existing `codeclone-mcp` launcher.

It must not:

- run a second analysis engine
- redefine tools, findings, or health semantics
- mutate source files, baselines, cache, or report artifacts
- turn local Claude Desktop integration into a separate report surface

## Current surface

The bundle currently provides:

- one installable `.mcpb` package
- one local Node launcher wrapper
- two user settings:
    - launcher command
    - advanced launcher args as a JSON array
- one build script for deterministic local packaging

It intentionally does not add bundle-only MCP tools or prompts.

## Runtime model

The wrapper:

1. resolves a local `codeclone-mcp` launcher
2. validates advanced args
3. forces `--transport stdio`
4. launches the child process with `shell: false`
5. proxies stdio until shutdown

The wrapper may auto-discover a few common global install locations, but it is
now prefers:

- a workspace-local `.venv`
- the active Poetry environment for the current workspace
- user-local install locations and `PATH`
- or an explicit launcher command in bundle settings

This keeps the launcher closer to the active project Python when possible.

## Design rules

- **Canonical MCP first**: the bundle must keep Claude Desktop on the same
  documented MCP surface as other clients.
- **Local-only transport**: reject transport and remote-listener overrides.
- **Setup honesty**: fail with a bounded install hint when the launcher is
  missing.
- **No hidden runtime dependency games**: the bundle does not pretend to bundle
  Python or CodeClone itself.
- **Small and deterministic**: package only the wrapper, manifest, icon, and
  documentation needed for local installation.

## Relationship to other interfaces

- CLI remains the scripting and CI surface.
- MCP remains the read-only agent/client contract.
- Claude Code can still register `codeclone-mcp` directly through `mcp add`.
- The Claude Desktop bundle is the installable local package layer for users
  who want a native Claude Desktop setup path.

## Non-guarantees

- Bundle presentation inside Claude Desktop may evolve with MCPB client UX.
- Auto-discovery heuristics for common launcher locations may evolve as long as
  the explicit launcher setting remains stable.
- The bundle does not guarantee automatic updates or remote install flows.
