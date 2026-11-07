"""Worker jobs. Every job runs through run_job(job_id), which reports stage, progress and logs in the jobs row.

process : pipeline stages 1-4 (audio, speech to text, step detection + correction memory, LLM text + quiz)
dub     : stages 5-7 after approval (translation, voice, timing/mixing/captions) for every target language
revoice : re-make one step's voice in one language and re-render that language (learner ticket fixes)
rerender: after approved annotation changes, re-translate/re-voice what changed and re-render
retrain : fine-tune the step model on approved corrections (see retrain.py)"""
import hashlib
import os
import shutil
import tempfile
import time
import traceback

from . import catalog, costs, ml_adapter, plans
from .config import get_settings
from .crypto import redact
from .db import get_store, now_iso
from .media import caption_vtt, download_youtube, probe_duration
from .mlpath import kp
from .providers import FACTORIES, NeedsCredits, StageFailed, chain, run_stage
from .storage import get_storage

PROCESS_STAGES = [("fetch", "Getting the video"), ("extract", "Extracting audio and frames"),
                  ("asr", "Transcribing speech"), ("steps", "Detecting steps (vision model + correction memory)"),
                  ("llm", "Writing step text and quiz (LLM)"), ("check", "Checking step order")]
DUB_STAGES = [("translate", "Translating"), ("tts", "Synthesising narration"),
              ("render", "Joining audio with video and building captions (.vtt)")]
REVOICE_STAGES = [("tts", "Re-making the voice for this step"), ("render", "Rebuilding the dubbed video")]
RETRAIN_STAGES = [("data", "Collecting approved corrections"), ("train", "Fine-tuning the step model"),
                  ("eval", "Scoring on the test videos"), ("activate", "Activating if not worse")]
STAGES = {"process": PROCESS_STAGES, "dub": DUB_STAGES, "rerender": DUB_STAGES, "revoice": REVOICE_STAGES,
          "retrain": RETRAIN_STAGES}


class Ctx:
    def __init__(self, job):
        self.db = get_store()
        self.job = job
        self.secrets = []
        self.cost = job.get("cost") or costs.empty_cost()
        self.stages = [{"key": k, "label": l, "status": "wait", "provider": None} for k, l in STAGES[job["kind"]]]
        self.logs = list(job.get("logs") or [])

    def save(self, **vals):
        vals.update({"stages": self.stages, "logs": self.logs[-200:], "cost": self.cost, "updated_at": now_iso()})
        self.job.update(vals)
        self.db.update("jobs", {"id": self.job["id"]}, vals)

    def log(self, msg, level="info", provider=None):
        self.logs.append({"t": now_iso(), "level": level, "msg": redact(msg, *self.secrets)[:500]})
        if provider:
            cur = next((s for s in self.stages if s["status"] == "run"), None)
            if cur:
                cur["provider"] = provider
        self.save()

    def stage(self, key, progress, label=None):
        for s in self.stages:
            if s["status"] == "run":
                s["status"] = "done"
            if s["key"] == key:
                s["status"] = "run"
                if label:
                    s["label"] = label
        self.save(stage=key, progress=int(progress), status="running")

    def fail_stage(self):
        for s in self.stages:
            if s["status"] == "run":
                s["status"] = "failed"

    def finish(self):
        for s in self.stages:
            if s["status"] == "run":
                s["status"] = "done"
        self.save(stage="done", progress=100, status="done", finished_at=now_iso())

    def check_budget(self):
        if self.job.get("key_source") == "platform" and costs.budget_status()["exhausted"]:
            raise NeedsCredits("The platform's monthly budget for free videos is used up. Add your own keys or "
                               "switch to the free local models, then resume.")


