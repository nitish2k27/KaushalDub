"""Annotator corrections -> per-change trainer approval -> video update, correction memory, retraining."""
import numpy as np
import pytest

from app import corrections, retrain
from app.config import reset_settings
from app.db import get_store
from app.ml_adapter import blend_prototypes
from conftest import login, ready_video, upload

MODEL = [{"label": "a", "start": 0, "end": 5, "confidence": .9}, {"label": "b", "start": 5, "end": 10, "confidence": .5},
         {"label": "c", "start": 10, "end": 15, "confidence": .8}]


def test_compute_and_apply_partial_changes():
    ann = [{"label": "a", "start": 0, "end": 5}, {"label": "x", "start": 5, "end": 10},
           {"label": "c", "start": 10, "end": 13}, {"label": "background", "start": 13, "end": 15}]
    ch = corrections.compute_changes(MODEL, ann)
    assert [(c["id"], c["kind"], c["from"]) for c in ch] == [(1, "label", "b"), (2, "boundary", "c"), (3, "both", "c")]
    assert ch[0]["confidence"] == .5
    only_label = corrections.apply_changes(MODEL, ann, [1])
    assert [(s["label"], s["start"], s["end"]) for s in only_label] == [("a", 0, 5), ("x", 5, 10), ("c", 10, 15)]
    all_ = corrections.apply_changes(MODEL, ann, [1, 2, 3])
    assert [(s["label"], s["start"], s["end"]) for s in all_] == [("a", 0, 5), ("x", 5, 10), ("c", 10, 13)]
    none = corrections.apply_changes(MODEL, ann, [])
    assert [(s["label"], s["start"], s["end"]) for s in none] == [("a", 0, 5), ("b", 5, 10), ("c", 10, 15)]


def test_fill_background():
    segs = corrections.fill_background([{"label": "a", "start": 2, "end": 4}], 6)
    assert [(s["label"], s["start"], s["end"]) for s in segs] == [("background", 0, 2), ("a", 2, 4), ("background", 4, 6)]


def test_blend_prototypes_moves_towards_memory():
    W = np.array([[1, 0], [0, 1]], np.float32)
    P = blend_prototypes(W, {1: np.array([[1, 0]] * 3, np.float32)})
    assert np.allclose(P[0], W[0])                         # untouched class
    assert P[1][0] > 0 and np.isclose(np.linalg.norm(P[1]), 1)
    P_many = blend_prototypes(W, {1: np.array([[1, 0]] * 50, np.float32)})
    assert P_many[1][0] >= P[1][0]                         # more corrections, more weight (capped at 50%)
    assert np.isclose(P_many[1][0], P_many[1][1])


def test_should_activate():
    assert retrain.should_activate(40.0, 40.0)
    assert retrain.should_activate(41.0, 40.0)
    assert not retrain.should_activate(39.9, 40.0)
    assert not retrain.should_activate(None, 40.0)


def annotate(client, annotator, vid, relabel_to=None):
    clip = client.get(f"/annotations/{vid}", headers=annotator).json()
    segs = [dict(s) for s in clip["model_segments"]]
    first = next(i for i, s in enumerate(segs) if s["label"] != "background")
    segs[first]["label"] = relabel_to or clip["vocab"][-1]
    segs[first]["end"] = round(segs[first]["end"] - 1.0, 2)                 # boundary moved...
    segs[first + 1]["start"] = segs[first]["end"]                             # ...next segment grows
    assert client.put(f"/annotations/{vid}", json={"segments": segs}, headers=annotator).status_code == 200
    return client.post(f"/annotations/{vid}/submit", headers=annotator)


