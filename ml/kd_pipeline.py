"""KaushalDub dubbing pipeline: speech-to-text, step text (LLM), translation, voice, timing and mixing.

Every stage has interchangeable providers so local open-source models and APIs can be switched:
  ASR: whisper | indicconformer | sarvam
  MT : indictrans2 | sarvam
  TTS: indicparler | sarvam
The same module is meant to be reused by the FastAPI backend."""
import json, os, re, subprocess, sys, tempfile, time
import numpy as np

LANGS = {
    "en": {"name": "English", "sarvam": "en-IN", "it2": "eng_Latn", "whisper": "english"},
    "hi": {"name": "Hindi", "sarvam": "hi-IN", "it2": "hin_Deva", "whisper": "hindi"},
    "kn": {"name": "Kannada", "sarvam": "kn-IN", "it2": "kan_Knda", "whisper": "kannada"},
}
SARVAM = "https://api.sarvam.ai"


# ------------------------------------------------------------------ audio / ffmpeg helpers
def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def run_ffmpeg(args):
    r = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-800:])


def has_audio(video):
    r = subprocess.run([ffmpeg_exe(), "-i", video], capture_output=True, text=True)
    return "Audio:" in r.stderr


def extract_audio(video, wav, sr=16000):
    run_ffmpeg(["-i", video, "-vn", "-ac", "1", "-ar", str(sr), wav])


def extract_frame(video, t, jpg):
    run_ffmpeg(["-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-vf", "scale=448:-2", jpg])


