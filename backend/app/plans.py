"""Plan and quota rules, enforced by the API (the UI only mirrors them).

free  : first FREE_VIDEOS videos on the platform's keys (and only while the monthly platform budget lasts)
byok  : the user's own keys; Sarvam is required plus Gemini or Groq
local : AI4Bharat models on the GPU worker, no keys
pro   : "coming soon"; cannot be selected (no payment code)"""
from fastapi import HTTPException

from . import catalog, costs
from .config import get_settings
from .crypto import decrypt
from .db import get_store, now_iso

PLANS = ("free", "byok", "local", "pro")
DEFAULTS = {"plan": "free", "free_used": 0, "asr": "sarvam", "mt": "sarvam", "tts": "sarvam"}
LOCAL_DEFAULTS = {"asr": "whisper", "mt": "indictrans2", "tts": "indicparler"}
KEY_PROVIDERS = ("sarvam", "gemini", "groq")


class PlanError(HTTPException):
    def __init__(self, code, message, status=402):
        super().__init__(status, {"code": code, "message": message})


def get_plan(user_id) -> dict:
    db = get_store()
    p = db.first("user_plans", user_id=user_id)
    if not p:
        p = db.upsert("user_plans", {"user_id": user_id, **DEFAULTS, "updated_at": now_iso()}, on=("user_id",))
    return p


def key_rows(user_id) -> dict:
    return {r["provider"]: r for r in get_store().select("user_api_keys", {"user_id": user_id})}


def public_keys(user_id) -> dict:
    """What the browser may see about stored keys: only the last 4 characters and test status."""
    return {p: {"last4": r.get("last4"), "verified_at": r.get("verified_at"), "saved": True}
            for p, r in key_rows(user_id).items()}


def byok_ready(keys: dict) -> bool:
    return "sarvam" in keys and ("gemini" in keys or "groq" in keys)


def plan_view(user_id) -> dict:
    s = get_settings()
    p = get_plan(user_id)
    keys = public_keys(user_id)
    free_left = max(0, s.free_videos - int(p.get("free_used") or 0))
    ok, reason = can_process(p, keys)
    return {"plan": p["plan"], "free_used": p.get("free_used", 0), "free_total": s.free_videos, "free_left": free_left,
            "asr": p.get("asr"), "mt": p.get("mt"), "tts": p.get("tts"), "keys": keys,
            "can_process": ok, "blocked_reason": reason, "gpu_queue_enabled": s.gpu_queue_enabled}


def can_process(plan: dict, keys: dict):
    s = get_settings()
    mode = plan["plan"]
    if mode == "free":
        if int(plan.get("free_used") or 0) >= s.free_videos:
            return False, f"Your {s.free_videos} free videos are used. Add your own API keys or switch to the free local models."
        if costs.budget_status()["exhausted"]:
            return False, "The platform's monthly budget for free videos is used up. Use your own keys or the local models."
        return True, None
    if mode == "byok":
        if not byok_ready(keys):
            return False, "Add a Sarvam key and a Gemini or Groq key first."
        return True, None
    if mode == "local":
        return True, None
    return False, "Pro is coming soon."


def update_plan(user_id, body: dict) -> dict:
    db = get_store()
    p = get_plan(user_id)
    vals = {}
    if "plan" in body and body["plan"] is not None:
        if body["plan"] not in PLANS:
            raise PlanError("bad_plan", f"Unknown plan {body['plan']}", 400)
        if body["plan"] == "pro":
            raise PlanError("pro_coming_soon", "Pro is coming soon. No payments are set up yet.", 400)
        if body["plan"] == "byok" and not byok_ready(key_rows(user_id)):
            raise PlanError("keys_missing", "Save a Sarvam key and a Gemini or Groq key before choosing this plan.", 400)
        vals["plan"] = body["plan"]
    for stage, allowed in (("asr", catalog.ASR), ("mt", catalog.MT), ("tts", catalog.TTS)):
        if body.get(stage):
            if body[stage] not in allowed:
                raise PlanError("bad_provider", f"{stage} must be one of {allowed}", 400)
            vals[stage] = body[stage]
    if vals:
        vals["updated_at"] = now_iso()
        p = db.update("user_plans", {"id": p["id"]}, vals)[0]
    return plan_view(user_id)


