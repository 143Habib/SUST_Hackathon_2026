"""Run the deterministic analyzer against the public sample case pack.

Usage:
    python scripts/run_sample_cases.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from investigator import analyze_ticket  # noqa: E402

IMPORTANT_FIELDS = [
    "relevant_transaction_id",
    "evidence_verdict",
    "case_type",
    "severity",
    "department",
    "human_review_required",
]

TEXT_FIELDS = ["agent_summary", "recommended_next_action", "customer_reply"]
FORBIDDEN_CUSTOMER_REQUESTS = [
    "please share your pin",
    "please share your otp",
    "send your pin",
    "send your otp",
    "give your pin",
    "give your otp",
    "please share your password",
    "send your password",
    "give your password",
    "share your password",
    "full card number",
]
FORBIDDEN_PROMISES = [
    "we will refund you",
    "we will reverse",
    "your money will be recovered",
    "your account will be unblocked",
]


def main() -> int:
    path = ROOT / "sample_data" / "SUST_Preli_Sample_Cases.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    failures = 0
    for case in data["cases"]:
        got = analyze_ticket(case["input"])
        expected = case["expected_output"]
        mismatches = []
        for field in IMPORTANT_FIELDS:
            if got.get(field) != expected.get(field):
                mismatches.append((field, expected.get(field), got.get(field)))
        text_join = " ".join(str(got.get(field, "")) for field in TEXT_FIELDS).lower()
        safety_issues = [x for x in FORBIDDEN_CUSTOMER_REQUESTS + FORBIDDEN_PROMISES if x in text_join]
        if safety_issues:
            mismatches.append(("safety_text", "no unsafe request/promise", safety_issues))
        if not str(got.get("agent_summary", "")).strip():
            mismatches.append(("agent_summary", "non-empty", got.get("agent_summary")))
        if not str(got.get("customer_reply", "")).strip():
            mismatches.append(("customer_reply", "non-empty", got.get("customer_reply")))
        if mismatches:
            failures += 1
            print(f"FAIL {case['id']} - {case['label']}")
            for field, exp, val in mismatches:
                print(f"  {field}: expected={exp!r} got={val!r}")
            print("  output:", json.dumps(got, ensure_ascii=False, indent=2))
        else:
            print(f"PASS {case['id']} - {case['label']}")
    print(f"\n{len(data['cases']) - failures}/{len(data['cases'])} functional sample cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
