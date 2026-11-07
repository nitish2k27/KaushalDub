"""Job queue. With REDIS_URL: RQ queues `cpu` (worker next to the API on the HF Space) and `gpu` (the Kaggle
notebook worker). Without REDIS_URL (local dev): jobs run in a background thread inside the API process.
Tests set INLINE_SYNC so jobs run synchronously."""
import threading

from .config import get_settings
from .db import get_store, now_iso

INLINE_SYNC = False
_redis = None


def redis_conn():
    global _redis
    if _redis is None:
        from redis import Redis
        _redis = Redis.from_url(get_settings().redis_url)
    return _redis


def create_job(video_id, kind, params, queue="cpu", owner_id=None, key_source="none"):
    db = get_store()
    job = db.insert("jobs", {"video_id": video_id, "kind": kind, "owner_id": owner_id, "status": "queued",
                             "stage": "queued", "progress": 0, "error": None, "logs": [], "stages": [],
                             "params": params, "queue": queue, "key_source": key_source,
                             "cost": {"audio_min": 0, "mt_chars": 0, "tts_chars": 0, "inr": 0, "by_provider": {}},
                             "created_at": now_iso(), "updated_at": now_iso()})
    enqueue(job["id"], queue)
    return job


def enqueue(job_id, queue="cpu"):
    from .jobs import run_job
    s = get_settings()
    if INLINE_SYNC:
        run_job(job_id)
    elif s.redis_url:
        from rq import Queue
        Queue(queue, connection=redis_conn(), default_timeout=6 * 3600).enqueue(run_job, job_id, job_timeout=6 * 3600)
    else:
        threading.Thread(target=run_job, args=(job_id,), daemon=True).start()


def worker_status():
    s = get_settings()
    if not s.redis_url:
        return {"mode": "inline", "workers": {"cpu": 1, "gpu": 0}}
    try:
        from rq import Worker
        ws = Worker.all(connection=redis_conn())
        count = {"cpu": 0, "gpu": 0}
        for w in ws:
            for q in w.queue_names():
                count[q] = count.get(q, 0) + 1
        return {"mode": "redis", "workers": count}
    except Exception as e:
        return {"mode": "redis", "error": str(e)[:200], "workers": {}}
