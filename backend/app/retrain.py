"""Retrain job (human-in-the-loop active learning, not reinforcement learning).

Training data = videos with approved annotator corrections: their stored CLIP features, labelled frame by frame
from the corrected step timeline. The loop is the training notebook's `train()` (weighted cross-entropy +
0.15 * smoothing loss, AdamW, grad clipping, early stopping), starting from the active model with a small
learning rate. The new version is activated only if its test-set macro-F1 is not worse than the active one.
Test set: <bundle>/testset/*.npz with arrays x [T,512], y [T] and a `task` string (export it from the training
notebook with backend/scripts/export_testset.py). Without a test set the version is saved but not activated."""
import copy
import glob
import io
import json
import os
import random

import numpy as np

from . import ml_adapter
from .config import get_settings
from .db import get_store, now_iso
from .storage import get_storage


def should_activate(new_f1, old_f1) -> bool:
    return new_f1 is not None and old_f1 is not None and new_f1 >= old_f1 - 1e-9


def frame_labels(steps, vocab, n_frames, fps):
    y = np.zeros(n_frames, np.int64)
    for s in steps:
        if s["label"] in vocab:
            y[int(s["start_s"] * fps):int(s["end_s"] * fps)] = vocab.index(s["label"])
    return y


def collect_items(tmp):
    """One training item per video that has approved corrections."""
    db = get_store()
    pending = db.select("correction_memory", {"used_in_version": None})
    vids = sorted({m["video_id"] for m in pending if m.get("video_id")})
    items = []
    for vid in vids:
        v = db.get("videos", vid)
        if not v or not v.get("features"):
            continue
        feats = ml_adapter.load_npy("outputs", v["features"]["path"], tmp)
        steps = db.select("steps", {"video_id": vid})
        vocab = ml_adapter.vocab_for(v["task"])
        items.append({"id": vid, "task": v["task"], "x": feats.astype(np.float32),
                      "y": frame_labels(steps, vocab, len(feats), v["features"]["fps"])})
    return pending, items


def load_testset(bundle):
    out = []
    for f in sorted(glob.glob(os.path.join(bundle, "testset", "*.npz"))):
        z = np.load(f, allow_pickle=False)
        out.append({"id": os.path.basename(f), "task": str(z["task"]), "x": z["x"].astype(np.float32),
                    "y": z["y"].astype(np.int64)})
    return out


