# MCP for AI Agents and IDE Clients

## Purpose

Explain how to use CodeClone as an MCP server in real agent workflows.

Important framing: MCP is primarily a **client integration surface**, not a
model-specific trick. CodeClone does not care whether the backend model is
GPT-5.x, Claude, Gemini, or something else. What matters is whether the
client/application you use can talk to MCP and which transport it expects.

## Install

Base install stays lean:

```bash
pip install codeclone
```

Install MCP support only when you need it:

```bash
pip install "codeclone[mcp]"
```

Tool install example:

```bash
uv tool install "codeclone[mcp]"
```

## Start the server

### Local agent workflows: prefer `stdio`

```bash
codeclone-mcp --transport stdio
```

This is the best default when the MCP-capable client runs on the same machine
and needs access to the local repository.

### Remote or HTTP-only clients: use `streamable-http`

```bash
codeclone-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

With current FastMCP defaults, clients usually connect to the streamable HTTP
endpoint at:

```text
http://127.0.0.1:8000/mcp
```

Use this mode when the client only supports remote MCP endpoints or when you
want to expose CodeClone from a controlled local/remote service boundary.

## What agents get

CodeClone MCP is designed as a **read-only structural governance layer**:

- run CodeClone analysis against a repository
- get a compact run summary
- list clone / structural / dead-code / design findings
- inspect one finding by id
- retrieve derived hotlists
- preview gate decisions without exiting the process
- read the canonical JSON report for a stored run

It does **not**:

- update baselines
- mutate source files
- add suppressions automatically

Current tool surface:

| Tool | Typical use |
|------|-------------|
| `analyze_repository` | Run a fresh analysis and register it as the latest in-memory run |
| `get_run_summary` | Get the compact baseline/cache/health/findings snapshot for the latest or selected run |
| `list_findings` | Browse findings with filters and pagination |
| `get_finding` | Inspect one finding group deeply by id |
| `list_hotspots` | Jump to high-signal derived views such as `highest_spread` or `production_hotspots` |
| `get_report_section` | Read a canonical section (`meta`, `findings`, `metrics`, `derived`, etc.) |
| `evaluate_gates` | Preview CI/gating outcomes without exiting the process |

## Recommended agent workflow

For agentic coding and review loops, the clean sequence is:

1. `analyze_repository`
2. `get_run_summary`
3. `list_hotspots` or `list_findings`
4. `get_finding` for the specific item the agent should inspect
5. `evaluate_gates` before finalizing the change

That pattern works especially well for AI-generated code because CodeClone is
baseline-aware: it helps separate accepted legacy debt from new structural
regressions introduced by the latest change set.

## Prompt patterns for real agent workflows

The most effective way to use CodeClone MCP is to ask the agent for a
**specific analysis task**, not just "run CodeClone".

Good prompts usually include:

- the scope:
    - full repository
    - clones only
    - production findings only
- the goal:
    - review
    - triage
    - safe cleanup plan
    - gate preview
- the constraint:
    - do not mutate code yet
    - do not add suppressions automatically
    - prioritize runtime-facing findings

Use prompts like these.

### 1. Full repository health check

```text
Use codeclone MCP to analyze this repository and give me a concise structural health summary.
Prioritize the highest-signal findings and explain what is worth looking at first.
```

### 2. Clone-focused review only

```text
Use codeclone MCP in clones-only mode and show me the most important clone findings.
Separate production findings from test/fixture noise and suggest which clone group is the safest first cleanup target.
```

### 3. Production-only clone triage

```text
Analyze this repository through codeclone MCP, filter to clone findings in production code only,
and show me the top 3 clone groups worth fixing first.
If there are no production clones, say that explicitly.
```

### 4. Structural hotspot review

```text
Use codeclone MCP to find the most important production structural findings.
Focus on duplicated branches, cohesion, coupling, and complexity hotspots.
Give me a safe cleanup plan ordered by ROI.
```

### 5. Dead-code triage

```text
Use codeclone MCP to review dead-code findings in this repository.
Separate actionable items from likely framework/runtime false positives and explain what should actually be cleaned up.
Do not add suppressions automatically.
```

### 6. Gate preview before CI

```text
Run codeclone through MCP and tell me whether this repository would fail stricter gating.
Preview the result for fail_on_new plus a zero clone threshold, and explain the exact reasons.
Do not change any files.
```

### 7. AI-generated code review

```text
I added a lot of code with an AI agent. Use codeclone MCP to check whether we introduced structural drift:
new clone groups, dead code, duplicated branches, or design hotspots.
Prioritize what is genuinely new or risky, not accepted baseline debt.
```

### 8. Safe refactor planning

```text
Use codeclone MCP as the source of truth for structural findings.
Pick one production issue that looks safe to refactor, explain why it is a good candidate,
and outline a minimal plan that should not change behavior.
```

### 9. Explain one finding deeply

```text
Use codeclone MCP to find the highest-priority production finding, then inspect it in detail.
Explain what triggered it, where it lives, how risky it is, and what refactoring shape would address it.
Do not make code changes yet.
```

### 10. Review after a change

```text
Use codeclone MCP to analyze the repository after my latest changes.
Tell me whether the structural picture got better, worse, or stayed flat relative to baseline,
and summarize only the findings that are worth acting on.
```

## Prompting tips

- Prefer "production-only" when you care about runtime code.
- Prefer "clones-only mode" when you want the cheapest focused pass on duplication.
- Ask for "safe first candidate" when you want the agent to move from triage to refactor planning.
- If your broader agent also has shell or file-editing tools, you can still say
  "do not update baseline" as a workflow constraint. CodeClone MCP itself is
  read-only and never updates baseline.
- For AI-generated code, explicitly ask the agent to separate:
    - accepted baseline debt
    - from new structural regressions

## Client recipes

Client UX changes fast, so prefer official client documentation for the exact
setup screens. The integration shape below is the stable part on the CodeClone
side.

### Codex / local command-based OpenAI clients

Recommended mode: `stdio`

```bash
codeclone-mcp --transport stdio
```

A typical command-based registration looks like:

```toml
[mcp_servers.codeclone]
enabled = true
command = "codeclone-mcp"
args = ["--transport", "stdio"]
```

Use command-based MCP registration when the client can spawn a local server
process. If `codeclone-mcp` is not on `PATH`, use an absolute path to the
launcher.

Official docs:

- [OpenAI: Connectors and MCP servers](https://platform.openai.com/docs/guides/tools-connectors-mcp?lang=javascript)
- [OpenAI Responses API reference (`mcp` tool)](https://platform.openai.com/docs/api-reference/responses/compact?api-mode=responses)

### OpenAI Responses API / remote MCP-capable OpenAI clients

Recommended mode: `streamable-http`

```bash
codeclone-mcp --transport streamable-http --host 127.0.0.1 --port 8000
```

Then register the remote MCP endpoint in the client or API flow that expects an
HTTP MCP server. Prefer allowing only the CodeClone tools you need for the
current workflow.

### Claude Code / Anthropic MCP-capable clients

Recommended mode: `stdio`

Generic command-based configuration:

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

This is the best fit when Claude runs on the same machine and should analyze
the local checkout directly.

Official docs:

- [Anthropic: Model Context Protocol (MCP)](https://docs.anthropic.com/en/docs/build-with-claude/mcp)
- [Anthropic: MCP with Claude Code](https://docs.anthropic.com/en/docs/claude-code/mcp)

### GitHub Copilot Chat / IDE MCP clients

Recommended mode: `stdio`

Use the same local command registration pattern:

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

Then configure the MCP server in the IDE/client that hosts Copilot Chat.

Official docs:

- [GitHub Docs: Extending GitHub Copilot Chat with MCP](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/extend-copilot-chat-with-mcp?tool=visualstudio)

### Other MCP-capable clients

Use the same transport rule:

- `stdio` for local repository analysis
- `streamable-http` for remote-only or hosted MCP clients

The CodeClone server surface itself stays the same.

## Security and operations

- CodeClone MCP is read-only by design.
- It stores run history in memory only.
- Repository access is limited to what the server process can read locally.
- Baseline/cache/report semantics remain owned by the normal CodeClone contracts.

## Troubleshooting

### `CodeClone MCP support requires the optional 'mcp' extra`

Install the extra:

```bash
pip install "codeclone[mcp]"
```

### The client cannot find `codeclone-mcp`

Either install it as a tool:

```bash
uv tool install "codeclone[mcp]"
```

or point the client at the absolute path to the launcher from the environment
where CodeClone was installed.

### The client only accepts remote MCP servers

Run CodeClone in `streamable-http` mode and point the client at the MCP
endpoint instead of using `stdio`.

### The agent is reading stale results

Run `analyze_repository` again. Runs are stored in memory per server process and
`latest` always points at the most recently analyzed run in that process.

## See also

- [book/20-mcp-interface.md](book/20-mcp-interface.md)
- [book/08-report.md](book/08-report.md)
- [book/09-cli.md](book/09-cli.md)
