"""PlantIQ FastAPI Backend Application.

Core responsibilities:
- HTTP API endpoint definition and routing
- Middleware setup (CORS, logging, request tracking)
- Authentication gate configuration
- Graceful shutdown (LLM model unload)
"""
import logging
import os
import time
import uuid
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.pipeline import router as pipeline_router
from .api.chat import router as chat_router
from .api.websocket import router as websocket_router
from .services.llm_service import LLMService

# Runtime configuration from environment
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "true").lower() == "true"
SLOW_REQUEST_THRESHOLD_MS = float(os.getenv("SLOW_REQUEST_THRESHOLD_MS", "500"))
LOG_REDACTION_ENABLED = os.getenv("LOG_REDACTION_ENABLED", "true").lower() == "true"


def _csv_to_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _csv_to_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


# Logging path granularity: certain paths are logged at QUIET level to reduce noise
# (health checks, root endpoint), while sensitive API paths use DETAILED level.
QUIET_LOG_PATHS = _csv_to_set(os.getenv("QUIET_LOG_PATHS", "/health,/"))
DETAILED_LOG_PATH_PREFIXES = _csv_to_set(
    os.getenv("DETAILED_LOG_PATH_PREFIXES", "/api/v1/chat,/api/v1/pipeline,/api/v1/auth,/api/docs")
)

# Redaction: mask sensitive parameters in query strings before logging.
# Prevents credential leakage in audit logs (tokens, API keys, passwords).
SENSITIVE_QUERY_KEYS = {k.lower() for k in _csv_to_set(os.getenv(
    "SENSITIVE_QUERY_KEYS",
    "token,access_token,refresh_token,api_key,key,secret,password,authorization,jwt",
))}


def _redact_query_string(raw_query: str) -> str:
    if not raw_query:
        return ""
    if not LOG_REDACTION_ENABLED:
        return raw_query[:512]

    params = parse_qsl(raw_query, keep_blank_values=True)
    redacted = []
    for key, value in params:
        key_lower = key.lower()
        if key_lower in SENSITIVE_QUERY_KEYS:
            redacted.append((key, "[REDACTED]"))
        else:
            redacted.append((key, value))
    return urlencode(redacted, doseq=True)[:512]

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="PlantIQ Backend API",
    description="RAG-powered chatbot backend with document processing pipeline",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Add trace-correlated request/latency/error logging."""
    start = time.perf_counter()
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    traceparent = request.headers.get("traceparent", "")
    trace_id = traceparent.split("-")[1] if traceparent.startswith("00-") and len(traceparent.split("-")) >= 2 else request_id
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    status_code = 500
    path_template = request.url.path

    try:
        response = await call_next(request)
        status_code = response.status_code
        route = request.scope.get("route")
        if route is not None and hasattr(route, "path"):
            path_template = route.path
    except Exception:
        duration = time.perf_counter() - start
        logger.exception(
            "http_request_failed method=%s path=%s status=%s duration_ms=%.2f request_id=%s trace_id=%s client_ip=%s user_agent=%s",
            request.method,
            path_template,
            status_code,
            duration * 1000,
            request_id,
            trace_id,
            client_ip,
            user_agent,
        )
        raise

    duration = time.perf_counter() - start
    duration_ms = duration * 1000
    query_string = _redact_query_string(request.url.query)
    content_length = request.headers.get("content-length", "0")
    auth_header_present = "authorization" in request.headers
    cookie_header_present = "cookie" in request.headers
    endpoint_class = "detailed" if any(path_template.startswith(prefix) for prefix in DETAILED_LOG_PATH_PREFIXES) else "standard"
    is_quiet = path_template in QUIET_LOG_PATHS

    response.headers["x-request-id"] = request_id
    response.headers["x-trace-id"] = trace_id

    should_log_request = not (is_quiet and status_code < 400 and duration_ms < SLOW_REQUEST_THRESHOLD_MS)
    if should_log_request:
        if duration_ms >= SLOW_REQUEST_THRESHOLD_MS:
            logger.warning(
                "http_request_complete method=%s path=%s status=%s duration_ms=%.2f slow_threshold_ms=%.2f endpoint_class=%s request_id=%s trace_id=%s client_ip=%s user_agent=%s content_length=%s auth_header_present=%s cookie_header_present=%s query=%s",
                request.method,
                path_template,
                status_code,
                duration_ms,
                SLOW_REQUEST_THRESHOLD_MS,
                endpoint_class,
                request_id,
                trace_id,
                client_ip,
                user_agent,
                content_length,
                auth_header_present,
                cookie_header_present,
                query_string,
            )
        else:
            logger.info(
                "http_request_complete method=%s path=%s status=%s duration_ms=%.2f slow_threshold_ms=%.2f endpoint_class=%s request_id=%s trace_id=%s client_ip=%s user_agent=%s content_length=%s auth_header_present=%s cookie_header_present=%s query=%s",
                request.method,
                path_template,
                status_code,
                duration_ms,
                SLOW_REQUEST_THRESHOLD_MS,
                endpoint_class,
                request_id,
                trace_id,
                client_ip,
                user_agent,
                content_length,
                auth_header_present,
                cookie_header_present,
                query_string,
            )
    return response

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_csv_to_list(os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://10.1.10.181:3000,https://plantiq.sahossain.com,https://api.plantiq.sahossain.com,https://plantiqapi.sahossain.com",
    )),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
if not AUTH_DISABLED:
    from .api.auth import router as auth_router

    app.include_router(auth_router)
app.include_router(pipeline_router)
app.include_router(chat_router)
app.include_router(websocket_router)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "plantig-backend"}


@app.get("/api/v1/llm/status", tags=["LLM"])
async def llm_lifecycle_status():
    """LLM lifecycle status: container reachability, active requests, demand idle time."""
    return await LLMService.get_lifecycle_status()


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "PlantIQ Backend API",
        "version": "1.0.0",
        "docs": "/api/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