def load_wav(path, sr=None):
    try:
        import soundfile as sf
        x, r = sf.read(path, dtype="float32", always_2d=True)
    except ImportError:
        from scipy.io import wavfile
        r, x = wavfile.read(path)
        x = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
        x = x.reshape(len(x), -1)
    x = x.mean(1)
    if sr and r != sr:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(r, sr)
        x = resample_poly(x, sr // g, r // g).astype(np.float32)
        r = sr
    return x, r


def save_wav(path, x, sr):
    x = np.clip(np.asarray(x, np.float32), -1, 1)
    try:
        import soundfile as sf
        sf.write(path, x, sr)
    except ImportError:
        from scipy.io import wavfile
        wavfile.write(path, sr, (x * 32767).astype(np.int16))


def chunk_audio(x, sr, max_s=25.0, search_s=5.0, win_s=0.05):
    """Split audio into chunks <= max_s, cutting at the quietest point in the last search_s seconds."""
    out, start, n = [], 0, len(x)
    w = max(1, int(win_s * sr))
    while start < n:
        end = min(n, start + int(max_s * sr))
        if end < n:
            lo = max(start + int((max_s - search_s) * sr), start + w)
            seg = x[lo:end]
            k = len(seg) // w
            if k > 1:
                rms = np.sqrt((seg[: k * w].reshape(k, w) ** 2).mean(1))
                end = lo + int(np.argmin(rms)) * w + w // 2
        out.append((start / sr, end / sr, x[start:end]))
        start = end
    return out


def atempo(wav_in, wav_out, factor):
    factor = float(np.clip(factor, 0.5, 2.0))
    run_ffmpeg(["-i", wav_in, "-filter:a", f"atempo={factor:.3f}", wav_out])


# ------------------------------------------------------------------ speech to text
class WhisperASR:
    name = "whisper"

    def __init__(self, model="openai/whisper-small", device=None):
        import torch
        from transformers import pipeline
        cuda = torch.cuda.is_available() if device is None else device == "cuda"
        self.pipe = pipeline("automatic-speech-recognition", model=model, device=0 if cuda else -1,
                             torch_dtype=torch.float16 if cuda else torch.float32)

    def detect_language(self, x, sr=16000):
        import torch
        m, fe, tok = self.pipe.model, self.pipe.feature_extractor, self.pipe.tokenizer
        feats = fe(x[: 30 * sr], sampling_rate=sr, return_tensors="pt").input_features.to(m.device, m.dtype)
        with torch.no_grad():
            ids = m.generate(feats, max_new_tokens=3)
        hit = re.search(r"<\|([a-z]{2})\|>", tok.decode(ids[0], skip_special_tokens=False))
        return hit.group(1) if hit else "en"

    def transcribe(self, x, sr, lang):
        kw = {"task": "transcribe"}
        if lang in LANGS:
            kw["language"] = LANGS[lang]["whisper"]
        try:          # word timings give precise per-step text; fall back to sentence chunks
            out = self.pipe({"raw": x.copy(), "sampling_rate": sr}, chunk_length_s=30, batch_size=8,
                            return_timestamps="word", generate_kwargs=kw)
            return group_words([{"start": c["timestamp"][0], "end": c["timestamp"][1], "text": c["text"]}
                                for c in out.get("chunks", [])])
        except Exception:
            out = self.pipe({"raw": x.copy(), "sampling_rate": sr}, chunk_length_s=30, batch_size=8,
                            return_timestamps=True, generate_kwargs=kw)
        segs = []
        for c in out.get("chunks", []):
            s, e = c["timestamp"]
            s = float(s or 0.0)
            segs.append({"start": s, "end": float(e) if e is not None else s + 5.0, "text": c["text"].strip()})
        return [s for s in segs if s["text"]]


def group_words(words, max_s=8.0, gap=0.8):
    """Join word-level timestamps into short segments: break at sentence ends, pauses, or every max_s seconds."""
    segs, cur = [], None
    for w in words:
        t = (w.get("text") or "").strip()
        if not t:
            continue
        a = float(w["start"] if w["start"] is not None else (cur["end"] if cur else 0.0))
        b = float(w["end"] if w["end"] is not None else a + 0.3)
        if cur and (a - cur["end"] > gap or b - cur["start"] > max_s):
            segs.append(cur); cur = None
        if cur is None:
            cur = {"start": a, "end": b, "text": t}
        else:
            cur["end"], cur["text"] = b, cur["text"] + " " + t
        if t[-1] in ".?!।":
            segs.append(cur); cur = None
    if cur:
        segs.append(cur)
    return segs


class IndicConformerASR:
    """AI4Bharat IndicConformer (22 Indian languages, no English). Fixed chunks give the timestamps."""
    name = "indicconformer"

    def __init__(self, local_dir="/tmp/indic_conformer"):
        # Download real files (not cache symlinks): newer onnxruntime refuses ONNX external-data
        # files that resolve outside the model folder, which the Hugging Face cache layout triggers.
        from huggingface_hub import snapshot_download
        from transformers import AutoModel
        path = snapshot_download("ai4bharat/indic-conformer-600m-multilingual", local_dir=local_dir)
        self.model = AutoModel.from_pretrained(path, trust_remote_code=True)

    def transcribe(self, x, sr, lang):
        import torch
        if lang not in ("hi", "kn"):
            raise ValueError("IndicConformer needs an Indian spoken language (hi/kn), got " + str(lang))
        segs = []
        for s, e, chunk in chunk_audio(x, sr, max_s=20):
            text = self.model(torch.from_numpy(chunk.copy())[None], lang, "ctc")
            text = text if isinstance(text, str) else str(text)
            if text.strip():
                segs.append({"start": s, "end": e, "text": text.strip()})
        return segs


class SarvamASR:
    name = "sarvam"

    def __init__(self, key):
        assert key, "SARVAM_API_KEY is missing"
        self.key = key

    def transcribe(self, x, sr, lang):
        import requests
        segs, detected = [], []
        for s, e, chunk in chunk_audio(x, sr, max_s=25):
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                save_wav(f.name, chunk, sr)
                data = {"language_code": LANGS[lang]["sarvam"] if lang in LANGS else "unknown",
                        "with_timestamps": "true"}
                for attempt in range(3):
                    r = requests.post(f"{SARVAM}/speech-to-text", headers={"api-subscription-key": self.key},
                                      files={"file": ("chunk.wav", open(f.name, "rb"), "audio/wav")}, data=data, timeout=120)
                    if r.status_code != 429:
                        break
                    time.sleep(3 * (attempt + 1))
            if r.status_code != 200:
                raise RuntimeError(f"Sarvam STT {r.status_code}: {r.text[:300]}")
            j = r.json()
            if j.get("language_code"):
                detected.append(j["language_code"])
            ts = j.get("timestamps") or {}
            words, st, en = ts.get("words") or [], ts.get("start_time_seconds") or [], ts.get("end_time_seconds") or []
            if words and len(words) == len(st) == len(en):
                segs += [{"start": s + a, "end": s + b, "text": w.strip()} for w, a, b in zip(words, st, en) if w.strip()]
            elif j.get("transcript", "").strip():
                segs.append({"start": s, "end": e, "text": j["transcript"].strip()})
        self.detected = detected
        return segs


def transcript_text(segs, start=None, end=None):
    keep = [s["text"] for s in segs if start is None or (s["end"] > start and s["start"] < end)]
    return " ".join(keep).strip()


# ------------------------------------------------------------------ steps (from the vision model)
def _join_same(steps, gap):
    out = []
    for s in sorted(steps, key=lambda z: z["start"]):
        if out and out[-1]["label"] == s["label"] and s["start"] - out[-1]["end"] <= gap:
            m = out[-1]
            w1, w2 = m["end"] - m["start"], s["end"] - s["start"]
            m["confidence"] = (m["confidence"] * w1 + s["confidence"] * w2) / max(w1 + w2, 1e-6)
            m["end"] = s["end"]
        else:
            out.append(dict(s))
    return out


def merge_steps(steps, min_len=2.0, gap=3.0, max_steps=12):
    """Clean the step model's raw output: join neighbouring segments with the same label, drop very short
    ones, join again (a dropped blip can separate two halves of one step), keep time order, renumber."""
    merged = _join_same(steps, gap)
    long_ = [m for m in merged if m["end"] - m["start"] >= min_len] or merged[:1]
    long_ = _join_same(long_, gap)
    long_ = sorted(sorted(long_, key=lambda m: m["end"] - m["start"], reverse=True)[:max_steps], key=lambda m: m["start"])
    for i, m in enumerate(long_, 1):
        m["idx"] = i
        m["low_confidence"] = m["confidence"] < 0.6
        m["keyframe_s"] = round((m["start"] + m["end"]) / 2, 2)
    return long_


# ------------------------------------------------------------------ LLM: step text, narration, quiz
def build_prompt(task_title, steps, segs, spoken_lang):
    rows = []
    for s in steps:
        dur = s["end"] - s["start"]
        rows.append({"idx": s["idx"], "start": round(s["start"], 1), "end": round(s["end"], 1),
                     "detected_step": s["label"], "confidence": round(s["confidence"], 2),
                     "max_narration_words": max(4, int(dur * 2.0)),
                     "speech_during_step": transcript_text(segs, s["start"], s["end"])[:600]})
    return (
        "You write short, clear instructions for vocational learners from a how-to video.\n"
        f"Task: {task_title}. The instructor speaks {LANGS.get(spoken_lang, {'name': spoken_lang})['name']}.\n"
        "For each detected step you get its time, the step label from a vision model, its confidence, and what the "
        "instructor said during it (may be empty or noisy). Images, if attached, are keyframes of low-confidence steps "
        "in the same order as those steps.\n"
        "Rules:\n"
        "- Return exactly one entry per input step, same idx, same order. Do not merge, split, add or drop steps.\n"
        "- title: 2 to 5 words. instruction: one imperative English sentence, at most 15 words.\n"
        "- narration: what a narrator says during that step, in simple spoken English, at most max_narration_words words.\n"
        "- Use the speech and keyframes as evidence. Only for steps with confidence below 0.6 may you change the "
        "meaning of the label, when the evidence clearly shows a different action.\n"
        "- Do not add facts, names, numbers or body parts that are not in the speech or the label.\n"
        "- quiz: 3 multiple-choice questions about the steps and their order, 4 options each, answer = index of the "
        "correct option.\n"
        'Output JSON only: {"steps":[{"idx":1,"title":"","instruction":"","narration":""}],'
        '"quiz":[{"q":"","options":["","","",""],"answer":0}]}\n\n'
        "Steps:\n" + json.dumps(rows, ensure_ascii=False, indent=1)
    )


def validate_llm(out, steps):
    try:
        got = out["steps"]
        if len(got) != len(steps):
            return False, f"expected {len(steps)} steps, got {len(got)}"
        for g, s in zip(got, steps):
            if int(g["idx"]) != s["idx"] or not g.get("narration") or not g.get("instruction"):
                return False, f"bad entry at idx {s['idx']}"
        for q in out.get("quiz", []):
            if len(q["options"]) != 4 or not 0 <= int(q["answer"]) < 4:
                return False, "bad quiz item"
        return True, "ok"
    except Exception as e:
        return False, f"invalid structure: {e}"


def template_steps(steps):
    """Fallback when the LLM fails validation twice: plain text from the labels."""
    out = []
    for s in steps:
        label = s["label"].strip().rstrip(".")
        sent = label[0].upper() + label[1:] + "."
        out.append({"idx": s["idx"], "title": label[:40].title(), "instruction": sent, "narration": sent})
    return {"steps": out, "quiz": [], "fallback": True}


def pick_gemini(names):
    """Newest general 'flash' model from a list of model names (skips lite/image/tts/live variants)."""
    clean = [n.split("/")[-1] for n in names]
    def ver(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0
    bad = ("lite", "image", "tts", "live", "audio", "embedding", "thinking", "exp")
    flash = [n for n in clean if "flash" in n and not any(b in n for b in bad)]
    pool = flash or [n for n in clean if "flash" in n] or clean
    stable = [n for n in pool if "preview" not in n] or pool
    return sorted(stable, key=lambda n: (ver(n), -len(n)), reverse=True)[0] if stable else None


class GeminiWriter:
    def __init__(self, key, model="auto"):
        assert key, "GEMINI_API_KEY is missing"
        from google import genai
        self.client = genai.Client(api_key=key)
        self.model = self.available_model() if model in (None, "", "auto") else model

    def available_model(self):
        names = []
        for m in self.client.models.list():
            acts = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None)
            if not acts or "generateContent" in acts:
                names.append(m.name)
        return pick_gemini(names)

    def _call(self, parts):
        from google.genai import types
        r = self.client.models.generate_content(
            model=self.model, contents=parts,
            config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json"))
        return json.loads(r.text)

    def write(self, prompt, images=()):
        from google.genai import types
        parts = [prompt] + [types.Part.from_bytes(data=open(p, "rb").read(), mime_type="image/jpeg") for p in images]
        for attempt in range(4):
            try:
                return self._call(parts)
            except Exception as e:
                msg = str(e)
                if ("404" in msg or "NOT_FOUND" in msg) and attempt == 0:   # model retired: switch to an available one
                    self.model = self.available_model()
                elif any(k in msg for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")) and attempt < 3:
                    time.sleep([5, 15, 30][attempt])                      # busy or rate-limited: wait and retry
                else:
                    raise


class GroqWriter:
    """Groq's OpenAI-compatible chat API (open-weight models such as Llama). Text only: keyframes are skipped."""
    URL = "https://api.groq.com/openai/v1"
    PREFERRED = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3-32b",
                 "llama-3.1-8b-instant"]

    def __init__(self, key, model="auto"):
        assert key, "GROQ_API_KEY is missing"
        self.key = key
        self.model = self.available_model() if model in (None, "", "auto") else model

    def _h(self):
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def available_model(self):
        import requests
        r = requests.get(f"{self.URL}/models", headers=self._h(), timeout=30)
        r.raise_for_status()
        ids = [m["id"] for m in r.json().get("data", [])]
        return next((m for m in self.PREFERRED if m in ids), next((m for m in ids if "whisper" not in m and "guard" not in m), None))

    def write(self, prompt, images=()):
        import requests
        body = {"model": self.model, "temperature": 0.2, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": "You reply with one JSON object only."},
                             {"role": "user", "content": prompt}]}
        for attempt in range(4):
            r = requests.post(f"{self.URL}/chat/completions", headers=self._h(), json=body, timeout=120)
            if r.status_code in (429, 500, 503) and attempt < 3:
                time.sleep([5, 15, 30][attempt])
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Groq {r.status_code}: {r.text[:300]}")
            return json.loads(r.json()["choices"][0]["message"]["content"])


class ChainWriter:
    """Try each LLM in order (e.g. Gemini, then Groq); remembers which one answered."""

    def __init__(self, writers):
        self.writers, self.used, self.errors = [w for w in writers if w], None, {}

    @property
    def model(self):
        return self.used

    def write(self, prompt, images=()):
        for w in self.writers:
            name = f"{type(w).__name__}:{w.model}"
            try:
                out = w.write(prompt, images)
                self.used = name
                return out
            except Exception as e:
                self.errors[name] = str(e)[:300]
        raise RuntimeError("all LLMs failed: " + json.dumps(self.errors)[:600])


def write_steps(writer, task_title, steps, segs, spoken_lang, images=()):
    prompt = build_prompt(task_title, steps, segs, spoken_lang)
    why = "no writer"
    for attempt in range(2):
        try:
            out = writer.write(prompt, images)
            ok, why = validate_llm(out, steps)
            if ok:
                out["fallback"] = False
                return out, prompt
        except Exception as e:
            why = str(e)[:300]
        prompt += f"\n\nYour previous answer was rejected ({why}). Follow the rules exactly."
    out = template_steps(steps)
    out["reason"] = why
    return out, prompt


# ------------------------------------------------------------------ translation
def isolated_python(name, packages):
    """A separate Python environment that sees the system torch but has its own pinned packages.
    Uses virtualenv because Kaggle's python lacks ensurepip (python -m venv fails there)."""
    d = f"/tmp/env_{name}"
    py = os.path.join(d, "bin", "python")
    if not os.path.exists(py):
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "virtualenv"], check=True, capture_output=True)
        r = subprocess.run([sys.executable, "-m", "virtualenv", "-q", "--system-site-packages", d], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("virtualenv failed: " + r.stderr[-600:])
    r = subprocess.run([py, "-m", "pip", "install", "-q"] + packages, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"installing {packages} failed: " + r.stderr[-900:])
    return py


def run_isolated(py, script, payload, hf_token=None, timeout=3600):
    with tempfile.TemporaryDirectory() as td:
        sp, ip, op = os.path.join(td, "job.py"), os.path.join(td, "in.json"), os.path.join(td, "out.json")
        open(sp, "w").write(script)
        json.dump(payload, open(ip, "w"), ensure_ascii=False)
        env = dict(os.environ)
        if hf_token:
            env["HF_TOKEN"] = hf_token
        r = subprocess.run([py, sp, ip, op], capture_output=True, text=True, env=env, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-1500:])
        return json.load(open(op)) if os.path.exists(op) else None


