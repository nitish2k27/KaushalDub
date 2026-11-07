"""Small media helpers next to kd_pipeline's ffmpeg functions."""
import os
import re
import subprocess
import sys

from .mlpath import kp


def probe_duration(path) -> float:
    r = subprocess.run([kp.ffmpeg_exe(), "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def download_youtube(url, out_dir) -> str:
    if not re.match(r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/", url):
        raise ValueError("Only YouTube links are supported")
    os.makedirs(out_dir, exist_ok=True)
    tpl = os.path.join(out_dir, "source.%(ext)s")
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "--no-playlist", "-f", "b[height<=480][ext=mp4]/bv*[height<=480]+ba/b",
                        "--merge-output-format", "mp4", "--max-filesize", "300M", "-o", tpl, url],
                       capture_output=True, text=True, timeout=900)
    files = [f for f in os.listdir(out_dir) if f.startswith("source.")]
    if r.returncode != 0 or not files:
        raise RuntimeError("YouTube download failed: " + (r.stderr or "")[-300:])
    return os.path.join(out_dir, files[0])


def caption_vtt(steps, texts, path, placements=None):
    """Captions for one language. With placements (from the dub) cues follow the narration timing,
    otherwise they cover each step."""
    if placements:
        cues = [{"start": p["start"], "end": p["end"], "text": t} for p, t in zip(placements, texts)]
    else:
        cues = [{"start": s["start_s"], "end": s["end_s"], "text": t} for s, t in zip(steps, texts)]
    kp.write_vtt(cues, path)
    return path
