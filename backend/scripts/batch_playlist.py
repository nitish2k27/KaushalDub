"""Fill the learner library from demo/playlist.csv through the running KaushalDub API.

For each video: upload (local file from demo/videos/ if present, else the YouTube link) -> stages 1-4 ->
approve -> stages 5-7 -> publish. Writes demo/batch_results.csv with status, time and estimated cost per video,
which is the data for the cost comparison.

    # Sarvam for speech, translation and voice (works on a laptop)
    python backend/scripts/batch_playlist.py --mode sarvam --only-demo
    python backend/scripts/batch_playlist.py --mode sarvam --limit 10

    # Free local models (needs the GPU worker: Supabase + Redis + notebooks/worker_gpu.ipynb)
    python backend/scripts/batch_playlist.py --mode local --api https://<you>-<space>.hf.space --token <access token>

Sign-in: with a local dev server (DEV_AUTH=true) the script signs in as --email; against a deployed API pass
--token (copy it in the browser console: (await supabase.auth.getSession()).data.session.access_token)."""
import argparse
import csv
import glob
import os
import sys
import time

import httpx

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODES = {"sarvam": {"asr": "sarvam", "mt": "sarvam", "tts": "sarvam"},
         "local": {"asr": "whisper", "mt": "indictrans2", "tts": "indicparler"},
         "plan": {}}                      # use whatever the trainer's plan says


