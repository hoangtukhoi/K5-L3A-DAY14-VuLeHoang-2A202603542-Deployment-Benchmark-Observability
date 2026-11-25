"""
Production AI Agent — Part 6 Final Project.

Chạy: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
Kiểm tra: python check_production_ready.py
"""
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging: mỗi dòng log là 1 JSON object ──
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        entry.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("agent")
    log.handlers = [handler]
    log.setLevel(settings.log_level)
    log.propagate = False
    return log


logger = _setup_logging()


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"extra_fields": fields})


# ── Lifecycle / graceful shutdown ──
# uvicorn tự bắt SIGTERM: ngừng nhận request mới, chờ request đang chạy xong,
# rồi chạy phần sau `yield` của lifespan và thoát với exit code 0.
STATE = {"ready": False, "in_flight": 0}


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE["ready"] = True
    log_event("startup", environment=settings.environment, port=settings.port,
              redis_ok=redis_healthy())
    yield
    STATE["ready"] = False
    log_event("shutdown", in_flight=STATE["in_flight"])


app = FastAPI(title="Production AI Agent", lifespan=lifespan,
              docs_url=None if settings.environment == "production" else "/docs")


@app.middleware("http")
async def request_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    STATE["in_flight"] += 1
    try:
        response = await call_next(request)
    except Exception:
        log_event("unhandled_error", logging.ERROR, path=request.url.path, request_id=request_id)
        response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    finally:
        STATE["in_flight"] -= 1
    response.headers["X-Request-ID"] = request_id
    log_event("request", method=request.method, path=request.url.path,
              status=response.status_code, ms=round((time.perf_counter() - start) * 1000, 1),
              request_id=request_id)
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    # Trả lỗi rõ ràng, không lộ stack trace / input nội bộ
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": "Invalid request body", "errors": errors})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/")
def root():
    return {"service": "production-ai-agent", "endpoints": ["/health", "/ready", "POST /ask"]}


@app.get("/health")
def health():
    """Liveness: process còn sống → 200, không phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: chỉ nhận traffic khi Redis kết nối được."""
    if not STATE["ready"]:
        raise HTTPException(status_code=503, detail="shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="redis unavailable")
    return {"status": "ready"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)

    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    log_event("llm_call", input_tokens=input_tokens, output_tokens=output_tokens,
              cost_usd=round(cost, 8), user_id=body.user_id)
    return {"question": body.question, "answer": answer,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cost_usd": round(cost, 8)}}