def torch_train_and_eval(bundle, items, testset, log, epochs=15, lr=1e-4, patience=5):
    """Returns (state_dict_bytes, new_macro_f1, old_macro_f1, per_task)."""
    import torch
    import torch.nn.functional as F
    km = ml_adapter.import_kd_model(bundle)
    from kd_metrics import evaluate, softmax
    rec = km.StepRecognizer(bundle, device="cuda" if torch.cuda.is_available() else "cpu")
    cfg, dev = rec.cfg, rec.device
    items = [i for i in items if i["task"] in cfg["vocab"]]
    if not items:
        raise RuntimeError("no corrected videos belong to a task the model knows")

    def tens(i):
        return {**i, "xt": torch.from_numpy(i["x"])[None].to(dev), "yt": torch.from_numpy(i["y"]).to(dev)}

    tr = [tens(i) for i in items]
    te = [tens(i) for i in testset if i["task"] in cfg["vocab"]]

    def score(model, data):
        if not data:
            return None, {}
        model.eval()
        per = {}
        with torch.no_grad():
            for t in sorted({d["task"] for d in data}):
                vids = [{"probs": softmax(model(d["xt"], t)[-1][0].float().cpu().numpy(), cfg["temperature"].get(t, 1.0)),
                         "gt": d["y"], "n_classes": len(cfg["vocab"][t])} for d in data if d["task"] == t]
                per[t] = evaluate(vids, cfg["fps"], cfg["min_len_s"])
        return float(np.mean([r["macro_f1"] for r in per.values()])), per

    def smoothing_loss(logits):
        lp = F.log_softmax(logits, -1)
        return torch.clamp((lp[:, 1:] - lp[:, :-1].detach()) ** 2, max=16).mean()

    old_f1, _ = score(rec.model, te)
    model = copy.deepcopy(rec.model).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    cw = {}
    for t in {i["task"] for i in tr}:
        n = len(cfg["vocab"][t])
        c = np.bincount(np.concatenate([i["y"] for i in tr if i["task"] == t]), minlength=n) + 1
        w = c ** -0.5
        cw[t] = torch.tensor(w / w.mean(), dtype=torch.float32, device=dev)
    best, best_state, bad = -1.0, copy.deepcopy(model.state_dict()), 0
    for ep in range(epochs):
        model.train()
        random.shuffle(tr)
        tot = 0.0
        for it in tr:
            outs = model(it["xt"], it["task"])
            loss = sum(F.cross_entropy(o[0], it["yt"], weight=cw[it["task"]]) + 0.15 * smoothing_loss(o) for o in outs)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            tot += loss.item()
        s, _ = score(model, tr)
        if s > best:
            best, best_state, bad = s, copy.deepcopy(model.state_dict()), 0
        else:
            bad += 1
        log(f"epoch {ep} loss {tot / len(tr):.3f} train macro-F1 {s:.1f}")
        if bad >= patience:
            break
    model.load_state_dict(best_state)
    new_f1, per = score(model, te)
    buf = io.BytesIO()
    torch.save({k: v.cpu() for k, v in model.state_dict().items()}, buf)
    return buf.getvalue(), new_f1, old_f1, per


TRAINER = {"fn": torch_train_and_eval}


def run_retrain(ctx, tmp):
    db, st = get_store(), get_storage()
    ctx.stage("data", 5)
    active = ml_adapter.active_version()
    bundle = ml_adapter.bundle_dir_for(active)
    pending, items = collect_items(tmp)
    ctx.log(f"{len(pending)} approved corrections from {len(items)} videos")
    if not items:
        raise RuntimeError("no approved corrections with stored features to train on")
    testset = load_testset(bundle)
    ctx.log(f"test set: {len(testset)} videos" if testset else "no test set found next to the bundle")

    ctx.stage("train", 20)
    state, new_f1, old_f1, per = TRAINER["fn"](bundle, items, testset, ctx.log)

    ctx.stage("eval", 80)
    version = max([v["version"] for v in db.select("model_versions")] or [1]) + 1
    path = f"models/v{version}"
    st.put_bytes("outputs", f"{path}/model.pt", state, "application/octet-stream")
    cfg_path = os.path.join(bundle, "config.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    cfg["created"] = now_iso()
    cfg["retrained_from"] = active["version"] if active else 1
    st.put_bytes("outputs", f"{path}/config.json", json.dumps(cfg, indent=1).encode(), "application/json")
    activate = should_activate(new_f1, old_f1)
    metrics = {"test_macro_f1": new_f1, "previous_macro_f1": old_f1, "per_task": per,
               "corrections": len(pending), "videos": len(items),
               "decision": ("activated: test macro-F1 not worse" if activate else
                            "kept previous version: " + ("no test set" if new_f1 is None else "test macro-F1 is worse"))}
    ctx.log(f"test macro-F1 new {new_f1} vs active {old_f1}: {metrics['decision']}")

    ctx.stage("activate", 95)
    row = db.insert("model_versions", {"version": version, "path": path, "metrics": metrics, "active": False,
                                       "created_at": now_iso()})
    if activate:
        for v in db.select("model_versions", {"active": True}):
            db.update("model_versions", {"id": v["id"]}, {"active": False})
        db.update("model_versions", {"id": row["id"]}, {"active": True})
        ml_adapter.reset_recognizer()
    for m in pending:
        db.update("correction_memory", {"id": m["id"]}, {"used_in_version": version})
    get_settings()
    return row
