"""Copy videos processed locally (SQLite + local files) into Supabase, so nothing is paid for twice.

    backend/.venv/Scripts/python backend/scripts/migrate_to_supabase.py --owner-email you@gmail.com
                                [--data-dir backend/data_live] [--dry-run]

Before running: fill SUPABASE_URL / SUPABASE_SERVICE_KEY in .env, run the migrations, and sign in to the app once with
Google as the trainer (so your user exists in Supabase). Copies every ready video with its steps, translations,
quiz, outputs, narration clips, jobs (cost records) and all files (raw video, dubbed mp4/vtt/wav, keyframes,
features). Videos already in Supabase are skipped, so it is safe to run again."""
import argparse
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.config import get_settings  # noqa: E402
from app.db import SqliteStore, SupabaseStore  # noqa: E402
from app.storage import LocalStorage, SupabaseStorage  # noqa: E402

CHILD = ["steps", "translations", "outputs", "quizzes", "tts_clips"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner-email", default="auto", help="Google account of the trainer (auto = the only user)")
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "backend", "data_live"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    s = get_settings()
    if not s.use_supabase or ".supabase.co" not in s.supabase_url:
        sys.exit("Set SUPABASE_URL (https://<ref>.supabase.co) and SUPABASE_SERVICE_KEY in .env first.")
    src = SqliteStore(os.path.join(a.data_dir, "kaushaldub.sqlite"))
    src_files = LocalStorage(os.path.join(a.data_dir, "files"), "x", "http://localhost")
    dst = SupabaseStore(s.supabase_url, s.supabase_service_key)
    dst_files = SupabaseStorage(s.supabase_url, s.supabase_service_key)

    users = dst.select("users")
    if a.owner_email == "auto":
        owner = users[0] if len(users) == 1 else None
        if not owner:
            sys.exit(f"{len(users)} users in Supabase; pass --owner-email explicitly.")
    else:
        owner = next((u for u in users if u.get("email", "").lower() == a.owner_email.lower()), None)
    if not owner:
        sys.exit(f"No Supabase user with email {a.owner_email}. Sign in to the app once with that Google account.")
    if owner.get("role") != "trainer" and not a.dry_run:
        dst.update("users", {"id": owner["id"]}, {"role": "trainer"})
    print(f"Owner: {owner['name']} ({owner['id']})")

    videos = [v for v in src.select("videos") if v["status"] == "ready"]
    print(f"{len(videos)} ready videos in {a.data_dir}")
    for v in videos:
        if dst.get("videos", v["id"]):
            print(f"  skip (already in Supabase): {v['title'][:60]}")
            continue
        print(f"  copy: {v['title'][:60]}")
        rows = {t: src.select(t, {"video_id": v["id"]}) for t in CHILD}
        jobs = src.select("jobs", {"video_id": v["id"]})
        # files: every object of this video in each bucket
        files = []
        for bucket in ("raw-videos", "outputs", "keyframes"):
            base = os.path.join(src_files.root, bucket)
            for dirpath, _, names in os.walk(base):
                for n in names:
                    rel = os.path.relpath(os.path.join(dirpath, n), base).replace(os.sep, "/")
                    if v["id"] in rel.split("/"):
                        files.append((bucket, rel))
        print(f"    {sum(len(r) for r in rows.values())} rows, {len(jobs)} jobs, {len(files)} files")
        if a.dry_run:
            continue
        for bucket, rel in files:
            dst_files.put_file(bucket, rel, src_files.local_path(bucket, rel))
        dst.insert("videos", {**v, "owner": owner["id"]})
        for t in ("steps", "translations", "outputs", "quizzes", "tts_clips"):     # parents before children
            for r in rows[t]:
                dst.insert(t, r)
        for j in jobs:
            dst.insert("jobs", {**j, "owner_id": owner["id"], "superseded_by": None})
    print("Done." if not a.dry_run else "Dry run only: nothing copied.")


if __name__ == "__main__":
    main()
