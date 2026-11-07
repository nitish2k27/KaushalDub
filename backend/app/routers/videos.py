import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import catalog, plans
from ..auth import current_user, require
from ..db import get_store, now_iso
from ..media import caption_vtt
from ..queue import create_job
from ..storage import get_storage
from .common import get_video, job_view, latest_job, owned_video, video_view, viewable_video

router = APIRouter()
MAX_BYTES = 300 * 1024 * 1024
DUB_MODES = ("steps", "full")
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _queue_followup(v, user, kind, params=None):
    cfg = plans.followup_config(user["id"])
    params = {**cfg, "voice": v.get("voice"), **(params or {})}
    return create_job(v["id"], kind, params, cfg["queue"], user["id"], cfg["key_source"])


@router.post("/videos")
async def upload(title: str = Form(...), task: str = Form(...), targets: str = Form("hi,kn"),
                 spoken_lang: str = Form("auto"), voice: str = Form("Female"), quiz: bool = Form(True),
                 youtube_url: str = Form(""), asr: str = Form(""), mt: str = Form(""), tts: str = Form(""),
                 dub_mode: str = Form("steps"),
                 file: UploadFile | None = File(None), user=Depends(require("trainer"))):
    title = title.strip()[:120]
    if not title:
        raise HTTPException(400, "Give the video a title")
    if task not in catalog.TASKS:
        raise HTTPException(400, f"Unknown skill {task}")
    tl = [t.strip() for t in targets.split(",") if t.strip()]
    if not tl or any(t not in catalog.TARGET_LANGS for t in tl):
        raise HTTPException(400, f"Pick at least one target language from {catalog.TARGET_LANGS}")
    if spoken_lang not in ("auto", *catalog.LANGS):
        raise HTTPException(400, "spoken_lang must be auto, en, hi or kn")
    if dub_mode not in DUB_MODES:
        raise HTTPException(400, "dub_mode must be steps or full")
    if voice not in ("Female", "Male"):
        raise HTTPException(400, "voice must be Female or Male")
    if not file and not youtube_url.strip():
        raise HTTPException(400, "Choose a video file or paste a YouTube link")

    tmp = None
    if file:
        ext = os.path.splitext(file.filename or "")[1].lower() or ".mp4"
        if ext not in VIDEO_EXT:
            raise HTTPException(400, "Upload an MP4, MOV, WebM or MKV video")
        fd, tmp = tempfile.mkstemp(suffix=ext)
        size = 0
        with os.fdopen(fd, "wb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_BYTES:
                    os.remove(tmp)
                    raise HTTPException(413, "Videos up to 300 MB are supported")
                f.write(chunk)
    try:
        cfg = plans.check_and_reserve(user["id"], {"asr": asr, "mt": mt, "tts": tts})   # plan + quota rules
    except Exception:
        if tmp:
            os.remove(tmp)
        raise
    db = get_store()
    try:
        v = db.insert("videos", {"owner": user["id"], "title": title, "task": task,
                                 "domain": catalog.TASKS[task]["domain"], "spoken_lang": spoken_lang, "targets": tl,
                                 "voice": voice, "quiz_enabled": quiz, "dub_mode": dub_mode, "status": "queued", "source_path": None,
                                 "duration_s": None, "published": False, "created_at": now_iso()})
        if tmp:
            path = f"{user['id']}/{v['id']}/source{os.path.splitext(tmp)[1]}"
            get_storage().put_file("raw-videos", path, tmp)
            db.update("videos", {"id": v["id"]}, {"source_path": path})
        params = {**cfg, "spoken_lang": spoken_lang, "quiz": quiz, "voice": voice,
                  "youtube_url": youtube_url.strip() if not tmp else None}
        job = create_job(v["id"], "process", params, cfg["queue"], user["id"], cfg["key_source"])
    except Exception:
        plans.refund_free(user["id"])
        raise
    finally:
        if tmp and os.path.exists(tmp):
            os.remove(tmp)
    return {"video_id": v["id"], "job_id": job["id"]}


@router.get("/videos")
def my_videos(user=Depends(require("trainer"))):
    db = get_store()
    vids = db.select("videos", {"owner": user["id"]}, order="created_at", desc=True)
    out = []
    for v in vids:
        row = video_view(v, user, full=False)
        j = latest_job(v["id"])
        row["job"] = {"id": j["id"], "kind": j["kind"], "status": j["status"], "progress": j["progress"]} if j else None
        out.append(row)
    return out


@router.get("/videos/{video_id}")
def get_one(video_id: str, user=Depends(current_user)):
    return video_view(viewable_video(video_id, user), user)


@router.delete("/videos/{video_id}")
def delete_video(video_id: str, user=Depends(require("trainer"))):
    v = owned_video(video_id, user)
    db = get_store()
    for t in ("steps", "translations", "outputs", "quizzes", "tts_clips", "tickets", "watch_history", "quiz_attempts"):
        db.delete(t, {"video_id": v["id"]})
    db.delete("videos", {"id": v["id"]})
    return {"ok": True}


class StepEdit(BaseModel):
    id: str
    title: str | None = None
    instruction: str | None = None
    narration_en: str | None = None
    start_s: float | None = None
    end_s: float | None = None
    label: str | None = None


class StepsBody(BaseModel):
    steps: list[StepEdit]


@router.patch("/videos/{video_id}/steps")
def patch_steps(video_id: str, body: StepsBody, user=Depends(require("trainer"))):
    v = owned_video(video_id, user)
    db = get_store()
    rows = {s["id"]: s for s in db.select("steps", {"video_id": v["id"]})}
    for e in body.steps:
        s = rows.get(e.id)
        if not s:
            raise HTTPException(404, f"step {e.id} not in this video")
        vals = {k: val for k, val in e.model_dump(exclude={"id"}).items() if val is not None}
        for k in ("title", "instruction", "narration_en"):
            if k in vals:
                vals[k] = vals[k].strip()
                if not vals[k]:
                    raise HTTPException(400, f"step {s['idx']}: {k} cannot be empty")
        if vals:
            vals.update({"edited": True, "needs_review": False})
            s.update(vals)
            db.update("steps", {"id": s["id"]}, vals)
    ordered = sorted(rows.values(), key=lambda s: s["idx"])
    for a, b in zip(ordered, ordered[1:]):
        if a["end_s"] > b["start_s"] + 1e-6 or a["start_s"] >= a["end_s"]:
            raise HTTPException(400, f"steps {a['idx']} and {b['idx']} overlap; keep them in time order")
    return video_view(get_video(video_id), user)


class QuizBody(BaseModel):
    items: list[dict]


@router.put("/videos/{video_id}/quiz")
def put_quiz(video_id: str, body: QuizBody, user=Depends(require("trainer"))):
    v = owned_video(video_id, user)
    for q in body.items:
        if not str(q.get("q", "")).strip() or len(q.get("options", [])) != 4 or not 0 <= int(q.get("answer", -1)) < 4:
            raise HTTPException(400, "Each question needs text, 4 options and the index of the right answer")
    db = get_store()
    quiz = db.first("quizzes", video_id=v["id"])
    if quiz:
        db.update("quizzes", {"id": quiz["id"]}, {"items": body.items, "translations": {}})
    else:
        db.insert("quizzes", {"video_id": v["id"], "items": body.items, "translations": {}})
    return video_view(get_video(video_id), user)


class TextBody(BaseModel):
    text: str


def set_step_text(v, idx, lang, text):
    """Change one step's narration/caption text in one language and rebuild that language's captions now."""
    db = get_store()
    text = text.strip()
    if not text:
        raise HTTPException(400, "Text cannot be empty")
    if lang not in ["en"] + list(v.get("targets") or []):
        raise HTTPException(400, f"This video has no {lang} version")
    step = db.first("steps", video_id=v["id"], idx=idx)
    if not step:
        raise HTTPException(404, f"Step {idx} not found")
    if lang == "en":
        db.update("steps", {"id": step["id"]}, {"narration_en": text, "edited": True})
    else:
        db.upsert("translations", {"step_id": step["id"], "video_id": v["id"], "lang": lang, "text": text,
                                   "provider": "trainer", "source_hash": None, "edited": True}, on=("step_id", "lang"))
    out = db.first("outputs", video_id=v["id"], lang=lang)
    if out and out.get("vtt_path") and (v.get("dub_mode") or "steps") == "steps":   # full mode captions follow the speech
        from ..jobs import lang_texts, step_rows
        steps = step_rows(v["id"])
        fd, tmp = tempfile.mkstemp(suffix=".vtt")
        os.close(fd)
        try:
            caption_vtt(steps, lang_texts(v["id"], steps, lang), tmp, out.get("placements"))
            get_storage().put_file("outputs", out["vtt_path"], tmp, "text/vtt")
        finally:
            os.remove(tmp)
    return step


@router.put("/videos/{video_id}/steps/{idx}/text")
def put_step_text(video_id: str, idx: int, lang: str, body: TextBody, user=Depends(require("trainer"))):
    v = owned_video(video_id, user)
    set_step_text(v, idx, lang, body.text)
    return video_view(get_video(video_id), user)


@router.post("/videos/{video_id}/steps/{idx}/revoice")
def revoice(video_id: str, idx: int, lang: str, user=Depends(require("trainer"))):
    v = owned_video(video_id, user)
    if lang not in (v.get("targets") or []):
        raise HTTPException(400, "Re-voicing works for the dubbed languages (Hindi, Kannada)")
    if not get_store().first("outputs", video_id=v["id"], lang=lang):
        raise HTTPException(409, "Create the dub first (approve the video)")
    if not get_store().first("steps", video_id=v["id"], idx=idx):
        raise HTTPException(404, f"Step {idx} not found")
    job = _queue_followup(v, user, "revoice", {"idx": idx, "lang": lang})
    return {"job_id": job["id"]}


@router.post("/videos/{video_id}/approve")
def approve(video_id: str, mode: str = "", user=Depends(require("trainer"))):
    """mode = steps (narrate each detected step) or full (translate and voice everything the instructor says)."""
    v = owned_video(video_id, user)
    if mode:
        if mode not in DUB_MODES:
            raise HTTPException(400, "mode must be steps or full")
        if mode != (v.get("dub_mode") or "steps"):
            get_store().update("videos", {"id": v["id"]}, {"dub_mode": mode})
            v["dub_mode"] = mode
    if v["status"] not in ("review", "ready"):
        raise HTTPException(409, f"Video is {v['status']}; it can be approved after processing")
    if not get_store().select("steps", {"video_id": v["id"]}, limit=1):
        raise HTTPException(409, "No steps to dub")
    get_store().update("videos", {"id": v["id"]}, {"status": "dubbing", "approved_at": now_iso()})
    job = _queue_followup(v, user, "dub")
    return {"job_id": job["id"]}


@router.post("/videos/{video_id}/publish")
def publish(video_id: str, user=Depends(require("trainer"))):
    v = owned_video(video_id, user)
    if v["status"] != "ready":
        raise HTTPException(409, "Only dubbed videos can be published")
    get_store().update("videos", {"id": v["id"]}, {"published": True, "published_at": now_iso()})
    return video_view(get_video(video_id), user)


@router.post("/videos/{video_id}/unpublish")
def unpublish(video_id: str, user=Depends(require("trainer"))):
    v = owned_video(video_id, user)
    get_store().update("videos", {"id": v["id"]}, {"published": False})
    return video_view(get_video(video_id), user)


# ---------------------------------------------------------------- jobs
@router.get("/jobs/{job_id}")
def job(job_id: str, user=Depends(current_user)):
    j = get_store().get("jobs", job_id)
    if not j or (j.get("owner_id") != user["id"]):
        raise HTTPException(404, "Job not found")
    return job_view(j)


@router.post("/jobs/{job_id}/resume")
def resume(job_id: str, user=Depends(require("trainer"))):
    db = get_store()
    j = db.get("jobs", job_id)
    if not j or j.get("owner_id") != user["id"]:
        raise HTTPException(404, "Job not found")
    if j["status"] not in ("needs_credits", "failed"):
        raise HTTPException(409, f"Job is {j['status']}")
    cfg = plans.followup_config(user["id"])
    params = {**(j.get("params") or {}), **cfg}
    v = get_video(j["video_id"]) if j.get("video_id") else None
    new = create_job(j.get("video_id"), j["kind"], params, cfg["queue"], user["id"], cfg["key_source"])
    db.update("jobs", {"id": j["id"]}, {"status": "superseded", "superseded_by": new["id"]})
    if v and j["kind"] == "process":
        db.update("videos", {"id": v["id"]}, {"status": "queued"})
    return {"job_id": new["id"]}


# ---------------------------------------------------------------- library, watching, quiz
@router.get("/library")
def library(q: str = "", domain: str = "", lang: str = "", user=Depends(current_user)):
    db = get_store()
    vids = db.select("videos", {"published": True}, order="published_at", desc=True)
    ql = q.strip().lower()
    out = []
    for v in vids:
        row = video_view(v, user, full=False)
        if domain and domain != "All" and v.get("domain") != domain:
            continue
        if lang and lang not in row["langs"]:
            continue
        if ql and ql not in " ".join([v["title"], row["task_title"], v.get("domain", ""), row["by"]]).lower():
            continue
        out.append(row)
    return out


class ProgressBody(BaseModel):
    progress: float
    lang: str | None = None


@router.post("/videos/{video_id}/progress")
def progress(video_id: str, body: ProgressBody, user=Depends(current_user)):
    v = viewable_video(video_id, user)
    db = get_store()
    cur = db.first("watch_history", user_id=user["id"], video_id=v["id"])
    p = max(0.0, min(100.0, body.progress))
    p = max(p, (cur or {}).get("progress", 0))
    db.upsert("watch_history", {"user_id": user["id"], "video_id": v["id"], "progress": round(p, 1),
                                "lang": body.lang, "updated_at": now_iso()}, on=("user_id", "video_id"))
    return {"progress": p}


class AttemptBody(BaseModel):
    answers: list[int]
    lang: str = "en"


@router.post("/quiz/{video_id}/attempts")
def attempt(video_id: str, body: AttemptBody, user=Depends(current_user)):
    v = viewable_video(video_id, user)
    db = get_store()
    quiz = db.first("quizzes", video_id=v["id"])
    if not quiz or not quiz.get("items"):
        raise HTTPException(404, "This video has no quiz")
    items = quiz["items"]
    if len(body.answers) != len(items):
        raise HTTPException(400, f"Answer all {len(items)} questions")
    score = sum(1 for a, q in zip(body.answers, items) if a == q["answer"])
    row = db.insert("quiz_attempts", {"quiz_id": quiz["id"], "video_id": v["id"], "user_id": user["id"],
                                      "answers": body.answers, "lang": body.lang, "score": score,
                                      "total": len(items), "created_at": now_iso()})
    return row
