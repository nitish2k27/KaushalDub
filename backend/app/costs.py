"""Estimated provider cost per job and the monthly cap for jobs that run on the platform's keys.
Rates are estimates in INR; check Sarvam's pricing page and override with env vars if they change."""
import os
from datetime import datetime, timezone

from .config import get_settings
from .db import get_store

RATES = {
    "sarvam_stt_per_min": float(os.getenv("RATE_SARVAM_STT_PER_MIN", "0.49")),       # sarvam.ai/api-pricing (Nov 2026)
    "sarvam_mt_per_10k_chars": float(os.getenv("RATE_SARVAM_MT_PER_10K", "20")),
    "sarvam_tts_per_10k_chars": float(os.getenv("RATE_SARVAM_TTS_PER_10K", "30")),
}


def empty_cost():
    return {"audio_min": 0.0, "mt_chars": 0, "tts_chars": 0, "inr": 0.0, "by_provider": {}}


def add(cost, provider, *, audio_min=0.0, mt_chars=0, tts_chars=0):
    cost["audio_min"] = round(cost["audio_min"] + audio_min, 3)
    cost["mt_chars"] += mt_chars
    cost["tts_chars"] += tts_chars
    inr = 0.0
    if provider == "sarvam":
        inr = (audio_min * RATES["sarvam_stt_per_min"] + mt_chars / 1e4 * RATES["sarvam_mt_per_10k_chars"]
               + tts_chars / 1e4 * RATES["sarvam_tts_per_10k_chars"])
    cost["inr"] = round(cost["inr"] + inr, 2)
    cost["by_provider"][provider] = round(cost["by_provider"].get(provider, 0.0) + inr, 2)
    return cost


def month_start_iso():
    n = datetime.now(timezone.utc)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def platform_spend_this_month() -> float:
    start = month_start_iso()
    jobs = get_store().select("jobs", {"key_source": "platform"})
    return round(sum((j.get("cost") or {}).get("inr", 0.0) for j in jobs if (j.get("created_at") or "") >= start), 2)


def budget_status():
    s = get_settings()
    spent = platform_spend_this_month()
    cap = s.platform_budget_inr
    return {"spent_inr": spent, "budget_inr": cap, "remaining_inr": round(max(0.0, cap - spent), 2),
            "exhausted": spent >= cap, "low": spent >= cap * s.low_balance_warn_ratio}
