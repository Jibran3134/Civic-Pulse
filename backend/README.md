# CivicPulse Backend

FastAPI-based municipal complaint intake, triage, and operations platform.

## Architecture

- **Framework**: FastAPI + Pydantic v2
- **Database**: PostgreSQL 16 + Alembic migrations
- **Cache/Rate Limit**: Redis 7
- **AI Providers**: Groq (primary), Ollama (offline), Rules (fallback), Simulated (CI)
- **Container**: Multi-stage Docker, non-root user

## Structure

```
app/
├── core/           # Config, logging, database, dependencies
├── routes/         # HTTP endpoints
├── services/       # Business logic (triage, status machine)
├── repositories/   # SQL data access
└── providers/      # External integrations (cache, AI, rate limiter)
```

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest --cov=app --cov-fail-under=65

# Lint & typecheck
ruff check .
mypy app/

# Run migrations
alembic upgrade head

# Seed database
python scripts/seed.py
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql://postgres:postgres@localhost:5432/civicpulse` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `GROQ_API_KEY` | Groq API key | (required for production) |
| `TRIAGE_PROVIDER` | Provider selection | `simulated` |
| `RATE_LIMIT_REQUESTS` | Requests per window | `10` |
| `RATE_LIMIT_WINDOW` | Window in seconds | `60` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/ready` | Readiness probe |
| `GET` | `/metrics` | Prometheus metrics |
| `POST` | `/api/complaints` | Submit complaint |
| `GET` | `/api/complaints` | List complaints |
| `GET` | `/api/complaints/{id}` | Get complaint |
| `PATCH` | `/api/complaints/{id}/status` | Update status |
| `GET` | `/api/stats` | Aggregated statistics |
| `GET` | `/api/meta/providers` | Provider info & outcomes |

## Docker

```bash
# Build
docker build -t civicpulse-backend .

# Run
docker run -p 8000:8000 civicpulse-backend
```

## License

MIT