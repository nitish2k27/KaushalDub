# Hosting KaushalDub (free tiers)

```
Vercel (frontend)  ──REST──>  Hugging Face Space (FastAPI + worker)  ──>  Supabase (database, login, files)
                                         │
                                         └──>  Sarvam / Gemini / Groq APIs,  step model from a private HF repo
```

You need: the GitHub repo, a Hugging Face account, a Vercel account (sign in with GitHub), and your Supabase project.
About 30–45 minutes. All commands run from the `kaushaldub` folder.

## 1. Hugging Face write token

huggingface.co → Settings → Access Tokens → **Create new token** → type **Write** → copy it. Then, in the terminal
(this sets it for the current terminal only; it is not saved in any file):

```bash
export HF_WRITE_TOKEN=<paste the write token>
```

## 2. Upload the step model (private)

```bash
backend/.venv/Scripts/python deploy/push_model.py <hf-username>/kaushaldub-model
```

Add this line to `.env`:

```
STEP_MODEL_REPO=<hf-username>/kaushaldub-model
```

## 3. Deploy the backend to a Hugging Face Space

```bash
backend/.venv/Scripts/python deploy/push_space.py <hf-username>/kaushaldub-api --secrets
```

This creates a Docker Space, uploads `backend/` and `ml/`, and copies your keys from `.env` into the Space's
**secrets** (never into the code). The Space is public so the browser can reach the API; the keys stay hidden.

The first build takes about 10–15 minutes (it installs PyTorch). Watch it at
`https://huggingface.co/spaces/<hf-username>/kaushaldub-api?logs=build`. When it says *Running*, open:

```
https://<hf-username>-kaushaldub-api.hf.space/health
```

It should show `"store": "supabase"` and `"dev_auth": false`.

## 4. Deploy the frontend to Vercel

1. vercel.com → **Add New → Project** → import the `kaushaldub` GitHub repo.
2. **Root Directory**: `frontend` (framework is detected as Vite).
3. **Environment Variables**:

   | Name | Value |
   |---|---|
   | `VITE_API_URL` | `https://<hf-username>-kaushaldub-api.hf.space` |
   | `VITE_SUPABASE_URL` | your Supabase project URL |
   | `VITE_SUPABASE_ANON_KEY` | the Supabase publishable (anon) key |

   Do not add `VITE_DEV_AUTH`.
4. **Deploy**. You get a URL like `https://kaushaldub.vercel.app`.

## 5. Connect the URLs

- **Hugging Face Space** → Settings → Variables: set `CORS_ORIGINS` to your Vercel URL, for example
  `https://kaushaldub.vercel.app` (optionally `CORS_ORIGIN_REGEX=https://kaushaldub-.*\.vercel\.app` for previews).
  The Space restarts by itself.
- **Supabase** → Authentication → URL Configuration: Site URL = your Vercel URL; add `https://<your-app>.vercel.app/**`
  to Redirect URLs.
- **Google Cloud** → your OAuth client → Authorised JavaScript origins: add the Vercel URL. (The redirect URI stays the
  Supabase callback.)

## 6. Test

Open the Vercel URL → Trainer → Continue with Google → the library shows your 30 videos. Upload one short video from
`demo/live/` and follow it through to Publish.

## Updating later

- Frontend: `git push` → Vercel redeploys automatically.
- Backend: run step 3 again (add `--secrets` only if keys changed).

## Good to know

- A free Space sleeps after about 48 hours without visits; the first request then takes a minute to wake it.
- A free Supabase project pauses after a week without use: open the dashboard and click Restore.
- Google sign-in only works for the test users you added, until you publish the OAuth app.
- Videos are processed on the Space's CPU (about 5 minutes each). For the free AI4Bharat models, run
  `notebooks/worker_gpu.ipynb` on Kaggle and set `REDIS_URL` and `GPU_QUEUE_ENABLED=true`
  (see [SETUP.md](SETUP.md)).
