"""Provider switches, error handling and per-stage fallback around ml/kd_pipeline.py (which is used as-is).

* HTTP 402 / insufficient_quota  -> OutOfCredits: no retry, go to the next provider.
* HTTP 429 / RESOURCE_EXHAUSTED  -> rate limited: retry with backoff, then the next provider.
* Chain exhausted and a credit/quota problem was involved -> NeedsCredits (job pauses as `needs_credits`)."""
import json
import re
import time

from . import catalog
from .config import get_settings
from .crypto import redact
from .mlpath import kp


class OutOfCredits(Exception):
    pass


class RateLimited(Exception):
    pass


class NeedsCredits(Exception):
    pass


class StageFailed(Exception):
    pass


def classify(e: Exception) -> Exception:
    msg = str(e)
    if isinstance(e, (OutOfCredits, RateLimited)):
        return e
    if re.search(r"\b402\b", msg) or "insufficient_quota" in msg or "Payment Required" in msg:
        return OutOfCredits(msg)
    if re.search(r"\b429\b", msg) or "RESOURCE_EXHAUSTED" in msg or "rate limit" in msg.lower():
        return RateLimited(msg)
    return e


def with_retry(fn, delays=None, sleep=time.sleep):
    delays = get_settings().delays if delays is None else delays
    for attempt in range(len(delays) + 1):
        try:
            return fn()
        except Exception as e:
            c = classify(e)
            if isinstance(c, RateLimited) and attempt < len(delays):
                sleep(delays[attempt])
                continue
            raise c from e


# ---------------------------------------------------------------- chains
ALTERNATIVES = {"asr": ["sarvam", "indicconformer", "whisper"], "mt": ["sarvam", "indictrans2"],
                "tts": ["sarvam", "indicparler"]}


def available(name, keys, plan) -> bool:
    s = get_settings()
    if name in catalog.NEEDS_SARVAM and (not keys.get("sarvam") or plan == "local"):
        return False
    if name in catalog.GPU_ONLY and s.worker_kind != "gpu" and not s.allow_local_on_cpu:
        return False
    return True


def chain(stage, chosen, keys, plan):
    order = [chosen] + [p for p in ALTERNATIVES[stage] if p != chosen]
    return [p for p in order if available(p, keys, plan)], [p for p in order if not available(p, keys, plan)]


# ---------------------------------------------------------------- factories (kd_pipeline classes)
def make_asr(name, keys, cache_dir):
    if name == "whisper":
        return kp.WhisperASR()
    if name == "sarvam":
        return kp.SarvamASR(keys["sarvam"])
    if name == "indicconformer":
        return kp.IndicConformerASR(local_dir=f"{cache_dir}/indic_conformer")
    raise ValueError(name)


def make_mt(name, keys):
    if name == "sarvam":
        return kp.SarvamMT(keys["sarvam"])
    if name == "indictrans2":
        return kp.IndicTrans2MT(hf_token=keys.get("hf") or None)
    raise ValueError(name)


def make_tts(name, keys, voice="Female"):
    s = get_settings()
    if name == "sarvam":
        spk = s.sarvam_speaker_female if voice == "Female" else s.sarvam_speaker_male
        return kp.SarvamTTS(keys["sarvam"], model=s.sarvam_tts_model, speaker=spk)
    if name == "indicparler":
        return kp.IndicParlerTTS(hf_token=keys.get("hf") or None)
    raise ValueError(name)


def gemini_fallback_model(primary):
    """Next-newest general Gemini flash model after the auto-picked one (used when the newest is overloaded)."""
    import re as _re
    names = []
    for m in primary.client.models.list():
        acts = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None)
        if not acts or "generateContent" in acts:
            names.append(m.name.split("/")[-1])
    bad = ("lite", "image", "tts", "live", "audio", "embedding", "thinking", "exp", "preview")
    flash = [n for n in names if "flash" in n and not any(b in n for b in bad) and n != primary.model]
    ver = lambda n: float(_re.search(r"gemini-(\d+(?:\.\d+)?)", n).group(1)) if _re.search(r"gemini-(\d+(?:\.\d+)?)", n) else 0.0
    older = sorted([n for n in flash if ver(n) < ver(primary.model)], key=lambda n: (ver(n), -len(n)), reverse=True)
    return older[0] if older else None


