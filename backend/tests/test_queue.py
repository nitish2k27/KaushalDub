"""The Redis path: an upload enqueues an RQ job on the right queue and an RQ worker runs it to the end."""
import fakeredis
from rq import Queue, SimpleWorker

from app import queue as kdqueue
from app.config import reset_settings
from app.db import get_store
from conftest import login, upload


def test_upload_goes_through_redis_and_rq_worker(client, sample_video, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    reset_settings()
    conn = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(kdqueue, "_redis", conn)
    monkeypatch.setattr(kdqueue, "INLINE_SYNC", False)

    t = login(client, "trainer")
    r = upload(client, t, sample_video)
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    q = Queue("cpu", connection=conn)
    assert q.count == 1 and get_store().get("jobs", job_id)["status"] == "queued"
    assert Queue("gpu", connection=conn).count == 0

    SimpleWorker([q], connection=conn).work(burst=True)
    job = client.get(f"/jobs/{job_id}", headers=t).json()
    assert job["status"] == "done", job
    assert client.get(f"/videos/{r.json()['video_id']}", headers=t).json()["status"] == "review"


def test_local_plan_jobs_go_to_gpu_queue(client, sample_video, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setenv("GPU_QUEUE_ENABLED", "true")
    reset_settings()
    conn = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(kdqueue, "_redis", conn)
    monkeypatch.setattr(kdqueue, "INLINE_SYNC", False)
    t = login(client, "trainer")
    client.put("/me/plan", json={"plan": "local"}, headers=t)
    assert upload(client, t, sample_video).status_code == 200
    assert Queue("gpu", connection=conn).count == 1 and Queue("cpu", connection=conn).count == 0
