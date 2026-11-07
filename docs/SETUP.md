# KaushalDub: full setup, run and deploy guide

Turns a short procedural how-to video into numbered steps, editable captions, a narrated (dubbed) version in
Hindi and Kannada, and a quiz. Three roles sign in with Google: **trainer**, **learner**, **annotator**.
RV University CS3235 (Module 3, multimodal) coursework. See `CLAUDE.md` for the product brief and
`design/kaushaldub_demo.html` for the clickable mockup the UI follows.

```
backend/     FastAPI API + RQ worker (reuses ml/kd_pipeline.py and the bundle's kd_model.py unchanged)
frontend/    React 18 + Vite + TypeScript + Tailwind + shadcn-style components (mockup design tokens)
ml/          kd_pipeline.py, kd_model.py, kd_metrics.py (+ kaushaldub_model/ bundle, not in git)
supabase/    SQL migrations: tables, row-level security, storage buckets, Google sign-up trigger
notebooks/   training + dub check notebooks, worker_gpu.ipynb (GPU worker for Kaggle/Colab)
deploy/      Hugging Face Space Dockerfile + push script
```

## How it works

| Step | Where | What |
|---|---|---|
| Upload | `POST /videos` | Plan and quota rules are checked **in the API**, the file goes to the `raw-videos` bucket, a `process` job is queued |
| Stages 1–4 | worker | ffmpeg audio → ASR (Whisper / IndicConformer / Sarvam) → step model + correction memory → `merge_steps` → keyframes for low-confidence steps → LLM text and quiz (Gemini → Groq → template) → order check |
| Review | trainer | edit step titles, narration, instructions and the quiz |
| Stages 5–7 | `POST /videos/{id}/approve` → worker | translation (Sarvam / IndicTrans2) → voice (Sarvam Bulbul / Indic Parler-TTS) → `kd_pipeline.dub()` per language → `outputs` bucket |
| Publish | trainer | video appears in the learner library |

Every job reports **per-stage progress** (`GET /jobs/{id}`: `stages[]`, `progress`, `logs`, estimated `cost`).
Providers are chosen **per job** from the owner's plan (and optional per-upload overrides). They fall back
stage by stage. HTTP 402 (out of credits) is never retried; HTTP 429 is retried with backoff and then the next
provider is tried. If nothing is left, the job pauses as `needs_credits` with a clear message and a **Resume**
button.

**Plans** (enforced in `backend/app/plans.py`, mirrored in the UI):
- **Free trial**: first 5 videos on the platform's keys, while the monthly `PLATFORM_BUDGET_INR` lasts.
- **Your own keys**: Sarvam plus Gemini or Groq. Keys are Fernet-encrypted at rest, shown only as `••••last4`,
  never logged, and used only for that user's jobs.
- **Free local models**: AI4Bharat models on the GPU worker, no keys.
- **Pro**: shown as "Coming soon". There is no payment code.

**Learner reports**: a learner reports a problem at a timestamp. The trainer edits that step's text in that
language (captions are rebuilt at once), re-makes that one step's voice (`revoice` job; other clips come from
the cache), replies, and closes the report as Resolved or "Closed without change".

**Annotator corrections (human-in-the-loop active learning)**: the annotator relabels, splits or merges
segments, and the trainer approves changes one by one. Approval (a) rebuilds the video's steps and re-renders
narration if it was already dubbed, (b) stores the corrected segments' CLIP features in the skill's
**correction memory**, which is blended into that task's class vectors on the next prediction, and (c) queues
them for retraining. At `RETRAIN_THRESHOLD` (20) pending corrections, or on "Retrain now", the `retrain` job
fine-tunes with the training notebook's loss. The new model version is activated only if test-set macro-F1 is
**not worse**.

## Status (what has been checked)

- `backend/tests`: **42 tests pass**. They cover plan and quota rules, key encryption and redaction, the
  402/429/fallback/`needs_credits` handling, the ticket flow (fix text → re-voice one step → close), the
  annotation flow (per-change approval → steps, memory, re-render), retrain activation (better / equal / worse),
  auto-retrain at the threshold, Supabase JWT verification, the Redis queue with an RQ worker (fakeredis), and one **end-to-end run on a generated 12 s video**
  with mocked API providers (real ffmpeg dub and mux, checked mp4, audio and VTT output).
