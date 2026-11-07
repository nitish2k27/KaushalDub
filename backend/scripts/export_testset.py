"""Export the COIN test split as the retrain job's test set (run where the training notebook ran).

    python export_testset.py --work /kaggle/working --out kaushaldub_model/testset

Reads the training notebook's cached CLIP features (WORK/feats/clip/<id>.npy), frame labels
(WORK/labels/<id>.npy) and manifest.json, and writes one <id>.npz per test video with x [T,512], y [T], task.
Copy the folder next to config.json/model.pt in the bundle; the retrain job compares old vs new model on it and
activates the new one only if macro-F1 is not worse."""
import argparse
import json
import os

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--work", required=True, help="training notebook WORK dir")
ap.add_argument("--out", required=True)
ap.add_argument("--manifest", default=None)
a = ap.parse_args()

man = json.load(open(a.manifest or os.path.join(a.work, "manifest.json")))
os.makedirs(a.out, exist_ok=True)
n = 0
for v in man["videos"]:
    if v["split"] != "test":
        continue
    f, l = os.path.join(a.work, "feats", "clip", f"{v['id']}.npy"), os.path.join(a.work, "labels", f"{v['id']}.npy")
    if not (os.path.exists(f) and os.path.exists(l)):
        continue
    x, y = np.load(f).astype(np.float32), np.load(l).astype(np.int64)
    k = min(len(x), len(y))
    np.savez_compressed(os.path.join(a.out, f"{v['id']}.npz"), x=x[:k], y=y[:k], task=np.array(v["task"]))
    n += 1
print(f"wrote {n} test videos to {a.out}")
