"""Annotator labelling, trainer approval of corrections, correction memory and the retrain job.
A clip is a processed video (clip_id = video id); clips with low-confidence steps come first."""
import tempfile

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import corrections, ml_adapter
from ..auth import current_user, require
from ..config import get_settings
from ..db import get_store, now_iso
from ..queue import create_job
from .common import get_video, job_view, latest_job, signed, user_name, video_view

router = APIRouter()


def current_segments(v):
    steps = sorted(get_store().select("steps", {"video_id": v["id"]}), key=lambda s: s["idx"])
    segs = [{"label": s["label"], "start": s["start_s"], "end": s["end_s"], "confidence": s["confidence"]} for s in steps]
    return corrections.fill_background(segs, v.get("duration_s") or (segs[-1]["end"] if segs else 0))


@router.get("/annotations/queue")
def queue(user=Depends(require("annotator"))):
    db = get_store()
    mine = {a["clip_id"]: a for a in db.select("annotations", {"annotator": user["id"]})}
    out = []
    for v in db.select("videos", in_={"status": ["review", "ready"]}):
        a = mine.get(v["id"])
        if a and a["status"] in ("submitted", "accepted", "partly_accepted"):
            continue
        steps = db.select("steps", {"video_id": v["id"]})
        if not steps:
            continue
        low = sum(1 for s in steps if s["low_conf"])
        out.append({"clip_id": v["id"], "title": v["title"], "domain": v.get("domain"), "task": v["task"],
                    "duration_s": v.get("duration_s"), "low_conf": low,
                    "min_conf": min(s["confidence"] for s in steps), "draft": bool(a and a["status"] == "draft"),
                    "sent_back": bool(a and a["status"] == "sent_back")})
    out.sort(key=lambda r: (-r["low_conf"], r["min_conf"]))
    submitted = len([a for a in mine.values() if a["status"] != "draft"])
    reviewed = [a for a in mine.values() if a["status"] in ("accepted", "partly_accepted", "sent_back")]
    agree = (sum(1 for a in reviewed if a["status"] != "sent_back") / len(reviewed) * 100) if reviewed else None
    return {"clips": out, "stats": {"waiting": len(out), "submitted": submitted,
                                    "agreement": round(agree) if agree is not None else None}}


@router.get("/annotations/{clip_id}")
def get_clip(clip_id: str, user=Depends(require("annotator"))):
    db = get_store()
    v = get_video(clip_id)
    if not db.select("steps", {"video_id": v["id"]}, limit=1):
        raise HTTPException(404, "This clip has no model suggestions yet")
    a = db.first("annotations", clip_id=clip_id, annotator=user["id"])
    vocab = ml_adapter.vocab_for(v["task"])
    return {"clip_id": clip_id, "title": v["title"], "task": v["task"], "domain": v.get("domain"),
            "duration_s": v.get("duration_s"), "source_url": signed("raw-videos", v.get("source_path"), 4 * 3600),
            "model_segments": current_segments(v), "vocab": vocab,
            "annotation": a, "transcript": v.get("transcript") or []}


class SegBody(BaseModel):
    segments: list[dict]


def _validate(v, segs):
    vocab = ml_adapter.vocab_for(v["task"])
    clean = []
    for s in segs:
        try:
            item = {"label": str(s["label"]), "start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2),
                    "unclear": bool(s.get("unclear", False)), "accepted": bool(s.get("accepted", False))}
        except (KeyError, ValueError, TypeError):
            raise HTTPException(400, "Each segment needs label, start and end")
        if item["label"] not in vocab:
            raise HTTPException(400, f"Unknown label {item['label']}")
        if item["end"] - item["start"] < 0.2:
            raise HTTPException(400, "Segments must be at least 0.2 s long")
        clean.append(item)
    clean.sort(key=lambda s: s["start"])
    for a, b in zip(clean, clean[1:]):
        if b["start"] < a["end"] - 0.05:
            raise HTTPException(400, "Segments overlap")
    return clean


