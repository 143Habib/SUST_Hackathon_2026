# QueueStorm Investigator

Masterclass v2 deterministic API service for the SUST CSE Carnival 2026 Codex Community Hackathon preliminary challenge.

The service investigates digital finance support tickets by reading both the customer complaint and recent transaction history. It returns a schema-valid JSON decision with the matching transaction, evidence verdict, case type, severity, routing department, safe support summary, next action, and customer reply.

## Why this solution is built this way

This solution uses deterministic rule-based reasoning instead of an external LLM for core decisions. That choice is intentional:

- Lower latency and no network dependency.
- Repeatable outputs for automated judging.
- Stronger control over enum values and schema.
- Safer replies that never ask for PIN, OTP, password, or full card number.
- No committed secrets and no API key required.


## Masterclass v2 Hardening

This build closes the major hidden-case gaps found during review:

- Uses `campaign_context` in decision traceability and severity context.
- Uses optional `metadata` signals such as premium user, suspicious device, retry count, and high reported value.
- Uses `channel` beyond merchant routing, including call-center phishing context and field-agent routing.
- Handles `language: mixed` with bilingual-safe replies when appropriate.
- Avoids rigid phishing-first misclassification when a complaint contains both financial-dispute and suspicious-contact signals.
- Produces richer `agent_summary` text with complaint-specific details such as unresponsive recipient, balance deduction, or changed-mind refund context.
- Uses preferred safe wording: `Please do not share your PIN or OTP with anyone.`
- Adds a Pydantic `AnalyzeResponse` model for output enum/type validation and better Swagger documentation.
- Handles both literal timestamp hours and Bangladesh local-time interpretation for hour clues.
- Keeps duplicate-payment relevant transaction selection pointed at the suspected duplicate.
- Adds best-effort JSONL audit logging for fintech-style traceability.
- Adds text-quality and safety checks to the sample runner.
- Adds hidden-like tests for campaign, metadata, channel, mixed-language, multi-signal complaints, summary quality, and OpenAPI response schemas.

## API endpoints

### `GET /health`

Returns:

```json
{"status":"ok"}
```

### `POST /analyze-ticket`

Accepts the problem statement input schema:

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today...",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "campaign_context": "boishakh_bonanza_day_1",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ]
}
```

Returns:

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Customer reports a transfer dispute for 5000 BDT via TXN-9101 to +8801719876543.",
  "recommended_next_action": "Verify TXN-9101 details with the customer and initiate the wrong-transfer dispute workflow according to policy.",
  "customer_reply": "We have noted your concern about transaction TXN-9101. Please do not share your PIN or OTP with anyone. Our dispute team will review the case and contact you through official support channels.",
  "human_review_required": true,
  "confidence": 0.9,
  "reason_codes": ["wrong_transfer", "transaction_match"]
}
```


## Professional UI

This version includes a polished web interface without changing the official judging API contract.

Open the dashboard after starting the server:

```txt
http://localhost:8000/
```

Useful UI/API routes:

- `/` professional landing page and live ticket analyzer
- `/docs` Swagger API documentation
- `/health` judge readiness endpoint
- `/metrics` optional demo metrics endpoint
- `/version` service and rule-engine version metadata
- `/analyze-ticket/batch` optional batch demo endpoint

Important: `POST /analyze-ticket` still returns only the required competition response fields. UI metrics and latency are not added to the official response schema.

## Supported enums

### `case_type`

- `wrong_transfer`
- `payment_failed`
- `refund_request`
- `duplicate_payment`
- `merchant_settlement_delay`
- `agent_cash_in_issue`
- `phishing_or_social_engineering`
- `other`

### `department`

- `customer_support`
- `dispute_resolution`
- `payments_ops`
- `merchant_operations`
- `agent_operations`
- `fraud_risk`

### `evidence_verdict`

- `consistent`
- `inconsistent`
- `insufficient_data`

### `severity`

- `low`
- `medium`
- `high`
- `critical`

## Evidence reasoning logic

The service is an investigator, not only a classifier.

It extracts:

- Complaint language and Bangla/Banglish signals.
- Bangla and English amount values.
- Transaction IDs.
- Phone numbers and merchant/agent/biller IDs.
- Time clues such as `2pm`, `morning`, `সকাল`, and similar phrases.
- Risk keywords such as OTP, PIN, suspicious caller, duplicate, failed payment, cash-in, settlement, and refund.

It then scores transactions using:

- Exact transaction ID mention.
- Amount match.
- Transaction type match.
- Status match.
- Counterparty match.
- Time clue match.
- Duplicate-payment pattern detection.

If multiple transactions are plausible and the complaint does not provide enough detail, it returns:

```json
{
  "relevant_transaction_id": null,
  "evidence_verdict": "insufficient_data"
}
```

This avoids unsafe guessing.

## Routing logic

