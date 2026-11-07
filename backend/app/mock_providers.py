"""MOCK_PROVIDERS=true: stand-in ASR / MT / TTS / LLM for UI demos and local development without paid keys or
torch. Output is clearly fake ("[hi] ..." text, a tone instead of a voice). Never enable it in production."""
import json

import numpy as np

from .mlpath import kp


class MockASR:
    def detect_language(self, x, sr):
        return "en"

    def transcribe(self, x, sr, lang):
        dur = len(x) / sr
        n = max(1, int(dur // 4))
        return [{"start": i * dur / n, "end": (i + 1) * dur / n, "text": f"(demo transcript part {i + 1})"} for i in range(n)]


class MockMT:
    def translate(self, sents, tgt, src="en"):
        return [f"[{tgt}] {s}" for s in sents]


class MockTTS:
    def synth(self, items):
        sr = 24000
        for it in items:
            n = max(0.6, min(4.0, len(it["text"]) / 18))
            t = np.arange(int(sr * n)) / sr
            kp.save_wav(it["out"], 0.15 * np.sin(2 * np.pi * (180 + 40 * (hash(it["lang"]) % 3)) * t) * np.hanning(len(t)), sr)


class MockWriter:
    used, errors = "MockLLM:demo", {}

    def write(self, prompt, images=()):
        rows = json.loads(prompt.split("Steps:\n", 1)[1])
        steps = [{"idx": r["idx"], "title": r["detected_step"].title()[:40],
                  "instruction": r["detected_step"][0].upper() + r["detected_step"][1:] + ".",
                  "narration": "Now " + r["detected_step"] + "."} for r in rows]
        labels = [r["detected_step"] for r in rows]
        quiz = []
        if len(labels) >= 2:
            opts = (labels + ["wait", "stop", "rest"])[:4]
            quiz = [{"q": "What is the first step?", "options": opts, "answer": 0},
                    {"q": "What comes after the first step?", "options": opts, "answer": 1},
                    {"q": "What is the last step?", "options": (labels[-1:] + [l for l in opts if l != labels[-1]])[:4], "answer": 0}]
        return {"steps": steps, "quiz": quiz}


def install():
    from . import providers
    providers.FACTORIES.update({
        "asr": lambda name, keys, cache: MockASR(),
        "mt": lambda name, keys: MockMT(),
        "tts": lambda name, keys, voice="Female": MockTTS(),
        "writer": lambda keys: (MockWriter(), {}),
    })
    _orig = providers.available
    providers.available = lambda name, keys, plan: True if name != "sarvam" or plan != "local" else False
    providers._orig_available = _orig