IT2_SCRIPT = r'''
import sys, json, torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
try:
    from IndicTransToolkit.processor import IndicProcessor
except ImportError:
    from IndicTransToolkit import IndicProcessor
job = json.load(open(sys.argv[1]))
dev = "cuda" if torch.cuda.is_available() else "cpu"
tok = AutoTokenizer.from_pretrained(job["model"], trust_remote_code=True)
model = AutoModelForSeq2SeqLM.from_pretrained(job["model"], trust_remote_code=True).to(dev).eval()
ip = IndicProcessor(inference=True)
out = {}
for tgt in job["targets"]:
    batch = ip.preprocess_batch(job["sents"], src_lang=job["src"], tgt_lang=tgt)
    enc = tok(batch, truncation=True, padding="longest", return_tensors="pt").to(dev)
    with torch.no_grad():
        gen = model.generate(**enc, use_cache=True, min_length=0, max_length=256, num_beams=4)
    dec = tok.batch_decode(gen, skip_special_tokens=True, clean_up_tokenization_spaces=True)
    out[tgt] = ip.postprocess_batch(dec, lang=tgt)
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
'''


class IndicTrans2MT:
    """AI4Bharat IndicTrans2 (English -> Indian languages), run in its own environment because its
    remote code needs transformers 4.x."""
    name = "indictrans2"
    PACKAGES = ["transformers==4.46.3", "IndicTransToolkit", "sentencepiece", "sacremoses"]

    def __init__(self, model="ai4bharat/indictrans2-en-indic-dist-200M", hf_token=None):
        self.model, self.hf_token = model, hf_token
        self.py = isolated_python("it2", self.PACKAGES)
        self.cache = {}

    def translate_all(self, sents, targets, src="en"):
        tg = [LANGS[t]["it2"] for t in targets if t != src]
        res = run_isolated(self.py, IT2_SCRIPT, {"model": self.model, "sents": list(sents), "src": LANGS[src]["it2"],
                                                  "targets": tg}, self.hf_token) if tg else {}
        out = {t: list(sents) if t == src else res[LANGS[t]["it2"]] for t in targets}
        self.cache.update(out)
        return out

    def translate(self, sents, tgt, src="en"):
        return self.translate_all(sents, [tgt], src)[tgt]


