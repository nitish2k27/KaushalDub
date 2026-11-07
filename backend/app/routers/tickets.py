"""Learner reports ("tickets") at a timestamp, answered by the video's trainer."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import catalog
from ..auth import require
from ..db import get_store, now_iso
from .common import get_video, step_at, user_name, video_view, viewable_video
from .videos import set_step_text

router = APIRouter()


class TicketBody(BaseModel):
    lang: str
    timestamp_s: float
    category: str
    message: str


@router.post("/videos/{video_id}/tickets")
def create_ticket(video_id: str, body: TicketBody, user=Depends(require("learner"))):
    v = viewable_video(video_id, user)
    if not v.get("published"):
        raise HTTPException(409, "Reports can be sent on published videos")
    if body.category not in catalog.CATEGORIES:
        raise HTTPException(400, f"category must be one of {catalog.CATEGORIES}")
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Add a short message so the trainer knows what to fix")
    if body.lang not in ["en"] + list(v.get("targets") or []):
        raise HTTPException(400, "Unknown language version")
    db = get_store()
    steps = sorted(db.select("steps", {"video_id": v["id"]}), key=lambda s: s["idx"])
    t = max(0.0, min(float(body.timestamp_s), float(v.get("duration_s") or body.timestamp_s)))
    return db.insert("tickets", {"video_id": v["id"], "trainer_id": v["owner"], "reporter_id": user["id"],
                                 "lang": body.lang, "timestamp_s": round(t, 2), "step_idx": step_at(steps, t),
                                 "category": body.category, "message": msg[:2000], "status": "open", "reply": None,
                                 "created_at": now_iso(), "closed_at": None})


def _view(t):
    db = get_store()
    v = db.get("videos", t["video_id"])
    return {**t, "video_title": (v or {}).get("title", "Deleted video"), "reporter_name": user_name(t["reporter_id"])}


@router.get("/tickets")
def list_tickets(status: str = "open", user=Depends(require("trainer"))):
    rows = get_store().select("tickets", {"trainer_id": user["id"]}, order="created_at", desc=True)
    if status == "open":
        rows = [r for r in rows if r["status"] == "open"]
    elif status == "closed":
        rows = [r for r in rows if r["status"] != "open"]
    return [_view(r) for r in rows]


def _owned_ticket(ticket_id, user):
    t = get_store().get("tickets", ticket_id)
    if not t or t["trainer_id"] != user["id"]:
        raise HTTPException(404, "Report not found")
    return t


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, user=Depends(require("trainer"))):
    t = _owned_ticket(ticket_id, user)
    return {"ticket": _view(t), "video": video_view(get_video(t["video_id"]), user)}


class TicketPatch(BaseModel):
    text: str | None = None          # new text for the reported step in the reported language
    reply: str | None = None
    status: str | None = None        # resolved | closed


@router.patch("/tickets/{ticket_id}")
def patch_ticket(ticket_id: str, body: TicketPatch, user=Depends(require("trainer"))):
    db = get_store()
    t = _owned_ticket(ticket_id, user)
    v = get_video(t["video_id"])
    if t["status"] != "open" and (body.text is not None or body.status):
        raise HTTPException(409, "This report is already closed")
    vals = {}
    if body.text is not None and t.get("step_idx"):
        set_step_text(v, t["step_idx"], t["lang"], body.text)
        vals["fixed_text"] = True
    if body.reply is not None:
        vals["reply"] = body.reply.strip()[:2000] or None
    if body.status:
        if body.status not in ("resolved", "closed"):
            raise HTTPException(400, "status must be resolved or closed")
        vals["status"] = body.status
        vals["closed_at"] = now_iso()
        if not vals.get("reply") and not t.get("reply"):
            vals["reply"] = ("Fixed the step at this moment." if body.status == "resolved"
                             else "Checked: no change needed.")
    if vals:
        t = db.update("tickets", {"id": t["id"]}, vals)[0]
    return {"ticket": _view(t), "video": video_view(get_video(t["video_id"]), user)}
