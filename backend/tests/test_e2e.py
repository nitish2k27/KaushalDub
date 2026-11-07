"""End to end: upload a short sample video -> stages 1-4 -> review/edit -> approve -> stages 5-7 (real ffmpeg
dub/mux from kd_pipeline) -> publish -> learner watches, takes the quiz. All API providers are mocked."""
import os

from app.media import probe_duration
from app.mlpath import kp
from app.storage import get_storage
from conftest import FakeMT, FakeTTS, login, upload


def test_full_pipeline(client, sample_video):
    trainer = login(client, "trainer")
    r = upload(client, trainer, sample_video, title="CPR basics")
    assert r.status_code == 200, r.text
    vid, job_id = r.json()["video_id"], r.json()["job_id"]

    job = client.get(f"/jobs/{job_id}", headers=trainer).json()
    assert job["status"] == "done", job
    assert [s["key"] for s in job["stages"]] == ["fetch", "extract", "asr", "steps", "llm", "check"]
    assert all(s["status"] == "done" for s in job["stages"])
    assert job["progress"] == 100

    v = client.get(f"/videos/{vid}", headers=trainer).json()
    assert v["status"] == "review"
    assert v["order_ok"] is True
    assert len(v["steps"]) >= 2
    assert [s["idx"] for s in v["steps"]] == list(range(1, len(v["steps"]) + 1))
    assert v["steps"][0]["narration_en"].startswith("Now ")
    assert any(s["low_conf"] for s in v["steps"])                     # mock marks one step low confidence
    assert v["quiz"] and len(v["quiz"]["items"]) == 3
    assert v["transcript"] and v["source_url"]

    # trainer edits a step, then approves
    s1 = v["steps"][0]
    r = client.patch(f"/videos/{vid}/steps", headers=trainer,
                     json={"steps": [{"id": s1["id"], "narration_en": "Check that the area is safe."}]})
    assert r.status_code == 200 and r.json()["steps"][0]["edited"] is True
    r = client.post(f"/videos/{vid}/approve", headers=trainer)
    assert r.status_code == 200, r.text
    dub = client.get(f"/jobs/{r.json()['job_id']}", headers=trainer).json()
    assert dub["status"] == "done", dub
    assert [s["key"] for s in dub["stages"]] == ["translate", "tts", "render"]

    v = client.get(f"/videos/{vid}", headers=trainer).json()
    assert v["status"] == "ready"
    assert set(v["outputs"]) == {"en", "hi", "kn"}
    assert v["steps"][0]["texts"]["hi"] == "[hi] Check that the area is safe."
    assert v["quiz"]["translations"]["kn"][0]["q"].startswith("[kn]")
    st = get_storage()
    from app.db import get_store
    for lang in ("hi", "kn"):
        o = get_store().first("outputs", video_id=vid, lang=lang)
        mp4 = st.local_path("outputs", o["mp4_path"])
        assert os.path.getsize(mp4) > 10_000
        assert kp.has_audio(mp4)
        assert abs(probe_duration(mp4) - 12) < 1.5
        vtt = open(st.local_path("outputs", o["vtt_path"]), encoding="utf-8").read()
        assert vtt.startswith("WEBVTT") and f"[{lang}]" in vtt
    en = get_store().first("outputs", video_id=vid, lang="en")
    assert "Check that the area is safe." in open(st.local_path("outputs", en["vtt_path"]), encoding="utf-8").read()
    n_tts = sum(FakeTTS.calls)

    # signed local file URLs work and expire-check
    url = v["outputs"]["hi"]["mp4"].replace("http://testserver", "")
    assert client.get(url).status_code == 200
    assert client.get(url.replace("sig=", "sig=x")).status_code == 403

    # publish -> library -> learner watches and takes the quiz
    assert client.post(f"/videos/{vid}/publish", headers=trainer).json()["published"] is True
    learner = login(client, "learner")
    lib = client.get("/library", params={"q": "cpr", "domain": "First aid", "lang": "kn"}, headers=learner).json()
    assert [x["id"] for x in lib] == [vid]
    assert client.get("/library", params={"domain": "Cooking"}, headers=learner).json() == []
    lv = client.get(f"/videos/{vid}", headers=learner).json()
    assert lv["outputs"]["kn"]["mp4"] and lv["outputs"]["kn"]["vtt"] and "transcript" not in lv
    assert client.post(f"/videos/{vid}/progress", json={"progress": 60, "lang": "kn"}, headers=learner).status_code == 200
    r = client.post(f"/quiz/{vid}/attempts", json={"answers": [0, 3, 2], "lang": "kn"}, headers=learner)
    assert r.json()["score"] == 2 and r.json()["total"] == 3
    hist = client.get("/me/history", headers=learner).json()
    assert hist["items"][0]["quiz"] == "2/3" and hist["preferred_lang"] == "kn"

    # re-approving re-uses cached translations and narration clips (no new provider calls)
    mt_calls = len(FakeMT.calls)
    r = client.post(f"/videos/{vid}/approve", headers=trainer)
    assert client.get(f"/jobs/{r.json()['job_id']}", headers=trainer).json()["status"] == "done"
    assert len(FakeMT.calls) == mt_calls and sum(FakeTTS.calls) == n_tts


