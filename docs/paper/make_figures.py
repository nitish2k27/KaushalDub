"""Paper figures from docs/paper/metrics.json and the dub-check run (vector PDFs, IEEE column width)."""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
m = json.load(open(os.path.join(HERE, "metrics.json"), encoding="utf-8"))
dub = sys.argv[1]
os.makedirs(os.path.join(HERE, "figures"), exist_ok=True)
plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.linewidth": 0.6, "xtick.major.width": 0.6,
                     "ytick.major.width": 0.6, "legend.frameon": False, "pdf.fonttype": 42})
COL = 3.45  # IEEE column width in inches

# Fig. 2 -- data efficiency (left) and few-shot on the unseen skill (right)
fig, (a, b) = plt.subplots(1, 2, figsize=(COL, 1.55), gridspec_kw={"width_ratios": [1.1, 1]})
ks = ["5", "10", "20", "all"]
xs = [5, 10, 20, 33]
a.plot(xs, [m["curve"][k]["macro_f1"] for k in ks], "o-", color="#0B6E6E", ms=3, lw=1, label="macro-F1")
a.plot(xs, [m["curve"][k]["f1@50"] for k in ks], "s--", color="#9A4A06", ms=3, lw=1, label="F1@50")
a.set_xticks(xs, ["5", "10", "20", "all"])
a.set_xlabel("training videos per skill")
a.set_ylabel("score (%)")
a.set_ylim(0, 50)
a.grid(alpha=0.25, lw=0.4)
a.legend(loc="lower right", fontsize=6.5)
a.set_title("(a) data efficiency", fontsize=7.5)
fs = m["few_shot"]
K = [0, 1, 5, 10]
proto = [fs[f"prototype_K{k}"]["macro_f1"] for k in K]
fine = [fs.get(f"finetune_K{k}", {}).get("macro_f1") for k in K]
w = 0.38
b.bar([i - w / 2 for i in range(4)], proto, w, color="#7FB8B5", label="prototype")
b.bar([i + w / 2 for i in range(2, 4)], [fine[2], fine[3]], w, color="#0B6E6E", label="+ head fine-tune")
b.set_xticks(range(4), [str(k) for k in K])
b.set_xlabel("support videos $K$")
b.set_ylim(0, 40)
b.grid(axis="y", alpha=0.25, lw=0.4)
b.legend(loc="upper left", fontsize=6)
b.set_title("(b) few-shot, unseen skill", fontsize=7.5)
fig.tight_layout(pad=0.3, w_pad=0.8)
fig.savefig(os.path.join(HERE, "figures", "data_efficiency.pdf"), bbox_inches="tight", pad_inches=0.02)

# Fig. 3 -- CPR case study: COIN ground truth, predicted steps, Hindi narration placement
log = json.load(open(os.path.join(dub, "run_log.json"), encoding="utf-8"))
sv = json.load(open(os.path.join(dub, "steps_vision.json"), encoding="utf-8"))
col = {"press the chest of the patient": "#0B6E6E", "do artificial breathing to the patient": "#D9822B"}
fig, ax = plt.subplots(figsize=(COL, 1.3))
rows = [("COIN ground truth", [(l, a_, b_) for l, (a_, b_) in log["coin_video"]["ground_truth"]]),
        ("Predicted steps", [(s["label"], s["start"], s["end"]) for s in sv["merged"]])]
for y, (name, segs) in enumerate(rows[::-1]):
    for lab, s, e in segs:
        ax.broken_barh([(s, e - s)], (y - 0.32, 0.64), color=col.get(lab, "#888"), lw=0)
for p in log["placements"]["hi"]:
    ax.broken_barh([(p["start"], p["end"] - p["start"])], (2 - 0.32, 0.64), color="#5B6B78", lw=0)
ax.set_yticks([0, 1, 2], ["Predicted", "Ground truth", "Hindi narration"])
ax.set_xlim(35, 112)
ax.set_xlabel("time (s)")
ax.tick_params(axis="y", length=0)
for sp in ("top", "right", "left"):
    ax.spines[sp].set_visible(False)
from matplotlib.patches import Patch  # noqa: E402
ax.legend(handles=[Patch(color=col["press the chest of the patient"], label="compressions"),
                   Patch(color=col["do artificial breathing to the patient"], label="breaths"),
                   Patch(color="#5B6B78", label="TTS clip")], ncol=3, fontsize=6, loc="upper center",
          bbox_to_anchor=(0.45, 1.38))
fig.tight_layout(pad=0.2)
fig.savefig(os.path.join(HERE, "figures", "cpr_timeline.pdf"), bbox_inches="tight", pad_inches=0.02)

# Fig. 4 -- per-stage latency, API vs open models (same CPR video, Kaggle T4)
t = m["timings"]
stages = ["ASR", "Translation", "Speech synthesis"]
api = [t["asr_sarvam"], t["mt_sarvam"], t["tts_sarvam"]]
loc = [t["asr_whisper"], t["mt_indictrans2"], t["tts_indicparler"]]
fig, ax = plt.subplots(figsize=(COL, 1.45))
yy = range(len(stages))
ax.barh([y + 0.2 for y in yy], api, 0.38, color="#0B6E6E", label="Sarvam API")
ax.barh([y - 0.2 for y in yy], loc, 0.38, color="#D9822B", label="open models on a T4 GPU")
for y, v in zip(yy, api):
    ax.text(v + 3, y + 0.2, f"{v:.1f}", va="center", fontsize=6)
for y, v in zip(yy, loc):
    ax.text(v + 3, y - 0.2, f"{v:.1f}", va="center", fontsize=6)
ax.set_yticks(list(yy), stages)
ax.invert_yaxis()
ax.set_xlabel("seconds for a 120 s video (Hindi + Kannada)")
ax.set_xlim(0, 290)
ax.legend(fontsize=6, loc="upper center", ncol=2, bbox_to_anchor=(0.45, 1.22))
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
fig.tight_layout(pad=0.2)
fig.savefig(os.path.join(HERE, "figures", "latency.pdf"), bbox_inches="tight", pad_inches=0.02)
print("figures written:", os.listdir(os.path.join(HERE, "figures")))
