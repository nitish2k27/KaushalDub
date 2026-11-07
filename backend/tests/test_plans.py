"""Plan and quota rules (enforced in the API), key storage, provider fallback and credit handling."""
import pytest

from app import costs, plans, providers
from app.config import get_settings, reset_settings
from app.crypto import redact
from app.db import get_store
from conftest import login, upload

SARVAM = "sk_test_sarvam_0123456789abcdef"
GROQ = "gsk_test0123456789abcdefghijkl"


def test_free_trial_allows_five_videos_then_blocks(client, sample_video):
    t = login(client, "trainer")
    for i in range(5):
        r = upload(client, t, sample_video, title=f"Video {i}")
        assert r.status_code == 200, r.text
    p = client.get("/me/plan", headers=t).json()
    assert p["free_used"] == 5 and p["free_left"] == 0 and p["can_process"] is False
    r = upload(client, t, sample_video, title="Sixth")
    assert r.status_code == 402
    assert r.json()["detail"]["code"] == "free_quota_used"
    assert len(get_store().select("videos")) == 5            # nothing stored for the refused upload


def test_free_video_counted_once_per_video(client, sample_video):
    t = login(client, "trainer")
    vid = upload(client, t, sample_video).json()["video_id"]
    client.post(f"/videos/{vid}/approve", headers=t)                     # approve/dub does not count again
    assert client.get("/me/plan", headers=t).json()["free_used"] == 1


def test_only_trainers_upload(client, sample_video):
    learner = login(client, "learner")
    assert upload(client, learner, sample_video).status_code == 403
    assert client.get("/me/plan", headers=learner).status_code == 403


def test_byok_needs_sarvam_plus_gemini_or_groq(client, sample_video):
    t = login(client, "trainer")
    r = client.put("/me/plan", json={"plan": "byok"}, headers=t)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "keys_missing"
    assert client.put("/me/keys/sarvam", json={"key": SARVAM}, headers=t).status_code == 200
    assert client.put("/me/plan", json={"plan": "byok"}, headers=t).status_code == 400
    assert client.put("/me/keys/groq", json={"key": GROQ}, headers=t).status_code == 200
    p = client.put("/me/plan", json={"plan": "byok"}, headers=t).json()
    assert p["plan"] == "byok" and p["can_process"]
    r = upload(client, t, sample_video)
    assert r.status_code == 200
    job = get_store().get("jobs", r.json()["job_id"])
    assert job["key_source"] == "user"
    assert client.get("/me/plan", headers=t).json()["free_used"] == 0   # own keys do not use the trial
    # deleting a required key drops the user back to the free plan
    client.delete("/me/keys/groq", headers=t)
    assert client.get("/me/plan", headers=t).json()["plan"] == "free"


def test_byok_still_works_after_free_trial_is_used(client, sample_video):
    t = login(client, "trainer")
    uid = client.get("/me", headers=t).json()["id"]
    plans.get_plan(uid)
    get_store().update("user_plans", {"user_id": uid}, {"free_used": 5})
    assert upload(client, t, sample_video).status_code == 402
    client.put("/me/keys/sarvam", json={"key": SARVAM}, headers=t)
    client.put("/me/keys/groq", json={"key": GROQ}, headers=t)
    client.put("/me/plan", json={"plan": "byok"}, headers=t)
    assert upload(client, t, sample_video).status_code == 200


def test_keys_are_encrypted_and_never_returned(client):
    t = login(client, "trainer")
    r = client.put("/me/keys/sarvam", json={"key": SARVAM}, headers=t)
    assert SARVAM not in r.text
    assert r.json()["keys"]["sarvam"] == {"last4": SARVAM[-4:], "verified_at": None, "saved": True}
    row = get_store().first("user_api_keys", provider="sarvam")
    assert row["encrypted_key"] != SARVAM and SARVAM not in row["encrypted_key"]
    for path in ("/me/plan", "/me"):
        assert SARVAM not in client.get(path, headers=t).text
    assert client.put("/me/keys/sarvam", json={"key": "short"}, headers=t).status_code == 400
    assert client.put("/me/keys/openai", json={"key": SARVAM}, headers=t).status_code == 404


def test_key_test_endpoint(client, monkeypatch):
    t = login(client, "trainer")
    client.put("/me/keys/groq", json={"key": GROQ}, headers=t)
    seen = {}

    def fake_check(provider, key):
        seen["key"] = key
        return True, "Key works"
    from app.routers import me
    monkeypatch.setattr(me, "check_key", fake_check)
    r = client.post("/me/keys/groq/test", headers=t).json()
    assert r["ok"] and seen["key"] == GROQ and GROQ not in str(r)
    assert r["plan"]["keys"]["groq"]["verified_at"]


def test_pro_is_coming_soon(client):
    t = login(client, "trainer")
    r = client.put("/me/plan", json={"plan": "pro"}, headers=t)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "pro_coming_soon"