def run_job(job_id):
    db = get_store()
    job = db.get("jobs", job_id)
    if not job:
        return
    ctx = Ctx(job)
    tmp = tempfile.mkdtemp(prefix=f"kd_{job['kind']}_")
    video = db.get("videos", job["video_id"]) if job.get("video_id") else None
    try:
        ctx.save(status="running", started_at=now_iso(), error=None)
        {"process": process, "dub": dub, "rerender": dub, "revoice": revoice, "retrain": retrain_job}[job["kind"]](ctx, video, tmp)
        ctx.finish()
    except NeedsCredits as e:
        ctx.log(str(e), level="error")
        ctx.fail_stage()
        ctx.save(status="needs_credits", error=str(e))
        if video:
            db.update("videos", {"id": video["id"]}, {"status": "needs_credits"})
    except Exception as e:
        msg = redact(f"{type(e).__name__}: {e}", *ctx.secrets)[:800]
        ctx.log(msg + "\n" + redact(traceback.format_exc()[-1500:], *ctx.secrets), level="error")
        ctx.fail_stage()
        ctx.save(status="failed", error=msg)
        if video:
            prev = {"process": "failed", "dub": "review", "rerender": "ready", "revoice": "ready"}.get(job["kind"])
            if prev:
                db.update("videos", {"id": video["id"]}, {"status": prev, "last_error": msg})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _keys(ctx, video):
    keys = plans.runtime_keys(video["owner"], ctx.job["key_source"] if ctx.job["key_source"] != "none" else "user")
    ctx.secrets = [v for v in keys.values() if v]
    return keys


def _source(ctx, video, tmp):
    st = get_storage()
    params = ctx.job["params"] or {}
    if video.get("source_path"):
        return st.download("raw-videos", video["source_path"], os.path.join(tmp, "source" + os.path.splitext(video["source_path"])[1]))
    if params.get("youtube_url"):
        local = download_youtube(params["youtube_url"], tmp)
        path = f"{video['owner']}/{video['id']}/source.mp4"
        st.put_file("raw-videos", path, local, "video/mp4")
        get_store().update("videos", {"id": video["id"]}, {"source_path": path})
        video["source_path"] = path
        return local
    raise RuntimeError("video has no source file")


