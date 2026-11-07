"""Supabase JWT verification paths and the PostgREST query builder (no network)."""
import time

import jwt

from app.config import reset_settings
from app.db import SupabaseStore

SECRET = "super-secret-jwt-token-with-at-least-32-characters"


def token(**over):
    now = int(time.time())
    claims = {"sub": "11111111-1111-1111-1111-111111111111", "email": "nitish@example.com", "aud": "authenticated",
              "iss": "https://proj.supabase.co/auth/v1", "iat": now, "exp": now + 600,
              "user_metadata": {"full_name": "Nitish"}, **over}
    return jwt.encode(claims, SECRET, "HS256")


def test_supabase_hs256_token(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    reset_settings()
    r = client.get("/me", headers={"Authorization": f"Bearer {token()}"})
    assert r.status_code == 200 and r.json()["name"] == "Nitish" and r.json()["role"] == "learner"
    assert client.put("/me/role", json={"role": "trainer"}, headers={"Authorization": f"Bearer {token()}"}).json()["role"] == "trainer"
    assert client.put("/me/role", json={"role": "admin"}, headers={"Authorization": f"Bearer {token()}"}).status_code == 400


def test_rejects_bad_tokens(client, monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    reset_settings()
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": f"Bearer {token(exp=int(time.time()) - 5)}"}).status_code == 401
    assert client.get("/me", headers={"Authorization": f"Bearer {token(aud='anon')}"}).status_code == 401
    forged = jwt.encode({"sub": "x", "aud": "authenticated", "exp": int(time.time()) + 60}, "wrong" * 10, "HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_dev_login_disabled_by_default(client, monkeypatch):
    monkeypatch.setenv("DEV_AUTH", "false")
    reset_settings()
    assert client.post("/dev/login", json={"email": "a@b.c", "name": "A"}).status_code == 404


def test_postgrest_params():
    s = SupabaseStore("https://proj.supabase.co", "service")
    p = s._params({"video_id": "v1", "published": True, "used_in_version": None}, {"status": ["review", "ready"]},
                  order="created_at", desc=True, limit=5)
    assert p == {"select": "*", "video_id": "eq.v1", "published": "eq.true", "used_in_version": "is.null",
                 "status": 'in.("review","ready")', "order": "created_at.desc", "limit": "5"}
    assert s.select("videos", in_={"status": []}) == []


def test_service_key_headers():
    from app.db import service_headers
    assert service_headers("sb_secret_abc") == {"apikey": "sb_secret_abc"}
    assert service_headers("eyJhbGciOi.x.y")["Authorization"] == "Bearer eyJhbGciOi.x.y"
