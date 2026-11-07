"""Learner tickets: report at a timestamp -> trainer fixes the text, re-voices one step, replies and closes."""
from app.db import get_store
from app.storage import get_storage
from conftest import FakeTTS, login, ready_video


def report(client, learner, vid, t=7.0, lang="hi", msg="The Hindi voice says the wrong thing here"):
    return client.post(f"/videos/{vid}/tickets", headers=learner,
                       json={"lang": lang, "timestamp_s": t, "category": "Wrong translation", "message": msg})


def test_ticket_flow(client, sample_video):
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video)
    learner = login(client, "learner")

    steps = client.get(f"/videos/{vid}", headers=learner).json()["steps"]
    t = 7.0
    expected = max(s["idx"] for s in steps if s["start_s"] <= t)
    r = report(client, learner, vid, t)
    assert r.status_code == 200, r.text
    tk = r.json()
    assert tk["step_idx"] == expected and tk["status"] == "open" and tk["timestamp_s"] == 7.0

    lst = client.get("/tickets", params={"status": "open"}, headers=trainer).json()
    assert len(lst) == 1 and lst[0]["video_title"] == "CPR basics" and lst[0]["reporter_name"] == "Learner"
    detail = client.get(f"/tickets/{tk['id']}", headers=trainer).json()
    assert detail["video"]["steps"][expected - 1]["texts"]["hi"].startswith("[hi]")

    # fix text -> captions rebuilt immediately
    r = client.patch(f"/tickets/{tk['id']}", headers=trainer, json={"text": "सही निर्देश"})
    assert r.status_code == 200
    assert r.json()["video"]["steps"][expected - 1]["texts"]["hi"] == "सही निर्देश"
    o = get_store().first("outputs", video_id=vid, lang="hi")
    assert "सही निर्देश" in open(get_storage().local_path("outputs", o["vtt_path"]), encoding="utf-8").read()

    # re-voice only that step
    before = sum(FakeTTS.calls)
    r = client.post(f"/videos/{vid}/steps/{expected}/revoice", params={"lang": "hi"}, headers=trainer)
    assert r.status_code == 200
    job = client.get(f"/jobs/{r.json()['job_id']}", headers=trainer).json()
    assert job["status"] == "done", job
    assert sum(FakeTTS.calls) - before == 1                       # one clip re-made, the rest from cache
    o2 = get_store().first("outputs", video_id=vid, lang="hi")
    assert o2["mp4_path"] != o["mp4_path"]

    # reply and close
    r = client.patch(f"/tickets/{tk['id']}", headers=trainer, json={"reply": "Fixed the Hindi text.", "status": "resolved"})
    assert r.json()["ticket"]["status"] == "resolved" and r.json()["ticket"]["closed_at"]
    assert client.get("/tickets", params={"status": "open"}, headers=trainer).json() == []
    assert len(client.get("/tickets", params={"status": "closed"}, headers=trainer).json()) == 1
    mine = client.get("/me/tickets", headers=learner).json()
    assert mine[0]["status"] == "resolved" and mine[0]["reply"] == "Fixed the Hindi text."
    assert client.patch(f"/tickets/{tk['id']}", headers=trainer, json={"status": "closed"}).status_code == 409


def test_close_without_change_gets_default_reply(client, sample_video):
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video)
    tk = report(client, login(client, "learner"), vid).json()
    r = client.patch(f"/tickets/{tk['id']}", headers=trainer, json={"status": "closed"})
    assert r.json()["ticket"]["reply"] == "Checked: no change needed."


def test_ticket_validation_and_permissions(client, sample_video):
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video)
    learner = login(client, "learner")
    assert report(client, learner, vid, msg="   ").status_code == 400
    assert client.post(f"/videos/{vid}/tickets", headers=learner,
                       json={"lang": "hi", "timestamp_s": 1, "category": "Bad", "message": "x"}).status_code == 400
    assert report(client, learner, vid, lang="ta").status_code == 400
    assert report(client, trainer, vid).status_code == 403                 # only learners report
    tk = report(client, learner, vid).json()
    other = login(client, "trainer", "other@example.com")
    assert client.get(f"/tickets/{tk['id']}", headers=other).status_code == 404
    assert client.get("/tickets", headers=other).json() == []


def test_cannot_report_unpublished(client, sample_video):
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video, publish=False)
    assert report(client, login(client, "learner"), vid).status_code == 403