# ---------------------------------------------------------------- stages 1-4
def process(ctx, video, tmp):
    db, st, p = get_store(), get_storage(), ctx.job["params"]
    db.update("videos", {"id": video["id"]}, {"status": "processing"})
    keys = _keys(ctx, video)

    ctx.stage("fetch", 2)
    src = _source(ctx, video, tmp)
    duration = probe_duration(src)
    ctx.log(f"video {duration:.1f} s")

    ctx.stage("extract", 8)
    wav = os.path.join(tmp, "audio.wav")
    segs, lang = [], p.get("spoken_lang") or "auto"
    x, sr = None, 16000
    if kp.has_audio(src):
        kp.extract_audio(src, wav)
        x, sr = kp.load_wav(wav, 16000)
    else:
        ctx.log("video has no audio track; steps come from the vision model only", level="warn")
    try:
        thumb = os.path.join(tmp, "thumb.jpg")
        kp.extract_frame(src, min(2.0, duration / 3), thumb)
        db.update("videos", {"id": video["id"]},
                  {"thumb_path": st.put_file("keyframes", f"{video['id']}/thumb.jpg", thumb, "image/jpeg")})
    except Exception as e:
        ctx.log(f"thumbnail failed: {e}", level="warn")

    ctx.stage("asr", 15)
    if x is not None and len(x):
        provs, skipped = chain("asr", p["asr"], keys, p["plan"])
        if skipped:
            ctx.log(f"asr: not available here: {', '.join(skipped)}")

        def do_asr(name):
            nonlocal lang
            if name == "sarvam":
                ctx.check_budget()
            asr = FACTORIES["asr"](name, keys, get_settings().data_dir)
            use = lang
            if use == "auto" and hasattr(asr, "detect_language"):
                use = asr.detect_language(x, sr)                  # Whisper detects the language itself
            elif use == "auto" and name != "sarvam":
                use = "hi"                                        # IndicConformer needs an Indian language
            out = asr.transcribe(x, sr, use)                      # Sarvam: "auto" is sent as "unknown" = auto-detect
            if name == "sarvam":
                costs.add(ctx.cost, "sarvam", audio_min=len(x) / sr / 60)
                if use == "auto":
                    codes = [c.split("-")[0] for c in getattr(asr, "detected", []) if c]
                    use = max(set(codes), key=codes.count) if codes else "en"
            lang = use
            return out

        _, segs = run_stage("asr", provs, do_asr, ctx.log, keys, ctx.job["key_source"])
    lang = lang if lang in catalog.LANGS else "en"
    ctx.log(f"spoken language: {lang}; {len(segs)} speech segments")

    ctx.stage("steps", 40)
    rec = ml_adapter.get_recognizer()
    memory = ml_adapter.memory_for(video["task"], tmp)
    if memory:
        ctx.log(f"correction memory: {len(memory)} corrected segments blended into {video['task']}")
    raw = rec.predict(src, video["task"], memory)
    steps = kp.merge_steps(raw["steps"])
    if not steps and hasattr(rec, "predict_forced"):
        ctx.log("step model saw no step (all background); decoding again without background, all steps low confidence",
                level="warn")
        steps = kp.merge_steps(rec.predict_forced(raw["features"], video["task"])["steps"])
    if not steps:
        raise StageFailed("the step model found no steps in this video")
    feat = ml_adapter.save_features(video["id"], raw["features"], raw["fps"])
    images, kf_paths = [], {}
    for s in steps:
        if s["low_confidence"]:
            jpg = os.path.join(tmp, f"kf_{s['idx']}.jpg")
            try:
                kp.extract_frame(src, s["keyframe_s"], jpg)
                images.append(jpg)
                kf_paths[s["idx"]] = st.put_file("keyframes", f"{video['id']}/step_{s['idx']}.jpg", jpg, "image/jpeg")
            except Exception as e:
                ctx.log(f"keyframe for step {s['idx']} failed: {e}", level="warn")
    ctx.log(f"{len(steps)} steps ({sum(s['low_confidence'] for s in steps)} low confidence) with {rec.kind} model")

    ctx.stage("llm", 65)
    writer, errs = FACTORIES["writer"](keys)
    for k, v in errs.items():
        ctx.log(f"llm: {k} unavailable: {v}", level="warn")
    task_title = catalog.TASKS.get(video["task"], {}).get("title", video["task"])
    out, _prompt = kp.write_steps(writer, task_title, steps, segs, lang, images)
    used = writer.used or "template"
    if out.get("fallback"):
        ctx.log(f"llm: template fallback ({redact(out.get('reason', 'no LLM'), *ctx.secrets)[:200]})", level="warn")
    else:
        ctx.log(f"llm: {used}", provider=used.split(":")[0])
    for k, v in (getattr(writer, "errors", {}) or {}).items():
        ctx.log(f"llm: {k} failed: {v}", level="warn")

    ctx.stage("check", 92)
    order_ok = all(a["end"] <= b["start"] + 1e-6 for a, b in zip(steps, steps[1:])) and \
        [s["idx"] for s in steps] == list(range(1, len(steps) + 1))
    texts = {t["idx"]: t for t in out["steps"]}
    db.delete("steps", {"video_id": video["id"]})
    db.delete("translations", {"video_id": video["id"]})
    for s in steps:
        t = texts.get(s["idx"], {})
        db.insert("steps", {"video_id": video["id"], "idx": s["idx"], "start_s": s["start"], "end_s": s["end"],
                            "label": s["label"], "confidence": round(float(s["confidence"]), 3),
                            "low_conf": bool(s["low_confidence"]), "title": t.get("title") or s["label"].title(),
                            "instruction": t.get("instruction") or s["label"], "narration_en": t.get("narration") or s["label"],
                            "edited": False, "keyframe_path": kf_paths.get(s["idx"])})
    db.delete("quizzes", {"video_id": video["id"]})
    if p.get("quiz", True):
        db.insert("quizzes", {"video_id": video["id"], "items": out.get("quiz", []), "translations": {}})
    db.update("videos", {"id": video["id"]}, {
        "status": "review", "duration_s": round(duration, 2), "spoken_lang": lang, "transcript": segs,
        "model_segments": [{"label": s["label"], "start": s["start"], "end": s["end"],
                            "confidence": round(float(s["confidence"]), 3)} for s in steps],
        "features": feat, "llm": used, "llm_fallback": bool(out.get("fallback")), "order_ok": order_ok,
        "model_kind": rec.kind})
    ctx.log("order check " + ("passed" if order_ok else "FAILED: please check the step times"))