class SarvamMT:
    name = "sarvam"

    def __init__(self, key):
        assert key, "SARVAM_API_KEY is missing"
        self.key = key

    def translate(self, sents, tgt, src="en"):
        import requests
        if tgt == src:
            return list(sents)
        out = []
        for s in sents:
            body = {"input": s[:1900], "source_language_code": LANGS[src]["sarvam"],
                    "target_language_code": LANGS[tgt]["sarvam"], "model": "sarvam-translate:v1"}
            r = requests.post(f"{SARVAM}/translate", headers={"api-subscription-key": self.key}, json=body, timeout=60)
            if r.status_code != 200:
                raise RuntimeError(f"Sarvam translate {r.status_code}: {r.text[:300]}")
            out.append(r.json().get("translated_text", ""))
        return out


# ------------------------------------------------------------------ text to speech
class SarvamTTS:
    name = "sarvam"

    def __init__(self, key, model="bulbul:v3", speaker="shubh", sr=24000):
        assert key, "SARVAM_API_KEY is missing"
        self.key, self.model, self.speaker, self.sr = key, model, speaker, sr

    def synth(self, items):
        """items: [{"text", "lang", "out"}] -> writes each wav."""
        import base64, requests
        for it in items:
            body = {"text": it["text"][:2400], "language_code": LANGS[it["lang"]]["sarvam"], "model": self.model,
                    "speaker": self.speaker, "speech_sample_rate": self.sr, "output_audio_codec": "wav"}
            for attempt in range(3):
                r = requests.post(f"{SARVAM}/text-to-speech", headers={"api-subscription-key": self.key},
                                  json=body, timeout=120)
                if r.status_code != 429:
                    break
                time.sleep(3 * (attempt + 1))
            if r.status_code != 200:
                raise RuntimeError(f"Sarvam TTS {r.status_code}: {r.text[:300]}")
            open(it["out"], "wb").write(base64.b64decode("".join(r.json()["audios"])))


