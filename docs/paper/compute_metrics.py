"""Collect every number used in the paper from the project's own outputs (no hand-typed results).

    backend/.venv/Scripts/python docs/paper/compute_metrics.py <dub_check_outputs_dir>

Inputs: ml/kaushaldub_model/results.json (training notebook), the dub-check notebook outputs (unzipped),
demo/demo_check*.json and demo/live_candidates/check.json (step model on unseen COIN test videos, CPU),
backend/data_live/kaushaldub.sqlite (30-video Sarvam batch). Output: docs/paper/metrics.json + console summary."""
import json
import os
import re
import sqlite3
import sys
import wave
from collections import defaultdict
from datetime import datetime

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ml"))
from kd_metrics import evaluate  # noqa: E402

dub = sys.argv[1]
out = {}
TARGET = ["ReplaceMobileScreenProtector", "PerformCPR", "PolishCar"]
TRAINED = TARGET + ["MakePizza", "UseRiceCookerToCookRice"]

# ---------------------------------------------------------------- 1. step-model comparison (test set)
res = json.load(open(os.path.join(ROOT, "ml", "kaushaldub_model", "results.json"), encoding="utf-8"))
runs = {}
for name, run in res["runs"].items():
    pt = run["per_task"]
    row = {}
    for group, tasks in (("target", TARGET), ("trained5", TRAINED)):
        ts = [t for t in tasks if t in pt]
        for k in ("macro_f1", "f1@50", "edit", "bf1@2s", "acc", "ece"):
            row[f"{group}_{k}"] = round(float(np.mean([pt[t][k] for t in ts])), 1) if ts else None
        if all("ece_raw" in pt[t] for t in ts) and ts:
            row[f"{group}_ece_raw"] = round(float(np.mean([pt[t]["ece_raw"] for t in ts])), 1)
    row["minutes"] = round(run.get("minutes", 0), 1)
    row["per_task_macro_f1"] = {t: round(pt[t]["macro_f1"], 1) for t in pt}
    row["test_videos"] = {t: pt[t].get("videos") for t in pt}
    runs[name] = row
out["models"] = runs
out["curve"] = {k: {m: round(v[m], 1) for m in v} for k, v in res["curve"].items()}
out["few_shot"] = {k: {m: round(v[m], 1) for m in v} for k, v in res["few_shot"].items()}

# ---------------------------------------------------------------- 2. dub-check run (COIN CPR test video)
log = json.load(open(os.path.join(dub, "run_log.json"), encoding="utf-8"))
sv = json.load(open(os.path.join(dub, "steps_vision.json"), encoding="utf-8"))
gt = log["coin_video"]["ground_truth"]
vocab = ["background", "press the chest of the patient", "do artificial breathing to the patient",
         "check the breath of the patient", "check the pulse of the patient", "check the foreign matter in the mouse",
         "call emergency number"]
fps, T = 2, int(log["video_s"] * 2)


def frames(segs):
    y = np.zeros(T, np.int64)
    for lab, a, b in segs:
        y[int(a * fps):int(b * fps)] = vocab.index(lab)
    return y


pred = frames([(s["label"], s["start"], s["end"]) for s in sv["merged"]])
gtl = frames([(l, a, b) for l, (a, b) in gt])
probs = np.eye(len(vocab))[pred]
m = evaluate([{"probs": probs, "gt": gtl, "n_classes": len(vocab)}], fps, 2.0)
out["dubcheck_steps"] = {k: round(float(m[k]), 1) for k in ("macro_f1", "f1@50", "edit", "acc", "bf1@2s")}
out["dubcheck_steps"].update(pred_steps=len(sv["merged"]), gt_steps=len(gt), video_s=log["video_s"])
out["timings"] = log["timings"]
pl = log["placements"]
out["placement"] = {l: {"max_speed": max(p["speed"] for p in v), "overflow_s": round(sum(p["overflow_s"] for p in v), 2),
                        "sped_up": sum(p["speed"] > 1.0 for p in v), "clips": len(v)} for l, v in pl.items()}


def wav_seconds(folder):
    tot = 0.0
    for f in os.listdir(folder):
        if f.endswith(".wav") and "_fit" not in f:
            with wave.open(os.path.join(folder, f)) as w:
                tot += w.getnframes() / w.getframerate()
    return tot


for sysname in ("indicparler", "sarvam"):
    a = wav_seconds(os.path.join(dub, f"tts_{sysname}"))
    t = log["timings"][f"tts_{sysname}"]
    out.setdefault("tts", {})[sysname] = {"audio_s": round(a, 1), "synth_s": t, "rtf": round(t / a, 2)}


# ASR agreement (no human reference exists: inter-system WER only)
def words(s):
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    d = np.zeros((len(r) + 1, len(h) + 1), int)
    d[:, 0], d[0, :] = range(len(r) + 1), range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[-1, -1] / max(len(r), 1)


def transcript(name):
    j = json.load(open(os.path.join(dub, f"transcript_{name}.json"), encoding="utf-8"))
    segs = j if isinstance(j, list) else j.get("segments", j.get("segs", []))
    return " ".join(s["text"] for s in segs)


tw, ts = transcript("whisper"), transcript("sarvam")
out["asr"] = {"wer_whisper_vs_sarvam": round(wer(ts, tw) * 100, 1), "words_sarvam": len(words(ts)),
              "words_whisper": len(words(tw)), "whisper_adds_music_tag": "music" in words(tw)[:2]}

