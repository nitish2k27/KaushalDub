"""Test setup: SQLite store + local storage in a temp folder, jobs run synchronously, the step model is the
deterministic mock, and every external provider (ASR, MT, TTS, LLM) is replaced by a fake."""
import json
import os
import subprocess
import sys

import numpy as np
import pytest
from cryptography.fernet import Fernet

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["KD_IGNORE_ENV_FILE"] = "1"          # a filled-in .env must never leak into tests (no real keys/Supabase)

from app import config, db, ml_adapter, providers, queue, storage  # noqa: E402
from app.mlpath import kp  # noqa: E402


# ---------------------------------------------------------------- fake providers
class FakeASR:
    name = "fake-asr"

    def detect_language(self, x, sr):
        return "en"

    def transcribe(self, x, sr, lang):
        dur = len(x) / sr
        words = ["First check the area.", "Then do the main step.", "Keep going carefully.", "Finish and check."]
        n = len(words)
        return [{"start": i * dur / n, "end": (i + 1) * dur / n, "text": w} for i, w in enumerate(words)]


class FakeMT:
    calls = []

    def translate(self, sents, tgt, src="en"):
        FakeMT.calls.append((tgt, len(sents)))
        return [f"[{tgt}] {s}" for s in sents]


class FakeTTS:
    calls = []

    def synth(self, items):
        FakeTTS.calls.append(len(items))
        sr = 24000
        for it in items:
            t = np.arange(int(sr * 0.8)) / sr
            kp.save_wav(it["out"], 0.2 * np.sin(2 * np.pi * 220 * t), sr)


class FakeWriter:
    def __init__(self):
        self.used, self.errors = "FakeLLM:test", {}

    def write(self, prompt, images=()):
        rows = json.loads(prompt.split("Steps:\n", 1)[1])
        return {"steps": [{"idx": r["idx"], "title": f"Step {r['idx']}", "instruction": f"Do {r['detected_step']}.",
                           "narration": f"Now {r['detected_step']}."} for r in rows],
                "quiz": [{"q": "What comes first?", "options": ["A", "B", "C", "D"], "answer": 0},
                         {"q": "What comes last?", "options": ["A", "B", "C", "D"], "answer": 3},
                         {"q": "Which tool?", "options": ["A", "B", "C", "D"], "answer": 1}]}


class Fakes:
    """Per-test switches: put a provider name in `broke` (with an error message) to make it fail."""

    def __init__(self):
        self.broke = {}

    def _check(self, stage, name):
        if (stage, name) in self.broke:
            raise RuntimeError(self.broke[(stage, name)])

    def asr(self, name, keys, cache):
        self._check("asr", name)
        return FakeASR()

    def mt(self, name, keys):
        self._check("mt", name)
        return FakeMT()

    def tts(self, name, keys, voice="Female"):
        self._check("tts", name)
        return FakeTTS()

    def writer(self, keys):
        return FakeWriter(), {}


# ---------------------------------------------------------------- environment
@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "REDIS_URL", "SARVAM_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STEP_MODEL", "mock")
    monkeypatch.setenv("DEV_AUTH", "true")
    monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())
    monkeypatch.setenv("RETRY_DELAYS", "0,0")
    monkeypatch.setenv("SARVAM_API_KEY", "platform-sarvam-test-key")       # platform keys exist (fake values)
    monkeypatch.setenv("GPU_QUEUE_ENABLED", "false")
    config.reset_settings()
    db.set_store(db.SqliteStore(str(tmp_path / "data" / "test.sqlite")))
    storage.set_storage(storage.LocalStorage(str(tmp_path / "data" / "files"), "test", "http://testserver"))
    queue.INLINE_SYNC = True
    ml_adapter.reset_recognizer()
    fakes = Fakes()
    for k, fn in {"asr": fakes.asr, "mt": fakes.mt, "tts": fakes.tts, "writer": fakes.writer}.items():
        monkeypatch.setitem(providers.FACTORIES, k, fn)
    FakeMT.calls.clear()
    FakeTTS.calls.clear()
    yield fakes
    config.reset_settings()


@pytest.fixture
def fakes(env):
    return env


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import create_app
    return TestClient(create_app())


def login(client, role, email=None, name=None):
    email = email or f"{role}@example.com"
    r = client.post("/dev/login", json={"email": email, "name": name or role.title(), "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """12 s 320x240 test pattern with a tone: enough for every pipeline stage."""
    out = tmp_path_factory.mktemp("media") / "sample.mp4"
    r = subprocess.run([kp.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=duration=12:size=320x240:rate=15", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return str(out)


def upload(client, headers, video, **form):
    data = {"title": "CPR basics", "task": "PerformCPR", "targets": "hi,kn", "spoken_lang": "auto",
            "voice": "Female", "quiz": "true", **form}
    with open(video, "rb") as f:
        return client.post("/videos", data=data, files={"file": ("sample.mp4", f, "video/mp4")}, headers=headers)


def ready_video(client, headers, video, publish=True):
    r = upload(client, headers, video)
    assert r.status_code == 200, r.text
    vid = r.json()["video_id"]
    assert client.get(f"/jobs/{r.json()['job_id']}", headers=headers).json()["status"] == "done"
    r = client.post(f"/videos/{vid}/approve", headers=headers)
    assert r.status_code == 200, r.text
    assert client.get(f"/jobs/{r.json()['job_id']}", headers=headers).json()["status"] == "done"
    if publish:
        assert client.post(f"/videos/{vid}/publish", headers=headers).status_code == 200
    return vid
