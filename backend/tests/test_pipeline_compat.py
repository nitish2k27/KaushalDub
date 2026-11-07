"""kd_pipeline's real Sarvam classes run (HTTP faked) on this OS, including Windows, and their errors are classified."""
import numpy as np
import pytest
import requests

from app import providers
from app.mlpath import kp


class FakeResp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, str(body)

    def json(self):
        return self._body


def test_sarvam_asr_runs_on_this_os(monkeypatch):
    seen = []

    def post(url, headers=None, files=None, data=None, timeout=None, json=None):
        f = files["file"][1]
        seen.append(len(f.read()))          # the chunk file must be readable by name (failed on Windows before)
        f.close()
        return FakeResp(200, {"transcript": "press the chest", "language_code": "en-IN"})

    monkeypatch.setattr(requests, "post", post)
    sr = 16000
    x = (0.1 * np.sin(np.arange(sr * 30) / 10)).astype(np.float32)        # 30 s -> 2 chunks
    segs = kp.SarvamASR("test-key").transcribe(x, sr, "en")
    assert len(seen) == 2 and all(n > 1000 for n in seen)
    assert [s["text"] for s in segs] == ["press the chest", "press the chest"]


def test_sarvam_402_is_out_of_credits(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp(402, {"error": {"code": "insufficient_quota_error"}}))
    with pytest.raises(RuntimeError) as e:
        kp.SarvamMT("test-key").translate(["hello"], "hi")
    assert isinstance(providers.classify(e.value), providers.OutOfCredits)


def test_repairing_writer_rescues_small_llm_slips():
    steps = [{"idx": i, "start": i * 5.0, "end": i * 5.0 + 4, "label": l, "confidence": 0.5}
             for i, l in enumerate(["wipe the screen", "paste protector on the screen", "wipe the screen"], 1)]
    prompt = kp.build_prompt("Replace a screen protector", steps, [], "en")

    class Chain:
        used, errors, model = "FakeLLM", {}, "FakeLLM"

        def write(self, prompt, images=()):
            return {"steps": [{"idx": 2, "title": "Paste", "instruction": "Paste it.", "narration": "Paste it now."},
                              {"idx": 1, "title": "Wipe", "instruction": "Wipe the screen.", "narration": "Wipe first."},
                              {"idx": 3, "title": "Wipe again", "instruction": "Wipe again.", "narration": ""}],
                    "quiz": [{"q": "First?", "options": ["a", "b", "c", "d"], "answer": 0}, {"q": "bad", "options": ["a"], "answer": 0}]}

    assert not kp.validate_llm(Chain().write(prompt), steps)[0]          # kd_pipeline would reject this as-is
    out, _ = kp.write_steps(providers.RepairingWriter(Chain()), "Replace a screen protector", steps, [], "en")
    assert out["fallback"] is False
    assert [s["idx"] for s in out["steps"]] == [1, 2, 3] and out["steps"][2]["narration"] == "Wipe again."
    assert len(out["quiz"]) == 1