def check_and_reserve(user_id, overrides: dict | None = None) -> dict:
    """Called by POST /videos before anything is stored. Raises PlanError when the user may not process,
    otherwise counts the free video and returns the job's provider config (no secrets in it)."""
    db = get_store()
    s = get_settings()
    p = get_plan(user_id)
    keys = key_rows(user_id)
    ok, reason = can_process(p, keys)
    if not ok:
        code = {"free": "free_quota_used", "byok": "keys_missing"}.get(p["plan"], "plan_blocked")
        if p["plan"] == "free" and costs.budget_status()["exhausted"] and int(p.get("free_used") or 0) < s.free_videos:
            code = "platform_budget_reached"
        raise PlanError(code, reason)
    cfg = {"plan": p["plan"], "asr": p.get("asr") or "sarvam", "mt": p.get("mt") or "sarvam",
           "tts": p.get("tts") or "sarvam"}
    for stage, allowed in (("asr", catalog.ASR), ("mt", catalog.MT), ("tts", catalog.TTS)):
        v = (overrides or {}).get(stage)
        if v:
            if v not in allowed:
                raise PlanError("bad_provider", f"{stage} must be one of {allowed}", 400)
            cfg[stage] = v
    if p["plan"] == "local":
        for stage in ("asr", "mt", "tts"):
            if cfg[stage] not in catalog.LOCAL:
                cfg[stage] = LOCAL_DEFAULTS[stage]
    cfg["key_source"] = {"free": "platform", "byok": "user", "local": "none"}[p["plan"]]
    cfg["queue"] = job_queue(cfg)
    if p["plan"] == "free":
        db.update("user_plans", {"id": p["id"]}, {"free_used": int(p.get("free_used") or 0) + 1, "updated_at": now_iso()})
    return cfg


def followup_config(user_id) -> dict:
    """Provider config for work on a video that was already counted (approve/dub, re-voice, re-render, resume):
    no free video is consumed again, but byok keys and the platform budget still apply."""
    p = get_plan(user_id)
    cfg = {"plan": p["plan"], "asr": p.get("asr") or "sarvam", "mt": p.get("mt") or "sarvam",
           "tts": p.get("tts") or "sarvam"}
    if p["plan"] == "byok" and not byok_ready(key_rows(user_id)):
        raise PlanError("keys_missing", "Add a Sarvam key and a Gemini or Groq key first.")
    if p["plan"] == "free" and costs.budget_status()["exhausted"]:
        raise PlanError("platform_budget_reached", "The platform's monthly budget is used up. Use your own keys or "
                                                   "the free local models.")
    if p["plan"] == "local":
        for stage in ("asr", "mt", "tts"):
            if cfg[stage] not in catalog.LOCAL:
                cfg[stage] = LOCAL_DEFAULTS[stage]
    cfg["key_source"] = {"free": "platform", "byok": "user", "local": "none", "pro": "platform"}[p["plan"]]
    cfg["queue"] = job_queue(cfg)
    return cfg


def refund_free(user_id):
    p = get_plan(user_id)
    if p["plan"] == "free" and int(p.get("free_used") or 0) > 0:
        get_store().update("user_plans", {"id": p["id"]}, {"free_used": int(p["free_used"]) - 1})


def job_queue(cfg) -> str:
    s = get_settings()
    wants_gpu = cfg["plan"] == "local" or any(cfg.get(k) in catalog.GPU_ONLY for k in ("asr", "mt", "tts"))
    return "gpu" if wants_gpu and s.gpu_queue_enabled else "cpu"


def runtime_keys(owner_id, key_source) -> dict:
    """Plain keys for one job, resolved inside the worker only. Never stored in the job row or logs."""
    s = get_settings()
    if key_source == "platform":
        return {"sarvam": s.sarvam_api_key, "gemini": s.gemini_api_key, "groq": s.groq_api_key, "hf": s.hf_token}
    out = {"sarvam": "", "gemini": "", "groq": "", "hf": s.hf_token}
    for prov, row in key_rows(owner_id).items():
        out[prov] = decrypt(row["encrypted_key"])
    return out
