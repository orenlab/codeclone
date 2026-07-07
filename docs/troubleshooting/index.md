---
title: "Troubleshooting"
audience: public
doc_type: troubleshooting
status: draft
source_commit: "d88c17f0f19cf753b9d43870528e0747b3161b9c"
---

# Troubleshooting

## How to use this section

CodeClone is a deterministic structural controller for Python repositories. When analysis produces unexpected results, findings, or errors, this guide helps you diagnose the issue.

Each subsection below describes a symptom, what it might indicate, and the next steps to resolve it. Review the symptom that matches your situation, then follow the troubleshooting path.

Most issues fall into one of these categories:

- **Analysis configuration**: thresholds, scope, or input settings
- **Repository state**: cache, baseline, or file changes
- **Dependency or environment**: Python version, package versions, or system resources

## Common symptoms

| Symptom | Likely cause | Next step |
|---------|--------------|-----------|
| Analysis runs but finds many unexpected issues | Thresholds set too low or baseline is stale | Review `DEFAULT_COMPLEXITY_THRESHOLD`, `DEFAULT_COUPLING_THRESHOLD`, `DEFAULT_COHESION_THRESHOLD` in your configuration. Compare your baseline against the current repository state. |
| Report or cache files are missing or corrupted | Cache version mismatch or incomplete analysis run | Check `.codeclone/` directory. Clear `.codeclone/` and re-run analysis. Verify cache version matches `CACHE_VERSION` contract. |
| Analysis hangs or times out | Large repository or resource constraints | Check available disk space and memory. Reduce `DEFAULT_PROCESSES` if system is constrained. Verify no circular dependencies are blocking traversal. |
| Baseline size exceeds limits | Repository growth or overly broad baseline scope | Check baseline file size against `DEFAULT_MAX_BASELINE_SIZE_MB`. If exceeded, re-baseline with narrower scope or larger limit if intentional. |
| Findings disappear between runs | Cache invalidation or configuration drift | Verify configuration settings are consistent. Re-run with fresh cache to confirm findings are reproducible. |
| File paths in reports are incorrect or relative | Working directory or root path mismatch | Ensure you pass an absolute root path to analysis. Check current working directory when running CodeClone. |
| Health score calculation seems wrong | Metric weights or dependency calculation | Review `HEALTH_WEIGHTS` for each metric (clones, cohesion, complexity, coupling, coverage, dead_code, dependencies). Verify dependency depth is calculated correctly. |
| Git integration is not working | Repository state or intent workspace issues | Confirm you are in a valid Git repository. Check that no stale intents are blocking operations. Use change control tools to inspect intent state. |

## Where to look next

After identifying your symptom, follow these paths:

**For configuration issues:**
- Review the defaults in your CodeClone configuration or `pyproject.toml`.
- Compare thresholds against your project's code volume and complexity.
- Re-run analysis with explicit threshold arguments to test different settings.

**For baseline or cache issues:**
- Remove `.codeclone/` directory completely.
- Run a fresh analysis to regenerate baseline and cache.
- Compare the new baseline against previous versions if available.

**For analysis or finding validation:**
- Inspect the JSON or Markdown report in `.codeclone/report.*`.
- Use targeted checks (clones, dead code, coupling, cohesion, complexity) instead of full analysis.
- Review specific findings with detailed context before acting on them.

**For performance issues:**
- Measure analysis time with and without cache enabled.
- Reduce the number of processes if system resources are constrained.
- Check for circular dependency chains that may cause deep traversal.

**For engineering memory or change control:**
- Review Engineering Memory records related to your scope or recent changes.
- Check active intents if you are using change control workflows.
- Validate patch contracts before and after edits.

**Additional resources:**
- See [Development guide](../guides/development.md) for setup and environment details.
- Review [Engineering Memory](../concepts/engineering-memory.md) for how CodeClone stores and uses context.
- Check the [Example report](../examples/report.md) for interpreting analysis output.

If you encounter issues not covered here, report them at: https://github.com/orenlab/codeclone/issues
