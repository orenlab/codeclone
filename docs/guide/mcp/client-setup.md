<!-- doc-scope: MCP client setup. class: guide max-lines: 120 -->
# MCP client setup

## Client setup

All clients use the same server. Only the registration format differs.

=== "Claude Code"

    ```bash
    claude plugin marketplace add orenlab/codeclone-claude-code
    claude plugin install codeclone@orenlab-codeclone
    ```

    The native plugin supplies the MCP definition and CodeClone skills. See the
    [Claude Code plugin guide](../integrations/claude-code/setup.md).

    Manual MCP registration without the plugin remains available:

    ```bash
    claude mcp add --scope project codeclone -- codeclone-mcp --transport stdio
    ```

=== "Codex"

    ```bash
    codex plugin marketplace add orenlab/codeclone-codex
    codex plugin add codeclone@orenlab-codeclone
    ```

    The native plugin includes the MCP definition and CodeClone skills.
    Manual MCP registration without the plugin is also valid:

    ```bash
    codex mcp add codeclone -- codeclone-mcp --transport stdio
    ```

    See [Codex plugin guide](../integrations/codex/setup.md).

=== "Cursor"

    For the complete integration, import
    `https://github.com/orenlab/codeclone-cursor` through
    **Dashboard → Settings → Plugins → Team Marketplaces → Add Marketplace →
    Import from Repo**, then install **CodeClone**.

    The bundled [Cursor plugin](../integrations/cursor/install-and-skills.md)
    includes MCP registration, skills, rules, and project hooks. Manual
    `.cursor/mcp.json` registration is covered under generic setup below, but
    does not install the rest of that surface.

=== "Claude Desktop"

    A local `.mcpb` bundle ships in `extensions/claude-desktop-codeclone/`.
    See [Claude Desktop bundle guide](../integrations/claude-desktop/setup.md).

=== "JSON config (generic)"

    ```json
    {
      "mcpServers": {
        "codeclone": {
          "command": "codeclone-mcp",
          "args": ["--transport", "stdio"]
        }
      }
    }
    ```

    Works with Copilot Chat, Gemini CLI, and other MCP-capable clients.

If `codeclone-mcp` is not on `PATH`, use the full launcher path.

---
