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
COPY --from=builder --chown=appuser:appuser /app/alembic.ini ./alembic.ini
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml ./pyproject.toml

# Switch to non-root user
USER appuser

# Health check
# NOTE: httpx must be a base (non-dev) dependency in pyproject.toml for this
# to work now that [dev] extras are no longer installed in this image.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=2)" || exit 1

# Expose port
EXPOSE 8000

# Run with gunicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]