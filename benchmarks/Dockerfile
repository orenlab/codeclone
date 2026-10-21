# syntax=docker/dockerfile:1.7

FROM python:3.14.5-slim-bookworm

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

# The base image's pip vendors a CA bundle that still trusts the eMudhra chains
# revoked in October 2026, and so does its Debian ca-certificates, which pip
# adds through truststore. pip 26.2.2 therefore arrives checksum-pinned, is
# installed from that file, and installs CodeClone trusting only its own
# vendored certifi (legacy-certs).
ADD --checksum=sha256:fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70 \
    https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl \
    /tmp/pip-26.2.2-py3-none-any.whl

COPY . /opt/codeclone

RUN python -m pip install --no-index --no-deps /tmp/pip-26.2.2-py3-none-any.whl \
    && PIP_USE_DEPRECATED=legacy-certs python -m pip install .

RUN useradd --create-home --uid 10001 bench \
    && mkdir -p /bench-out \
    && chown -R bench:bench /bench-out /opt/codeclone

USER bench

ENTRYPOINT ["python", "/opt/codeclone/benchmarks/run_benchmark.py"]