PARLER_SCRIPT = r'''
import sys, json, torch, soundfile as sf
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer
items = json.load(open(sys.argv[1]))
dev = "cuda" if torch.cuda.is_available() else "cpu"
name = "ai4bharat/indic-parler-tts"
model = ParlerTTSForConditionalGeneration.from_pretrained(name).to(dev)
tok = AutoTokenizer.from_pretrained(name)
dtok = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
for it in items:
    d = dtok(it["description"], return_tensors="pt").to(dev)
    p = tok(it["text"], return_tensors="pt").to(dev)
    with torch.no_grad():
        g = model.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                           prompt_input_ids=p.input_ids, prompt_attention_mask=p.attention_mask)
    sf.write(it["out"], g.cpu().float().numpy().squeeze(), model.config.sampling_rate)
    print("ok", it["out"], flush=True)
'''

PARLER_VOICES = {
    "hi": "Rohit speaks at a moderate pace with a clear, friendly voice. The recording is very clear with no background noise.",
    "kn": "Suresh speaks at a moderate pace with a clear, friendly voice. The recording is very clear with no background noise.",
    "en": "Thoma speaks at a moderate pace with a clear, friendly voice. The recording is very clear with no background noise.",
}


class IndicParlerTTS:
    """AI4Bharat Indic Parler-TTS, run in its own environment (it pins an older transformers)."""
    name = "indicparler"

    def __init__(self, hf_token=None):
        self.hf_token = hf_token
        self.py = isolated_python("parler", ["git+https://github.com/huggingface/parler-tts.git"])

    def synth(self, items):
        jobs = [dict(it, description=PARLER_VOICES.get(it["lang"], PARLER_VOICES["en"])) for it in items]
        script = PARLER_SCRIPT.replace("items = json.load(open(sys.argv[1]))", "items = json.load(open(sys.argv[1]))")
        run_isolated(self.py, script, jobs, self.hf_token)
        missing = [it["out"] for it in items if not os.path.exists(it["out"])]
        if missing:
            raise RuntimeError(f"Indic Parler-TTS wrote {len(items) - len(missing)} of {len(items)} clips")


