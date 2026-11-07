"""Supabase JWT verification. New Supabase projects sign tokens with asymmetric keys (verified with the
project's JWKS); legacy projects use the HS256 JWT secret. DEV_AUTH adds locally signed tokens for
offline development only."""
import time
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException

from .config import get_settings
from .db import get_store, now_iso

ROLES = ("trainer", "learner", "annotator")
DEV_ISS = "kaushaldub-dev"


@lru_cache
def _jwks_client(url):
    return jwt.PyJWKClient(url, cache_keys=True)


def verify_token(token: str) -> dict:
    s = get_settings()
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid token")
    if unverified.get("iss") == DEV_ISS:
        if not s.dev_auth:
            raise HTTPException(401, "Dev tokens are disabled")
        try:
            return jwt.decode(token, s.dev_jwt_secret, algorithms=["HS256"], audience="authenticated")
        except jwt.PyJWTError as e:
            raise HTTPException(401, f"Invalid dev token: {e}")
    try:
        alg = jwt.get_unverified_header(token).get("alg", "HS256")
        if alg == "HS256":
            if not s.supabase_jwt_secret:
                raise HTTPException(401, "Server has no SUPABASE_JWT_SECRET for HS256 tokens")
            return jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        if not s.supabase_url:
            raise HTTPException(401, "Server has no SUPABASE_URL to verify tokens")
        key = _jwks_client(s.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json").get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["ES256", "RS256", "EdDSA"], audience="authenticated")
    except HTTPException:
        raise
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired, sign in again")
    except Exception as e:
        raise HTTPException(401, f"Invalid token: {type(e).__name__}")


def make_dev_token(user_id, email, name, hours=12):
    s = get_settings()
    now = int(time.time())
    return jwt.encode({"sub": user_id, "email": email, "aud": "authenticated", "iss": DEV_ISS, "iat": now,
                       "exp": now + hours * 3600, "user_metadata": {"full_name": name}}, s.dev_jwt_secret, "HS256")


def ensure_user(claims: dict) -> dict:
    db = get_store()
    uid = claims["sub"]
    u = db.get("users", uid)
    if u:
        return u
    meta = claims.get("user_metadata") or {}
    email = claims.get("email", "")
    return db.insert("users", {"id": uid, "email": email, "role": "learner",
                               "name": meta.get("full_name") or meta.get("name") or email.split("@")[0],
                               "avatar_url": meta.get("avatar_url"), "created_at": now_iso()})


def current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first")
    return ensure_user(verify_token(authorization.split(" ", 1)[1].strip()))


def require(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, f"This needs the {' or '.join(roles)} role (you are {user['role']})")
        return user
    return dep


def is_admin(user) -> bool:
    return user.get("email", "").lower() in get_settings().admins
