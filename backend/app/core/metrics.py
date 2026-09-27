"""Prometheus metric definitions.

These live in their own module rather than in `routes/health.py` because two
different layers need them: the HTTP middleware in `main.py` counts requests,
and `services/triage.py` records triage latency and fallbacks. Importing the
counters from a route module would invert the dependency arrow -- services/ must
not depend on routes/ -- which is one of the four-layer rules the assignment
sets out.

Names and label sets are part of the observability contract, so they are
declared once, here, and never re-declared elsewhere.
"""

from prometheus_client import Counter, Histogram

# Buckets bracket the triage path: RuleBasedTriage returns in single-digit
# milliseconds, a 1B model on CPU takes seconds, and the provider layer caps
# calls at 10s. The prometheus default Histogram bucket set stops at 10s, which
# would drop every slow model call into +Inf and make the histogram useless for
# the question it exists to answer.
TRIAGE_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests handled, by method, route template and response status.",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route template.",
    ["method", "endpoint"],
    buckets=TRIAGE_BUCKETS,
)

TRIAGE_LATENCY = Histogram(
    "triage_duration_seconds",
    "End-to-end triage latency in seconds, including cache lookup and any fallback.",
    buckets=TRIAGE_BUCKETS,
)

FALLBACK_COUNTER = Counter(
    "triage_fallback_total",
    "Number of times a triage provider failed and the rules fallback was used.",
    ["provider"],
)

TRIAGE_COUNT = Counter(
    "triage_total",
    "Triage operations by outcome, so a content-cache hit is distinguishable from real inference.",
    ["provider", "outcome"],
)


def record_triage(provider: str, latency_seconds: float, *, fallback: bool, cached: bool) -> None:
    """Record one triage outcome against every metric that describes it.

    Called from the triage service, the only layer that knows whether a result
    came from the model, from the content-hash cache, or from the rules
    fallback.
    """
    TRIAGE_LATENCY.observe(latency_seconds)
    TRIAGE_COUNT.labels(provider, "cached" if cached else "live").inc()
    if fallback:
        FALLBACK_COUNTER.labels(provider).inc()