# ------------------------------------------------------------------ timing, mixing, captions
def place_clips(steps, durations, total, max_speed=1.3, pad=0.15):
    """Decide where each narration clip goes. A clip longer than its step is sped up (up to max_speed);
    whatever still does not fit pushes the next clip later. Returns one placement per step."""
    out, prev_end = [], 0.0
    for i, (s, d) in enumerate(zip(steps, durations)):
        slot_end = steps[i + 1]["start"] if i + 1 < len(steps) else total
        start = max(s["start"], prev_end + (pad if i else 0.0))
        room = max(slot_end - start, 0.5)
        speed = 1.0 if d <= room else min(max_speed, d / room)
        length = d / speed
        out.append({"idx": s["idx"], "start": round(start, 3), "end": round(start + length, 3),
                    "speed": round(speed, 3), "overflow_s": round(max(0.0, start + length - slot_end), 3)})
        prev_end = start + length
    return out


def render_track(clips, placements, total, sr=24000):
    track = np.zeros(int((max(total, placements[-1]["end"] if placements else 0) + 0.5) * sr), np.float32)
    for x, p in zip(clips, placements):
        a = int(p["start"] * sr)
        track[a:a + len(x)] += x[: max(0, len(track) - a)]
    peak = np.abs(track).max()
    return track / peak * 0.95 if peak > 1 else track


