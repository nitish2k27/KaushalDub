# KaushalDub runbook: from keys to a full library

Two ways to run the dubbing. Pick per video; you can mix them.

| | **Mode A: Sarvam** | **Mode B: Free local models** |
|---|---|---|
| Speech to text | Sarvam (Indian languages + English, auto-detects the language) | IndicConformer for Hindi/Kannada speech; English speech needs Whisper or Sarvam (see note) |
| Translation | Sarvam Translate | IndicTrans2 (AI4Bharat) |
| Voice | Sarvam Bulbul v3 | Indic Parler-TTS (AI4Bharat) |
| Step text + quiz | Gemini (free tier) → Groq → template | same |
| Cost | about ₹7–8 per 100 s video (₹100 free credit ≈ 12 videos) | ₹0 (Kaggle's free T4, 30 h/week) |
| Speed | about 2 min per video | 5–8 min per video |
| Runs on | your laptop | Kaggle GPU notebook (needs Supabase + Redis so the notebook and your app share data) |

Note on speech for Mode B: the COIN playlist videos are spoken in **English**. IndicConformer only understands Indian
languages, so for these videos use `--asr sarvam` (₹0.49/min, the cheapest Sarvam part) or Whisper. For Hindi or
Kannada speech (e.g. the Tawa pizza video) IndicConformer is the right choice.

---

## Mode A: Sarvam, on your laptop

### 1. Fill `.env` (in the `kaushaldub/` folder; you already copied it from `.env.example`)

Set these lines; leave everything else as it is:

```
SARVAM_API_KEY=<your Sarvam key>
GEMINI_API_KEY=<your Gemini key>
GROQ_API_KEY=<your Groq key, optional backup>
KEY_ENCRYPTION_SECRET=<output of the command below>
DEV_AUTH=true
MOCK_PROVIDERS=false
STEP_MODEL=bundle
FREE_VIDEOS=40
PLATFORM_BUDGET_INR=100
```

- `DEV_AUTH=true` lets you sign in on your laptop without Supabase. Set it back to `false` before deploying.
- `FREE_VIDEOS=40`: you are the platform owner, so the "free trial" runs on *your* keys; 40 lets you process the playlist.
- `PLATFORM_BUDGET_INR=100` stops jobs when the estimated spend reaches your ₹100 Sarvam credit.

Generate the encryption secret once:

```bash
backend/.venv/Scripts/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. (Optional) Start with an empty library

Removes the demo-mode test videos (local data only):

```bash
rm -rf backend/data
```

### 3. Start the app (two terminals, from `kaushaldub/`)

```bash
backend/.venv/Scripts/python backend/scripts/dev.py
```

```bash
cd frontend && npm run dev
```

Open http://localhost:5173 → Trainer → sign in with any name. In **API keys & plan → Which models to use** check that all
three stages say **Sarvam** (the default) and save.

### 4. Test one video by hand

My videos → Choose file → `demo/videos/cpr_nz_red_cross_bEBEOuaQcag.mp4`, title, Skill **Perform CPR**, spoken language
**Detect automatically**, Hindi + Kannada → Process. Review the steps → Approve → listen to the Hindi and Kannada
versions → Publish.

### 5. Process the other demo videos in one go

```bash
backend/.venv/Scripts/python backend/scripts/batch_playlist.py --mode sarvam --only-demo
```

It skips videos already in your list, prints each stage, and writes `demo/batch_results_sarvam.csv` (time and
estimated ₹ per video).

### 6. Grow the library from the playlist

```bash
backend/.venv/Scripts/python backend/scripts/batch_playlist.py --mode sarvam --limit 12
```

Videos not in `demo/videos/` are fetched from YouTube by the server. With the ₹100 credit, about 12 videos fit; the
script stops by itself when credits or budget run out (the job shows **Needs credits**). Do the rest in Mode B.

### 7. Check as a learner

Switch role → Learner → Library: search, filter by domain, watch in Hindi/Kannada, take the quiz, report a problem.

---

## Mode B: free local models on Kaggle

The GPU notebook runs on Kaggle's servers, so it can't see your laptop's SQLite file. Both need the same cloud
database and queue, all free tier:

1. **Supabase**: create a project, run the three files in `supabase/migrations/` in the SQL editor (in order), and turn
   on Google sign-in (docs/SUPABASE_SETUP.md).
2. **Redis**: create a free Upstash Redis and copy its `rediss://…` URL.
3. In `.env` set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `GPU_QUEUE_ENABLED=true`,
   `HF_TOKEN` (accept the AI4Bharat model licences on Hugging Face first) and **`DEV_AUTH=false`** (with Supabase you
   sign in with Google). In `frontend/.env.development.local` set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` and
   remove `VITE_DEV_AUTH`.
4. Start the app as in Mode A step 3 and sign in with Google as Trainer. Keep the plan on **Free trial** (your keys):
   the batch script asks for IndicTrans2 + Indic Parler-TTS per video, which sends the job to the GPU queue, and only
   speech-to-text uses Sarvam if you pass `--asr sarvam`. (The **Free local models** plan never uses any key, so with
   it English videos fall back to Whisper.)
5. On Kaggle: upload `kaushaldub/` (or push it to GitHub) and `ml/kaushaldub_model/` as datasets, open
   `notebooks/worker_gpu.ipynb`, GPU T4 + Internet on, add the secrets it lists (same values as `.env`), Run all.
6. Copy your sign-in token (browser console on the app: `JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.includes("auth-token")))).access_token`)
   and run:

```bash
backend/.venv/Scripts/python backend/scripts/batch_playlist.py --mode local --asr sarvam --token <token>
```

(`--asr indicconformer` for Hindi/Kannada speech, `--asr whisper` for ₹0 English speech.)

---

## Cost comparison for the report

- `demo/batch_results_sarvam.csv` and `demo/batch_results_local.csv`: real time and estimated cost per video.
- `backend/scripts/demo_check.py`: runs the step model alone on `demo/videos/` and prints steps vs COIN ground truth,
  macro-F1 and the estimated Sarvam cost (no API calls).
- `demo/cost_page.html`: calculator + playlist with official Sarvam prices.

## If something fails

| Message | Meaning | Fix |
|---|---|---|
| "Dev tokens are disabled" / sign-in 404 | `DEV_AUTH=false` without Supabase | set `DEV_AUTH=true` (laptop only) |
| Job **Needs credits**, "out of credits (HTTP 402)" | Sarvam balance is ₹0 | top up, or switch the stage to a local model, then **Resume** |
| "rate limited (HTTP 429)" | Gemini/Groq free tier busy | it retries and falls back by itself; the step text uses a template if all fail |
| "free videos are used" | `FREE_VIDEOS` reached | raise `FREE_VIDEOS` in `.env` and restart |
| YouTube download failed | YouTube blocked the server | download the video yourself and upload the file |
