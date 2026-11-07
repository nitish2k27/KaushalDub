# KaushalDub: build brief

Read this whole file before writing code. It records decisions already made and what is already built and tested.

## What the product is

A web app that turns a short procedural "how-to" video (vocational skill: CPR, screen protector, car polishing, cooking...)
into numbered steps, editable captions, a narrated (dubbed) version in Hindi and Kannada, and a quiz.
Coursework project (RV University, CS3235, Module 3 Multimodal: computer vision + speech + LLM). Owner: Nitish.

Three roles, each signs in with Google:
- **Trainer**: uploads a video, picks skill/task, spoken language, target languages, voice; reviews and edits detected
  steps, narration and quiz; approves; gets dubbed videos; publishes to the library.
- **Learner**: searches the library, watches a video in their language (step list, captions, narration), takes the quiz,
  sees progress history.
- **Annotator**: labels or corrects step boundaries on clips (model suggestions shown, low-confidence first); submitted
  corrections go to the video's trainer for approval, and approved ones update the video and the model (see below).

## Added features (in the mockup, must be built)

1. **Learner reports ("tickets")**: on the watch page a learner clicks "Report a problem"; the player pauses and the
   form captures the current timestamp (re-capturable), the step at that moment, the language version, a category
   (Wrong step, Wrong translation, Narration out of sync, Unclear instruction, Unsafe instruction, Other) and a
   required message. The trainer gets a "Learner reports" tab with an open-count badge and a banner on My videos;
   opening a report jumps the player to the timestamp, shows that step's text in that language for editing, lets the
   trainer re-make that step's voice, reply, and close as "Resolved" or "Closed without change". The learner sees
   status and reply under My progress → My reports.
2. **Annotator corrections → trainer approval → model learning**: annotator submits labels → an "Annotation request"
   for the video's trainer (badge count). The review screen shows two timelines (model vs annotator), a list of
   changes (label changed / boundary moved, model confidence) with a checkbox each, play buttons, an optional note,
   "Approve selected changes" and "Send back". Approval: (a) updates that video's steps (and re-renders affected
   narration if needed); (b) adds the corrected segments to the skill's **correction memory**: their CLIP features
   are stored and blended into that task's class prototypes, so the next video of the same skill benefits
   immediately; (c) queues them for retraining. A "Model learning" card shows pending corrections, corrections in
   memory, model version, last retrain, and "Retrain now". Retraining (a worker job reusing the training notebook
   logic) runs automatically at 20 pending corrections; the new version replaces the old only if test-set macro-F1 is
   not worse. This is human-in-the-loop active learning, not reinforcement learning; call it that in the UI/report.
3. **API keys and plans** (trainer "API keys & plan" tab): Free trial = first 5 videos on the platform's keys (counter
   and progress bar; Process is disabled with a prompt when used up); "Your own API keys" = Sarvam (required) plus
   Gemini or Groq, with a Test button per key, stored encrypted server-side (never returned to the browser in full,
   never logged), used only for that user's jobs; "Free local models" = AI4Bharat models on the GPU worker, no keys;
   "Pro" = platform keys without limit, shown as "Coming soon" (no payment integration in scope). Also per-user
   model choice per stage (speech to text, translation, voice). The worker picks keys per job from the owner's plan.


## UI: follow the existing design

`design/kaushaldub_demo.html` is a clickable mockup (single HTML file, open it in a browser). Build the real app to look
and flow like it, with small tweaks allowed. Screens:
role picker → Google sign-in → per-role shell (top bar: logo, role chip, switch role, avatar, sign out; tab nav).
- Trainer: "My videos" (upload card: drop zone, title, domain, target-language chips, voice, quiz toggle,
  Process button; history table) → Processing (pipeline stepper Upload/Process/Review/Dub/Publish with stage list and
  progress) → Review (video player with step ticks, caption-language chips, per-step editable text with confidence
  pills and a low-confidence warning, Quiz tab) → Dub progress → Result (player with language switch, downloads,
  Publish).
- Learner: Library (search, domain chips, cards) → Watch (player, language chips, clickable step list) → Quiz
  (one question at a time, feedback, score) → My progress.
- Annotator: Queue (stats, clips table) → Labelling (player, segment timeline with playhead, label dropdown, play
  segment, split at playhead, merge with next, accept, mark unclear, submit) → My labels.
Design tokens are in the mockup's `:root` CSS (teal brand, amber accent, light and dark themes, Sora + Noto Sans incl.
Devanagari and Kannada). Keep accessibility: real buttons and labels, 44px touch targets, works at phone width.

## Stack (decided)

- Frontend: React 18 + Vite + TypeScript, Tailwind + shadcn/ui, a video player supporting multiple audio/caption
  tracks (video.js or native `<video>` with per-language mp4 + `<track>` vtt). Deploy: Vercel.