def test_unpublished_video_is_private(client, sample_video):
    trainer = login(client, "trainer")
    vid = upload(client, trainer, sample_video).json()["video_id"]
    learner = login(client, "learner")
    assert client.get(f"/videos/{vid}", headers=learner).status_code == 403
    assert client.post(f"/videos/{vid}/publish", headers=trainer).status_code == 409   # not dubbed yet
    other = login(client, "trainer", "other@example.com")
    assert client.post(f"/videos/{vid}/approve", headers=other).status_code == 403


def test_needs_credits_pauses_and_resumes(client, sample_video, fakes):
    trainer = login(client, "trainer")
    vid = upload(client, trainer, sample_video).json()["video_id"]
    fakes.broke[("mt", "sarvam")] = "Sarvam translate 402: insufficient_quota_error"
    fakes.broke[("mt", "indictrans2")] = "IndicTrans2 environment could not be installed"
    r = client.post(f"/videos/{vid}/approve", headers=trainer)
    j = client.get(f"/jobs/{r.json()['job_id']}", headers=trainer).json()
    assert j["status"] == "needs_credits"
    assert "out of credits" in j["error"] and "KaushalDub's shared" in j["error"]
    assert client.get(f"/videos/{vid}", headers=trainer).json()["status"] == "needs_credits"
    assert not any("platform-sarvam-test-key" in (l["msg"]) for l in j["logs"])   # keys never logged
    fakes.broke.clear()
    r = client.post(f"/jobs/{j['id']}/resume", headers=trainer)
    assert r.status_code == 200
    assert client.get(f"/jobs/{r.json()['job_id']}", headers=trainer).json()["status"] == "done"
    assert client.get(f"/videos/{vid}", headers=trainer).json()["status"] == "ready"


def test_full_speech_dub(client, sample_video):
    """Full-speech mode: every transcript sentence is translated, voiced and placed at its own time."""
    trainer = login(client, "trainer")
    r = upload(client, trainer, sample_video, dub_mode="full")
    assert r.status_code == 200, r.text
    vid = r.json()["video_id"]
    FakeMT.calls.clear()
    tts_before = sum(FakeTTS.calls)
    job = client.get(f"/jobs/{client.post(f'/videos/{vid}/approve', headers=trainer).json()['job_id']}", headers=trainer).json()
    assert job["status"] == "done", job
    assert any("full speech: 4 sentences" in l["msg"] for l in job["logs"])
    v = client.get(f"/videos/{vid}", headers=trainer).json()
    assert v["dub_mode"] == "full" and set(v["outputs"]) == {"en", "hi", "kn"}
    from app.db import get_store
    st = get_storage()
    o = get_store().first("outputs", video_id=vid, lang="kn")
    vtt = open(st.local_path("outputs", o["vtt_path"]), encoding="utf-8").read()
    assert "[kn] First check the area." in vtt and "[kn] Finish and check." in vtt   # transcript, not step narration
    assert len(o["placements"]) == 4
    assert sum(FakeTTS.calls) - tts_before == 8                                       # 4 sentences x 2 languages
    en = get_store().first("outputs", video_id=vid, lang="en")
    assert "Keep going carefully." in open(st.local_path("outputs", en["vtt_path"]), encoding="utf-8").read()
    # switching the same video back to step narration
    r = client.post(f"/videos/{vid}/approve", params={"mode": "steps"}, headers=trainer)
    assert client.get(f"/jobs/{r.json()['job_id']}", headers=trainer).json()["status"] == "done"
    o = get_store().first("outputs", video_id=vid, lang="kn")
    assert len(o["placements"]) == len(v["steps"])
    assert client.post(f"/videos/{vid}/approve", params={"mode": "loud"}, headers=trainer).status_code == 400