def test_local_plan_forces_local_models_and_gpu_queue(client, sample_video, monkeypatch):
    t = login(client, "trainer")
    client.put("/me/plan", json={"plan": "local", "mt": "sarvam", "tts": "sarvam"}, headers=t)
    uid = client.get("/me", headers=t).json()["id"]
    cfg = plans.check_and_reserve(uid)
    assert (cfg["asr"], cfg["mt"], cfg["tts"]) == ("whisper", "indictrans2", "indicparler")
    assert cfg["key_source"] == "none" and cfg["queue"] == "cpu"          # GPU queue disabled in tests
    monkeypatch.setenv("GPU_QUEUE_ENABLED", "true")
    reset_settings()
    assert plans.check_and_reserve(uid)["queue"] == "gpu"


def test_per_job_provider_switch(client, sample_video):
    t = login(client, "trainer")
    r = upload(client, t, sample_video, asr="sarvam", mt="indictrans2")
    job = get_store().get("jobs", r.json()["job_id"])
    assert job["params"]["asr"] == "sarvam" and job["params"]["mt"] == "indictrans2"
    assert upload(client, t, sample_video, asr="nope").status_code == 400


def test_platform_budget_blocks_free_jobs_only(client, sample_video, monkeypatch):
    monkeypatch.setenv("PLATFORM_BUDGET_INR", "10")
    reset_settings()
    t = login(client, "trainer")
    get_store().insert("jobs", {"kind": "dub", "status": "done", "key_source": "platform", "cost": {"inr": 12.0}})
    assert costs.budget_status()["exhausted"]
    r = upload(client, t, sample_video)
    assert r.status_code == 402 and r.json()["detail"]["code"] == "platform_budget_reached"
    client.put("/me/keys/sarvam", json={"key": SARVAM}, headers=t)
    client.put("/me/keys/groq", json={"key": GROQ}, headers=t)
    client.put("/me/plan", json={"plan": "byok"}, headers=t)
    assert upload(client, t, sample_video).status_code == 200


def test_admin_budget_view(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    reset_settings()
    assert client.get("/admin/budget", headers=login(client, "trainer")).status_code == 403
    a = login(client, "trainer", "boss@example.com")
    assert "budget_inr" in client.get("/admin/budget", headers=a).json()
    assert "budget" in client.get("/me", headers=a).json()


def test_cost_estimate():
    c = costs.empty_cost()
    costs.add(c, "sarvam", audio_min=2, mt_chars=10_000, tts_chars=10_000)
    costs.add(c, "whisper", audio_min=5)
    assert c["inr"] == pytest.approx(2 * 0.49 + 20 + 30)
    assert c["audio_min"] == 7


# ---------------------------------------------------------------- provider errors and fallback
def test_classify_errors():
    assert isinstance(providers.classify(RuntimeError("Sarvam TTS 402: insufficient_quota_error")), providers.OutOfCredits)
    assert isinstance(providers.classify(RuntimeError("Groq 429: slow down")), providers.RateLimited)
    assert isinstance(providers.classify(RuntimeError("429 RESOURCE_EXHAUSTED")), providers.RateLimited)
    assert not isinstance(providers.classify(RuntimeError("Sarvam 400 bad speaker")), (providers.OutOfCredits, providers.RateLimited))


def test_402_is_not_retried_429_is():
    calls = {"n": 0}

    def out_of_credits():
        calls["n"] += 1
        raise RuntimeError("Sarvam translate 402: insufficient_quota_error")
    with pytest.raises(providers.OutOfCredits):
        providers.with_retry(out_of_credits, delays=[0, 0], sleep=lambda s: None)
    assert calls["n"] == 1

    calls["n"] = 0

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "ok"
    waits = []
    assert providers.with_retry(flaky, delays=[1, 2], sleep=waits.append) == "ok"
    assert waits == [1, 2]


def test_stage_falls_back_then_pauses():
    logs = []
    log = lambda m, **k: logs.append(m)

    def fn(name):
        if name == "sarvam":
            raise RuntimeError("Sarvam STT 402: insufficient_quota_error")
        return f"done by {name}"
    assert providers.run_stage("mt", ["sarvam", "indictrans2"], fn, log, {}, "user") == ("indictrans2", "done by indictrans2")
    with pytest.raises(providers.NeedsCredits) as e:
        providers.run_stage("tts", ["sarvam"], fn, log, {}, "user")
    assert "your Sarvam account is out of credits" in str(e.value)
    with pytest.raises(providers.StageFailed):
        providers.run_stage("tts", ["sarvam"], lambda n: 1 / 0, log, {}, "user")


def test_chain_respects_keys_plan_and_worker():
    keys = {"sarvam": "x"}
    assert providers.chain("tts", "sarvam", keys, "free")[0] == ["sarvam"]            # parler needs the GPU worker
    assert providers.chain("tts", "sarvam", {}, "free")[0] == []
    assert providers.chain("mt", "sarvam", keys, "local")[0] == ["indictrans2"]       # local plan never uses Sarvam
    assert providers.chain("asr", "whisper", keys, "byok")[0] == ["whisper", "sarvam"]


def test_redact_hides_keys():
    msg = redact(f"failed with key {SARVAM} and AIzaSyA1234567890abcdefghijklmnop", SARVAM)
    assert SARVAM not in msg and "AIza" not in msg
