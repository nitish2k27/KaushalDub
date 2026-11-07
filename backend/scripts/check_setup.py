"""Check that .env is filled in correctly. Prints OK / problem per item, never the keys themselves.

    backend/.venv/Scripts/python backend/scripts/check_setup.py

Calls made: Supabase (read tables, list buckets, one tiny upload+delete in `outputs`), Gemini and Groq model lists
(free), Sarvam one 2-character translation (costs a fraction of a paisa), Redis PING, Hugging Face whoami."""
import os
import sys
import uuid

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from app.config import get_settings  # noqa: E402

s = get_settings()
ok_all = True


def line(ok, name, msg=""):
    global ok_all
    ok_all &= bool(ok) or ok is None
    mark = "OK  " if ok else ("--  " if ok is None else "FAIL")
    print(f"[{mark}] {name}{': ' + msg if msg else ''}")


TABLES = ["users", "videos", "steps", "translations", "outputs", "tts_clips", "quizzes", "quiz_attempts", "watch_history",
          "tickets", "annotations", "annotation_requests", "correction_memory", "model_versions", "user_plans",
          "user_api_keys", "jobs"]

print("Supabase")
if not s.supabase_url:
    line(None, "SUPABASE_URL", "empty (app runs on local SQLite)")
else:
    from app.db import SupabaseStore, service_headers
    from app.storage import SupabaseStorage
    line(s.supabase_url.startswith("https://") and ".supabase.co" in s.supabase_url, "SUPABASE_URL format")
    line(bool(s.supabase_anon_key), "SUPABASE_ANON_KEY set", "" if s.supabase_anon_key else "copy the anon / publishable key")
    if not s.supabase_service_key:
        line(False, "SUPABASE_SERVICE_KEY", "empty: copy the service_role / secret key")
    else:
        st = SupabaseStore(s.supabase_url, s.supabase_service_key)
        missing = []
        for t in TABLES:
            try:
                st.select(t, limit=1)
            except Exception as e:
                missing.append(t if "404" in str(e) or "PGRST205" in str(e) or "does not exist" in str(e) else f"{t} ({str(e)[:80]})")
        line(not missing, "tables (migration 1)", "missing: " + ", ".join(missing) if missing else f"{len(TABLES)} found")
        r = httpx.get(f"{s.supabase_url.rstrip('/')}/rest/v1/videos", params={"select": "dub_mode,segment_texts", "limit": 1},
                      headers=service_headers(s.supabase_service_key), timeout=20)
        line(r.status_code == 200, "full-speech columns (migration 4)",
             "" if r.status_code == 200 else "run supabase/migrations/20261107000004_full_speech_dub.sql")
        try:
            mv = st.select("model_versions", {"active": True})
            line(bool(mv), "model version 1 seeded", "" if mv else "run migration 1 again")
        except Exception:
            pass
        r = httpx.get(f"{s.supabase_url.rstrip('/')}/storage/v1/bucket", headers=service_headers(s.supabase_service_key), timeout=20)
        names = {b["name"] for b in r.json()} if r.status_code == 200 else set()
        need = {"raw-videos", "outputs", "keyframes"}
        line(need <= names, "storage buckets (migration 3)", f"HTTP {r.status_code}" if r.status_code != 200 else
             ("missing: " + ", ".join(sorted(need - names)) if need - names else "3 found"))
        if need <= names:
            try:
                sto = SupabaseStorage(s.supabase_url, s.supabase_service_key)
                p = f"_setup_check/{uuid.uuid4().hex}.txt"
                sto.put_bytes("outputs", p, b"ok", "text/plain")
                url = sto.signed_url("outputs", p, 60)
                got = httpx.get(url, timeout=20).text if url else ""
                sto.delete("outputs", p)
                line(got == "ok", "storage upload + signed URL")
            except Exception as e:
                line(False, "storage upload + signed URL", str(e)[:120])
    r = httpx.get(f"{s.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json", timeout=20)
    keys = r.json().get("keys", []) if r.status_code == 200 else []
    if keys:
        line(True, "sign-in tokens", "asymmetric JWT keys found (SUPABASE_JWT_SECRET not needed)")
    else:
        line(bool(s.supabase_jwt_secret), "SUPABASE_JWT_SECRET",
             "set" if s.supabase_jwt_secret else "project uses the legacy HS256 secret: copy it from Project Settings → JWT Keys")
    r = httpx.get(f"{s.supabase_url.rstrip('/')}/auth/v1/settings", headers={"apikey": s.supabase_anon_key or ""}, timeout=20)
    if r.status_code == 200:
        line(r.json().get("external", {}).get("google"), "Google sign-in enabled", "" if r.json().get("external", {}).get("google")
             else "Authentication → Sign In / Providers → Google")
    if s.dev_auth:
        line(False, "DEV_AUTH", "must be false when Supabase is used (sign in with Google instead)")

print("\nKeys")
line(bool(s.key_encryption_secret), "KEY_ENCRYPTION_SECRET", "" if s.key_encryption_secret else "generate it (see .env.example)")
if s.key_encryption_secret:
    try:
        from cryptography.fernet import Fernet
        Fernet(s.key_encryption_secret.encode())
        line(True, "KEY_ENCRYPTION_SECRET format")
    except Exception:
        line(False, "KEY_ENCRYPTION_SECRET format", "not a Fernet key; generate a new one")
from app.routers.me import check_key  # noqa: E402
for name, key in (("SARVAM_API_KEY", s.sarvam_api_key), ("GEMINI_API_KEY", s.gemini_api_key), ("GROQ_API_KEY", s.groq_api_key)):
    if not key:
        line(None if name == "GROQ_API_KEY" else False, name, "empty")
        continue
    ok, msg = check_key(name.split("_")[0].lower(), key)
    line(ok, name, msg)
if s.hf_token:
    r = httpx.get("https://huggingface.co/api/whoami-v2", headers={"Authorization": f"Bearer {s.hf_token}"}, timeout=20)
    line(r.status_code == 200, "HF_TOKEN", f"user {r.json().get('name')}" if r.status_code == 200 else f"HTTP {r.status_code}")
else:
    line(None, "HF_TOKEN", "empty (only needed for the local AI4Bharat models)")

print("\nQueue")
if s.redis_url:
    try:
        from redis import Redis
        line(Redis.from_url(s.redis_url, socket_timeout=10).ping(), "REDIS_URL ping")
    except Exception as e:
        line(False, "REDIS_URL", str(e)[:120])
else:
    line(None, "REDIS_URL", "empty (jobs run inside the API; fine on a laptop)")

print("\nModel")
mp = os.path.join(s.model_bundle_dir, "model.pt")
line(os.path.exists(mp), "step model bundle", s.model_bundle_dir)
line(s.step_model == "bundle", "STEP_MODEL=bundle", s.step_model)
line(not s.mock_providers, "MOCK_PROVIDERS=false", "true means fake voices" if s.mock_providers else "")

print("\nAll good." if ok_all else "\nFix the FAIL lines, then run this again.")