# ---------------------------------------------------------------- stages 5-7
def h(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def step_rows(video_id):
    return sorted(get_store().select("steps", {"video_id": video_id}), key=lambda s: s["idx"])


def lang_texts(video_id, steps, lang):
    if lang == "en":
        return [s["narration_en"] for s in steps]
    tr = {t["step_id"]: t for t in get_store().select("translations", {"video_id": video_id, "lang": lang})}
    return [tr[s["id"]]["text"] if s["id"] in tr else s["narration_en"] for s in steps]


def translate(ctx, video, steps, langs, keys):
    db, p = get_store(), ctx.job["params"]
    targets = [l for l in langs if l != "en"]
    existing = {(t["step_id"], t["lang"]): t for t in db.select("translations", {"video_id": video["id"]})}
    need = [l for l in targets if any((s["id"], l) not in existing or
                                      (existing[(s["id"], l)]["source_hash"] != h(s["narration_en"])
                                       and not existing[(s["id"], l)].get("edited")) for s in steps)]
    quiz = db.first("quizzes", video_id=video["id"])
    q_items = (quiz or {}).get("items") or []
    q_sents = [x for q in q_items for x in [q["q"], *q["options"]]]
    q_need = [l for l in targets if quiz and q_items and l not in (quiz.get("translations") or {})]
    langs_needed = sorted(set(need) | set(q_need))
    if not langs_needed:
        ctx.log("translations up to date")
        return
    sents = [s["narration_en"] for s in steps]
    provs, skipped = chain("mt", p.get("mt", "sarvam"), keys, p["plan"])
    if skipped:
        ctx.log(f"mt: not available here: {', '.join(skipped)}")

    def do_mt(name):
        if name == "sarvam":
            ctx.check_budget()
        mt = FACTORIES["mt"](name, keys)
        res = {}
        for l in langs_needed:
            batch = (sents if l in need else []) + (q_sents if l in q_need else [])
            res[l] = mt.translate(batch, l) if batch else []
            if name == "sarvam":
                costs.add(ctx.cost, "sarvam", mt_chars=sum(len(b) for b in batch))
        return res

    prov, res = run_stage("mt", provs, do_mt, ctx.log, keys, ctx.job["key_source"])
    for l in langs_needed:
        out = list(res[l])
        if l in need:
            step_part, out = out[:len(sents)], out[len(sents):]
            for s, text in zip(steps, step_part):
                old = existing.get((s["id"], l))
                if old and old.get("edited"):
                    continue
                db.upsert("translations", {"step_id": s["id"], "video_id": video["id"], "lang": l, "text": text,
                                           "provider": prov, "source_hash": h(s["narration_en"]), "edited": False},
                          on=("step_id", "lang"))
        if l in q_need and out:
            tq, i = [], 0
            for q in q_items:
                n = 1 + len(q["options"])
                chunk = out[i:i + n]
                i += n
                tq.append({"q": chunk[0], "options": chunk[1:], "answer": q["answer"]})
            quiz["translations"] = {**(quiz.get("translations") or {}), l: tq}
            db.update("quizzes", {"id": quiz["id"]}, {"translations": quiz["translations"]})


def voice(ctx, video, steps, langs, keys, tmp, force=None, items=None):
    """Make (or reuse cached) clips. Returns {lang: [wav paths]}. force = {(lang, idx)} to remake.
    items = {lang: [(idx, text)]} for full-speech mode; default = one clip per step."""
    db, st, p = get_store(), get_storage(), ctx.job["params"]
    v = video.get("voice") or "Female"
    files, todo = {}, []
    for l in langs:
        if l == "en":
            continue
        pairs = items[l] if items else [(s["idx"], t) for s, t in zip(steps, lang_texts(video["id"], steps, l))]
        files[l] = []
        for idx, text in pairs:
            key = h(f"{l}|{v}|{text}")
            local = os.path.join(tmp, f"tts_{l}_{idx}_{key}.wav")
            files[l].append(local)
            row = db.first("tts_clips", video_id=video["id"], lang=l, idx=idx, hash=key)
            if row and not (force and (l, idx) in force):
                try:
                    st.download("outputs", row["path"], local)
                    continue
                except Exception:
                    pass
            todo.append({"text": text, "lang": l, "out": local, "idx": idx, "hash": key})
    if not todo:
        ctx.log("all narration clips reused from cache")
        return files
    provs, skipped = chain("tts", p.get("tts", "sarvam"), keys, p["plan"])
    if skipped:
        ctx.log(f"tts: not available here: {', '.join(skipped)}")

    def do_tts(name):
        if name == "sarvam":
            ctx.check_budget()
        tts = FACTORIES["tts"](name, keys, v)
        tts.synth([{"text": t["text"], "lang": t["lang"], "out": t["out"]} for t in todo])
        if name == "sarvam":
            costs.add(ctx.cost, "sarvam", tts_chars=sum(len(t["text"]) for t in todo))
        return True

    prov, _ = run_stage("tts", provs, do_tts, ctx.log, keys, ctx.job["key_source"])
    for t in todo:
        path = f"{video['id']}/tts/{t['lang']}/{t['idx']}_{t['hash']}.wav"
        st.put_file("outputs", path, t["out"], "audio/wav")
        db.upsert("tts_clips", {"video_id": video["id"], "lang": t["lang"], "idx": t["idx"], "hash": t["hash"],
                                "path": path, "provider": prov}, on=("video_id", "lang", "idx", "hash"))
    ctx.log(f"{len(todo)} narration clips made with {prov}")
    return files


def render(ctx, video, steps, langs, files, src, tmp, timeline=None, texts=None, orig_volume=0.15):
    """timeline/texts (full-speech mode): [{idx, start, end}] and {lang: [text]}; default = the steps."""
    db, st = get_store(), get_storage()
    total = float(video.get("duration_s") or probe_duration(src))
    sd = timeline or [{"idx": s["idx"], "start": s["start_s"], "end": s["end_s"], "label": s["label"]} for s in steps]
    for l in langs:
        if l == "en":
            if timeline and texts and texts.get("en"):
                vtt = os.path.join(tmp, "captions_en.vtt")
                kp.write_vtt([{"start": t["start"], "end": t["end"], "text": x} for t, x in zip(timeline, texts["en"])], vtt)
            else:
                vtt = caption_vtt(steps, lang_texts(video["id"], steps, "en"), os.path.join(tmp, "captions_en.vtt"))
            st.put_file("outputs", f"{video['id']}/en/captions.vtt", vtt, "text/vtt")
            db.upsert("outputs", {"video_id": video["id"], "lang": "en", "mp4_path": None,
                                  "vtt_path": f"{video['id']}/en/captions.vtt", "narration_path": None,
                                  "placements": None, "updated_at": now_iso()}, on=("video_id", "lang"))
            continue
        out_dir = os.path.join(tmp, f"out_{l}")
        os.makedirs(out_dir, exist_ok=True)
        res = kp.dub(src, sd, texts[l] if texts else lang_texts(video["id"], steps, l), l, files[l], out_dir, total,
                     orig_volume=orig_volume)
        base = f"{video['id']}/{l}/{int(time.time())}"
        mp4 = st.put_file("outputs", f"{base}/dubbed_{l}.mp4", res["mp4"], "video/mp4")
        vtt = st.put_file("outputs", f"{base}/captions_{l}.vtt", res["vtt"], "text/vtt")
        nar = st.put_file("outputs", f"{base}/narration_{l}.wav", res["narration"], "audio/wav")
        db.upsert("outputs", {"video_id": video["id"], "lang": l, "mp4_path": mp4, "vtt_path": vtt,
                              "narration_path": nar, "placements": res["placements"], "updated_at": now_iso()},
                  on=("video_id", "lang"))
        over = [p for p in res["placements"] if p["overflow_s"] > 0.5]
        ctx.log(f"{catalog.LANGS[l]}: dubbed video ready" + (f" ({len(over)} narration clips run past their step)" if over else ""))


FULL_IDX = 10000          # tts_clips idx offset for full-speech sentences (steps use 1..n)
FULL_ORIG_VOLUME = 0.05   # original soundtrack under a full translation (kd_pipeline default for steps: 0.15)


def speech_segments(video):
    """Transcript -> sentence-sized timed segments (kd_pipeline.group_words: sentence ends, pauses, max 8 s)."""
    raw = [t for t in (video.get("transcript") or []) if (t.get("text") or "").strip()]
    segs = kp.group_words(raw) if raw else []
    return [{"idx": FULL_IDX + i, "start": round(float(x["start"]), 2), "end": round(float(x["end"]), 2),
             "text": x["text"].strip()} for i, x in enumerate(segs) if len(x["text"].strip()) > 1]


def translate_segments(ctx, video, segs, langs, keys):
    """Translate every sentence the instructor said into each target language (cached on the video)."""
    db, p = get_store(), ctx.job["params"]
    src = video.get("spoken_lang") if video.get("spoken_lang") in catalog.LANGS else "en"
    sents = [x["text"] for x in segs]
    store = dict(video.get("segment_texts") or {})
    if store.get("src_hash") != h("|".join(sents)):
        store = {"src_hash": h("|".join(sents))}
    store[src] = sents
    need = [l for l in langs if l != "en" and l not in store]
    if need:
        provs, skipped = chain("mt", p.get("mt", "sarvam"), keys, p["plan"])
        if skipped:
            ctx.log(f"mt: not available here: {', '.join(skipped)}")

        def do_mt(name):
            if name == "sarvam":
                ctx.check_budget()
            mt = FACTORIES["mt"](name, keys)
            res = {}
            for l in need:
                res[l] = mt.translate(sents, l, src)
                if name == "sarvam":
                    costs.add(ctx.cost, "sarvam", mt_chars=sum(len(x) for x in sents))
            return res

        _, res = run_stage("mt", provs, do_mt, ctx.log, keys, ctx.job["key_source"])
        for l in need:
            store[l] = [t.strip() or o for t, o in zip(res[l], sents)]       # never voice an empty line
        ctx.log(f"full speech: {len(sents)} sentences translated into {', '.join(catalog.LANGS[l] for l in need)}")
    db.update("videos", {"id": video["id"]}, {"segment_texts": store})
    video["segment_texts"] = store
    return store


def dub_full(ctx, video, steps, langs, keys, src, tmp):
    segs = speech_segments(video)
    if not segs:
        ctx.log("full speech: no speech found in this video, using step narration instead", level="warn")
        return False
    texts = translate_segments(ctx, video, segs, langs, keys)
    ctx.stage("tts", 35, f"Voicing {len(segs)} sentences per language")
    items = {l: [(x["idx"], t) for x, t in zip(segs, texts[l])] for l in langs if l != "en"}
    files = voice(ctx, video, steps, langs, keys, tmp, items=items)
    ctx.stage("render", 75)
    timeline = [{"idx": x["idx"], "start": x["start"], "end": x["end"]} for x in segs]
    out_texts = {l: texts[l] for l in langs if l != "en"}
    if texts.get("en"):
        out_texts["en"] = texts["en"]
    render(ctx, video, steps, langs, files, src, tmp, timeline=timeline, texts=out_texts, orig_volume=FULL_ORIG_VOLUME)
    return True


def dub(ctx, video, tmp):
    db = get_store()
    db.update("videos", {"id": video["id"]}, {"status": "dubbing"})
    keys = _keys(ctx, video)
    steps = step_rows(video["id"])
    langs = ["en"] + [l for l in (video.get("targets") or []) if l != "en"]
    names = ", ".join(catalog.LANGS[l] for l in langs if l != "en")
    full = (video.get("dub_mode") or "steps") == "full"
    label = ("Translating the full speech · " if full else "Translating · ") + names if names else "Translating"
    ctx.stage("translate", 5, label)
    translate(ctx, video, steps, langs, keys)           # step list, step captions and the quiz
    src = _source(ctx, video, tmp)
    if full and dub_full(ctx, video, steps, langs, keys, src, tmp):
        db.update("videos", {"id": video["id"]}, {"status": "ready", "last_error": None})
        return
    ctx.stage("tts", 35)
    files = voice(ctx, video, steps, langs, keys, tmp)
    ctx.stage("render", 75)
    render(ctx, video, steps, langs, files, src, tmp)
    db.update("videos", {"id": video["id"]}, {"status": "ready", "last_error": None})


def revoice(ctx, video, tmp):
    p = ctx.job["params"]
    lang, idx = p["lang"], int(p["idx"])
    keys = _keys(ctx, video)
    steps = step_rows(video["id"])
    ctx.stage("tts", 10)
    src = _source(ctx, video, tmp)
    if video.get("dub_mode") == "full" and speech_segments(video):
        ctx.log("full-speech dub: the voice follows the instructor's sentences; the edited step text updates the "
                "step list", level="warn")
        dub_full(ctx, video, steps, [lang], keys, src, tmp)
        return
    files = voice(ctx, video, steps, [lang], keys, tmp, force={(lang, idx)})
    ctx.stage("render", 60)
    render(ctx, video, steps, [lang], files, src, tmp)


def retrain_job(ctx, video, tmp):
    from .retrain import run_retrain
    run_retrain(ctx, tmp)
