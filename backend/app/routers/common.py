from fastapi import HTTPException

from .. import catalog
from ..db import get_store
from ..storage import get_storage


def signed(bucket, path, expires=3600):
    if not path:
        return None
    try:
        return get_storage().signed_url(bucket, path, expires)
    except Exception:
        return None


def get_video(video_id) -> dict:
    v = get_store().get("videos", video_id)
    if not v:
        raise HTTPException(404, "Video not found")
    return v


def owned_video(video_id, user) -> dict:
    v = get_video(video_id)
    if v["owner"] != user["id"]:
        raise HTTPException(403, "Only the trainer who uploaded this video can do that")
    return v


def can_view(v, user) -> bool:
    if v["owner"] == user["id"] or v.get("published"):
        return True
    return user["role"] == "annotator" and bool(v.get("model_segments"))


def viewable_video(video_id, user) -> dict:
    v = get_video(video_id)
    if not can_view(v, user):
        raise HTTPException(403, "This video is not published")
    return v


def user_name(uid):
    u = get_store().get("users", uid) if uid else None
    return (u or {}).get("name") or "Unknown"


def step_at(steps, t):
    """Index (1-based) of the step on screen at time t; before the first step -> 1, between steps -> previous."""
    cur = steps[0]["idx"] if steps else None
    for s in steps:
        if s["start_s"] <= t:
            cur = s["idx"]
    return cur


def latest_job(video_id, kinds=None):
    jobs = get_store().select("jobs", {"video_id": video_id}, order="created_at", desc=True)
    jobs = [j for j in jobs if not kinds or j["kind"] in kinds]
    return jobs[0] if jobs else None


def job_view(j):
    if not j:
        return None
    return {k: j.get(k) for k in ("id", "video_id", "kind", "status", "stage", "progress", "error", "stages", "logs",
                                  "cost", "queue", "key_source", "created_at", "updated_at", "finished_at")}


def video_view(v, user, full=True):
    db = get_store()
    owner = v["owner"] == user["id"]
    langs = ["en"] + [l for l in (v.get("targets") or []) if l != "en"]
    out = {k: v.get(k) for k in ("id", "title", "task", "domain", "spoken_lang", "targets", "status", "duration_s",
                                 "created_at", "published", "published_at", "voice", "quiz_enabled", "dub_mode", "llm",
                                 "llm_fallback", "order_ok", "model_kind", "last_error")}
    out["task_title"] = catalog.TASKS.get(v["task"], {}).get("title", v["task"])
    out["by"] = user_name(v["owner"])
    out["dub_mode"] = v.get("dub_mode") or "steps"
    out["is_owner"] = owner
    out["langs"] = langs
    out["thumb_url"] = signed("keyframes", v.get("thumb_path"))
    if not full:
        return out
    steps = sorted(db.select("steps", {"video_id": v["id"]}), key=lambda s: s["idx"])
    trs = db.select("translations", {"video_id": v["id"]})
    by_step = {}
    for t in trs:
        by_step.setdefault(t["step_id"], {})[t["lang"]] = {"text": t["text"], "edited": t.get("edited", False),
                                                           "provider": t.get("provider")}
    out["steps"] = [{"id": s["id"], "idx": s["idx"], "start_s": s["start_s"], "end_s": s["end_s"], "label": s["label"],
                     "confidence": s["confidence"], "low_conf": s["low_conf"], "title": s["title"],
                     "instruction": s["instruction"], "narration_en": s["narration_en"], "edited": s.get("edited"),
                     "needs_review": s.get("needs_review", False),
                     "keyframe_url": signed("keyframes", s.get("keyframe_path")) if owner else None,
                     "texts": {"en": s["narration_en"], **{l: x["text"] for l, x in by_step.get(s["id"], {}).items()}}}
                    for s in steps]
    quiz = db.first("quizzes", video_id=v["id"])
    out["quiz"] = ({"id": quiz["id"], "items": quiz["items"], "translations": quiz.get("translations") or {}}
                   if quiz else None)
    outs = {o["lang"]: o for o in db.select("outputs", {"video_id": v["id"]})}
    src = signed("raw-videos", v.get("source_path"), 4 * 3600)
    out["source_url"] = src if (owner or user["role"] == "annotator" or v.get("published")) else None
    out["outputs"] = {}
    for l in langs:
        o = outs.get(l)
        if not o:
            continue
        out["outputs"][l] = {"mp4": signed("outputs", o["mp4_path"], 4 * 3600) if o.get("mp4_path") else src,
                             "vtt": signed("outputs", o.get("vtt_path"), 4 * 3600),
                             "narration": signed("outputs", o.get("narration_path"), 4 * 3600),
                             "dubbed": bool(o.get("mp4_path")), "updated_at": o.get("updated_at")}
    if owner:
        out["transcript"] = v.get("transcript") or []
        out["job"] = job_view(latest_job(v["id"]))
    return out
