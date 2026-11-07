"""Step 1b: download the manifest's videos (run on Colab/Kaggle, not locally if YouTube is blocked).
pip install -U yt-dlp deno ; python download_videos.py --group target --out /content/videos
Videos are capped at 360p to save space. Missing/private videos are skipped and listed in missing.txt."""
import json, os, argparse, subprocess
ap = argparse.ArgumentParser()
ap.add_argument("--manifest", default="manifest.json"); ap.add_argument("--group", choices=["target", "cooking", "all"], default="target")
ap.add_argument("--out", default="videos"); a = ap.parse_args()
m = json.load(open(a.manifest)); os.makedirs(a.out, exist_ok=True)
missing = []
for v in m["videos"]:
    if a.group != "all" and v["group"] != a.group: continue
    d = os.path.join(a.out, v["task"]); os.makedirs(d, exist_ok=True)
    if any(x.startswith(v["id"] + ".") for x in os.listdir(d)): continue
    f = os.path.join(d, v["id"] + ".%(ext)s")
    r = subprocess.run(["yt-dlp", "-q", "--remote-components", "ejs:github", "-f", "bv*[height<=360]/b[height<=360]/bv*/b", "-o", f, v["url"]])
    f = next((os.path.join(d, x) for x in os.listdir(d) if x.startswith(v["id"] + ".")), f)
    if r.returncode != 0 or not os.path.exists(f): missing.append(v["id"])
open("missing.txt", "w").write("\n".join(missing)); print("missing:", len(missing))