def wait(c, job_id, label, timeout=3600):
    t0, last = time.time(), None
    while True:
        j = c.get(f"/jobs/{job_id}").json()
        now = f"{j['stage']} {j['progress']}%"
        if now != last:
            print(f"      {label}: {now}", flush=True)
            last = now
        if j["status"] not in ("queued", "running"):
            return j
        if time.time() - t0 > timeout:
            raise TimeoutError(f"{label} still {j['status']} after {timeout}s")
        time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--mode", choices=list(MODES), default="sarvam")
    ap.add_argument("--email", default="trainer@example.com", help="dev sign-in (local server with DEV_AUTH)")
    ap.add_argument("--name", default="Nitish")
    ap.add_argument("--token", default=os.getenv("KD_TOKEN"), help="Supabase access token for a deployed API")
    ap.add_argument("--playlist", default=os.path.join(ROOT, "demo", "playlist.csv"))
    ap.add_argument("--only-demo", action="store_true", help="only the ★ videos downloaded to demo/videos/")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="", help="comma-separated YouTube ids to process (default: all)")
    ap.add_argument("--targets", default="hi,kn")
    ap.add_argument("--asr", choices=["sarvam", "indicconformer", "whisper"], default=None,
                    help="override speech-to-text (local mode: indicconformer for Hindi/Kannada speech, sarvam for English at ₹0.49/min)")
    ap.add_argument("--dub-mode", choices=["steps", "full"], default="steps")
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--skip-existing", action="store_true", default=True)
    a = ap.parse_args()

    c = httpx.Client(base_url=a.api.rstrip("/"), timeout=600)
    if a.token:
        c.headers["Authorization"] = f"Bearer {a.token}"
    else:
        r = c.post("/dev/login", json={"email": a.email, "name": a.name, "role": "trainer"})
        if r.status_code != 200:
            sys.exit(f"Dev sign-in failed ({r.status_code}). Start backend/scripts/dev.py or pass --token.")
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    c.put("/me/role", json={"role": "trainer"})
    plan = c.get("/me/plan").json()
    print(f"Signed in. Plan: {plan['plan']} · free videos left: {plan['free_left']} · mode: {a.mode}\n")

    rows = list(csv.DictReader(open(a.playlist, encoding="utf-8")))
    if a.only_demo:
        rows = [r for r in rows if r["demo"]]
    if a.ids:
        want = [i.strip() for i in a.ids.split(",") if i.strip()]
        rows = sorted([r for r in rows if r["youtube_id"] in want], key=lambda r: want.index(r["youtube_id"]))
    if a.limit:
        rows = rows[:a.limit]
    mine = c.get("/videos").json()
    existing = {v["title"] for v in mine if v["status"] not in ("failed", "needs_credits", "review")}
    in_review = {v["title"]: v["id"] for v in mine if v["status"] == "review"}     # processed, never dubbed
    retry = {v["title"]: v["id"] for v in mine if v["status"] in ("failed", "needs_credits")}
    out_path = os.path.join(ROOT, "demo", f"batch_results_{a.mode}.csv")
    prev = list(csv.DictReader(open(out_path, encoding="utf-8"))) if os.path.exists(out_path) else []
    results = []
    for i, r in enumerate(rows, 1):
        title = r["title"][:110]
        print(f"[{i}/{len(rows)}] {title}  ({r['task']}, {r['duration_s']} s)")
        if title in existing:
            print("      already in your videos, skipped\n")
            continue
        if title in retry:
            c.delete(f"/videos/{retry[title]}")
            print("      earlier attempt failed: deleted, trying again")
        local = glob.glob(os.path.join(ROOT, "demo", "videos", f"*_{r['youtube_id']}.mp4"))
        form = {"title": title, "task": r["task"], "targets": a.targets, "spoken_lang": "auto", "voice": "Female",
                "quiz": "true", "dub_mode": a.dub_mode, **MODES[a.mode], **({"asr": a.asr} if a.asr else {})}
        t0 = time.time()
        row = {"youtube_id": r["youtube_id"], "title": title, "task": r["task"], "duration_s": r["duration_s"],
               "mode": a.mode, "status": "", "steps": "", "cost_inr": "", "minutes": "", "error": ""}
        try:
            if title in in_review:
                vid = in_review[title]
                print("      already processed: approving and dubbing")
                j1 = (c.get(f"/videos/{vid}").json().get("job") or {"status": "done", "cost": {}})
                j1 = {**j1, "status": "done"}
            elif local:
                with open(local[0], "rb") as f:
                    up = c.post("/videos", data=form, files={"file": (os.path.basename(local[0]), f, "video/mp4")})
            else:
                up = c.post("/videos", data={**form, "youtube_url": r["url"]})
            if title not in in_review:
                if up.status_code != 200:
                    raise RuntimeError(f"upload refused: {up.json().get('detail')}")
                vid = up.json()["video_id"]
                j1 = wait(c, up.json()["job_id"], "process")
            if j1["status"] != "done":
                raise RuntimeError(f"process {j1['status']}: {j1['error']}")
            ap_ = c.post(f"/videos/{vid}/approve")
            if ap_.status_code != 200:
                raise RuntimeError(f"approve refused: {ap_.json().get('detail')}")
            j2 = wait(c, ap_.json()["job_id"], "dub")
            if j2["status"] != "done":
                raise RuntimeError(f"dub {j2['status']}: {j2['error']}")
            if not a.no_publish:
                c.post(f"/videos/{vid}/publish")
            v = c.get(f"/videos/{vid}").json()
            cost = (j1.get("cost") or {}).get("inr", 0) + (j2.get("cost") or {}).get("inr", 0)
            row.update(status="published" if not a.no_publish else "ready", steps=len(v.get("steps") or []),
                       cost_inr=round(cost, 2))
            print(f"      done: {row['steps']} steps, est. ₹{row['cost_inr']}, LLM {v.get('llm')}")
        except Exception as e:
            row.update(status="failed", error=str(e)[:300])
            print(f"      FAILED: {row['error']}")
            if "needs_credits" in str(e) or "free_quota" in str(e) or "budget" in str(e):
                results.append(row)
                print("      stopping: out of credits / quota")
                break
        row["minutes"] = round((time.time() - t0) / 60, 1)
        results.append(row)
        print()
    if results:
        done_ids = {x["youtube_id"] for x in results}
        merged = [x for x in prev if x["youtube_id"] not in done_ids] + results       # keep earlier runs
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0]))
            w.writeheader()
            w.writerows(merged)
        ok = [x for x in results if x["status"] in ("published", "ready")]
        total = sum(float(x["cost_inr"] or 0) for x in ok)
        print(f"{len(ok)}/{len(results)} videos done · estimated cost ₹{total:.2f} · results in {out_path}")


if __name__ == "__main__":
    main()
