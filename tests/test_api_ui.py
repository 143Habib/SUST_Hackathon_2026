from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_root_ui_loads():
    res = client.get("/")
    assert res.status_code == 200
    assert "QueueStorm Investigator" in res.text
    assert "Live Ticket Analyzer" in res.text


def test_analyze_schema_unchanged():
    payload = {
        "ticket_id": "TKT-UI-SCHEMA",
        "complaint": "I sent 5000 taka to the wrong number around 2pm.",
        "transaction_history": [
            {
                "transaction_id": "TXN-UI-1",
                "timestamp": "2026-04-14T14:08:22Z",
                "type": "transfer",
                "amount": 5000,
                "counterparty": "+8801719876543",
                "status": "completed",
            }
        ],
    }
    res = client.post("/analyze-ticket", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert set(data.keys()) == {
        "ticket_id",
        "relevant_transaction_id",
        "evidence_verdict",
        "case_type",
        "severity",
        "department",
        "agent_summary",
        "recommended_next_action",
        "customer_reply",
        "human_review_required",
        "confidence",
        "reason_codes",
    }
    assert data["relevant_transaction_id"] == "TXN-UI-1"
