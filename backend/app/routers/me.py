import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import catalog, costs, plans
from ..auth import ROLES, current_user, is_admin, require
from ..crypto import KeyVaultError, decrypt, encrypt, last4, redact
from ..db import get_store, now_iso
from ..mlpath import kp
from .common import user_name

router = APIRouter()


@router.get("/config")
def config():
    return {"tasks": [{"id": k, **v} for k, v in catalog.TASKS.items()], "domains": catalog.DOMAINS,
            "langs": catalog.LANGS, "target_langs": catalog.TARGET_LANGS, "categories": catalog.CATEGORIES,
            "providers": {"asr": catalog.ASR, "mt": catalog.MT, "tts": catalog.TTS}}


@router.get("/me")
def me(user=Depends(current_user)):
    out = {**user, "is_admin": is_admin(user)}
    if out["is_admin"]:
        out["budget"] = costs.budget_status()
    return out


class RoleBody(BaseModel):
    role: str


@router.put("/me/role")
def set_role(body: RoleBody, user=Depends(current_user)):
    if body.role not in ROLES:
        raise HTTPException(400, f"role must be one of {ROLES}")
    return get_store().update("users", {"id": user["id"]}, {"role": body.role})[0]


# ---------------------------------------------------------------- plan and keys
@router.get("/me/plan")
def get_plan(user=Depends(require("trainer"))):
    return plans.plan_view(user["id"])


class PlanBody(BaseModel):
    plan: str | None = None
    asr: str | None = None
    mt: str | None = None
    tts: str | None = None


@router.put("/me/plan")
def put_plan(body: PlanBody, user=Depends(require("trainer"))):
    return plans.update_plan(user["id"], body.model_dump())


class KeyBody(BaseModel):
    key: str

    def __repr__(self):                 # never show the key in tracebacks or logs
        return "KeyBody(key=[hidden])"

    __str__ = __repr__


def _provider(p):
    if p not in plans.KEY_PROVIDERS:
        raise HTTPException(404, f"provider must be one of {plans.KEY_PROVIDERS}")
    return p


@router.put("/me/keys/{provider}")
def put_key(provider: str, body: KeyBody, user=Depends(require("trainer"))):
    _provider(provider)
    key = body.key.strip()
    if len(key) < 12 or any(c.isspace() for c in key):
        raise HTTPException(400, "That key looks too short or has spaces. Paste the full key.")
    try:
        enc = encrypt(key)
    except KeyVaultError as e:
        raise HTTPException(500, str(e))
    get_store().upsert("user_api_keys", {"user_id": user["id"], "provider": provider, "encrypted_key": enc,
                                         "last4": last4(key), "verified_at": None, "updated_at": now_iso()},
                       on=("user_id", "provider"))
    return plans.plan_view(user["id"])


@router.delete("/me/keys/{provider}")
def delete_key(provider: str, user=Depends(require("trainer"))):
    _provider(provider)
    db = get_store()
    db.delete("user_api_keys", {"user_id": user["id"], "provider": provider})
    p = plans.get_plan(user["id"])
    if p["plan"] == "byok" and not plans.byok_ready(plans.key_rows(user["id"])):
        db.update("user_plans", {"id": p["id"]}, {"plan": "free"})
    return plans.plan_view(user["id"])


def check_key(provider, key):
    """Cheapest real call per provider. Returns (ok, message)."""
    try:
        if provider == "sarvam":
            r = httpx.post(f"{kp.SARVAM}/translate", headers={"api-subscription-key": key}, timeout=30,
                           json={"input": "ok", "source_language_code": "en-IN", "target_language_code": "hi-IN",
                                 "model": "sarvam-translate:v1"})
        elif provider == "gemini":
            r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 1},
                          headers={"x-goog-api-key": key}, timeout=30)
        else:
            r = httpx.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    except Exception as e:
        return False, "Could not reach the provider: " + redact(e, key)[:120]
    if r.status_code == 200:
        return True, "Key works"
    if r.status_code == 402:
        return False, "Key is valid but the account has no credits left (HTTP 402)"
    if r.status_code == 429:
        return True, "Key works but is rate limited right now (HTTP 429)"
    if r.status_code in (401, 403):
        return False, "The provider rejected this key"
    return False, f"Provider answered HTTP {r.status_code}"


@router.post("/me/keys/{provider}/test")
def test_key(provider: str, user=Depends(require("trainer"))):
    _provider(provider)
    db = get_store()
    row = db.first("user_api_keys", user_id=user["id"], provider=provider)
    if not row:
        raise HTTPException(404, "Save the key first")
    try:
        ok, msg = check_key(provider, decrypt(row["encrypted_key"]))
    except KeyVaultError as e:
        raise HTTPException(500, str(e))
    db.update("user_api_keys", {"id": row["id"]}, {"verified_at": now_iso() if ok else None})
    return {"ok": ok, "message": msg, "plan": plans.plan_view(user["id"])}


# ---------------------------------------------------------------- learner history and reports
@router.get("/me/history")
def history(user=Depends(current_user)):
    db = get_store()
    watched = db.select("watch_history", {"user_id": user["id"]}, order="updated_at", desc=True)
    attempts = db.select("quiz_attempts", {"user_id": user["id"]}, order="created_at", desc=True)
    rows, seen = [], set()
    for w in watched:
        v = db.get("videos", w["video_id"])
        if not v:
            continue
        a = next((x for x in attempts if x["video_id"] == w["video_id"]), None)
        rows.append({"video_id": v["id"], "title": v["title"], "progress": w.get("progress", 0), "lang": w.get("lang"),
                     "updated_at": w.get("updated_at"),
                     "quiz": f"{a['score']}/{a['total']}" if a else None})
        seen.add(v["id"])
    for a in attempts:
        if a["video_id"] not in seen:
            v = db.get("videos", a["video_id"])
            rows.append({"video_id": a["video_id"], "title": (v or {}).get("title", "Deleted video"), "progress": 100,
                         "updated_at": a["created_at"], "quiz": f"{a['score']}/{a['total']}"})
            seen.add(a["video_id"])
    langs = [w.get("lang") for w in watched if w.get("lang")]
    pref = max(set(langs), key=langs.count) if langs else None
    return {"items": rows, "videos_watched": len(watched), "quizzes_taken": len(attempts),
            "preferred_lang": pref}


@router.get("/me/tickets")
def my_tickets(user=Depends(current_user)):
    db = get_store()
    out = []
    for t in db.select("tickets", {"reporter_id": user["id"]}, order="created_at", desc=True):
        v = db.get("videos", t["video_id"])
        out.append({**t, "video_title": (v or {}).get("title", "Deleted video")})
    return out


@router.get("/me/annotations")
def my_annotations(user=Depends(require("annotator"))):
    db = get_store()
    out = []
    for a in db.select("annotations", {"annotator": user["id"]}, order="updated_at", desc=True):
        v = db.get("videos", a["clip_id"])
        req = db.get("annotation_requests", a["request_id"]) if a.get("request_id") else None
        out.append({"clip_id": a["clip_id"], "title": (v or {}).get("title", "Deleted video"), "status": a["status"],
                    "segments": len(a.get("segments") or []), "updated_at": a.get("updated_at"),
                    "reviewer_note": a.get("reviewer_note"), "request_status": (req or {}).get("status"),
                    "trainer": user_name((req or {}).get("trainer_id"))})
    return out