- The frontend type-checks and builds. All flows were clicked through in a browser against the local demo
  backend: upload → process → review/edit → dub → publish → learner watch, quiz and report → trainer fixes the
  report → annotator labels → trainer approves. Phone width (375 px) and dark theme were checked as well.
- **Not verified here** (they need your accounts): real Sarvam/Gemini/Groq calls, Whisper/CLIP on real
  weights (the bundle `ml/kaushaldub_model/` isn't in the repo), a live Supabase project, the HF Space build,
  the Vercel deploy, and running `worker_gpu.ipynb` on Kaggle.

## Run locally

Requirements: Python 3.11, Node 20, ffmpeg on PATH.

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt      # Linux/macOS: .venv/bin/pip
```

```bash
cd frontend
npm install
```

### 1. Demo mode (no accounts, no keys)

SQLite + local files, jobs run inside the API process, dev sign-in, mock step model and **mock providers**.
Transcripts, translations ("[hi] …") and voices (a tone) are fake.

```bash
backend/.venv/Scripts/python backend/scripts/dev.py
```

```bash
cd frontend && echo VITE_DEV_AUTH=1 > .env.development.local && npm run dev
```

Open http://localhost:5173, pick a role, and sign in with any name.

### 2. Real models and keys, still local

Fill `.env` (copy `.env.example`), install the model packages and put the trained bundle in place:

```bash
backend/.venv/Scripts/pip install -r backend/requirements-ml.txt
```

Unzip `kaushaldub_model.zip` into `ml/kaushaldub_model/` (it should contain `config.json`, `model.pt`,
`kd_model.py` and `kd_metrics.py`). Then set `STEP_MODEL=bundle` and `MOCK_PROVIDERS=false` in `.env` and run
the same `dev.py`; values in `.env` win over the demo defaults. With `REDIS_URL` set, run a worker as well:

```bash
cd backend && .venv/Scripts/python -m app.worker --queues cpu
```

Windows note: `kd_pipeline.SarvamASR` reopens a `NamedTemporaryFile`, which Windows does not allow, so Sarvam
speech-to-text fails on a Windows worker. Whisper and the Sarvam translate/TTS calls are fine. Sarvam ASR works
on the Linux Space and on Kaggle.

### Tests

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

The tests never read `.env`, never call a real provider, and use SQLite and a temp folder.

## Supabase setup (free tier)

1. Create a project at supabase.com. **Project settings → API** gives `SUPABASE_URL`, `SUPABASE_ANON_KEY` and
   `SUPABASE_SERVICE_KEY` (service role: backend only, never in the frontend).
2. Apply the migrations in `supabase/migrations/` in file order, using `supabase db push` or the SQL editor.
   They create all tables, row-level security, the three private buckets (`raw-videos`, `outputs`,
   `keyframes`), the sign-up trigger (profile + free plan) and model version 1.
3. **Google sign-in**: create an OAuth client in Google Cloud Console (type "Web application"). Add the
   authorised redirect URI `https://<project>.supabase.co/auth/v1/callback`. Paste the client ID and secret
   into **Authentication → Providers → Google**.
4. **Authentication → URL configuration**: set Site URL to your Vercel URL, and add `http://localhost:5173` and
   the Vercel URL to the redirect URLs.
5. JWT: new projects sign tokens with asymmetric keys, and the backend verifies them with the project's JWKS
   (nothing to set). Older projects using the legacy HS256 secret should set `SUPABASE_JWT_SECRET`.

Roles: users choose a role on the first screen and can switch with "Switch role" (`PUT /me/role`). Each API
route checks the role and ownership. RLS is a second guard for direct database access, and the
`user_api_keys` table has no client policies at all.

## Deploy

### Backend: Hugging Face Space (Docker, free CPU)

1. Create a **Docker** Space (free CPU basic).
2. Create a free Redis, for example Upstash. Use the `rediss://…` URL as `REDIS_URL`.
3. In the Space, open **Settings → Variables and secrets** and add the `.env.example` values. Required:
   `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `KEY_ENCRYPTION_SECRET`, `CORS_ORIGINS` (your Vercel
   URL) and `STEP_MODEL_REPO` (a private HF model repo holding the bundle, downloaded at start with `HF_TOKEN`),
   plus the platform keys if you want the free trial to work. Keep `DEV_AUTH=false` and `MOCK_PROVIDERS=false`.
4. Push the code:

   ```bash
   bash deploy/push_space.sh <hf-user>/<space-name>
   ```

   The container runs the API on port 7860 and an RQ worker on the `cpu` queue. Check `/health` when it's up.

### Frontend: Vercel

1. Import the repo in Vercel and set **Root directory** to `frontend` (framework: Vite). `vercel.json` already
   handles SPA routing.
2. Set the environment variables: `VITE_API_URL=https://<hf-user>-<space-name>.hf.space`,
   `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`. Don't set `VITE_DEV_AUTH`.
3. Deploy, then add the Vercel URL to `CORS_ORIGINS` on the Space and to Supabase's redirect URLs.

### Optional GPU worker (Kaggle/Colab)

Open `notebooks/worker_gpu.ipynb` on Kaggle with a T4 GPU and internet on. Add the secrets it lists, attach the
code (git URL or dataset) and the model bundle, then Run all. It runs the same `app.worker` on the `gpu` queue.
Set `GPU_QUEUE_ENABLED=true` on the Space so that local-model jobs (Free local models plan, Indic Parler-TTS,
IndicConformer) are routed there.

### Retraining test set

Retraining activates a new model only if test-set macro-F1 is not worse, so it needs the COIN test features next
to the bundle. Where the training notebook ran:

```bash
python backend/scripts/export_testset.py --work /kaggle/working --out ml/kaushaldub_model/testset
```

Put the folder next to `model.pt`; on the Space, include it in the `STEP_MODEL_REPO` bundle. Without it, a
retrain still saves the new version but keeps the old one active ("no test set").

## Budget and credits

- Each job records estimated cost: audio minutes, characters translated and characters voiced, at the
  `RATE_SARVAM_*` rates.
- Jobs on platform keys stop at `PLATFORM_BUDGET_INR` per month. Admins (`ADMIN_EMAILS`) get a low-balance
  banner from 80 % and can see `/admin/budget`.
- Sarvam's ₹100 free credit covers about 10 dubbed videos. Nothing is charged unless you switch on
  auto-recharge in Sarvam's dashboard.

## API

`GET /config` · `GET /me` · `PUT /me/role` · `GET/PUT /me/plan` · `PUT/DELETE /me/keys/{provider}` ·
`POST /me/keys/{provider}/test` · `GET /me/history` · `GET /me/tickets` · `GET /me/annotations` ·
`POST /videos` · `GET /videos` · `GET/DELETE /videos/{id}` · `PATCH /videos/{id}/steps` · `PUT /videos/{id}/quiz` ·
`PUT /videos/{id}/steps/{idx}/text?lang=` · `POST /videos/{id}/steps/{idx}/revoice?lang=` · `POST /videos/{id}/approve` ·
`POST /videos/{id}/publish` · `POST /videos/{id}/unpublish` · `GET /jobs/{id}` · `POST /jobs/{id}/resume` ·
`GET /library?q=&domain=&lang=` · `POST /videos/{id}/progress` · `POST /quiz/{video_id}/attempts` ·
`POST /videos/{id}/tickets` · `GET /tickets?status=` · `GET/PATCH /tickets/{id}` · `GET /annotations/queue` ·
`GET/PUT /annotations/{clip_id}` · `POST /annotations/{clip_id}/submit` · `GET /annotation-requests?status=` ·
`GET /annotation-requests/{id}` · `POST /annotation-requests/{id}/approve` · `POST /annotation-requests/{id}/send-back` ·
`GET /model/status` · `POST /model/retrain` · `GET /admin/budget` · `GET /health`. Interactive docs are at `/docs`.

## Notes and deviations from the brief

- `kd_model.py` is at `ml/kd_model.py`, not `ml/kaushaldub_model/kd_model.py`. The backend loads the bundle's
  own copy when the bundle is present (as `ml/README.md` says) and falls back to `ml/kd_model.py` otherwise.
- Translation runs after approval (stages 5–7), as specified. Review therefore edits English, and translated
  text is edited on the result page or from a learner report.
- The mockup's "Regenerate quiz" button became an editable quiz, which avoids a synchronous LLM call in the API.
- A "clip" for annotators is a whole processed video (`clip_id` = video id). Clips with low-confidence steps
  come first in the queue.
- Indic Parler-TTS uses `kd_pipeline`'s fixed voice descriptions, so the Female/Male choice only affects Sarvam
  voices. Check `SARVAM_SPEAKER_*` against Sarvam's speaker list for `bulbul:v3`.
