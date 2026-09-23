from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "returnflow_http_requests_total",
    "Total HTTP requests",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "returnflow_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
)
EXTRACTION_LATENCY = Histogram(
    "returnflow_extraction_duration_seconds",
    "Fact extraction latency",
    ["provider"],
)
DECISIONS = Counter(
    "returnflow_decisions_total",
    "Return decisions",
    ["decision", "reason_code"],
)
