"""
Main Gateway Application

FastAPI server that exposes:
    /v1/plan        - Context extraction + trust scoring
    /health         - Health check
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from plan import router as plan_router
from trace_store import init_db, save_trace

# Initialize
init_db()

app = FastAPI(
    title="CognOS Session Memory",
    description="Verified context injection via epistemic trust scoring",
    version="0.1.0",
)


# ── Middleware ─────────────────────────────────────────────────────────────────


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """Log all requests as traces for context extraction."""
    trace_id = str(uuid.uuid4())
    start = datetime.now(timezone.utc)

    try:
        response = await call_next(request)
        duration = (datetime.now(timezone.utc) - start).total_seconds()

        # Log trace
        save_trace({
            "trace_id": trace_id,
            "created_at": start.isoformat(),
            "decision": "PASS",  # placeholder
            "policy": request.url.path,
            "trust_score": 0.8,  # placeholder
            "risk": 0.2,
            "is_stream": False,
            "status_code": response.status_code,
            "model": request.headers.get("User-Agent", "unknown"),
            "metadata": {
                "duration_seconds": duration,
                "endpoint": request.url.path,
            },
        })

        response.headers["X-Trace-ID"] = trace_id
        return response

    except Exception as e:
        # Log error trace
        save_trace({
            "trace_id": trace_id,
            "created_at": start.isoformat(),
            "decision": "ESCALATE",
            "policy": request.url.path,
            "trust_score": 0.0,
            "risk": 1.0,
            "is_stream": False,
            "status_code": 500,
            "model": request.headers.get("User-Agent", "unknown"),
            "metadata": {
                "error": str(e),
                "endpoint": request.url.path,
            },
        })
        raise


# ── Routes ─────────────────────────────────────────────────────────────────────


app.include_router(plan_router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "cognos-session-memory",
        "version": "0.1.0",
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "CognOS Session Memory Gateway",
        "endpoints": [
            "/health",
            "/v1/plan",
            "/docs",
        ],
    }


# ── Error Handlers ────────────────────────────────────────────────────────────


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8788,
        log_level="info",
    )
