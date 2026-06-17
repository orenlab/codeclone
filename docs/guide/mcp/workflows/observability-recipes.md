# Platform Observability recipes (MCP)

<!-- doc-scope: guide -->

**Maintainer-only.** These recipes apply when you develop **CodeClone itself**
(MCP server, CLI instrumentation, memory pipelines, observer storage). They do
**not** help users analyze their Python repositories — for that use
[Analyze & triage](analyze-and-triage.md) and [Change control](change-control.md).

Prerequisite: [Explicit observer enable](../../observability/maintainer-workflow.md#explicit-enable-required).

Skill: `/codeclone-platform-observability` in bundled plugins.

## 0. Confirm you need this surface

| Question                                        | Tool                                                       |
|-------------------------------------------------|------------------------------------------------------------|
| Health / clones / metrics of **user repo**      | `get_production_triage`, `check_*` — **not** observability |
| Slow **CodeClone** MCP handler or DB during dev | `query_platform_observability`                             |
| Patch verify / edit scope                       | change-control workflow — **not** observability            |

If the user is not a CodeClone maintainer, **do not** call
`query_platform_observability`.

## 1. Enable observer on the producing process

```bash
export CODECLONE_OBSERVABILITY_ENABLED=1
# restart codeclone-mcp (or CLI) with this env in the same shell / IDE config
```

Re-run the workflow under test. Without enablement every section returns
`status=disabled` or `status=no_store`.

## 2. Read contract

```text
help(topic="observability", detail="normal")
```

Covers sections, anti-inference rules, and inert disabled states.

## 3. Start broad

```json
{
  "root": "/absolute/path/to/codeclone",
  "section": "summary",
  "window": "latest",
  "detail_level": "compact"
}
```

Tool: `query_platform_observability`.

Follow `recommended_next_sections` in the response — **one section per call**.

## 4. Common drill paths

### Slow MCP session

1. `summary`
2. `slow_operations`
3. `mcp_tool_matrix`
4. `correlated_chains` (if multi-step)

### Memory / semantic rebuild cost

1. `summary`
2. `memory_pipeline_cost`
3. `db_cost` (if SQL-heavy)

### Pipeline analysis cost

1. `summary`
2. `pipeline`
3. `costly_noops`

### One workflow across CLI + MCP + worker

1. Reproduce with shared correlation (same env-enabled processes)
2. `correlated_chains` with `window=<correlation_id>` when known

## 5. Interpretation rules (mandatory)

- Audience is **CodeClone development** — envelope says so explicitly.
- Metrics are diagnostic hints, not findings or vulnerabilities.
- Do **not** tell end users their repo is unhealthy based on observer output.
- Do **not** use observer data in `finish_controlled_change` claims or review
  receipts about repository quality.

## 6. Human full trace

MCP sections are bounded (≤50 rows). For waterfall HTML, maintainers run CLI
locally:

```bash
codeclone observability trace --root . --html /tmp/codeclone-observer.html
```

Agents should not substitute CLI output for repository analysis.

## Related

- [Maintainer workflow](../../observability/maintainer-workflow.md)
- [Tool contract](../../../book/25-mcp-interface/tools/platform-observability.md)
- [Help topic catalog](../../../book/25-mcp-interface/tools/help-and-topics.md)