@router.put("/annotations/{clip_id}")
def save_draft(clip_id: str, body: SegBody, user=Depends(require("annotator"))):
    v = get_video(clip_id)
    segs = _validate(v, body.segments)
    db = get_store()
    a = db.first("annotations", clip_id=clip_id, annotator=user["id"])
    if a and a["status"] == "submitted":
        raise HTTPException(409, "Already submitted; wait for the trainer's review")
    return db.upsert("annotations", {"clip_id": clip_id, "annotator": user["id"], "segments": segs, "status": "draft",
                                     "updated_at": now_iso()}, on=("clip_id", "annotator"))


@router.post("/annotations/{clip_id}/submit")
def submit(clip_id: str, body: SegBody | None = None, user=Depends(require("annotator"))):
    db = get_store()
    v = get_video(clip_id)
    a = db.first("annotations", clip_id=clip_id, annotator=user["id"])
    if a and a["status"] == "submitted":
        raise HTTPException(409, "Already submitted")
    segs = _validate(v, body.segments) if body and body.segments else (a or {}).get("segments")
    if not segs:
        raise HTTPException(400, "Nothing to submit")
    model = current_segments(v)
    ann = [{"label": s["label"], "start": s["start"], "end": s["end"]} for s in segs]
    changes = corrections.compute_changes(model, ann)
    req = db.insert("annotation_requests", {"video_id": v["id"], "annotator_id": user["id"], "trainer_id": v["owner"],
                                            "model_segments": model, "annotator_segments": ann, "changes": changes,
                                            "approved_changes": [], "status": "pending", "note": None,
                                            "created_at": now_iso()})
    db.upsert("annotations", {"clip_id": clip_id, "annotator": user["id"], "segments": segs, "status": "submitted",
                              "request_id": req["id"], "updated_at": now_iso()}, on=("clip_id", "annotator"))
    return {"request_id": req["id"], "changes": len(changes)}


# ---------------------------------------------------------------- trainer side
def _req_view(r, full=False):
    db = get_store()
    v = db.get("videos", r["video_id"])
    out = {**r, "video_title": (v or {}).get("title", "Deleted video"), "annotator_name": user_name(r["annotator_id"])}
    if not full:
        out.pop("model_segments", None)
        out.pop("annotator_segments", None)
    return out


@router.get("/annotation-requests")
def list_requests(status: str = "", user=Depends(require("trainer"))):
    rows = get_store().select("annotation_requests", {"trainer_id": user["id"]}, order="created_at", desc=True)
    if status:
        rows = [r for r in rows if r["status"] == status]
    return [_req_view(r) for r in rows]


def _owned_req(rid, user):
    r = get_store().get("annotation_requests", rid)
    if not r or r["trainer_id"] != user["id"]:
        raise HTTPException(404, "Request not found")
    return r


@router.get("/annotation-requests/{rid}")
def get_request(rid: str, user=Depends(require("trainer"))):
    r = _owned_req(rid, user)
    return {"request": _req_view(r, full=True), "video": video_view(get_video(r["video_id"]), user)}


class ApproveBody(BaseModel):
    change_ids: list[int]
    note: str | None = None


def maybe_auto_retrain(user):
    db = get_store()
    pending = len(db.select("correction_memory", {"used_in_version": None}))
    running = [j for j in db.select("jobs", {"kind": "retrain"}) if j["status"] in ("queued", "running")]
    if pending >= get_settings().retrain_threshold and not running:
        return create_job(None, "retrain", {"auto": True}, "gpu" if get_settings().gpu_queue_enabled else "cpu", user["id"])
    return None


