"""FastAPI entry point for QueueStorm Investigator."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import os
import time
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from investigator import analyze_ticket


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="QueueStorm Investigator",
    version="2.0.0",
    description=(
        "Deterministic support-ticket investigation API for digital finance complaints. "
        "Includes a professional UI at / without changing the competition API contract."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


METRICS: Dict[str, Any] = {
    "started_at": time.time(),
    "total_processed": 0,
    "total_latency_ms": 0.0,
    "high_or_critical": 0,
    "by_case_type": defaultdict(int),
    "by_department": defaultdict(int),
    "by_verdict": defaultdict(int),
    "last_response": None,
}


class AnalyzeRequest(BaseModel):
    ticket_id: str = Field(..., description="Unique ticket identifier")
    complaint: str = Field(..., description="Customer complaint text")
    language: Optional[Literal["en", "bn", "mixed"]] = None
    channel: Optional[Literal["in_app_chat", "call_center", "email", "merchant_portal", "field_agent"]] = None
    user_type: Optional[Literal["customer", "merchant", "agent", "unknown"]] = None
    campaign_context: Optional[str] = None
    transaction_history: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


class AnalyzeResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str]
    evidence_verdict: Literal["consistent", "inconsistent", "insufficient_data"]
    case_type: Literal[
        "wrong_transfer",
        "payment_failed",
        "refund_request",
        "duplicate_payment",
        "merchant_settlement_delay",
        "agent_cash_in_issue",
        "phishing_or_social_engineering",
        "other",
    ]
    severity: Literal["low", "medium", "high", "critical"]
    department: Literal[
        "customer_support",
        "dispute_resolution",
        "payments_ops",
        "merchant_operations",
        "agent_operations",
        "fraud_risk",
    ]
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    reason_codes: Optional[List[str]] = None


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Professional UI landing page. Does not affect judge API endpoints."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return FileResponse(BASE_DIR / "README.md")


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> RedirectResponse:
    return RedirectResponse(url="/")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> Dict[str, Any]:
    return {
        "service": "QueueStorm Investigator",
        "version": app.version,
        "hidden_case_hardening": "campaign_metadata_channel_mixed_language_quality_safety_audit",
        "api_contract": "SUST QueueStorm Preliminary",
        "core_engine": "deterministic_rule_based",
        "ui": "professional_dashboard",
    }


@app.get("/metrics")
def metrics() -> Dict[str, Any]:
    total = int(METRICS["total_processed"])
    avg = round(float(METRICS["total_latency_ms"]) / total, 2) if total else 0
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - float(METRICS["started_at"]), 2),
        "total_processed": total,
        "avg_latency_ms": avg,
        "high_or_critical": int(METRICS["high_or_critical"]),
        "by_case_type": dict(METRICS["by_case_type"]),
        "by_department": dict(METRICS["by_department"]),
        "by_verdict": dict(METRICS["by_verdict"]),
        "last_response": METRICS["last_response"],
    }


@app.post("/analyze-ticket", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> Dict[str, Any]:
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    start = time.perf_counter()
    try:
        result = analyze_ticket(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        # Non-sensitive error. Never expose stack traces or secrets.
        raise HTTPException(status_code=500, detail="Internal analysis error")

    elapsed_ms = (time.perf_counter() - start) * 1000
    _record_metrics(result, elapsed_ms)
    _audit_decision(payload, result, elapsed_ms)
    # Important: return ONLY the competition response shape from analyze_ticket.
    # Do not add latency or UI-only fields here.
    return result


@app.post("/analyze-ticket/batch")
def analyze_batch(items: list[AnalyzeRequest]) -> Dict[str, Any]:
    """Optional helper for demos; the official judge endpoint remains /analyze-ticket."""
    results = []
    started = time.perf_counter()
    for item in items:
        payload = item.model_dump() if hasattr(item, "model_dump") else item.dict()
        item_start = time.perf_counter()
        result = analyze_ticket(payload)
        _record_metrics(result, (time.perf_counter() - item_start) * 1000)
        results.append(result)
    return {
        "count": len(results),
        "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
        "results": results,
    }


def _audit_decision(payload: Dict[str, Any], result: Dict[str, Any], elapsed_ms: float) -> None:
    """Best-effort structured audit log for fintech-style traceability.

    It never affects the API response. If the environment is read-only, logging is
    silently skipped so the judge harness is not impacted.
    """
    try:
        log_path = Path(os.getenv("AUDIT_LOG_PATH", str(BASE_DIR / "logs" / "audit_log.jsonl")))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": round(time.time(), 3),
            "ticket_id": result.get("ticket_id"),
            "case_type": result.get("case_type"),
            "department": result.get("department"),
            "evidence_verdict": result.get("evidence_verdict"),
            "severity": result.get("severity"),
            "human_review_required": result.get("human_review_required"),
            "confidence": result.get("confidence"),
            "reason_codes": result.get("reason_codes", []),
            "channel": payload.get("channel"),
            "user_type": payload.get("user_type"),
            "campaign_context": payload.get("campaign_context"),
            "latency_ms": round(elapsed_ms, 2),
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _record_metrics(result: Dict[str, Any], elapsed_ms: float) -> None:
    METRICS["total_processed"] += 1
    METRICS["total_latency_ms"] += elapsed_ms
    case_type = str(result.get("case_type") or "unknown")
    department = str(result.get("department") or "unknown")
    verdict = str(result.get("evidence_verdict") or "unknown")
    severity = str(result.get("severity") or "").lower()
    METRICS["by_case_type"][case_type] += 1
    METRICS["by_department"][department] += 1
    METRICS["by_verdict"][verdict] += 1
    if severity in {"high", "critical"}:
        METRICS["high_or_critical"] += 1
    METRICS["last_response"] = {
        "ticket_id": result.get("ticket_id"),
        "case_type": result.get("case_type"),
        "department": result.get("department"),
        "evidence_verdict": result.get("evidence_verdict"),
        "severity": result.get("severity"),
        "latency_ms": round(elapsed_ms, 2),
    }


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):  # pragma: no cover
    # Malformed JSON or missing required schema fields. Keep the message non-sensitive.
    return JSONResponse(status_code=400, content={"detail": "Malformed input or missing required fields"})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):  # pragma: no cover
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
