"""Step 1: build a training manifest from the COIN annotations for KaushalDub.
Usage: python prepare_coin.py path/to/COIN.json  ->  manifest.json
COIN annotations: CC BY-NC 4.0 (credit COIN, non-commercial, do not redistribute videos)."""
import json, sys, random, collections

TARGET  = ["ReplaceMobileScreenProtector", "PerformCPR", "PolishCar"]            # mastered skills
COOKING = ["CookOmelet", "MakePizza", "UseRiceCookerToCookRice", "BoilNoodles", "MakeCookie"]  # base training + unseen-domain demo
random.seed(7)

db = json.load(open(sys.argv[1]))["database"]
tasks = TARGET + COOKING
vocab = {}          # per task: ["background", step1, step2, ...] (most frequent first)
videos = []
for t in tasks:
    vs = {k: v for k, v in db.items() if v["class"] == t}
    cnt = collections.Counter(a["label"] for v in vs.values() for a in v["annotation"])
    vocab[t] = ["background"] + [s for s, _ in cnt.most_common()]
    train_ids = sorted(k for k, v in vs.items() if v["subset"] == "training")
    random.shuffle(train_ids)
    val = set(train_ids[: max(3, round(0.15 * len(train_ids)))])
    for k, v in vs.items():
        split = "test" if v["subset"] == "testing" else ("val" if k in val else "train")
        segs = sorted(({"label": a["label"], "start": a["segment"][0], "end": a["segment"][1]}
                       for a in v["annotation"]), key=lambda s: s["start"])
        videos.append({"id": k, "task": t, "group": "target" if t in TARGET else "cooking",
                       "url": "https://www.youtube.com/watch?v=" + k, "split": split,
                       "duration": v["duration"], "window": [v["start"], v["end"]], "segments": segs})

json.dump({"tasks": tasks, "target": TARGET, "cooking": COOKING, "vocab": vocab, "videos": videos},
          open("manifest.json", "w"), indent=1, ensure_ascii=False)
tab = collections.Counter((v["task"], v["split"]) for v in videos)
for t in tasks:
    print(f"{t:32s} train {tab[(t,'train')]:3d}  val {tab[(t,'val')]:2d}  test {tab[(t,'test')]:2d}  steps {len(vocab[t])-1}")
print("total videos:", len(videos))
