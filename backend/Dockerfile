# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only the dependency manifest first. This is the cache-friendly order
# the assignment asks for: changing application code below must NOT force a
# full dependency reinstall, since this layer only invalidates when
# pyproject.toml itself changes.
COPY pyproject.toml .

# pyproject.toml declares `[tool.setuptools] packages = ["app", "alembic"]`,
# so `pip install -e .` needs those two directories to exist on disk to
# validate the package layout — even though it's an editable install and
# won't actually copy their contents anywhere. Create empty placeholders
# now so the dependency layer above can stay cached independently of source
# changes; the real files land a few lines down and simply overwrite these.
RUN mkdir -p app alembic && touch app/__init__.py

# Install Python dependencies (upgrade setuptools first to patch CVE-2025-47273).
# NOTE: production image installs base deps only, not the [dev] extras
# (pytest, ruff, mypy). Those are installed separately in CI
# (.github/workflows/ci.yml) on the runner directly and have no reason to
# ship inside the image we actually deploy.
RUN pip install --no-cache-dir --upgrade "pip" "setuptools>=78.1.1" && \
    pip install --no-cache-dir -e .

# Now copy the real source, overwriting the placeholders above. Because the
# install was editable, pip just points back at this same /app directory —
# nothing needs reinstalling once the real files land. Source changes here
# no longer bust the cached dependency layer above.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY scripts/ ./scripts/
COPY alembic.ini .

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Runtime stage
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Remove pip to eliminate vulnerabilities in pip's vendored packages (msgpack, setuptools)
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip \
    /usr/local/lib/python3.12/site-packages/pip-* \
    /usr/local/bin/pip \
    /usr/local/bin/pip3 \
    /usr/local/bin/pip3.12

# Copy application code
COPY --from=builder --chown=appuser:appuser /app/app ./app
COPY --from=builder --chown=appuser:appuser /app/alembic ./alembic
# scripts/ carries the operational entrypoints (seed.py). Without it in the
# image, `python scripts/seed.py` only works where a bind mount happens to
# supply the source -- so it passes in dev compose and fails in
# compose.prod.yaml and on Kubernetes, which run the image as built. An image
# that cannot seed itself is not the artifact CI scanned and pushed.
COPY --from=builder --chown=appuser:appuser /app/scripts ./scripts
COPY --from=builder --chown=appuser:appuser /app/alembic.ini ./alembic.ini
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml ./pyproject.toml

# Switch to non-root user
USER appuser

# Health check. Hits /health, the liveness endpoint, which never touches
# Postgres or Redis: a healthcheck that failed on a slow database would restart
# a perfectly healthy container and, through `depends_on: service_healthy`,
# cascade the failure across the stack.
# Uses urllib from the standard library, so the image does not have to carry
# httpx for the sole purpose of a probe.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"

# Expose port
EXPOSE 8000

# Exec form, no shell, so the container receives SIGTERM directly and uvicorn's
# own graceful-shutdown path runs: it stops the listener, waits for in-flight
# requests to drain, and only then runs the lifespan teardown that closes the
# psycopg pool and the Redis client. (Registering a competing signal handler
# from the lifespan is what previously turned this into a SIGKILL; see
# app/main.py.)
#
# --proxy-headers / --forwarded-allow-ips are REQUIRED for correctness behind
# the Ingress, not an optimisation. Without them uvicorn ignores
# X-Forwarded-For, so request.client.host is the Ingress controller's pod IP --
# and the rate limiter keys on the client IP, which would put every user on the
# internet into one shared token bucket and let a single caller lock everyone
# else out. 127.0.0.1 is the only hop we trust to set that header.
#
# ONE worker on purpose. Horizontal scaling here is the HPA's job
# (minReplicas 2 -> maxReplicas 10), and that only works if each pod is one
# measurable unit of CPU. Against multiple workers per pod:
#   1. Prometheus counters live in process memory, so a POST handled by worker
#      B increments B while a scrape lands on worker A -- /metrics would report
#      roughly half the traffic and zero for half the series. Fixing that
#      properly needs prometheus_client's multiprocess mode and a shared
#      PROMETHEUS_MULTIPROC_DIR.
#   2. The HPA divides usage by requests.cpu. Splitting a pod across N
#      processes makes per-process CPU a fraction of the pod total, so the
#      utilisation the HPA sees understates real pressure and it reacts late.
# Concurrency inside the pod is the async loop's job; capacity above that is
# adding pods.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "127.0.0.1"]