def fmt_vtt(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def write_vtt(cues, path):
    lines = ["WEBVTT", ""]
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{fmt_vtt(c['start'])} --> {fmt_vtt(c['end'])}", c["text"], ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def mux(video, narration_wav, out_mp4, orig_volume=0.15, vtt=None):
    """Replace the soundtrack with the narration, keeping the original softly underneath."""
    args = ["-i", video, "-i", narration_wav]
    if vtt:
        args += ["-i", vtt]
    if has_audio(video) and orig_volume > 0:
        args += ["-filter_complex", f"[0:a]volume={orig_volume}[a0];[a0][1:a]amix=inputs=2:duration=longest:normalize=0[a]",
                 "-map", "0:v", "-map", "[a]"]
    else:
        args += ["-map", "0:v", "-map", "1:a"]
    if vtt:
        args += ["-map", "2:s", "-c:s", "mov_text", "-metadata:s:s:0", "language=und"]
    args += ["-c:v", "copy", "-c:a", "aac", "-b:a", "128k", out_mp4]
    run_ffmpeg(args)


def dub(video, steps, texts, lang, tts_files, out_dir, total, orig_volume=0.15, sr=24000):
    """Build the dubbed video for one language from per-step wav files."""
    clips, durs, used = [], [], []
    for f in tts_files:
        x, _ = load_wav(f, sr)
        clips.append(x)
        durs.append(len(x) / sr)
    pl = place_clips(steps, durs, total)
    for i, (p, f) in enumerate(zip(pl, tts_files)):
        if p["speed"] > 1.0:
            g = f.replace(".wav", "_fit.wav")
            atempo(f, g, p["speed"])
            clips[i], _ = load_wav(g, sr)
        used.append(clips[i])
    narr = os.path.join(out_dir, f"narration_{lang}.wav")
    save_wav(narr, render_track(used, pl, total, sr), sr)
    vtt = os.path.join(out_dir, f"captions_{lang}.vtt")
    write_vtt([{"start": p["start"], "end": p["end"], "text": t} for p, t in zip(pl, texts)], vtt)
    mp4 = os.path.join(out_dir, f"dubbed_{lang}.mp4")
    mux(video, narr, mp4, orig_volume, vtt)
    return {"mp4": mp4, "vtt": vtt, "narration": narr, "placements": pl}