class RepairingWriter:
    """Wraps kd_pipeline.ChainWriter. Before kd_pipeline.validate_llm sees the answer, fix harmless slips that would
    otherwise throw away a good answer: entries keyed by idx but out of order, an empty narration or instruction
    (filled from the other field or the step label), idx numbers off by position. Step count is never changed."""

    def __init__(self, chain):
        self.chain = chain

    @property
    def used(self):
        return self.chain.used

    @property
    def errors(self):
        return self.chain.errors

    @property
    def model(self):
        return self.chain.model

    def write(self, prompt, images=()):
        out = self.chain.write(prompt, images)
        try:
            rows = json.loads(prompt.split("Steps:" + chr(10), 1)[1].split(chr(10) * 2 + "Your previous answer", 1)[0])
            got = out.get("steps") or []
            if isinstance(got, list) and len(got) == len(rows):
                by_idx = {int(g.get("idx", -1)): g for g in got if isinstance(g, dict)}
                fixed = []
                for pos, r in enumerate(rows):
                    g = dict(by_idx.get(r["idx"]) or (got[pos] if isinstance(got[pos], dict) else {}))
                    label = r["detected_step"].strip().rstrip(".")
                    sent = label[:1].upper() + label[1:] + "."
                    g["idx"] = r["idx"]
                    g["instruction"] = (g.get("instruction") or g.get("narration") or sent).strip()
                    g["narration"] = (g.get("narration") or g["instruction"]).strip()
                    g["title"] = (g.get("title") or label.title()[:40]).strip()
                    fixed.append(g)
                out["steps"] = fixed
            out["quiz"] = [q for q in (out.get("quiz") or []) if isinstance(q, dict) and len(q.get("options", [])) == 4
                           and str(q.get("answer", "")).lstrip("-").isdigit() and 0 <= int(q["answer"]) < 4]
        except Exception:
            pass
        return out


def make_writer(keys):
    writers, errors = [], {}
    if keys.get("gemini"):
        try:
            g = kp.GeminiWriter(keys["gemini"], "auto")
            writers.append(g)
            try:
                fb = gemini_fallback_model(g)
                if fb:
                    writers.append(kp.GeminiWriter(keys["gemini"], fb))
            except Exception:
                pass
        except Exception as e:
            errors["gemini"] = redact(e, keys["gemini"])[:200]
    if keys.get("groq"):
        try:
            writers.append(kp.GroqWriter(keys["groq"], "auto"))
        except Exception as e:
            errors["groq"] = redact(e, keys["groq"])[:200]
    return RepairingWriter(kp.ChainWriter(writers)), errors


# Factories are looked up through this dict so tests can swap in fakes.
FACTORIES = {"asr": make_asr, "mt": make_mt, "tts": make_tts, "writer": make_writer}


def run_stage(stage, providers, fn, log, keys, key_source):
    """Try each provider in order. fn(provider_name) does the work. Returns (provider_name, result)."""
    credit_problem, errors = None, []
    for name in providers:
        try:
            result = with_retry(lambda: fn(name))
            log(f"{stage}: {name} ok", provider=name)
            return name, result
        except OutOfCredits as e:
            credit_problem = credit_problem or (name, "out of credits (HTTP 402)")
            errors.append(f"{name}: out of credits")
            log(f"{stage}: {name} is out of credits, trying the next provider", level="warn")
        except RateLimited as e:
            credit_problem = credit_problem or (name, "rate limit / free quota exhausted (HTTP 429)")
            errors.append(f"{name}: rate limited")
            log(f"{stage}: {name} still rate limited after retries, trying the next provider", level="warn")
        except Exception as e:
            msg = redact(e, *keys.values())[:300]
            errors.append(f"{name}: {msg}")
            log(f"{stage}: {name} failed: {msg}", level="warn")
    if credit_problem:
        prov, what = credit_problem
        who = "your" if key_source == "user" else "KaushalDub's shared"
        raise NeedsCredits(f"{stage.upper()}: {who} {prov.title()} account is {what}, and no other provider could "
                           f"run this stage. Add credits or keys, or switch to the free local models, then resume.")
    raise StageFailed(f"{stage}: every provider failed ({'; '.join(errors) or 'none available'})")