@router.post("/annotation-requests/{rid}/approve")
def approve_request(rid: str, body: ApproveBody, user=Depends(require("trainer"))):
    db = get_store()
    r = _owned_req(rid, user)
    if r["status"] != "pending":
        raise HTTPException(409, f"Request is {r['status']}")
    all_ids = {c["id"] for c in r["changes"]}
    ids = sorted(set(body.change_ids) & all_ids)
    if not ids:
        raise HTTPException(400, "Select at least one change, or send the request back")
    v = get_video(r["video_id"])
    approved = [c for c in r["changes"] if c["id"] in ids]
    new_segs = corrections.apply_changes(r["model_segments"], r["annotator_segments"], ids)       # (a) fix the video
    changed = corrections.rebuild_steps(v, new_segs)
    with tempfile.TemporaryDirectory() as tmp:
        added = corrections.add_to_memory(v, r["id"], approved, tmp)                               # (b) memory, (c) retrain queue
    status = "approved" if len(ids) == len(all_ids) else "partly_approved"
    r = db.update("annotation_requests", {"id": r["id"]}, {"status": status, "approved_changes": ids,
                                                           "note": (body.note or "").strip() or None,
                                                           "reviewed_at": now_iso()})[0]
    db.update("annotations", {"request_id": r["id"]}, {"status": "accepted" if status == "approved" else "partly_accepted",
                                                       "reviewer_note": r.get("note")})
    rerender = None
    if changed and db.select("outputs", {"video_id": v["id"]}, limit=1):
        from .videos import _queue_followup
        try:
            rerender = _queue_followup(v, user, "rerender")["id"]
        except HTTPException:
            rerender = None
    auto = maybe_auto_retrain(user)
    return {"request": _req_view(r), "applied": len(ids), "memory_added": added, "rerender_job": rerender,
            "retrain_job": auto["id"] if auto else None}


class NoteBody(BaseModel):
    note: str | None = None


@router.post("/annotation-requests/{rid}/send-back")
def send_back(rid: str, body: NoteBody, user=Depends(require("trainer"))):
    db = get_store()
    r = _owned_req(rid, user)
    if r["status"] != "pending":
        raise HTTPException(409, f"Request is {r['status']}")
    note = (body.note or "").strip() or None
    r = db.update("annotation_requests", {"id": r["id"]}, {"status": "sent_back", "note": note,
                                                           "reviewed_at": now_iso()})[0]
    db.update("annotations", {"request_id": r["id"]}, {"status": "sent_back", "reviewer_note": note})
    return {"request": _req_view(r)}


# ---------------------------------------------------------------- model learning
@router.get("/model/status")
def model_status(user=Depends(current_user)):
    db = get_store()
    active = ml_adapter.active_version()
    mem = db.select("correction_memory")
    retrains = db.select("jobs", {"kind": "retrain"}, order="created_at", desc=True)
    last_done = next((j for j in retrains if j["status"] == "done"), None)
    running = next((j for j in retrains if j["status"] in ("queued", "running")), None)
    versions = sorted(db.select("model_versions"), key=lambda x: x["version"], reverse=True)
    return {"active_version": (active or {}).get("version", 1), "active_metrics": (active or {}).get("metrics"),
            "pending": sum(1 for m in mem if m.get("used_in_version") is None), "memory": len(mem),
            "threshold": get_settings().retrain_threshold,
            "last_retrain": (last_done or {}).get("finished_at"), "running_job": job_view(running),
            "last_job": job_view(retrains[0]) if retrains else None,
            "versions": [{k: x.get(k) for k in ("version", "active", "metrics", "created_at")} for x in versions],
            "method": "human-in-the-loop active learning"}


@router.post("/model/retrain")
def retrain(user=Depends(require("trainer"))):
    db = get_store()
    if any(j["status"] in ("queued", "running") for j in db.select("jobs", {"kind": "retrain"})):
        raise HTTPException(409, "A retrain is already running")
    if not db.select("correction_memory", {"used_in_version": None}, limit=1):
        raise HTTPException(409, "No approved corrections are waiting for retraining")
    job = create_job(None, "retrain", {"auto": False}, "gpu" if get_settings().gpu_queue_enabled else "cpu", user["id"])
    return {"job_id": job["id"]}
