"""Step recogniser wrapper: loads the active model version and applies the skill's correction memory.

Correction memory (human-in-the-loop active learning): every approved annotator correction stores the CLIP
frame features of the corrected segment. Before predicting a video of skill T, the class vectors of T's head
are blended with the mean embedding of the stored segments of each class (same formula as the few-shot
prototypes in the training notebook), so the next video benefits immediately. kd_model.py is not modified:
the blend is applied to a temporary copy of the head weights."""
import io
import json
import os
import shutil
import sys
import threading

import numpy as np

from .config import ML_DIR, get_settings
from .db import get_store
from .storage import get_storage

MOCK_VOCAB = {
    "PerformCPR": ["background", "check responsiveness", "call for help", "open the airway",
                   "give chest compressions", "give rescue breaths"],
    "ReplaceMobileScreenProtector": ["background", "remove the old protector", "clean the screen",
                                     "align the new protector", "press out the bubbles"],
    "PolishCar": ["background", "wash the car", "apply polish", "buff the surface", "wipe off residue"],
    "MakePizza": ["background", "knead the dough", "spread the sauce", "add toppings", "bake the pizza"],
    "UseRiceCookerToCookRice": ["background", "wash the rice", "add water", "start the cooker", "serve the rice"],
    "CookOmelet": ["background", "crack the eggs", "whisk the eggs", "pour into the pan", "fold the omelette"],
}


def blend_prototypes(W: np.ndarray, label_embs: dict, alpha_min=0.5, k=5.0) -> np.ndarray:
    """W [C,E] class vectors; label_embs {class_index: [n,E] embeddings of corrected segments}.
    Class c becomes normalize(a*w_c + (1-a)*mean_c) with a = max(alpha_min, k/(k+n)): the more corrections,
    the more the memory counts, but the trained vector always keeps at least alpha_min of the weight."""
    nrm = lambda v: v / max(np.linalg.norm(v), 1e-8)
    P = W.astype(np.float32).copy()
    for c, Z in label_embs.items():
        Z = np.asarray(Z, np.float32)
        if Z.ndim != 2 or len(Z) == 0:
            continue
        a = max(alpha_min, k / (k + len(Z)))
        P[c] = nrm(a * nrm(P[c]) + (1 - a) * nrm(Z.mean(0)))
    return P


def active_version():
    db = get_store()
    rows = db.select("model_versions", {"active": True}, order="version", desc=True, limit=1)
    if rows:
        return rows[0]
    if db.select("model_versions", limit=1):
        return None
    return db.insert("model_versions", {"version": 1, "path": "bundle", "active": True,
                                        "metrics": {"note": "trained bundle from kaushaldub_train.ipynb"}})


def bundle_dir_for(version) -> str:
    s = get_settings()
    if not version or version["path"] == "bundle":
        return s.model_bundle_dir
    local = os.path.join(s.data_dir, "models", f"v{version['version']}")
    if not os.path.exists(os.path.join(local, "model.pt")):
        st = get_storage()
        os.makedirs(local, exist_ok=True)
        for f in ("model.pt", "config.json"):
            st.download("outputs", f"{version['path']}/{f}", os.path.join(local, f))
        for f in ("kd_model.py", "kd_metrics.py"):
            src = os.path.join(s.model_bundle_dir, f)
            shutil.copy(src if os.path.exists(src) else str(ML_DIR / f), local)
    return local


def import_kd_model(bundle):
    """Prefer the bundle's own kd_model.py (the version the weights were trained with)."""
    for p in (str(ML_DIR), bundle):
        if p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(ML_DIR))
    if os.path.exists(os.path.join(bundle, "kd_model.py")):
        sys.path.insert(0, bundle)
    for m in ("kd_model", "kd_metrics"):
        sys.modules.pop(m, None)
    import kd_model
    return kd_model


