<!-- doc-scope: REPRODUCIBLE DOCKER BENCHMARKING.
     owns: benchmark methodology, Docker setup, reproduction guarantees.
     does-not-own: determinism policy (→ 22), versioning (→ 24). -->

# 20. Benchmarking (Docker)

## Purpose

Define a reproducible, deterministic benchmark workflow for CodeClone in Docker.

## Public surface

- Benchmark image: `benchmarks/Dockerfile`
- Benchmark runner (inside container): `benchmarks/run_benchmark.py`
- Host wrapper script: `benchmarks/run_docker_benchmark.sh`

## Data model

Benchmark output (`benchmark_schema_version=1.1`) contains:

- tool metadata (`name`, `version`, `python_tag`)
- benchmark config (`target`, `runs`, `warmups`, `scenario_profile`,
  `startup_runs`)
- execution environment (platform, cpu limits/affinity, cgroup limits)
- startup/import probes that isolate new-process cost from analysis cost:
    - `python_empty`
    - `import_codeclone`
    - `import_codeclone_main`
    - `cli_version`
- scenario results:
    - `cold_full` (cold cache each run)
    - `warm_full` (shared warm cache)
    - `warm_clones_only` (shared warm cache with `--skip-metrics`)
    - extended profile only: `cold_html`, `warm_html`, `cold_all_reports`,
      `warm_all_reports`
    - diagnostic profile only: `ci_cold_diagnostic`
- latency stats per scenario and probe (`min`, `max`, `mean`, `median`, `p95`, `stdev`)
- child process CPU stats per scenario/probe (`child_user_stats_seconds`,
  `child_system_stats_seconds`, `child_cpu_stats_seconds`)
- per-scenario inventory and artifact samples (`inventory_sample`,
  `artifact_bytes_sample`, `cache_bytes_sample`, `exit_code_counts`)
- deterministic digest check (`integrity.digest.value` must be stable within scenario)
- cross-scenario comparisons (speedup ratios)

Scenario profiles:

| Profile      | Purpose                                                                 | Default in CI |
|--------------|-------------------------------------------------------------------------|---------------|
| `smoke`      | Historical core scenarios only; bounded push/PR signal.                 | yes           |
| `extended`   | Adds HTML/all-report scenarios with per-scenario run caps.              | manual only   |
| `diagnostic` | Adds `ci_cold_diagnostic`, where exit `0`, `2`, or `3` is recorded.     | no            |

## Contracts

- Benchmark must run in containerized, isolated environment.
- CPU/memory limits are pinned at container run time (`--cpuset-cpus`, `--cpus`,
  `--memory`).
- Runtime environment is normalized:
  `PYTHONHASHSEED=0`, `TZ=UTC`, `LC_ALL/LANG=C.UTF-8`.
- Each measured run must exit successfully (`exit=0`); any failure aborts the benchmark.
  The `diagnostic` profile is the only exception: `ci_cold_diagnostic` records
  `0`, `2`, or `3` so gate-failure timing can be measured without treating the
  benchmark sample as a product failure.
- Determinism guard: if scenario digest diverges across measured runs, benchmark fails.
- Extended report scenarios are intentionally capped below global `runs`/`warmups`
  so GitHub-hosted workers do not pay unbounded cold-report CPU.

## Invariants (MUST)

- Cold scenario uses a fixed cache path and removes cache file before each run
  (cold cache with stable canonical metadata path).
- Warm scenarios seed one shared cache file before warmups/measured runs.
- Startup/import probes run as fresh Python subprocesses and do not read report
  output; they are for process/bootstrap/import cost only.
- Core smoke scenarios remain gate-neutral by passing explicit no-fail flags.
- Benchmark JSON write is atomic (`.tmp` + replace).
- Benchmark scenario ordering is stable and fixed.

## Failure modes

| Condition                               | Behavior                                      |
|-----------------------------------------|-----------------------------------------------|
| Docker unavailable                      | Host wrapper fails fast                       |
| Non-zero CLI exit in any run            | Runner aborts with command stdout/stderr tail |
| Missing/invalid report integrity digest | Runner aborts as invalid benchmark sample     |
| Digest mismatch in one scenario         | Runner aborts as non-deterministic            |

## Determinism / canonicalization

- Per-run determinism uses canonical report digest:
  `report.integrity.digest.value`.
- Digest intentionally ignores runtime timestamp (`meta.runtime`) in canonical payload,
  so deterministic check remains valid.
- Output JSON is serialized with stable formatting (`indent=2`) and written atomically.

Refs:

- `codeclone/report/document/integrity.py:_build_integrity_payload`
- `benchmarks/run_benchmark.py`

## Recommended run profile

```bash
./benchmarks/run_docker_benchmark.sh
```

Useful overrides:

```bash
CPUSET=0 CPUS=1.0 MEMORY=2g RUNS=16 WARMUPS=4 \
  ./benchmarks/run_docker_benchmark.sh
```

Extended report-profile run:

```bash
SCENARIO_PROFILE=extended RUNS=16 WARMUPS=4 STARTUP_RUNS=3 \
  ./benchmarks/run_docker_benchmark.sh
```

Local diagnostic run that also measures the CI-gate timing path:

```bash
uv run python benchmarks/run_benchmark.py \
  --target . \
  --scenario-profile diagnostic \
  --runs 3 \
  --warmups 1 \
  --output /tmp/codeclone-benchmark-diagnostic.json
```

Permissions note:

- The host wrapper runs the container as host `uid:gid` by default
  (`--user "$(id -u):$(id -g)"`) so benchmark artifact writes to bind-mounted
  output paths are stable in CI.
- Override explicitly if needed: `CONTAINER_USER=10001:10001`.

## GitHub Actions

- Workflow: `.github/workflows/benchmark.yml`
- Triggers:
    - `push` on all branches
    - `pull_request` (all targets)
    - manual (`workflow_dispatch`) with profile choice (`smoke` / `extended`)
- Job behavior:
    - runs Docker benchmark with pinned runner limits
    - uploads `.cache/benchmarks/codeclone-benchmark.json` as artifact
    - emits startup/import probe, scenario, and ratio tables into
      `GITHUB_STEP_SUMMARY`
    - prints ratios in job logs (important for quick trend checks)

## Non-guarantees

- Cross-host absolute timings are not comparable by contract.
- Throughput numbers can vary with host kernel, thermal state, and background load.

## See also

- [22-determinism.md](22-determinism.md)
- [24-compatibility-and-versioning.md](24-compatibility-and-versioning.md)
- [16-metrics-and-quality-gates.md](16-metrics-and-quality-gates.md)
