"""Run the trained step model on the demo videos, compare with COIN ground truth, and estimate provider cost.

    backend/.venv/Scripts/python backend/scripts/demo_check.py [demo/videos/*.mp4]

Needs requirements-ml.txt and ml/kaushaldub_model/. No API keys are used: this only runs the local vision model
(CLIP + MS-TCN) and computes what the Sarvam calls *would* cost for the same video (from the detected step
lengths and kd_pipeline's narration word budget of ~2 words per second of step)."""
import glob
import json
import os
import re
import sys
import time

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.environ.setdefault("KD_IGNORE_ENV_FILE", "1")
os.environ["STEP_MODEL"] = "bundle"

from app import costs  # noqa: E402
from app.media import probe_duration  # noqa: E402
from app.ml_adapter import BundleRecognizer  # noqa: E402
from app.mlpath import kp  # noqa: E402

TASK_BY_NAME = {"cpr": "PerformCPR", "screen": "ReplaceMobileScreenProtector", "polish": "PolishCar",
                "pizza": "MakePizza", "rice": "UseRiceCookerToCookRice", "omelet": "CookOmelet", "egg": "CookOmelet"}
CHARS_PER_WORD = 5.8          # English incl. spaces
INDIC_FACTOR = 1.1            # Hindi/Kannada text is about as long in characters
LLM_FILL = 0.7                # the LLM usually writes ~70% of the word budget
QUIZ_CHARS = 350              # 3 questions x (question + 4 options)


def estimate(steps, duration, targets=2):
    words = sum(max(4, int((s["end"] - s["start"]) * 2.0)) for s in steps) * LLM_FILL
    en = words * CHARS_PER_WORD
    mt = int((en + QUIZ_CHARS) * targets)
    tts = int(en * INDIC_FACTOR * targets)
    api = costs.empty_cost()
    costs.add(api, "sarvam", audio_min=duration / 60, mt_chars=mt, tts_chars=tts)
    hybrid = costs.empty_cost()
    costs.add(hybrid, "sarvam", mt_chars=mt, tts_chars=tts)               # Whisper local + Sarvam MT/TTS
    return {"narration_words": int(words), "mt_chars": mt, "tts_chars": tts, "all_sarvam_inr": api["inr"],
            "whisper_plus_sarvam_inr": hybrid["inr"], "clips": len(steps) * targets}


def gt_labels(segs, vocab, n, fps):
    y = np.zeros(n, np.int64)
    for label, a, b in segs:
        if label in vocab:
            y[int(a * fps):int(b * fps)] = vocab.index(label)
    return y


def main(paths):
    gt = json.load(open(os.path.join(ROOT, "demo", "ground_truth.json"), encoding="utf-8"))
    from kd_metrics import evaluate
    t0 = time.time()
    rec = BundleRecognizer(os.path.join(ROOT, "ml", "kaushaldub_model"))
    print(f"model loaded in {time.time() - t0:.1f}s on {rec.rec.device}\n")
    report = []
    for p in paths:
        name = os.path.basename(p).lower()
        task = next(t for k, t in TASK_BY_NAME.items() if k in name)
        vid = re.search(r"_([A-Za-z0-9_-]{11})\.mp4$", os.path.basename(p))
        vid = vid.group(1) if vid else None
        dur = probe_duration(p)
        t1 = time.time()
        out = rec.predict(p, task)
        steps = kp.merge_steps(out["steps"])
        secs = time.time() - t1
        print(f"== {os.path.basename(p)}  ({task}, {dur:.0f}s)  step model: {secs:.1f}s on CPU")
        for s in steps:
            flag = "  LOW" if s["low_confidence"] else ""
            print(f"   {s['idx']}. {s['start']:6.1f}-{s['end']:6.1f}s  {s['label']:<45} conf {s['confidence']:.2f}{flag}")
        row = {"video": os.path.basename(p), "task": task, "duration_s": round(dur, 1), "cpu_seconds": round(secs, 1),
               "steps": len(steps), "low_conf": sum(s["low_confidence"] for s in steps), **estimate(steps, dur)}
        if vid in gt:
            vocab = rec.vocab(task)
            n = len(out["features"])
            probs = rec.rec.predict_features(out["features"], task)
            m = evaluate([{"probs": probs, "gt": gt_labels(gt[vid], vocab, n, rec.fps), "n_classes": len(vocab)}],
                         rec.fps, rec.cfg["min_len_s"])
            row.update({"gt_steps": len(gt[vid]), "macro_f1": round(m["macro_f1"], 1), "f1@50": round(m["f1@50"], 1),
                        "frame_acc": round(m["acc"], 1)})
            print("   ground truth: " + " | ".join(f"{a:.0f}-{b:.0f}s {l}" for l, a, b in gt[vid]))
            print(f"   macro-F1 {row['macro_f1']}  F1@50 {row['f1@50']}  frame accuracy {row['frame_acc']}%")
        print(f"   est. cost for Hindi + Kannada: all-Sarvam ₹{row['all_sarvam_inr']}, "
              f"Whisper local + Sarvam ₹{row['whisper_plus_sarvam_inr']}, all local ₹0\n")
        report.append(row)
    out = os.path.join(ROOT, "demo", "demo_check.json")
    json.dump(report, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1:] or sorted(glob.glob(os.path.join(ROOT, "demo", "videos", "*.mp4"))))