- Backend: FastAPI (Python 3.11+), background jobs with Celery + Redis (or RQ), job progress polled by the UI.
- Auth, Postgres, file storage: Supabase (Google OAuth provider; JWT verified by FastAPI).
- ML pipeline: `ml/kd_pipeline.py` (reuse as-is, it is tested), step model bundle `ml/kaushaldub_model/`.
- Deployment target: Hugging Face Space (CPU) for the API. Local AI4Bharat models need a GPU, so the pipeline must
  support provider switches (below) and an optional GPU worker (Kaggle/Colab notebook running the same worker code).
  Budget: free tiers only (Sarvam has ₹100 free credits, roughly 10 dubbed videos).

## ML pipeline (built and tested on Kaggle)

Per video, in order (all functions/classes are in `ml/kd_pipeline.py`):
1. ffmpeg: extract 16 kHz mono audio (`extract_audio`).
2. Speech to text, provider switch `ASR`: `WhisperASR` (openai/whisper-small, word timestamps grouped into short
   segments) | `IndicConformerASR` (AI4Bharat, gated on HF, needs `onnxruntime`, Indian languages only) | `SarvamASR`.
   Whisper also detects the spoken language.
3. Step detection: `StepRecognizer` from `ml/kaushaldub_model/kd_model.py` (frozen CLIP ViT-B/16-quickgelu at 2 fps →
   MS-TCN temporal model, one head per task) → `merge_steps()` cleans it (joins same-label neighbours, drops <2 s
   blips, renumbers, flags confidence < 0.6). Low-confidence steps get a keyframe jpg (`extract_frame`).
4. LLM writes per-step title, instruction, narration (word budget from step length) and a 3-question quiz as JSON:
   `build_prompt` → `ChainWriter([GeminiWriter("auto"), GroqWriter("auto")])` → `validate_llm` (same step count and
   order) → retry once → `template_steps` fallback. Gemini auto-picks the newest flash model, retries on 503/429;
   Groq is the backup (text only).
5. Translation, switch `MT`: `IndicTrans2MT` (AI4Bharat en→indic 200M; runs in an isolated virtualenv with
   transformers 4.46.3 because Kaggle has transformers 5; may be gated) | `SarvamMT`.
6. Voice, switch `TTS`: `IndicParlerTTS` (AI4Bharat, isolated virtualenv, works on GPU, ~2 min for 10 clips on T4) |
   `SarvamTTS` (bulbul:v3, speaker "shubh").