def test_annotation_request_flow(client, sample_video):
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video)
    ann = login(client, "annotator")

    q = client.get("/annotations/queue", headers=ann).json()
    assert q["clips"][0]["clip_id"] == vid and q["clips"][0]["low_conf"] >= 1
    r = annotate(client, ann, vid)
    assert r.status_code == 200 and r.json()["changes"] >= 2
    assert client.get("/annotations/queue", headers=ann).json()["clips"] == []      # submitted clips leave the queue
    assert client.post(f"/annotations/{vid}/submit", headers=ann).status_code == 409

    reqs = client.get("/annotation-requests", params={"status": "pending"}, headers=trainer).json()
    assert len(reqs) == 1 and reqs[0]["annotator_name"] == "Annotator"
    detail = client.get(f"/annotation-requests/{reqs[0]['id']}", headers=trainer).json()["request"]
    changes = detail["changes"]
    label_change = next(c for c in changes if c["kind"] in ("label", "both"))

    before = client.get(f"/videos/{vid}", headers=trainer).json()["steps"]
    r = client.post(f"/annotation-requests/{reqs[0]['id']}/approve", headers=trainer,
                    json={"change_ids": [label_change["id"]], "note": "Thanks"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["request"]["status"] == "partly_approved" and out["applied"] == 1
    assert out["memory_added"] == 1
    after = client.get(f"/videos/{vid}", headers=trainer).json()["steps"]
    assert after[0]["label"] == label_change["label"] != before[0]["label"]
    assert after[0]["needs_review"] is True
    assert out["rerender_job"]                                                    # dubbed video gets re-rendered
    assert client.get(f"/jobs/{out['rerender_job']}", headers=trainer).json()["status"] == "done"
    mem = get_store().select("correction_memory")
    assert len(mem) == 1 and mem[0]["task"] == "PerformCPR" and mem[0]["used_in_version"] is None
    hist = client.get("/me/annotations", headers=ann).json()
    assert hist[0]["status"] == "partly_accepted" and hist[0]["reviewer_note"] == "Thanks"

    st = client.get("/model/status", headers=trainer).json()
    assert st["pending"] == 1 and st["memory"] == 1 and st["active_version"] == 1
    assert st["method"] == "human-in-the-loop active learning"

    # the next video of the same skill sees the memory
    vid2 = upload(client, trainer, sample_video, title="CPR again").json()["video_id"]
    j = [j for j in get_store().select("jobs", {"video_id": vid2})][0]
    assert any("correction memory: 1" in l["msg"] for l in j["logs"])


def test_send_back_and_permissions(client, sample_video):
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video)
    ann = login(client, "annotator")
    annotate(client, ann, vid)
    rid = client.get("/annotation-requests", headers=trainer).json()[0]["id"]
    other = login(client, "trainer", "other@example.com")
    assert client.post(f"/annotation-requests/{rid}/approve", json={"change_ids": [0]}, headers=other).status_code == 404
    assert client.post(f"/annotation-requests/{rid}/approve", json={"change_ids": []}, headers=trainer).status_code == 400
    r = client.post(f"/annotation-requests/{rid}/send-back", json={"note": "Step 1 is correct"}, headers=trainer)
    assert r.json()["request"]["status"] == "sent_back"
    assert client.get("/me/annotations", headers=ann).json()[0]["status"] == "sent_back"
    assert get_store().select("correction_memory") == []
    q = client.get("/annotations/queue", headers=ann).json()["clips"]
    assert q[0]["sent_back"] is True                                               # annotator can try again
    assert client.get("/annotations/queue", headers=login(client, "learner")).status_code == 403


def test_bad_labels_rejected(client, sample_video):
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video, publish=False)
    ann = login(client, "annotator")
    assert client.put(f"/annotations/{vid}", headers=ann,
                      json={"segments": [{"label": "dance", "start": 0, "end": 3}]}).status_code == 400
    assert client.put(f"/annotations/{vid}", headers=ann,
                      json={"segments": [{"label": "background", "start": 0, "end": 3},
                                         {"label": "background", "start": 2, "end": 5}]}).status_code == 400


@pytest.mark.parametrize("new_f1,activated", [(45.0, True), (42.3, True), (40.0, False)])
def test_retrain_activates_only_if_not_worse(client, sample_video, monkeypatch, new_f1, activated):
    calls = {}

    def fake_trainer(bundle, items, testset, log):
        calls["items"] = items
        return b"weights", new_f1, 42.3, {"PerformCPR": {"macro_f1": new_f1}}
    monkeypatch.setitem(retrain.TRAINER, "fn", fake_trainer)
    trainer = login(client, "trainer")
    assert client.post("/model/retrain", headers=trainer).status_code == 409        # nothing pending yet
    vid = ready_video(client, trainer, sample_video)
    ann = login(client, "annotator")
    annotate(client, ann, vid)
    rid = client.get("/annotation-requests", headers=trainer).json()[0]["id"]
    ids = [c["id"] for c in client.get(f"/annotation-requests/{rid}", headers=trainer).json()["request"]["changes"]]
    client.post(f"/annotation-requests/{rid}/approve", json={"change_ids": ids}, headers=trainer)

    r = client.post("/model/retrain", headers=trainer)
    assert r.status_code == 200
    job = client.get(f"/jobs/{r.json()['job_id']}", headers=trainer).json()
    assert job["status"] == "done", job
    assert len(calls["items"]) == 1 and calls["items"][0]["y"].max() > 0
    st = client.get("/model/status", headers=trainer).json()
    assert st["active_version"] == (2 if activated else 1)
    assert st["pending"] == 0 and st["versions"][0]["version"] == 2
    assert st["versions"][0]["metrics"]["previous_macro_f1"] == 42.3
    assert st["last_retrain"]


def test_auto_retrain_at_threshold(client, sample_video, monkeypatch):
    monkeypatch.setenv("RETRAIN_THRESHOLD", "1")
    reset_settings()
    monkeypatch.setitem(retrain.TRAINER, "fn", lambda b, i, t, log: (b"w", 50.0, 42.3, {}))
    trainer = login(client, "trainer")
    vid = ready_video(client, trainer, sample_video)
    annotate(client, login(client, "annotator"), vid)
    rid = client.get("/annotation-requests", headers=trainer).json()[0]["id"]
    ids = [c["id"] for c in client.get(f"/annotation-requests/{rid}", headers=trainer).json()["request"]["changes"]]
    out = client.post(f"/annotation-requests/{rid}/approve", json={"change_ids": ids}, headers=trainer).json()
    assert out["retrain_job"]
    assert client.get("/model/status", headers=trainer).json()["active_version"] == 2
