from investigator import analyze_ticket


def test_banglish_wrong_transfer_vul_number():
    payload = {
        "ticket_id": "TKT-BANGLISH-001",
        "complaint": "ami 5000 taka vul number e pathaisi, please help",
        "language": "mixed",
        "channel": "in_app_chat",
        "user_type": "customer",
        "transaction_history": [
            {
                "transaction_id": "TXN-1001",
                "timestamp": "2026-04-14T14:08:22Z",
                "type": "transfer",
                "amount": 5000,
                "counterparty": "+8801719876543",
                "status": "completed",
            }
        ],
    }
    out = analyze_ticket(payload)
    assert out["case_type"] == "wrong_transfer"
    assert out["relevant_transaction_id"] == "TXN-1001"
    assert out["evidence_verdict"] == "consistent"
    assert out["department"] == "dispute_resolution"
    assert out["human_review_required"] is True


def test_banglish_payment_failed():
    payload = {
        "ticket_id": "TKT-BANGLISH-002",
        "complaint": "amar 1200 taka balance theke kete gese but payment fail hoise",
        "language": "mixed",
        "channel": "in_app_chat",
        "user_type": "customer",
        "transaction_history": [
            {
                "transaction_id": "TXN-2001",
                "timestamp": "2026-04-14T15:08:22Z",
                "type": "payment",
                "amount": 1200,
                "counterparty": "MERCHANT-77",
                "status": "failed",
            }
        ],
    }
    out = analyze_ticket(payload)
    assert out["case_type"] == "payment_failed"
    assert out["relevant_transaction_id"] == "TXN-2001"
    assert out["evidence_verdict"] == "consistent"
    assert out["department"] == "payments_ops"


def test_banglish_phishing_otp():
    out = analyze_ticket(
        {
            "ticket_id": "TKT-BANGLISH-003",
            "complaint": "keu call kore bolse account block korbe, otp chaiche",
            "language": "mixed",
            "channel": "call_center",
            "user_type": "customer",
            "transaction_history": [],
        }
    )
    assert out["case_type"] == "phishing_or_social_engineering"
    assert out["department"] == "fraud_risk"
    assert "please share your pin" not in out["customer_reply"].lower()