| Case type | Department |
|---|---|
| `wrong_transfer` | `dispute_resolution` |
| `payment_failed` | `payments_ops` |
| `duplicate_payment` | `payments_ops` |
| `merchant_settlement_delay` | `merchant_operations` |
| `agent_cash_in_issue` | `agent_operations` |
| `phishing_or_social_engineering` | `fraud_risk` |
| Low-risk `refund_request` | `customer_support` |
| Contested/high-risk `refund_request` | `dispute_resolution` |
| `other` | `customer_support` |

## Safety logic

The customer-facing reply is template based. It never asks for:

- PIN
- OTP
- password
- full card number

It also never guarantees:

- refund
- reversal
- account unblock
- money recovery

Safe language is used instead, for example:

> any eligible amount will be returned through official channels

Prompt-injection text inside the complaint is ignored. The system does not echo unsafe user instructions in the reply.


## Easiest run on Windows

Option 1: double-click `run_windows.bat`.

Option 2: run these commands from PowerShell inside this project folder:

```powershell
py -m pip install -r requirements.txt
py main.py
```

Then open:

```txt
http://localhost:8000/health
```

If `py` is not recognized, use `python` instead of `py`. Python 3.10 to 3.13 is supported by the dependency ranges in `requirements.txt`.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Health check:

```bash
curl http://localhost:8000/health
```

Analyze a sample ticket:

```bash
curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  --data @sample_request.json
```

## Run tests

```bash
python scripts/run_sample_cases.py
pytest -q
```

The included sample runner compares the most important automated-scoring fields against the public sample case pack.

## Run with Docker

```bash
docker build -t queuestorm-investigator .
docker run --rm -p 8000:8000 queuestorm-investigator
```

Then test:

```bash
curl http://localhost:8000/health
```

## Deployment notes

This app can be deployed on Render, Railway, Fly.io, an AWS/Poridhi VM, or any platform that can run a Python web service.

Suggested start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

No environment variables are required except the platform-provided `PORT` if applicable.


## MODELS

No external LLM or paid AI model is required for core analysis.

| Component | Model | Where it runs | Why | Cost |
|---|---|---|---|---|
| Evidence reasoning | Deterministic rule engine | Inside this FastAPI service | Low latency, repeatable hidden-test behavior, exact enum control, and safer fintech replies | Free |
| Response templates | Rule-based safe templates | Inside this FastAPI service | Prevents PIN/OTP/password requests and unauthorized refund/reversal promises | Free |
| UI | Static HTML/CSS/JS | Served by FastAPI | Demo and manual testing only; does not affect judge endpoint | Free |

External AI providers can be added later only for wording assistance, but final decisions should remain rule-controlled for safety and schema reliability.

## Known limitations

- This is a deterministic preliminary-round service, not a production-grade banking investigation engine.
- It does not call live payment systems.
- It cannot verify real refund eligibility.
- Multilingual support focuses on common English, Bangla, and Banglish complaint patterns relevant to the challenge.
- For ambiguous cases, it intentionally asks for clarification instead of guessing.


## Banglish support

The rule engine includes English, Bangla, and Banglish phrase coverage for common fintech complaints such as `vul number e pathaisi`, `taka kete gese`, `duibar charge`, `cash in hoy nai`, `otp chaiche`, and `taka ferot chai`.


## Masterclass Hidden-Case Hardening

This build is hardened beyond the 10 public examples. The deterministic engine now covers:

- Banglish wrong-transfer phrasing such as `vul number`, `bhul kore pathailam`, `onno namber`, `pathaisi`, and `pay nai`.
- Bangla digits and multiplier amounts such as `৫০০০`, `5k`, `5 hajar`, `৫ হাজার`, and comma amounts like `1,200`.
- Payment-failed Banglish such as `taka kete geche`, `balance komse`, `recharge fail dise`, and `payment hoy nai`.
- Duplicate payment phrasing such as `duibar`, `2 bar`, `same merchant e duibar`, and repeated completed same-merchant payments.
- Agent cash-in phrasing such as `agent er kase cash in korlam`, `balance e ase nai`, and pending agent ledger cases.
- Merchant settlement phrasing such as `settlement paini`, `settle hoy nai`, and merchant sales settlement delays.
- Prompt-injection attempts that try to override system behavior or ask for OTP/PIN.
- Ambiguous same-amount transactions where the engine must ask for more details instead of guessing.
- Repeated-recipient wrong-transfer contradictions where history suggests an established recipient pattern.

The UI now presents a support-agent style investigation report first and keeps raw JSON under a collapsible **Developer View**. The official `POST /analyze-ticket` response schema remains unchanged for the judge harness.

### Extra Test Pack

Run all public and hidden-like tests:

```bash
pytest -q
python scripts/run_sample_cases.py
```

Expected in this build:

```text
26 passed
10/10 functional sample cases passed
```
#   S U S T _ H a c k a t h o n _ 2 0 2 6  
 