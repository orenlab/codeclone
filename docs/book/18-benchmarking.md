# 18. Benchmarking (Docker)

## Purpose

Define a reproducible, deterministic benchmark workflow for CodeClone in Docker.

## Public surface

- Benchmark image: `benchmarks/Dockerfile`
- Benchmark runner (inside container): `benchmarks/run_benchmark.py`
- Host wrapper script: `benchmarks/run_docker_benchmark.sh`

## Data model

Benchmark output (`benchmark_schema_version=1.0`) contains:

- tool metadata (`name`, `version`, `python_tag`)
- benchmark config (`target`, `runs`, `warmups`)
- execution environment (platform, cpu limits/affinity, cgroup limits)
- scenario results:
  - `cold_full` (cold cache each run)
  - `warm_full` (shared warm cache)
  - `warm_clones_only` (shared warm cache with `--skip-metrics`)
- latency stats per scenario (`min`, `max`, `mean`, `median`, `p95`, `stdev`)
- deterministic digest check (`integrity.digest.value` must be stable within scenario)
- cross-scenario comparisons (speedup ratios)

## Contracts

- Benchmark must run in containerized, isolated environment.
- CPU/memory limits are pinned at container run time (`--cpuset-cpus`, `--cpus`,
  `--memory`).
- Runtime environment is normalized:
  `PYTHONHASHSEED=0`, `TZ=UTC`, `LC_ALL/LANG=C.UTF-8`.
- Each measured run must exit successfully (`exit=0`); any failure aborts the benchmark.
- Determinism guard: if scenario digest diverges across measured runs, benchmark fails.

## Invariants (MUST)

- Cold scenario uses a fixed cache path and removes cache file before each run
  (cold cache with stable canonical metadata path).
- Warm scenarios seed one shared cache file before warmups/measured runs.
- Benchmark JSON write is atomic (`.tmp` + replace).
- Benchmark scenario ordering is stable and fixed.

## Failure modes

| Condition                              | Behavior                                      |
|----------------------------------------|-----------------------------------------------|
| Docker unavailable                     | Host wrapper fails fast                       |
| Non-zero CLI exit in any run           | Runner aborts with command stdout/stderr tail |
| Missing/invalid report integrity digest | Runner aborts as invalid benchmark sample     |
| Digest mismatch in one scenario        | Runner aborts as non-deterministic            |

## Determinism / canonicalization

- Per-run determinism uses canonical report digest:
  `report.integrity.digest.value`.
- Digest intentionally ignores runtime timestamp (`meta.runtime`) in canonical payload,
  so deterministic check remains valid.
- Output JSON is serialized with stable formatting (`indent=2`) and written atomically.

Refs:

- `codeclone/report/json_contract.py:_build_integrity_payload`
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

## GitHub Actions

- Workflow: `.github/workflows/benchmark.yml`
- Triggers:
  - manual (`workflow_dispatch`)
  - pull requests targeting `feat/2.0.0`
- Job behavior:
  - runs Docker benchmark with pinned runner limits
  - uploads `.cache/benchmarks/codeclone-benchmark.json` as artifact
  - emits scenario table and ratio table into `GITHUB_STEP_SUMMARY`
  - prints ratios in job logs (important for quick trend checks)

## Non-guarantees

- Cross-host absolute timings are not comparable by contract.
- Throughput numbers can vary with host kernel, thermal state, and background load.

## See also

- [12-determinism.md](12-determinism.md)
- [14-compatibility-and-versioning.md](14-compatibility-and-versioning.md)
- [15-metrics-and-quality-gates.md](15-metrics-and-quality-gates.md)