7. `dub()`: `place_clips` (each step's clip starts at its step; sped up to 1.3x if too long; overflow pushes later),
   `render_track`, `write_vtt`, `mux` (original audio kept at 15% volume, narration on top, mov_text captions) →
   `dubbed_<lang>.mp4`, `captions_<lang>.vtt`, `narration_<lang>.wav`.

Reference run: `notebooks/kaushaldub_dub_check.ipynb` (end-to-end check with provider comparison). Training:
`notebooks/kaushaldub_train.ipynb` (COIN annotations, CLIP/ResNet/X-CLIP features, MS-TCN, few-shot, export).

Status of the last check run (COIN CPR test video, English speech): ALL CHECKS PASSED. Steps matched ground truth
(5 steps, correct order). Gemini (auto-picked gemini-3.8-flash) passed validation after 503 retries (~2.5 min) and
wrote narration with the instructor's details plus a 3-question quiz. IndicTrans2 (isolated env) and Sarvam both
translated; IndicTrans2 used for dubbing. Indic Parler-TTS made the voice (~24 s per clip on a T4; Sarvam ~3 s).
Only IndicConformer failed (onnxruntime rejected cache symlinks; fixed by downloading to a real folder, not yet
re-run). Watch: the LLM once added a detail not in the speech ("carotid"); the prompt now forbids added facts and the
trainer review step stays mandatory.

Step model results (test set, 3 target skills): CLIP+TCN macro-F1 42.3, F1@50 34.3, edit 45.7; CLIP+BiLSTM 44.3;
ResNet+BiLSTM 37.9; X-CLIP linear 37.4; CLIP zero-shot 16.7. Videos-per-skill curve 5→25.5, 10→29.6, 20→33.6,
all→43.9. Few-shot unseen task (omelette) best 31.0 with 10 videos + head fine-tune. Trained tasks:
ReplaceMobileScreenProtector, PerformCPR, PolishCar, MakePizza, UseRiceCookerToCookRice, (BoilNoodles, MakeCookie had
few or no videos; exclude them in the UI), CookOmelet (few-shot head).

## API (from the requirements document; adjust if needed)

- `POST /videos` (multipart upload or YouTube URL; title, task, spoken_lang, targets, voice, quiz) → `{video_id, job_id}`
- `GET /jobs/{id}` → stage, progress 0–100, error
- `GET /videos/{id}` → metadata, steps, transcript, quiz, outputs per language (signed URLs)
- `PATCH /videos/{id}/steps` (edited text/titles; boundaries for annotator corrections)
- `POST /videos/{id}/approve` → starts translation + voice + render job
- `POST /videos/{id}/publish`; `GET /library?q=&domain=&lang=`
- `POST /quiz/{video_id}/attempts`; `GET /me/history`
- Annotator: `GET /annotations/queue`, `GET/PUT /annotations/{clip_id}`, `POST /annotations/{clip_id}/submit`
- Tickets: `POST /videos/{id}/tickets` (learner), `GET /tickets?status=` (trainer), `PATCH /tickets/{id}` (fix text,
  reply, status), `POST /videos/{id}/steps/{idx}/revoice?lang=`; `GET /me/tickets` (learner)
- Annotation requests: `GET /annotation-requests?status=`, `POST /annotation-requests/{id}/approve` (list of change
  ids), `POST /annotation-requests/{id}/send-back`; `GET /model/status`, `POST /model/retrain`
- Plan and keys: `GET/PUT /me/plan`, `PUT /me/keys/{provider}`, `POST /me/keys/{provider}/test`, `DELETE /me/keys/{provider}`
Long work happens in the worker; the API only enqueues and reports progress.

## Data model (Postgres / Supabase)

users(id, email, name, role) · videos(id, owner, title, task, domain, spoken_lang, targets[], status, source_path,
duration_s, created_at, published) · steps(id, video_id, idx, start_s, end_s, label, confidence, low_conf, title,
instruction, narration_en, edited) · translations(step_id, lang, text, provider) · outputs(video_id, lang, mp4_path,
vtt_path, narration_path) · quizzes(id, video_id, items jsonb) · quiz_attempts(id, quiz_id, user_id, answers, score,
created_at) · watch_history(user_id, video_id, progress, updated_at) · tickets(id, video_id, reporter_id, lang,
timestamp_s, step_idx, category, message, status open/resolved/closed, reply, created_at, closed_at) ·
annotation_requests(id, video_id, annotator_id, trainer_id, model_segments jsonb, annotator_segments jsonb,
approved_changes jsonb, status pending/approved/partly_approved/sent_back, note, created_at) · correction_memory(id,
task, label, feature_path, source_request_id, created_at) · model_versions(id, version, path, metrics jsonb, active,
created_at) · user_plans(user_id, plan free/byok/local/pro, free_used, asr, mt, tts) · user_api_keys(user_id,
provider, encrypted_key, last4, verified_at) · annotations(id, clip_id, annotator, segments
jsonb, status, reviewer_note) · jobs(id, video_id, kind, stage, progress, error, logs jsonb, created_at).
Storage buckets: raw-videos, outputs (mp4/vtt/wav), keyframes. Row-level security by owner/role.

## Secrets (env vars; never commit)

SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY, SARVAM_API_KEY, GEMINI_API_KEY, GROQ_API_KEY, HF_TOKEN,
REDIS_URL. Providers are chosen per job (defaults: ASR=whisper, MT=sarvam until IndicTrans2 is confirmed,
TTS=sarvam on CPU / indicparler on the GPU worker).

## Running out of API credits (must handle)

Sarvam is prepaid: when credits hit zero every call returns HTTP 402 `insufficient_quota_error` (not a rate limit;
retrying will not help). Nothing is charged automatically unless auto-recharge is switched on in the Sarvam dashboard.
Gemini/Groq free tiers return 429 when exhausted. The worker must: (1) treat 402 as "out of credits" (no retries) and
429 as "retry with backoff"; (2) fall back per stage to the next provider (Sarvam → local model on the GPU worker,
Gemini → Groq → template); (3) if no provider is left, pause the job with status `needs_credits` and a clear message
to the trainer instead of failing silently; (4) record estimated cost per job (audio minutes, characters translated
and voiced) and stop platform-key jobs when a configurable monthly budget (env `PLATFORM_BUDGET_INR`) is reached;
(5) show the admin a low-balance warning. Users on their own keys get the same 402 message about their account.

## Suggested build order

1. Repo scaffold: `frontend/`, `backend/`, `ml/` (copy as given), `notebooks/`, `design/`.
2. Backend: FastAPI app, Supabase JWT auth, DB schema + migrations, upload → job → worker running kd_pipeline stages
   1–4 → review data; approve → stages 5–7 → outputs. Unit-test with a short sample video and mocked API providers.
3. Frontend: shell + role picker + Supabase Google login; trainer flow end to end against the real API; then learner;
   then annotator.
4. Learner tickets; annotation requests + approval; correction memory + retrain job + model versions; plans, key
   storage (encrypted) and the 5-free-videos quota enforced in the API, not only the UI.
5. Deploy: API on HF Space (CPU), frontend on Vercel, optional GPU worker notebook; smoke test with a COIN video and a
   Kannada/Hindi YouTube tutorial.
6. Evaluation page/data for the report (provider comparison, step metrics, user ratings).
