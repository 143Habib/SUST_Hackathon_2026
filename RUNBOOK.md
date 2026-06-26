# RUNBOOK

## Fast Windows run

Double-click `run_windows.bat`, or run:

```powershell
py -m pip install -r requirements.txt
py main.py
```

If `py` is not recognized, use `python` instead.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```


## Open the professional UI

After the service starts, open:

```txt
http://localhost:8000/
```

API docs:

```txt
http://localhost:8000/docs
```

Judge endpoints remain:

```txt
GET  /health
POST /analyze-ticket
```

## Docker run

```bash
docker build -t queuestorm-investigator .
docker run --rm -p 8000:8000 queuestorm-investigator
```

## Verify before submission

```bash
curl http://localhost:8000/health
python scripts/run_sample_cases.py
pytest -q
```

## Submit

Preferred: deploy and submit the public base URL. `/health` and `/analyze-ticket` must be reachable from the judge harness.

Fallback: submit repository URL with this runbook and/or a Docker image pull command.


## Banglish support

The rule engine includes English, Bangla, and Banglish phrase coverage for common fintech complaints such as `vul number e pathaisi`, `taka kete gese`, `duibar charge`, `cash in hoy nai`, `otp chaiche`, and `taka ferot chai`.


## Hidden-like test pack

This build includes extra tests for Banglish, Bangla digits, prompt injection, ambiguous same-amount transfers, repeated-recipient contradictions, payment failure, duplicate payment, merchant settlement, agent cash-in, and already-reversed refund cases.

```bash
pytest -q
python scripts/run_sample_cases.py
```

Expected:

```text
26 passed
10/10 functional sample cases passed
```


## Masterclass v2 coverage

This version also checks campaign context, metadata risk signals, channel-aware routing, mixed-language replies, multi-signal complaints, response-model validation, audit logging, and stronger customer-reply safety phrasing.