class BundleRecognizer:
    kind = "bundle"

    def __init__(self, bundle):
        if not os.path.exists(os.path.join(bundle, "model.pt")):
            raise RuntimeError(f"Step model bundle not found in {bundle}. Unzip kaushaldub_model.zip there "
                               "(config.json, model.pt, kd_model.py, kd_metrics.py) or set STEP_MODEL_REPO.")
        self.km = import_kd_model(bundle)
        self.rec = self.km.StepRecognizer(bundle)
        self.cfg = self.rec.cfg
        self.lock = threading.Lock()

    def vocab(self, task):
        return self.cfg["vocab"].get(task) or []

    def tasks(self):
        return self.rec.tasks()

    @property
    def fps(self):
        return self.cfg["fps"]

    def features(self, video):
        frames = self.km.read_frames(video, self.cfg["fps"], 224, self.cfg["max_frames"])
        return self.rec.encoder.frames(frames)

    def embed_mean(self, feats):
        import torch
        with torch.no_grad():
            x = torch.from_numpy(np.asarray(feats, np.float32))[None].to(self.rec.device)
            return self.rec.model.embed(x)[0].float().cpu().numpy()

    def predict(self, video, task, memory=None):
        import torch
        feats = self.features(video)
        with self.lock:
            W = self.rec.model.heads.W[task]
            orig = W.data.clone()
            try:
                if memory:
                    vocab = self.vocab(task)
                    embs = {}
                    for label, f in memory:
                        if label in vocab and len(f):
                            embs.setdefault(vocab.index(label), []).append(self.embed_mean(f))
                    embs = {c: np.concatenate(v) for c, v in embs.items()}
                    P = blend_prototypes(orig.cpu().numpy(), embs)
                    W.data.copy_(torch.from_numpy(P).to(W.device))
                probs = self.rec.predict_features(feats, task)
            finally:
                W.data.copy_(orig)
        out = self.rec.format(probs, task)
        out["features"], out["fps"] = feats, self.fps
        return out

    def predict_forced(self, feats, task):
        """Second try when every frame came out as background (short or unusual clips): decode again with the
        background class removed, so the trainer gets steps to review. All of them are marked low confidence."""
        with self.lock:
            probs = self.rec.predict_features(feats, task)
        probs = probs.copy()
        probs[:, 0] = 0.0
        probs /= np.maximum(probs.sum(1, keepdims=True), 1e-8)
        out = self.rec.format(probs, task)
        for s in out["steps"]:
            s["confidence"] = min(s["confidence"], 0.59)
            s["low_confidence"] = True
        return out


class MockRecognizer:
    """Deterministic stand-in (STEP_MODEL=mock) for demos without the bundle and for tests."""
    kind = "mock"
    fps = 2

    def vocab(self, task):
        return MOCK_VOCAB.get(task, ["background", "step one", "step two", "step three"])

    def tasks(self):
        return list(MOCK_VOCAB)

    def predict(self, video, task, memory=None):
        from .media import probe_duration
        dur = max(probe_duration(video), 4.0)
        labels = self.vocab(task)[1:]
        n = min(len(labels), max(2, int(dur // 3)))
        T = int(dur * self.fps)
        feats = np.random.default_rng(len(task)).normal(size=(T, 8)).astype(np.float32)
        steps, w = [], dur / n
        mem_labels = {l for l, _ in (memory or [])}
        for i in range(n):
            conf = 0.55 if i == n - 2 else 0.9
            if labels[i] in mem_labels:
                conf = min(0.95, conf + 0.2)          # memory makes the mock more confident, like the real blend
            steps.append({"idx": i + 1, "label": labels[i], "start": round(i * w, 2), "end": round((i + 1) * w, 2),
                          "confidence": conf, "low_confidence": conf < 0.6, "keyframe_s": round((i + 0.5) * w, 2)})
        return {"task": task, "duration_s": round(dur, 2), "steps": steps, "features": feats, "fps": self.fps}


_cache = {}


def get_recognizer():
    s = get_settings()
    if s.step_model == "mock":
        return _cache.setdefault("mock", MockRecognizer())
    v = active_version()
    key = f"v{v['version'] if v else 1}"
    if key not in _cache:
        _cache.clear()
        _cache[key] = BundleRecognizer(bundle_dir_for(v))
    return _cache[key]


def reset_recognizer():
    _cache.clear()


def vocab_for(task):
    try:
        return get_recognizer().vocab(task)
    except Exception:
        return MOCK_VOCAB.get(task, ["background"])


# ---------------------------------------------------------------- features and memory storage
def save_features(video_id, feats, fps):
    buf = io.BytesIO()
    np.save(buf, np.asarray(feats, np.float32))
    path = f"{video_id}/features.npy"
    get_storage().put_bytes("outputs", path, buf.getvalue(), "application/octet-stream")
    return {"path": path, "fps": fps, "frames": int(len(feats))}


def load_npy(bucket, path, tmp_dir):
    local = os.path.join(tmp_dir, path.replace("/", "_"))
    get_storage().download(bucket, path, local)
    return np.load(local)


def memory_for(task, tmp_dir):
    out = []
    for m in get_store().select("correction_memory", {"task": task}):
        try:
            out.append((m["label"], load_npy("outputs", m["feature_path"], tmp_dir)))
        except Exception:
            continue
    return out


def segment_features(feats, fps, start, end):
    a, b = int(start * fps), max(int(start * fps) + 1, int(end * fps))
    return np.asarray(feats[a:b], np.float32)


def write_segment(path, arr):
    buf = io.BytesIO()
    np.save(buf, arr)
    get_storage().put_bytes("outputs", path, buf.getvalue(), "application/octet-stream")
    return path


def bundle_meta():
    s = get_settings()
    try:
        return json.load(open(os.path.join(s.model_bundle_dir, "config.json")))
    except Exception:
        return {}
