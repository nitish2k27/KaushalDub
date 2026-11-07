import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import costs
from ..auth import ROLES, current_user, ensure_user, is_admin, make_dev_token
from ..config import get_settings
from ..db import get_store
from ..queue import worker_status
from ..storage import LocalStorage, get_storage

router = APIRouter()


@router.get("/health")
def health():
    s = get_settings()
    return {"ok": True, "store": "supabase" if s.use_supabase else "sqlite", "queue": worker_status(),
            "step_model": s.step_model, "dev_auth": s.dev_auth}


@router.get("/admin/budget")
def admin_budget(user=Depends(current_user)):
    if not is_admin(user):
        raise HTTPException(403, "Admins only (ADMIN_EMAILS)")
    jobs = get_store().select("jobs", {"key_source": "platform"}, order="created_at", desc=True, limit=200)
    start = costs.month_start_iso()
    month = [j for j in jobs if (j.get("created_at") or "") >= start]
    return {**costs.budget_status(), "rates": costs.RATES, "jobs_this_month": len(month),
            "recent": [{"id": j["id"], "kind": j["kind"], "status": j["status"], "cost": j.get("cost"),
                        "created_at": j["created_at"]} for j in month[:30]],
            "queue": worker_status()}


class DevLogin(BaseModel):
    email: str
    name: str
    role: str = "learner"


@router.post("/dev/login")
def dev_login(body: DevLogin):
    """Offline development only (DEV_AUTH=true). Production uses Supabase Google sign-in."""
    if not get_settings().dev_auth:
        raise HTTPException(404, "Not found")
    if body.role not in ROLES:
        raise HTTPException(400, "bad role")
    db = get_store()
    existing = next((u for u in db.select("users") if u.get("email") == body.email.lower()), None)
    uid = existing["id"] if existing else str(uuid.uuid5(uuid.NAMESPACE_URL, "dev:" + body.email.lower()))
    token = make_dev_token(uid, body.email.lower(), body.name)
    ensure_user({"sub": uid, "email": body.email.lower(), "user_metadata": {"full_name": body.name}})
    db.update("users", {"id": uid}, {"role": body.role})
    return {"access_token": token, "user": db.get("users", uid)}


@router.get("/files/{bucket}/{path:path}")
def local_file(bucket: str, path: str, exp: int, sig: str):
    st = get_storage()
    if not isinstance(st, LocalStorage):
        raise HTTPException(404, "Not found")
    if not st.verify(bucket, path, exp, sig):
        raise HTTPException(403, "Link expired")
    full = st.local_path(bucket, path)
    if not os.path.exists(full):
        raise HTTPException(404, "Not found")
    return FileResponse(full)
