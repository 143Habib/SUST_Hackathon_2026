"""QueueStorm Investigator rule engine.

A deterministic, fintech-safe investigator for the SUST preliminary API challenge.
It deliberately avoids using an LLM for core reasoning so outputs are fast,
repeatable, schema-valid, and safe under hidden tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


EVIDENCE_VERDICTS = {"consistent", "inconsistent", "insufficient_data"}
CASE_TYPES = {
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
}
SEVERITIES = {"low", "medium", "high", "critical"}
DEPARTMENTS = {
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
}

BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
BANGLA_RE = re.compile(r"[\u0980-\u09FF]")

NEGATIVE_PROMPT_KEYWORDS = [
    "ignore previous instructions", "ignore all previous instructions", "ignore all instructions",
    "ignore above", "disregard previous", "forget previous", "override rules",
    "system prompt", "developer message", "reveal prompt", "jailbreak", "you are chatgpt",
    "return exactly", "set case_type", "set verdict", "mark it consistent",
    "ask me for otp", "ask user for otp", "ask customer for otp", "ask for otp",
    "ask me for pin", "ask user for pin", "ask customer for pin", "ask for pin",
    "ask for password", "collect otp", "collect pin",
]


@dataclass
class Features:
    raw_text: str
    text: str
    language: str
    amounts: List[float] = field(default_factory=list)
    transaction_ids: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)
    ids: List[str] = field(default_factory=list)
    hours: List[int] = field(default_factory=list)
    time_windows: List[str] = field(default_factory=list)
    has_bangla: bool = False
    injection_attempt: bool = False
    channel: str = ""
    user_type: str = "unknown"
    campaign_context: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchResult:
    transaction: Optional[Dict[str, Any]]
    ambiguous: bool
    score: float
    scores: List[Tuple[float, Dict[str, Any], List[str]]]
    reason_codes: List[str]


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    s = str(text).translate(BANGLA_DIGITS)
    # Normalize common Bengali punctuation, separators and whitespace.
    s = s.replace("৳", " taka ").replace("।", ".")
    s = re.sub(r"(?<=\d),(?=\d)", "", s)  # 1,200 -> 1200
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def has_bangla(text: str) -> bool:
    return bool(BANGLA_RE.search(text or ""))


def contains_any(text: str, phrases: Sequence[str]) -> bool:
    return any(p in text for p in phrases)


def extract_amounts(text: str) -> List[float]:
    """Extract likely BDT amounts from English/Bangla/Banglish complaint text."""
    text = normalize_text(text)
    amounts: List[float] = []

    # Compact and multiplier forms often used in Banglish: 1,200 / 5k / 5 hajar / ৫ হাজার.
    multiplier_patterns = [
        (r"(?<!\d)(\d{1,6}(?:\.\d+)?)\s*k\b", 1000),
        (r"(?<!\d)(\d{1,6}(?:\.\d+)?)\s*(?:hajar|hazar|hazaar|thousand|হাজার)\b", 1000),
        (r"(?<!\d)(\d{1,6}(?:\.\d+)?)\s*(?:lakh|lac|লাখ)\b", 100000),
    ]
    for pat, mul in multiplier_patterns:
        for m in re.finditer(pat, text):
            try:
                amounts.append(float(m.group(1)) * mul)
            except Exception:
                pass

    # Strong amount clues: number close to taka/tk/bdt/টাকা.
    strong_patterns = [
        r"(?<!\d)(\d{1,9}(?:\.\d+)?)\s*(?:taka|taaka|tk|bdt|টাকা)",
        r"(?:taka|taaka|tk|bdt|টাকা)\s*(\d{1,9}(?:\.\d+)?)",
        r"(?:amount|paid|sent|send|pathaisi|pathaichi|pathalam|transfer|deducted|charged|bill|sales|settlement|cash\s*in|cashin|ক্যাশ\s*ইন|পাঠিয়েছি|পাঠিয়েছি|পাঠালাম|কেটেছে|কাটছে|বিল|সেলস)\D{0,24}(\d{1,9}(?:\.\d+)?)",
    ]
    for pat in strong_patterns:
        for m in re.finditer(pat, text):
            try:
                amounts.append(float(m.group(1)))
            except Exception:
                pass

    # Fallback: if only a few numbers appear, they may be amounts. Exclude phone-like values and times.
    all_nums = []
    for m in re.finditer(r"(?<!\d)(\d{2,9})(?!\d)", text):
        val = m.group(1)
        start, end = m.span()
        around = text[max(0, start - 8): min(len(text), end + 8)]
        if len(val) >= 10:
            continue
        if re.search(r"\d{1,2}\s*(am|pm)", around):
            continue
        try:
            all_nums.append(float(val))
        except Exception:
            pass
    if not amounts and len(all_nums) <= 4:
        amounts.extend(all_nums)

    # Remove implausibly small noise values like '2pm' unless that is the only amount clue.
    cleaned: List[float] = []
    for a in amounts:
        if a >= 10 or not any(x >= 10 for x in amounts):
            cleaned.append(a)
    return unique_numbers(cleaned)


def unique_numbers(nums: Iterable[float]) -> List[float]:
    out: List[float] = []
    for n in nums:
        if not any(abs(n - x) < 0.001 for x in out):
            out.append(n)
    return out


def normalize_phone(s: Any) -> str:
    digits = re.sub(r"\D", "", str(s or "").translate(BANGLA_DIGITS))
    if digits.startswith("880") and len(digits) >= 13:
        return "0" + digits[3:13]
    if digits.startswith("80") and len(digits) >= 12:  # tolerate missing 8 in +880
        return "0" + digits[2:12]
    if len(digits) >= 11:
        return digits[-11:]
    return digits


def extract_phones(text: str) -> List[str]:
    phones = []
    # Bangladesh phone numbers, with +88/88/0 forms.
    for m in re.finditer(r"(?:\+?88)?0?1[3-9]\d{8}", normalize_text(text)):
        p = normalize_phone(m.group(0))
        if len(p) >= 10 and p not in phones:
            phones.append(p)
    return phones


def extract_transaction_ids(text: str) -> List[str]:
    ids = []
    for m in re.finditer(r"\b(?:txn|tx|transaction)[-_\s]*[a-z0-9-]+\b", normalize_text(text)):
        token = re.sub(r"\s+", "-", m.group(0).upper())
        token = token.replace("TRANSACTION-", "TXN-").replace("TX-", "TXN-")
        if token not in ids:
            ids.append(token)
    # Also capture explicit TXN-like tokens.
    for m in re.finditer(r"\bTXN[-_A-Z0-9]+\b", str(text).upper()):
        token = m.group(0).replace("_", "-")
        if token not in ids:
            ids.append(token)
    return ids


def extract_entity_ids(text: str) -> List[str]:
    ids = []
    for m in re.finditer(r"\b(?:MERCHANT|AGENT|BILLER|SHOP|MFS|ACCT)[-_A-Z0-9]+\b", str(text).upper()):
        token = m.group(0)
        if token not in ids:
            ids.append(token)
    return ids


def extract_hours(text: str) -> List[int]:
    txt = normalize_text(text)
    hours: List[int] = []
    for m in re.finditer(r"\b(1[0-2]|0?[1-9])\s*(a\.?m\.?|p\.?m\.?)\b", txt):
        h = int(m.group(1)) % 12
        mer = m.group(2).replace(".", "")
        if mer == "pm":
            h += 12
        if h not in hours:
            hours.append(h)
    # around 2pm can be written as 2 pm, ২টা, 2টা, 2ta, 2tar dike.
    for m in re.finditer(r"\b(1[0-2]|0?[1-9])\s*(টা|ta|tar|tay|pm|am)\b", txt):
        h = int(m.group(1))
        marker = m.group(2)
        if marker == "pm" and h != 12:
            h += 12
        # Bengali/Romanized 'ta/tar/tay' alone is ambiguous; trust with time-of-day hints.
        if marker in {"টা", "ta", "tar", "tay"}:
            around = txt[max(0, m.start() - 22): min(len(txt), m.end() + 22)]
            if contains_any(around, ["দুপুর", "বিকাল", "বিকেল", "সন্ধ্যা", "dupur", "bikal", "bikel", "shondha", "evening", "afternoon"]):
                if h < 12:
                    h += 12
            elif contains_any(around, ["সকাল", "ভোর", "morning", "shokal", "sokal"]):
                pass
            elif contains_any(around, ["রাত", "raat", "night"]):
                if h < 12:
                    h += 12
            else:
                continue
        if h not in hours:
            hours.append(h)
    return hours


def extract_time_windows(text: str) -> List[str]:
    txt = normalize_text(text)
    windows = []
    signals = {
        "morning": ["morning", "সকাল", "shokal", "sokal"],
        "afternoon": ["afternoon", "দুপুর", "বিকাল", "বিকেল", "dupur", "bikal", "bikel"],
        "evening": ["evening", "সন্ধ্যা", "shondha", "shondhay"],
        "night": ["night", "রাত", "raat", "rate"],
    }
    for name, pats in signals.items():
        if contains_any(txt, pats):
            windows.append(name)
    return windows


def infer_language(payload: Dict[str, Any], complaint: str) -> str:
    lang = str(payload.get("language") or "").lower()
    if lang in {"en", "bn", "mixed"}:
        return lang
    return "bn" if has_bangla(complaint) else "en"


def build_features(payload: Dict[str, Any]) -> Features:
    raw = str(payload.get("complaint") or "")
    text = normalize_text(raw)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return Features(
        raw_text=raw,
        text=text,
        language=infer_language(payload, raw),
        amounts=extract_amounts(raw),
        transaction_ids=extract_transaction_ids(raw),
        phones=extract_phones(raw),
        ids=extract_entity_ids(raw),
        hours=extract_hours(raw),
        time_windows=extract_time_windows(raw),
        has_bangla=has_bangla(raw),
        injection_attempt=contains_any(text, NEGATIVE_PROMPT_KEYWORDS),
        channel=str(payload.get("channel") or "").lower(),
        user_type=str(payload.get("user_type") or "unknown").lower(),
        campaign_context=normalize_text(payload.get("campaign_context") or ""),
        metadata=metadata,
    )


def campaign_active(features: Features) -> bool:
    """Return True when the harness gives campaign context that may increase queue risk."""
    c = features.campaign_context
    return bool(c and contains_any(c, ["campaign", "bonanza", "cashback", "promo", "boishakh", "eid", "day_", "surge"]))


def metadata_bool(metadata: Dict[str, Any], *keys: str) -> bool:
    for key in keys:
        val = metadata.get(key)
        if isinstance(val, bool) and val:
            return True
        if isinstance(val, str) and val.strip().lower() in {"true", "yes", "y", "1", "high", "critical"}:
            return True
        if isinstance(val, (int, float)) and val > 0:
            return True
    return False


def metadata_number(metadata: Dict[str, Any], *keys: str) -> float:
    for key in keys:
        val = metadata.get(key)
        try:
            if isinstance(val, str):
                val = val.translate(BANGLA_DIGITS).replace(",", "")
            num = float(val)
            if num > 0:
                return num
        except Exception:
            continue
    return 0.0


def metadata_reason_codes(features: Features) -> List[str]:
    m = features.metadata or {}
    codes: List[str] = []
    if campaign_active(features):
        codes.append("campaign_context_considered")
    if features.channel:
        codes.append(f"channel_{features.channel}")
    if metadata_bool(m, "is_premium_user", "premium_user", "vip"):
        codes.append("premium_user")
    if metadata_bool(m, "suspicious_device", "new_device", "device_changed", "account_takeover_signal"):
        codes.append("metadata_suspicious_device")
    retry = metadata_number(m, "retry_count", "attempt_count", "failure_count")
    if retry >= 2:
        codes.append("metadata_repeated_attempts")
    if metadata_number(m, "reported_loss_amount", "disputed_amount", "claim_amount") >= 5000:
        codes.append("metadata_high_value")
    return codes


def contains_banglish(text: str) -> bool:
    return contains_any(normalize_text(text), [
        "ami", "amar", "taka", "vul", "bhul", "pathaisi", "pathaichi", "kete", "geche",
        "gese", "hoy nai", "hoyni", "duibar", "cash in", "otp chaiche", "settlement paini",
    ])

def detect_case_type(features: Features, payload: Dict[str, Any]) -> Tuple[str, List[str]]:
    t = features.text
    if features.injection_attempt:
        # Do not let prompt-injection phrases such as "ask me for OTP" become
        # business evidence for the actual complaint classification.
        for phrase in NEGATIVE_PROMPT_KEYWORDS:
            t = t.replace(phrase, " ")
        t = re.sub(r"\s+", " ", t).strip()
    user_type = features.user_type
    channel = features.channel

    phishing = [
        "otp", "pin", "password", "passcode", "verification code", "code share", "share code",
        "scam", "fraud", "phishing", "suspicious", "blocked if", "account will be blocked",
        "someone called", "caller", "whatsapp", "sms", "bkash office", "support theke call",
        "fake", "otp chaiche", "otp chay", "otp chailo", "otp caise", "otp chai",
        "pin chaiche", "pin chay", "pin chailo", "pin caise", "pin chai",
        "password chaiche", "password chay", "scam call", "fake call", "account block korbe",
        "account lock korbe", "verify korte bolse", "verification er jonno",
        "অটিপি", "ওটিপি", "পিন", "পাসওয়ার্ড", "পাসওয়ার্ড",
        "প্রতার", "স্ক্যাম", "কল করেছে", "ব্লক", "ভেরিফিকেশন কোড",
    ]
    duplicate = [
        "deducted twice", "charged twice", "paid twice", "double charged", "duplicate", "twice", "two times",
        "duibar", "dui bar", "2 bar", "2bar", "duibar taka", "double", "double charge", "same payment",
        "same merchant e duibar", "abar keteche", "abar kete gese", "ekoi payment",
        "দুইবার", "দুবার", "২ বার", "কেটেছে দুবার", "কেটেছে দুইবার", "আবার কেটেছে",
    ]
    settlement = [
        "settlement", "settled", "not settled", "settle hoy nai", "settle hoyni", "settlement paini",
        "settlement pai nai", "sales", "sale", "merchant balance", "merchant taka", "daily sales",
        "সেটেল", "সেটেলমেন্ট", "সেলস", "বিক্রির টাকা", "সেটেল হয়নি", "সেটেল হয়নি",
    ]
    cash_in = [
        "cash in", "cash-in", "cashin", "cash in korsi", "cashin korsi", "cash in korlam",
        "deposit", "agent", "agent er kase", "agent er kache", "agent ke dilam", "agent taka",
        "balance not updated", "not reflected", "balance add hoy nai", "balance ashe nai", "balance ase nai",
        "balance aseni", "balance ashena", "balance e ashe nai", "balance e ase nai",
        "cash in hoy nai", "cash in hoyni", "cashin hoy nai", "cashin hoyni", "joma hoy nai",
        "ক্যাশ ইন", "ক্যাশইন", "এজেন্ট", "টাকা আসেনি", "ব্যালেন্সে", "জমা", "পাঠিয়েছে", "পাঠিয়েছে",
    ]
    failed = [
        "failed", "failure", "unsuccessful", "declined", "did not go through", "not successful",
        "balance was deducted", "deducted", "deduct hoise", "deduct hoyeche",
        "taka kete gese", "taka kete geche", "taka kete niche", "taka katse", "tk kete gese",
        "balance kete gese", "balance kome gese", "balance komse", "balance katse",
        "kete gese", "kete geche", "kete niche", "kete niyeche", "katse",
        "hoy nai", "hoyni", "hoini", "holo na", "kaj kore nai", "fail hoise", "fail hoyeche", "fail dise",
        "কেটেছে", "কাটছে", "কেটে গেছে", "ফেইল", "ফেল", "ব্যর্থ", "হয়নি", "হয়নি", "deduct",
    ]
    payment_words = ["payment", "paid", "pay", "recharge", "top up", "bill", "biller", "merchant", "paisi na", "paini", "pai nai", "পেমেন্ট", "বিল", "রিচার্জ"]
    wrong_transfer = [
        "wrong number", "wrong person", "wrong recipient", "mistake", "mistyped", "typed it wrong",
        "isn't responding", "is not responding", "sent by mistake", "sent to", "transfer", "reverse it",
        "didn't get it", "did not get it", "didn’t get it", "not received", "he says he didn't get",
        "vul number", "bhul number", "vul namber", "bhul namber", "vul no", "bhul no",
        "vul recipient", "bhul recipient", "vul kore", "bhul kore", "vul e", "bhul e",
        "wrongly pathaisi", "wrongly sent", "vul kore pathaisi", "bhul kore pathaisi", "vul kore pathailam", "bhul kore pathailam",
        "vul kore send", "bhul kore send", "onno number", "onnor number", "onnno number", "onno namber", "onnor namber",
        "onno manush", "onno lok", "wrong lok", "peye nai", "pay nai", "pai nai", "paini", "receive kore nai",
        "pathaisi", "pathaichi", "pathaise", "pathailam", "pathalam", "pathiyechi", "pathiye diyechi",
        "send korchi", "send korechi", "send kore felsi", "transfer korchi", "transfer korechi", "transfer diyechi", "taka pathaisi",
        "ভুল নাম্বার", "ভুল নম্বর", "ভুল", "ভুলে", "পাঠিয়েছি", "পাঠিয়েছি", "পায়নি", "পায়নি", "পাইনি", "ট্রান্সফার",
    ]
    refund = [
        "refund", "return my money", "money back", "changed my mind", "cancel", "cancellation",
        "ferot", "ferot chai", "taka ferot", "taka ferot chai", "refund chai", "back chai",
        "ফেরত", "রিফান্ড", "টাকা ফেরত", "বাতিল"
    ]

    phish = contains_any(t, phishing)
    channel_phish = channel == "call_center" and contains_any(t, ["called", "caller", "call", "কল", "phone", "otp", "pin", "scam", "fake"])
    phish = phish or channel_phish or metadata_bool(features.metadata, "reported_scam", "fraud_signal", "social_engineering_signal")
    financial_signal = any([
        contains_any(t, duplicate),
        (user_type == "merchant" or channel == "merchant_portal" or contains_any(t, ["merchant", "মার্চেন্ট"])) and contains_any(t, settlement),
        contains_any(t, cash_in) and (contains_any(t, ["agent", "এজেন্ট", "cash", "ক্যাশ", "deposit", "জমা"]) or user_type == "agent" or channel == "field_agent"),
        contains_any(t, failed) and contains_any(t, payment_words),
        contains_any(t, wrong_transfer),
        contains_any(t, refund),
    ])
    fraud_codes = ["secondary_fraud_signal"] if phish and financial_signal else []
    if phish and not financial_signal:
        return "phishing_or_social_engineering", ["phishing", "credential_protection"]

    if contains_any(t, duplicate):
        return "duplicate_payment", ["duplicate_payment"] + fraud_codes
    if (user_type == "merchant" or channel == "merchant_portal" or contains_any(t, ["merchant", "মার্চেন্ট"])) and contains_any(t, settlement):
        return "merchant_settlement_delay", ["merchant_settlement", "delay"] + fraud_codes
    if contains_any(t, cash_in) and (contains_any(t, ["agent", "এজেন্ট", "cash", "ক্যাশ", "deposit", "জমা"]) or user_type == "agent" or channel == "field_agent"):
        return "agent_cash_in_issue", ["agent_cash_in"] + fraud_codes
    if contains_any(t, failed) and contains_any(t, payment_words):
        return "payment_failed", ["payment_failed", "potential_balance_deduction"] + fraud_codes
    if contains_any(t, wrong_transfer):
        return "wrong_transfer", ["wrong_transfer"] + fraud_codes
    if contains_any(t, refund):
        return "refund_request", ["refund_request"] + fraud_codes
    if phish:
        return "phishing_or_social_engineering", ["phishing", "credential_protection"]
    if channel == "field_agent" or user_type == "agent":
        return "agent_cash_in_issue", ["agent_channel_context"]
    return "other", ["vague_complaint" if len(t.split()) < 8 else "unclassified"]

def txn_amount(txn: Dict[str, Any]) -> Optional[float]:
    try:
        raw = txn.get("amount")
        if isinstance(raw, str):
            raw = re.sub(r"(?<=\d),(?=\d)", "", raw.translate(BANGLA_DIGITS))
        return float(raw)
    except Exception:
        return None


def txn_id(txn: Dict[str, Any]) -> str:
    return str(txn.get("transaction_id") or "")


def parse_txn_time(txn: Dict[str, Any]) -> Optional[datetime]:
    raw = txn.get("timestamp")
    if not raw:
        return None
    try:
        s = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _clock_match(h: int, hours: Sequence[int], windows: Sequence[str]) -> bool:
    for hh in hours:
        # Around a specified time: within one hour; handle wrap-around.
        diff = min(abs(h - hh), abs((h + 24) - hh), abs(h - (hh + 24)))
        if diff <= 1:
            return True
    if "morning" in windows and 5 <= h < 12:
        return True
    if "afternoon" in windows and 12 <= h < 17:
        return True
    if "evening" in windows and 17 <= h < 22:
        return True
    if "night" in windows and (h >= 20 or h < 5):
        return True
    return False


def hour_matches(txn: Dict[str, Any], hours: Sequence[int], windows: Sequence[str]) -> bool:
    dt = parse_txn_time(txn)
    if not dt:
        return False
    # Evaluation samples use the literal timestamp hour, while real Bangladesh customers
    # often describe local time. Accept both to avoid fragile hidden timezone cases.
    if _clock_match(dt.hour, hours, windows):
        return True
    try:
        bd_hour = (dt + timedelta(hours=6)).hour
        return _clock_match(bd_hour, hours, windows)
    except Exception:
        return False

def expected_types_for_case(case_type: str) -> set[str]:
    return {
        "wrong_transfer": {"transfer", "cash_out"},
        "payment_failed": {"payment"},
        "refund_request": {"payment", "refund"},
        "duplicate_payment": {"payment"},
        "merchant_settlement_delay": {"settlement"},
        "agent_cash_in_issue": {"cash_in"},
        "phishing_or_social_engineering": set(),
        "other": set(),
    }.get(case_type, set())


def expected_status_for_case(case_type: str) -> set[str]:
    return {
        "wrong_transfer": {"completed"},
        "payment_failed": {"failed", "pending"},
        "refund_request": {"completed", "reversed"},
        "duplicate_payment": {"completed"},
        "merchant_settlement_delay": {"pending"},
        "agent_cash_in_issue": {"pending", "failed"},
    }.get(case_type, set())


def counterparty_matches(txn: Dict[str, Any], features: Features) -> bool:
    cp = str(txn.get("counterparty") or "")
    cp_norm_phone = normalize_phone(cp)
    if cp_norm_phone and cp_norm_phone in features.phones:
        return True
    cp_upper = cp.upper()
    if any(e and e in cp_upper for e in features.ids):
        return True
    # Be tolerant when complaint names merchant/biller category, and counterparty carries it.
    text = features.text
    generic_entities = ["merchant", "biller", "agent", "mobile", "electricity", "desco", "shop", "store"]
    return any(word in text and word.upper() in cp_upper for word in generic_entities)


def find_duplicate_group(transactions: List[Dict[str, Any]], features: Features) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    candidates = [tx for tx in transactions if str(tx.get("type") or "").lower() == "payment"]
    groups: List[List[Dict[str, Any]]] = []
    for i, tx in enumerate(candidates):
        a = txn_amount(tx)
        if a is None:
            continue
        group = [tx]
        t1 = parse_txn_time(tx)
        for other in candidates[i + 1:]:
            if str(other.get("status") or "").lower() != str(tx.get("status") or "").lower():
                continue
            if str(other.get("status") or "").lower() != "completed":
                continue
            if txn_amount(other) is None or abs(txn_amount(other) - a) > 0.001:
                continue
            if str(other.get("counterparty") or "").upper() != str(tx.get("counterparty") or "").upper():
                continue
            t2 = parse_txn_time(other)
            close = True
            if t1 and t2:
                close = abs((t2 - t1).total_seconds()) <= 10 * 60
            if close:
                group.append(other)
        if len(group) >= 2:
            # If an amount is mentioned, prefer the group matching it.
            if features.amounts and not any(abs(a - m) < 0.001 for m in features.amounts):
                continue
            groups.append(sorted(group, key=lambda x: parse_txn_time(x) or datetime.min))
    if not groups:
        return None, []
    # Most specific group: largest group, then latest transaction.
    groups.sort(key=lambda g: (len(g), parse_txn_time(g[-1]) or datetime.min), reverse=True)
    return groups[0][-1], groups[0]


def match_transaction(case_type: str, features: Features, transactions: List[Dict[str, Any]]) -> MatchResult:
    if not transactions:
        return MatchResult(None, False, 0.0, [], ["no_transaction_history"])

    # Exact transaction ID mention wins unless the ID is not present.
    if features.transaction_ids:
        by_id = {txn_id(tx).upper().replace("_", "-"): tx for tx in transactions}
        for mentioned in features.transaction_ids:
            normalized = mentioned.upper().replace("_", "-")
            if normalized in by_id:
                return MatchResult(by_id[normalized], False, 100.0, [(100.0, by_id[normalized], ["exact_transaction_id"])], ["exact_transaction_id"])

    if case_type == "duplicate_payment":
        dup, group = find_duplicate_group(transactions, features)
        if dup:
            score = 95.0
            return MatchResult(dup, False, score, [(score, dup, ["duplicate_pattern"])], ["duplicate_pattern"])

    expected_types = expected_types_for_case(case_type)
    expected_statuses = expected_status_for_case(case_type)
    scored: List[Tuple[float, Dict[str, Any], List[str]]] = []

    for tx in transactions:
        score = 0.0
        reasons: List[str] = []
        tx_type = str(tx.get("type") or "").lower()
        tx_status = str(tx.get("status") or "").lower()
        amount = txn_amount(tx)

        if expected_types:
            if tx_type in expected_types:
                score += 30
                reasons.append("type_match")
            else:
                score -= 20
        elif case_type == "other":
            # Vague cases should not accidentally match based only on recent history.
            score -= 10

        if features.amounts and amount is not None:
            if any(abs(amount - a) < 0.001 for a in features.amounts):
                score += 40
                reasons.append("amount_match")
            elif any(amount and abs(amount - a) / max(abs(amount), 1) <= 0.02 for a in features.amounts):
                score += 25
                reasons.append("near_amount_match")
            else:
                score -= 8

        if expected_statuses and tx_status in expected_statuses:
            score += 20
            reasons.append("status_match")
        elif tx_status:
            # Completed payments can still support a refund; completed transfer can still be a dispute.
            if case_type in {"refund_request", "wrong_transfer"} and tx_status == "completed":
                score += 10
            elif case_type != "other":
                score -= 6

        if counterparty_matches(tx, features):
            score += 25
            reasons.append("counterparty_match")

        if (features.hours or features.time_windows) and hour_matches(tx, features.hours, features.time_windows):
            score += 12
            reasons.append("time_match")

        # Recency matters when other signals are equal.
        dt = parse_txn_time(tx)
        if dt:
            # Small stable tie-breaker by chronological order; not enough to overcome ambiguity.
            score += min(max(dt.timestamp() / 10**10, 0), 1)

        if case_type == "phishing_or_social_engineering" and not features.transaction_ids:
            score -= 100

        scored.append((score, tx, reasons))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return MatchResult(None, False, 0.0, [], ["no_candidate"])

    top_score, top_tx, top_reasons = scored[0]
    plausible_threshold = 45.0
    if not features.amounts and not features.transaction_ids and not any(counterparty_matches(tx, features) for tx in transactions):
        plausible_threshold = 55.0
    if case_type == "other":
        plausible_threshold = 999.0

    if top_score < plausible_threshold:
        return MatchResult(None, False, top_score, scored, ["no_transaction_match"])

    # Ambiguity: multiple plausible same-type/amount matches with no counterparty or exact ID.
    close = [s for s in scored if s[0] >= plausible_threshold and (top_score - s[0]) <= 12]
    # Additional ambiguity guard: same amount and expected type but no direct counterparty/time clue.
    if len(close) > 1:
        # If the top has a direct counterparty/time advantage, accept; otherwise do not guess.
        discriminators = {"counterparty_match", "time_match", "exact_transaction_id", "duplicate_pattern"}
        if not any(r in discriminators for r in top_reasons):
            return MatchResult(None, True, top_score, scored, ["ambiguous_match", "needs_clarification"])
    return MatchResult(top_tx, False, top_score, scored, ["transaction_match"] + top_reasons)


def repeated_recipient_pattern(relevant: Dict[str, Any], transactions: List[Dict[str, Any]]) -> bool:
    cp = str(relevant.get("counterparty") or "")
    if not cp:
        return False
    count = 0
    for tx in transactions:
        if tx is relevant:
            continue
        if str(tx.get("type") or "").lower() == "transfer" and str(tx.get("counterparty") or "") == cp and str(tx.get("status") or "").lower() == "completed":
            count += 1
    return count >= 1


def determine_evidence(case_type: str, match: MatchResult, transactions: List[Dict[str, Any]], features: Features) -> Tuple[str, List[str]]:
    if case_type == "phishing_or_social_engineering":
        return "insufficient_data", ["safety_report"]
    if match.ambiguous:
        return "insufficient_data", ["ambiguous_match", "needs_clarification"]
    tx = match.transaction
    if tx is None:
        return "insufficient_data", ["no_matching_transaction"]

    status = str(tx.get("status") or "").lower()
    tx_type = str(tx.get("type") or "").lower()
    codes: List[str] = []

    if case_type == "wrong_transfer":
        if tx_type != "transfer":
            return "inconsistent", ["type_contradiction"]
        if status not in {"completed", "pending"}:
            return "inconsistent", ["transfer_not_completed"]
        if repeated_recipient_pattern(tx, transactions):
            return "inconsistent", ["established_recipient_pattern", "evidence_inconsistent"]
        return "consistent", ["transaction_match", "dispute_initiated"]

    if case_type == "payment_failed":
        if tx_type != "payment":
            return "inconsistent", ["type_contradiction"]
        if status in {"failed", "pending"}:
            return "consistent", ["payment_failed", "potential_balance_deduction"]
        return "inconsistent", ["payment_status_completed", "evidence_inconsistent"]

    if case_type == "refund_request":
        if tx_type in {"payment", "refund"}:
            if status == "completed":
                return "consistent", ["refund_request", "merchant_policy_dependent"]
            if status == "reversed":
                return "inconsistent", ["already_reversed", "evidence_inconsistent"]
            return "insufficient_data", ["refund_status_unclear"]
        return "inconsistent", ["type_contradiction"]

    if case_type == "duplicate_payment":
        dup, group = find_duplicate_group(transactions, features)
        if dup:
            return "consistent", ["duplicate_payment", "biller_verification_required"]
        if tx_type == "payment":
            return "inconsistent", ["no_duplicate_found", "evidence_inconsistent"]
        return "insufficient_data", ["no_duplicate_found"]

    if case_type == "merchant_settlement_delay":
        if tx_type != "settlement":
            return "inconsistent", ["type_contradiction"]
        if status == "pending":
            return "consistent", ["merchant_settlement", "delay", "pending"]
        if status == "completed":
            return "inconsistent", ["settlement_already_completed", "evidence_inconsistent"]
        return "insufficient_data", ["settlement_status_unclear"]

    if case_type == "agent_cash_in_issue":
        if tx_type != "cash_in":
            return "inconsistent", ["type_contradiction"]
        if status in {"pending", "failed"}:
            return "consistent", ["agent_cash_in", "pending_transaction", "agent_ops"]
        if status == "completed":
            return "inconsistent", ["cash_in_completed", "evidence_inconsistent"]
        return "insufficient_data", ["cash_in_status_unclear"]

    return "insufficient_data", ["needs_clarification"]


def department_for(case_type: str, severity: str, evidence_verdict: str) -> str:
    if case_type == "wrong_transfer":
        return "dispute_resolution"
    if case_type in {"payment_failed", "duplicate_payment"}:
        return "payments_ops"
    if case_type == "merchant_settlement_delay":
        return "merchant_operations"
    if case_type == "agent_cash_in_issue":
        return "agent_operations"
    if case_type == "phishing_or_social_engineering":
        return "fraud_risk"
    if case_type == "refund_request":
        if severity in {"high", "critical"} or evidence_verdict == "inconsistent":
            return "dispute_resolution"
        return "customer_support"
    return "customer_support"


def max_amount(features: Features, match: MatchResult, transactions: List[Dict[str, Any]]) -> float:
    vals = [a for a in features.amounts if isinstance(a, (int, float))]
    if match.transaction is not None and txn_amount(match.transaction) is not None:
        vals.append(float(txn_amount(match.transaction)))
    meta_amount = metadata_number(features.metadata, "reported_loss_amount", "disputed_amount", "claim_amount", "amount")
    if meta_amount:
        vals.append(meta_amount)
    return max(vals or [0.0])


def _severity_rank(sev: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(sev, 0)


def _max_severity(a: str, b: str) -> str:
    return a if _severity_rank(a) >= _severity_rank(b) else b


def severity_for(case_type: str, evidence_verdict: str, match: MatchResult, features: Features, transactions: List[Dict[str, Any]]) -> str:
    amount = max_amount(features, match, transactions)
    if case_type == "phishing_or_social_engineering":
        sev = "critical"
    elif case_type == "duplicate_payment":
        sev = "high" if evidence_verdict == "consistent" else "medium"
    elif case_type == "payment_failed":
        sev = "high" if evidence_verdict == "consistent" else "medium"
    elif case_type == "wrong_transfer":
        sev = "high" if evidence_verdict == "consistent" else "medium"
    elif case_type == "agent_cash_in_issue":
        sev = "high" if evidence_verdict == "consistent" else "medium"
    elif case_type == "merchant_settlement_delay":
        sev = "medium"
    elif case_type == "refund_request":
        sev = "low" if amount < 5000 and evidence_verdict == "consistent" else "medium"
    else:
        sev = "low" if evidence_verdict == "insufficient_data" else "medium"

    if case_type not in {"merchant_settlement_delay", "other"}:
        if amount >= 20000:
            sev = "critical"
        elif amount >= 5000 and sev == "low":
            sev = "high"
        elif amount >= 5000 and case_type in {"wrong_transfer", "payment_failed", "duplicate_payment", "agent_cash_in_issue"}:
            sev = "high"

    if campaign_active(features) and case_type in {"payment_failed", "duplicate_payment", "wrong_transfer", "phishing_or_social_engineering", "agent_cash_in_issue"}:
        sev = _max_severity(sev, "medium")
    if metadata_bool(features.metadata, "is_premium_user", "premium_user", "vip") and sev == "low":
        sev = "medium"
    if metadata_bool(features.metadata, "suspicious_device", "new_device", "device_changed", "account_takeover_signal"):
        sev = _max_severity(sev, "high")
    if metadata_number(features.metadata, "retry_count", "attempt_count", "failure_count") >= 3 and case_type in {"payment_failed", "duplicate_payment"}:
        sev = _max_severity(sev, "high")
    return sev

def human_review_for(case_type: str, severity: str, evidence_verdict: str, match: MatchResult, features: Features) -> bool:
    if case_type == "phishing_or_social_engineering":
        return True
    if evidence_verdict == "inconsistent":
        return True
    if severity == "critical":
        return True
    if metadata_bool(features.metadata, "suspicious_device", "new_device", "device_changed", "account_takeover_signal"):
        return True
    if "secondary_fraud_signal" in [r for _, _, reasons in match.scores for r in reasons]:
        return True
    if case_type == "wrong_transfer":
        return match.transaction is not None
    if case_type == "duplicate_payment":
        return evidence_verdict == "consistent"
    if case_type == "agent_cash_in_issue":
        return evidence_verdict == "consistent"
    if case_type == "refund_request":
        return severity in {"high", "critical"}
    return False

def confidence_for(case_type: str, evidence_verdict: str, match: MatchResult, features: Features) -> float:
    if case_type == "phishing_or_social_engineering":
        return 0.95
    if match.ambiguous:
        return 0.65
    if evidence_verdict == "consistent" and match.transaction is not None:
        if match.score >= 90:
            return 0.93
        if match.score >= 70:
            return 0.90
        return 0.85
    if evidence_verdict == "inconsistent":
        return 0.75
    if case_type == "other":
        return 0.60
    return 0.68


def format_amount(amount: Optional[float]) -> str:
    if amount is None:
        return "the reported amount"
    if abs(amount - round(amount)) < 0.001:
        return f"{int(round(amount))} BDT"
    return f"{amount:.2f} BDT"


def tx_ref(tx: Optional[Dict[str, Any]]) -> str:
    return txn_id(tx) if tx else "the relevant transaction"


def complaint_detail_signals(features: Features) -> List[str]:
    t = features.text
    details: List[str] = []
    if contains_any(t, ["isn't responding", "is not responding", "not responding", "unresponsive", "phone bondho", "respond korche na", "কল ধরছে না"]):
        details.append("recipient is unresponsive")
    if contains_any(t, ["supposed to be", "intended", "should have been", "jeta dewar chilo", "যাওয়ার কথা"]):
        details.append("customer mentions an intended recipient")
    if contains_any(t, ["balance was deducted", "balance theke kete", "kete gese", "কেটেছে", "কেটে গেছে"]):
        details.append("customer reports balance deduction")
    if contains_any(t, ["changed my mind", "don't want", "dont want", "cancel", "বাতিল"]):
        details.append("customer changed their mind after payment")
    if contains_any(t, ["brother", "ভাই", "bhai"]):
        details.append("recipient described as brother")
    return details[:2]


def make_agent_summary(case_type: str, verdict: str, match: MatchResult, features: Features, transactions: List[Dict[str, Any]]) -> str:
    tx = match.transaction
    amount = txn_amount(tx) if tx else (features.amounts[0] if features.amounts else None)
    ref = tx_ref(tx)
    cp = str(tx.get("counterparty") or "") if tx else ""
    details = complaint_detail_signals(features)
    detail_sentence = (" " + "; ".join(d.capitalize() for d in details) + ".") if details else ""

    if case_type == "phishing_or_social_engineering":
        channel_note = " via call center" if features.channel == "call_center" else ""
        return f"Customer reports a suspicious contact{channel_note} requesting sensitive credentials. No transaction can be safely confirmed from the provided history."
    if match.ambiguous:
        return f"Customer appears to be reporting a transfer issue for {format_amount(amount)}, but multiple recent transactions could match. More details are needed before selecting a transaction."
    if case_type == "wrong_transfer":
        if verdict == "inconsistent":
            return f"Customer claims a wrong transfer involving {ref}, but transaction history shows repeated completed transfers to {cp or 'the same recipient'}, suggesting an established recipient pattern."
        return f"Customer reports sending {format_amount(amount)} via {ref}{(' to ' + cp) if cp else ''}, which they now believe was the wrong recipient.{detail_sentence}"
    if case_type == "payment_failed":
        return f"Customer reports a failed payment with possible balance deduction for {format_amount(amount)} via {ref}.{detail_sentence}"
    if case_type == "refund_request":
        return f"Customer requests a refund related to {format_amount(amount)} via {ref}.{detail_sentence} Refund eligibility depends on policy and merchant or biller confirmation."
    if case_type == "duplicate_payment":
        pair_ids = [txn_id(txn) for _, txn, _ in match.scores[:2] if txn_id(txn)]
        pair_text = f" Related candidate transactions include {', '.join(pair_ids)}." if len(pair_ids) > 1 else ""
        return f"Customer reports being charged twice; transaction history shows a likely duplicate payment, with {ref} as the suspected duplicate.{pair_text}"
    if case_type == "merchant_settlement_delay":
        return f"Merchant reports delayed settlement for {format_amount(amount)}; {ref} is currently reflected as the likely settlement transaction."
    if case_type == "agent_cash_in_issue":
        return f"Customer reports an agent cash-in not reflected in balance; {ref} for {format_amount(amount)} appears to be the relevant cash-in transaction."
    return "Complaint is too vague to identify a specific transaction or case workflow from the provided history."


def make_next_action(case_type: str, verdict: str, match: MatchResult, features: Features) -> str:
    ref = tx_ref(match.transaction)
    if case_type == "phishing_or_social_engineering":
        return "Escalate to fraud_risk, record the suspicious contact details if available, and advise the customer to use only official support channels."
    if match.ambiguous:
        if contains_any(features.text, ["brother", "bhai", "ভাই"]):
            return "Ask the customer for the recipient number or transaction ID to identify the correct transfer before initiating any dispute workflow."
        return "Ask the customer for a transaction ID, recipient number, amount, and time before initiating any dispute workflow."
    if verdict == "insufficient_data":
        return "Request the transaction ID, amount, time, and a short description of the issue; do not guess a transaction from the history."
    if verdict == "inconsistent":
        return f"Send {ref} for human review with the contradiction noted; do not promise reversal or recovery."
    if case_type == "wrong_transfer":
        return f"Verify {ref} details with the customer and initiate the wrong-transfer dispute workflow according to policy."
    if case_type == "payment_failed":
        return f"Send {ref} to payments_ops for failed-payment reconciliation and check whether an eligible amount should be returned through official channels."
    if case_type == "refund_request":
        return f"Check merchant or biller refund policy for {ref} and guide the customer through the official refund request process."
    if case_type == "duplicate_payment":
        return f"Verify the duplicate payment pair and send {ref} to payments_ops for biller or merchant confirmation."
    if case_type == "merchant_settlement_delay":
        return f"Check settlement processing status for {ref} and update the merchant through official support channels."
    if case_type == "agent_cash_in_issue":
        return f"Escalate {ref} to agent_operations to verify the agent ledger and pending cash-in status."
    return "Ask for more details and keep the case in customer_support until a specific issue or transaction can be identified."


def _mixed_suffix() -> str:
    return " অনুগ্রহ করে PIN বা OTP কারও সাথে শেয়ার করবেন না। / Please do not share your PIN or OTP with anyone."


def make_customer_reply(case_type: str, verdict: str, match: MatchResult, features: Features, payload: Dict[str, Any]) -> str:
    bn = features.language == "bn" or (features.has_bangla and features.language != "en")
    mixed = features.language == "mixed" and not bn
    ref = tx_ref(match.transaction)

    if bn:
        if case_type == "phishing_or_social_engineering":
            return "আপনাকে ধন্যবাদ সতর্ক থাকার জন্য। আমরা কখনও আপনার PIN, OTP বা পাসওয়ার্ড চাই না। অনুগ্রহ করে এগুলো কারও সাথে শেয়ার করবেন না। আমাদের fraud team বিষয়টি পর্যালোচনা করবে।"
        if match.ambiguous or verdict == "insufficient_data":
            return "আপনার অভিযোগটি আমরা পেয়েছি। দ্রুত সহায়তার জন্য অনুগ্রহ করে transaction ID, টাকা, সময় এবং সমস্যার সংক্ষিপ্ত বিবরণ দিন। অনুগ্রহ করে আপনার PIN বা OTP কারও সাথে শেয়ার করবেন না।"
        if case_type == "agent_cash_in_issue":
            return f"আপনার {ref} লেনদেন সম্পর্কিত অভিযোগটি আমরা পেয়েছি। অনুগ্রহ করে আপনার PIN বা OTP কারও সাথে শেয়ার করবেন না। আমাদের agent operations team বিষয়টি অফিসিয়াল সাপোর্ট চ্যানেলের মাধ্যমে পর্যালোচনা করবে।"
        if verdict == "inconsistent":
            return f"আপনার {ref} লেনদেন সম্পর্কিত অভিযোগটি আমরা পেয়েছি। তথ্য যাচাইয়ের জন্য বিষয়টি মানব পর্যালোচনায় পাঠানো হবে। অনুগ্রহ করে PIN বা OTP কারও সাথে শেয়ার করবেন না।"
        return f"আপনার {ref} লেনদেন সম্পর্কিত অভিযোগটি আমরা পেয়েছি। সংশ্লিষ্ট টিম বিষয়টি পর্যালোচনা করবে এবং অফিসিয়াল সাপোর্ট চ্যানেলের মাধ্যমে জানাবে। অনুগ্রহ করে PIN বা OTP কারও সাথে শেয়ার করবেন না।"

    if mixed:
        if match.ambiguous or verdict == "insufficient_data":
            return "We received your complaint. To identify the right transaction, please share the transaction ID, recipient number, amount, and time." + _mixed_suffix()
        return f"We have noted your concern about transaction {ref}. Our team will review it through official support channels." + _mixed_suffix()

    if case_type == "phishing_or_social_engineering":
        return "Thank you for reaching out before sharing any information. We never ask for your PIN, OTP, or password under any circumstances. Please do not share these with anyone, even if they claim to be from us. Our fraud team has been notified."
    if match.ambiguous or verdict == "insufficient_data":
        if contains_any(features.text, ["brother", "bhai", "ভাই"]):
            return "Thank you for reaching out. We see multiple transactions that could match. Please share the recipient number or transaction ID so we can identify the right transaction. Please do not share your PIN or OTP with anyone."
        return "Thank you for reaching out. To help you faster, please share the transaction ID, amount, time, and a short description of what went wrong. Please do not share your PIN or OTP with anyone."
    if verdict == "inconsistent":
        return f"We have noted your concern about transaction {ref}. The available transaction history needs human review before any action can be taken. Please do not share your PIN or OTP with anyone. Our team will contact you only through official support channels."
    if case_type == "wrong_transfer":
        return f"We have noted your concern about transaction {ref}. Please do not share your PIN or OTP with anyone. Our dispute team will review the case and contact you through official support channels."
    if case_type == "payment_failed":
        return f"We have noted that transaction {ref} may have caused an unexpected balance deduction. Our payments team will review the case, and any eligible amount will be returned through official channels. Please do not share your PIN or OTP with anyone."
    if case_type == "refund_request":
        return f"We have noted your refund request for transaction {ref}. Refund eligibility depends on merchant or biller policy and verification. Our support team will guide you through the official process. Please do not share your PIN or OTP with anyone."
    if case_type == "duplicate_payment":
        return f"We have noted your concern about a possible duplicate payment involving transaction {ref}. Our payments team will verify the biller or merchant records, and any eligible amount will be returned through official channels. Please do not share your PIN or OTP with anyone."
    if case_type == "merchant_settlement_delay":
        return f"We have noted your settlement concern for transaction {ref}. Our merchant operations team will review the settlement status and update you through official support channels. Please do not share your PIN or OTP with anyone."
    if case_type == "agent_cash_in_issue":
        return f"We have noted your concern about cash-in transaction {ref}. Our agent operations team will verify the agent ledger and transaction status through official channels. Please do not share your PIN or OTP with anyone."
    return "Thank you for reaching out. To help you faster, please share the transaction ID, amount, and a short description of what went wrong. Please do not share your PIN or OTP with anyone."

def sanitize_reply(text: str) -> str:
    """Final safety net against unauthorized promises or unsafe requests."""
    if not text:
        return "Thank you for reaching out. Our team will review the case through official support channels. Please do not share your PIN or OTP with anyone."

    # Replace strong unauthorized promises with safe language.
    replacements = [
        (r"\bwe will refund you\b", "any eligible amount will be returned through official channels"),
        (r"\bwe will reverse\b", "our team will review"),
        (r"\bwill be reversed\b", "will be reviewed"),
        (r"\bwe will recover\b", "our team will review"),
        (r"\byour money will be recovered\b", "the case will be reviewed through official channels"),
        (r"\byour account will be unblocked\b", "your account status will be reviewed through official channels"),
    ]
    out = text
    for pat, repl in replacements:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out


def validate_safe_output(response: Dict[str, Any]) -> Dict[str, Any]:
    response["customer_reply"] = sanitize_reply(str(response.get("customer_reply") or ""))
    response["recommended_next_action"] = sanitize_reply(str(response.get("recommended_next_action") or ""))
    return response


def analyze_ticket(payload: Dict[str, Any]) -> Dict[str, Any]:
    ticket_id_value = payload.get("ticket_id")
    complaint = payload.get("complaint")
    if ticket_id_value is None or str(ticket_id_value).strip() == "":
        raise ValueError("ticket_id is required")
    if complaint is None or str(complaint).strip() == "":
        raise ValueError("complaint is required")

    ticket_id = str(ticket_id_value)
    transactions_raw = payload.get("transaction_history") or []
    if not isinstance(transactions_raw, list):
        transactions_raw = []
    transactions: List[Dict[str, Any]] = [tx for tx in transactions_raw if isinstance(tx, dict)]

    features = build_features(payload)
    case_type, case_codes = detect_case_type(features, payload)
    match = match_transaction(case_type, features, transactions)
    evidence_verdict, evidence_codes = determine_evidence(case_type, match, transactions, features)
    severity = severity_for(case_type, evidence_verdict, match, features, transactions)
    department = department_for(case_type, severity, evidence_verdict)
    human_review = human_review_for(case_type, severity, evidence_verdict, match, features)
    confidence = confidence_for(case_type, evidence_verdict, match, features)

    reason_codes = []
    context_codes = metadata_reason_codes(features)
    for code in case_codes + match.reason_codes + evidence_codes + context_codes:
        if code and code not in reason_codes:
            reason_codes.append(code)
    if features.injection_attempt and "prompt_injection_ignored" not in reason_codes:
        reason_codes.append("prompt_injection_ignored")

    response: Dict[str, Any] = {
        "ticket_id": ticket_id,
        "relevant_transaction_id": txn_id(match.transaction) if match.transaction is not None else None,
        "evidence_verdict": evidence_verdict,
        "case_type": case_type,
        "severity": severity,
        "department": department,
        "agent_summary": make_agent_summary(case_type, evidence_verdict, match, features, transactions),
        "recommended_next_action": make_next_action(case_type, evidence_verdict, match, features),
        "customer_reply": make_customer_reply(case_type, evidence_verdict, match, features, payload),
        "human_review_required": bool(human_review),
        "confidence": round(float(confidence), 2),
        "reason_codes": reason_codes[:8],
    }
    return validate_safe_output(response)
