#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="${IMAGE_TAG:-codeclone-benchmark:2.0.0b1}"
OUT_DIR="${OUT_DIR:-$ROOT_DIR/.cache/benchmarks}"
OUTPUT_BASENAME="${OUTPUT_BASENAME:-codeclone-benchmark.json}"
CPUSET="${CPUSET:-0}"
CPUS="${CPUS:-1.0}"
MEMORY="${MEMORY:-2g}"
RUNS="${RUNS:-12}"
WARMUPS="${WARMUPS:-3}"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
CONTAINER_USER="${CONTAINER_USER:-${HOST_UID}:${HOST_GID}}"

mkdir -p "$OUT_DIR"

echo "[bench] building image: $IMAGE_TAG"
docker build \
  --pull \
  --file "$ROOT_DIR/benchmarks/Dockerfile" \
  --tag "$IMAGE_TAG" \
  "$ROOT_DIR"

echo "[bench] running benchmark container"
docker run \
  --rm \
  --user "$CONTAINER_USER" \
  --cpuset-cpus="$CPUSET" \
  --cpus="$CPUS" \
  --memory="$MEMORY" \
  --pids-limit=256 \
  --network=none \
  --security-opt=no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=2g \
  --tmpfs /home/bench:rw,noexec,nosuid,size=128m \
  --mount "type=bind,src=$OUT_DIR,dst=/bench-out" \
  "$IMAGE_TAG" \
  --output "/bench-out/$OUTPUT_BASENAME" \
  --runs "$RUNS" \
  --warmups "$WARMUPS" \
  "$@"

echo "[bench] results: $OUT_DIR/$OUTPUT_BASENAME"