# MT agreement between IndicTrans2 and Sarvam (chrF; agreement, not accuracy)
try:
    import sacrebleu
    it2 = json.load(open(os.path.join(dub, "translations_indictrans2.json"), encoding="utf-8"))
    sar = json.load(open(os.path.join(dub, "translations_sarvam.json"), encoding="utf-8"))
    for lang in ("hi", "kn"):
        a, b = it2[lang], sar[lang]
        out.setdefault("mt_agreement_chrf", {})[lang] = round(sacrebleu.corpus_chrf(a, [b]).score, 1)
        out.setdefault("mt_chars", {})[lang] = {"indictrans2": sum(map(len, a)), "sarvam": sum(map(len, b))}
except Exception as e:
    out["mt_agreement_error"] = str(e)[:200]

# Grounding of LLM narration: content words not present in the speech or the step label
sw = json.load(open(os.path.join(dub, "steps_written.json"), encoding="utf-8"))
stop = set("a an the to of and or for in on at is are be by with if no not your you it this that until just then "
           "before after over two five thirty least ensure give deliver".split())
evidence = set(words(ts + " " + tw + " " + " ".join(vocab)))
narr = " ".join(s["narration"] for s in sw["steps"])
content = [w for w in words(narr) if w not in stop and not w.isdigit()]
unsupported = sorted({w for w in content if w not in evidence and w.rstrip("s") not in evidence})
out["llm_grounding"] = {"content_words": len(content), "unsupported": unsupported,
                        "supported_pct": round(100 * (1 - sum(w in unsupported for w in content) / max(len(content), 1)), 1),
                        "quiz_items": len(sw.get("quiz", []))}

# ---------------------------------------------------------------- 3. step model on unseen videos (laptop CPU)
cands = []
for f in ("demo_check_playlist_demo4.json", os.path.join("live_candidates", "check.json")):
    p = os.path.join(ROOT, "demo", f)
    if os.path.exists(p):
        cands += json.load(open(p, encoding="utf-8"))
if cands:
    out["unseen_cpu"] = {
        "videos": len(cands),
        "macro_f1_mean": round(float(np.mean([c["macro_f1"] for c in cands])), 1),
        "macro_f1_range": [min(c["macro_f1"] for c in cands), max(c["macro_f1"] for c in cands)],
        "frame_acc_mean": round(float(np.mean([c["frame_acc"] for c in cands])), 1),
        "cpu_s_per_video_s": round(float(np.mean([c["cpu_seconds"] / c["duration_s"] for c in cands])), 2),
        "rows": [{k: c[k] for k in ("video", "task", "duration_s", "steps", "gt_steps", "macro_f1", "f1@50", "cpu_seconds")}
                 for c in cands]}

# ---------------------------------------------------------------- 4. 30-video Sarvam batch (end to end)
db = os.path.join(ROOT, "backend", "data_live", "kaushaldub.sqlite")
if os.path.exists(db):
    c = sqlite3.connect(db)
    vids = {v["id"]: v for v in (json.loads(d) for (d,) in c.execute("select data from videos"))}
    jobs = [json.loads(d) for (d,) in c.execute("select data from jobs")]
    per = defaultdict(lambda: {"inr": 0.0, "sec": 0.0, "stages": defaultdict(float)})
    for j in jobs:
        if j["video_id"] in vids and j["status"] == "done":
            p = per[j["video_id"]]
            p["inr"] += (j.get("cost") or {}).get("inr", 0)
            if j.get("started_at") and j.get("finished_at"):
                p["sec"] += (datetime.fromisoformat(j["finished_at"]) - datetime.fromisoformat(j["started_at"])).total_seconds()
    dom = defaultdict(list)
    for vid, p in per.items():
        v = vids[vid]
        dom[v["domain"]].append({"inr": p["inr"], "sec": p["sec"], "len": v.get("duration_s") or 0,
                                 "steps": len([1 for (d,) in c.execute("select data from steps") if json.loads(d)["video_id"] == vid]),
                                 "low": v.get("model_segments") and sum(s["confidence"] < 0.6 for s in v["model_segments"]),
                                 "llm": (v.get("llm") or "").split(":")[0]})
    rows = {}
    for d, rs in dom.items():
        rows[d] = {"n": len(rs), "inr_mean": round(np.mean([r["inr"] for r in rs]), 2),
                   "min_mean": round(np.mean([r["sec"] for r in rs]) / 60, 1), "len_mean": round(np.mean([r["len"] for r in rs])),
                   "steps_mean": round(np.mean([r["steps"] for r in rs]), 1)}
    allr = [r for rs in dom.values() for r in rs]
    out["batch"] = {"per_domain": rows, "videos": len(allr), "inr_total": round(sum(r["inr"] for r in allr), 2),
                    "inr_all_attempts": round(sum((j.get("cost") or {}).get("inr", 0) for j in jobs), 2),
                    "inr_mean": round(np.mean([r["inr"] for r in allr]), 2),
                    "min_mean": round(np.mean([r["sec"] for r in allr]) / 60, 1),
                    "inr_per_video_minute": round(sum(r["inr"] for r in allr) / (sum(r["len"] for r in allr) / 60), 2),
                    "llm_used": {k: sum(r["llm"] == k for r in allr) for k in {r["llm"] for r in allr}},
                    "template_fallbacks": sum(bool(v.get("llm_fallback")) for v in vids.values())}

json.dump(out, open(os.path.join(os.path.dirname(__file__), "metrics.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(json.dumps({k: v for k, v in out.items() if k not in ("models",)}, indent=1, ensure_ascii=False)[:6000])
print("\nmodels (target skills):")
for n, r in runs.items():
    print(f"  {n:<15} mF1 {r['target_macro_f1']}  F1@50 {r['target_f1@50']}  edit {r['target_edit']}  "
          f"bF1 {r['target_bf1@2s']}  acc {r['target_acc']}  ECE {r.get('target_ece_raw')}->{r['target_ece']}  "
          f"| 5 skills mF1 {r['trained5_macro_f1']}  min {r['minutes']}")
