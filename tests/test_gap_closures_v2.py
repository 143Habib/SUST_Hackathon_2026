from __future__ import annotations

from fastapi.testclient import TestClient

from investigator import analyze_ticket
from main import app

client = TestClient(app)


def tx(txid, typ, amount, status, cp="CP-1", ts="2026-04-14T14:00:00Z"):
    return {
        "transaction_id": txid,
        "timestamp": ts,
        "type": typ,
        "amount": amount,
        "counterparty": cp,
        "status": status,
    }


def test_campaign_context_is_used_in_reason_codes():
    out = analyze_ticket({
        "ticket_id": "TKT-CAMPAIGN",
        "complaint": "I paid 700 taka recharge but payment failed and balance was deducted",
        "campaign_context": "boishakh_bonanza_day_1",
        "transaction_history": [tx("TXN-CAMP", "payment", 700, "failed", "MOBILE")],
    })
    assert out["case_type"] == "payment_failed"
    assert "campaign_context_considered" in out["reason_codes"]


def test_metadata_can_escalate_suspicious_device():
    out = analyze_ticket({
        "ticket_id": "TKT-META",
        "complaint": "I want refund for 400 taka payment",
        "metadata": {"suspicious_device": True, "is_premium_user": True},
        "transaction_history": [tx("TXN-META", "payment", 400, "completed", "MERCHANT-1")],
    })
    assert out["severity"] in {"high", "critical"}
    assert out["human_review_required"] is True
    assert "metadata_suspicious_device" in out["reason_codes"]
    assert "premium_user" in out["reason_codes"]


def test_channel_field_agent_can_route_agent_issue():
    out = analyze_ticket({
        "ticket_id": "TKT-CHANNEL",
        "complaint": "customer cash in balance not reflected",
        "channel": "field_agent",
        "user_type": "agent",
        "transaction_history": [tx("TXN-AG", "cash_in", 1200, "pending", "AGENT-9")],
    })
    assert out["case_type"] == "agent_cash_in_issue"
    assert out["department"] == "agent_operations"
    assert "channel_field_agent" in out["reason_codes"]


def test_mixed_language_reply_is_bilingual_safe():
    out = analyze_ticket({
        "ticket_id": "TKT-MIXED",
        "complaint": "ami 500 taka niye problem face kortesi please check",
        "language": "mixed",
        "transaction_history": [],
    })
    reply = out["customer_reply"]
    assert "Please do not share your PIN or OTP" in reply
    assert "অনুগ্রহ করে" in reply


def test_financial_case_not_overridden_by_secondary_phishing_signal():
    out = analyze_ticket({
        "ticket_id": "TKT-MULTI",
        "complaint": "I sent 5000 taka to wrong number, also someone called me suspiciously asking OTP",
        "transaction_history": [tx("TXN-MULTI", "transfer", 5000, "completed", "+8801711111111")],
    })
    assert out["case_type"] == "wrong_transfer"
    assert out["department"] == "dispute_resolution"
    assert "secondary_fraud_signal" in out["reason_codes"]


def test_richer_summary_and_preferred_safe_phrase():
    out = analyze_ticket({
        "ticket_id": "TKT-RICH",
        "complaint": "I sent 5000 taka to a wrong number around 2pm today. The person isn't responding to my call.",
        "transaction_history": [tx("TXN-RICH", "transfer", 5000, "completed", "+8801719876543", "2026-04-14T14:08:22Z")],
    })
    assert "recipient is unresponsive" in out["agent_summary"].lower()
    assert "Please do not share your PIN or OTP" in out["customer_reply"]


def test_openapi_has_response_model_schema():
    schema = client.get("/openapi.json").json()
    analyze_post = schema["paths"]["/analyze-ticket"]["post"]
    response_schema = analyze_post["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema
    assert "AnalyzeResponse" in str(response_schema)
