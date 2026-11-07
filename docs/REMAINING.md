# KaushalDub: what's done and what's left

## Done

- [x] Backend (FastAPI), worker jobs, plans/keys/budget, tickets, annotations, correction memory, retrain (45 tests pass)
- [x] Frontend: every mockup screen, light/dark, phone width
- [x] Supabase: project, 17 tables, row-level security, 3 buckets, Google sign-in (`check_setup.py` says "All good")
- [x] Keys: Sarvam, Gemini, Groq, HF, encryption secret
- [x] Trained step model installed (`ml/kaushaldub_model/`), runs on CPU
- [x] Sarvam auto-detects the spoken language; Windows fix for Sarvam speech-to-text
- [x] Gemini fallback (next model when the newest is overloaded) and repair of small LLM slips
- [x] Playlist: 30 COIN test videos, 5 per skill (`demo/PLAYLIST.md`), 4 demo videos downloaded

## Library (done 7 Nov 2026)

- [x] 30 videos dubbed with Sarvam (5 per skill: CPR, screen protector, car polishing, pizza, rice cooker, omelette),
      all published and copied into Supabase. Estimated Sarvam spend ₹121.98 for the 30 (₹127.33 including failed
      attempts): about ₹4 and 4–5 minutes per video.
- [x] Your Google account is the owner (trainer) of all 30.
- [x] Live-demo videos (not in the library): `demo/live/` with `DEMO_SCRIPT.md`.

## Next, in order

1. [ ] **Test the whole flow on Supabase** (use a second Google account, or switch roles):
       - [ ] Trainer: upload one new video (`demo/videos/…`), review, approve, publish
       - [ ] Learner: search, watch in Hindi and Kannada, quiz, report a problem
       - [ ] Trainer: Learner reports → fix text, re-make voice, close; learner sees the reply
       - [ ] Annotator: label a low-confidence clip (e.g. Samsung screen protector, 1 step) → submit
       - [ ] Trainer: approve corrections → Model learning card counts them
       - [ ] API keys & plan: save and test a key; check that the free-trial counter works
2. [ ] **Put the code on GitHub** (private repo). `.env`, videos, `model.pt` and local data are git-ignored.
3. [ ] **Model bundle on Hugging Face** (private model repo), so the hosted API can download it (`STEP_MODEL_REPO`).
4. [ ] **Host the backend** on a Hugging Face Docker Space (`bash deploy/push_space.sh <user>/<space>`) with the
       `.env` values as Space secrets (`DEV_AUTH=false`, `MOCK_PROVIDERS=false`, `CORS_ORIGINS=<vercel url>`).
       Without `REDIS_URL` jobs run inside the Space; that's fine for the demo.
5. [ ] **Host the frontend** on Vercel (root `frontend`, env `VITE_API_URL`, `VITE_SUPABASE_URL`,
       `VITE_SUPABASE_ANON_KEY`).
6. [ ] **Connect the hosted URLs**: add the Vercel URL to Supabase → URL configuration (Site URL + redirect),
       Google OAuth client (JavaScript origin), and the Space's `CORS_ORIGINS`.
7. [ ] **Smoke test the hosted app** with one video; publish the cost page with the real numbers from
       `demo/batch_results_sarvam.csv`.

## Optional

- [ ] Local models on Kaggle for the report's ₹0 comparison (needs Upstash Redis + `notebooks/worker_gpu.ipynb`)
- [ ] Export the COIN test set next to the bundle so "Retrain" can activate a better model
- [ ] Publish the Google OAuth app (removes the test-user limit) before sharing the hosted link widely
