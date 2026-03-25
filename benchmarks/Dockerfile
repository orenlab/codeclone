# syntax=docker/dockerfile:1.7

FROM python:3.13.2-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    TZ=UTC \
    CODECLONE_BENCH_ROOT=/opt/codeclone \
    CODECLONE_BENCH_OUTPUT=/bench-out/codeclone-benchmark.json \
    CODECLONE_BENCH_RUNS=12 \
    CODECLONE_BENCH_WARMUPS=3

WORKDIR /opt/codeclone

COPY . /opt/codeclone

RUN python -m pip install --upgrade pip \
    && python -m pip install .

RUN useradd --create-home --uid 10001 bench \
    && mkdir -p /bench-out \
    && chown -R bench:bench /bench-out /opt/codeclone

USER bench

ENTRYPOINT ["python", "/opt/codeclone/benchmarks/run_benchmark.py"]
