# Day 1: Supabase, Google sign-in and keys

Everything here is on free tiers. Time: about 30–40 minutes. After each part, run the checker:

```bash
backend/.venv/Scripts/python backend/scripts/check_setup.py
```

## Part 1: Create the Supabase project (5 min)

1. Go to https://supabase.com → **Start your project** → sign in with GitHub.
2. **New project**: organisation = your personal one (Free plan), name `kaushaldub`, a strong **database password**
   (save it in a password manager; the app doesn't need it), region **South Asia (Mumbai)**. Create.
3. Wait about 2 minutes until the dashboard says the project is ready.

## Part 2: Copy the keys into `.env` (5 min)

Open **Project Settings (gear) → API Keys**:

| Supabase shows | Put it in `.env` as |
|---|---|
| Project URL (Project Settings → Data API, `https://<ref>.supabase.co`) | `SUPABASE_URL` |
| **Publishable** key (`sb_publishable_…`), or legacy **anon** key | `SUPABASE_ANON_KEY` |
| **Secret** key (`sb_secret_…`, click Reveal), or legacy **service_role** key | `SUPABASE_SERVICE_KEY` |

Either the new keys or the legacy ones (tab "Legacy API Keys") work. The secret key bypasses all security rules:
it goes only in `.env` and the Hugging Face Space secrets, never in the frontend or in git.

Then **Project Settings → JWT Keys**. If it shows a **Legacy JWT secret** as the current key, copy it into
`SUPABASE_JWT_SECRET`. If it shows ECC/RSA signing keys, leave `SUPABASE_JWT_SECRET` empty (the checker tells you which).

Also in `.env`:

```
DEV_AUTH=false
KEY_ENCRYPTION_SECRET=<output of the command below>
```

```bash
backend/.venv/Scripts/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep that secret forever: if it changes, the API keys users saved can no longer be decrypted.

## Part 3: Create the tables, security rules and storage (5 min)

In Supabase: **SQL Editor → New query**. Run these three files **in order**: open each in VS Code, copy all, paste,
click **Run**, and check it says "Success. No rows returned".

1. `supabase/migrations/20261107000001_schema.sql` (tables, sign-up trigger, model version 1)
2. `supabase/migrations/20261107000002_rls.sql` (row-level security)
3. `supabase/migrations/20261107000003_storage.sql` (buckets raw-videos, outputs, keyframes)

Check: **Table Editor** lists 17 tables; **Storage** shows 3 private buckets. Run `check_setup.py`: the Supabase lines
should be OK except Google sign-in.

## Part 4: Google sign-in (15 min)

### 4a. Google Cloud (OAuth client)

1. https://console.cloud.google.com → project picker → **New project** `kaushaldub` → select it.
2. **APIs & Services → OAuth consent screen** (called "Google Auth Platform" in the new console) → Get started:
   app name `KaushalDub`, support email = yours, audience **External**, contact email = yours → Create.
3. **Audience → Test users → Add users**: your Gmail and anyone who will test (your professor, classmates). While the
   app is in "Testing" only these accounts can sign in. That's fine for the demo; "Publish app" removes the limit
   (no verification needed for name/email/picture).
4. **Clients → Create client** → type **Web application**, name `KaushalDub web`:
   - Authorised JavaScript origins: `http://localhost:5173` (later also your Vercel URL)
   - Authorised redirect URIs: `https://<ref>.supabase.co/auth/v1/callback` (exact; Supabase shows it in 4b)
   - Create → copy the **Client ID** and **Client secret**.

### 4b. Supabase

1. **Authentication → Sign In / Providers → Google** → enable, paste Client ID and Client secret → Save. The page shows
   the "Callback URL"; it must match the redirect URI in 4a.
2. **Authentication → URL Configuration**: Site URL `http://localhost:5173`; Redirect URLs: add
   `http://localhost:5173/**` (later add `https://<your-app>.vercel.app/**`).

## Part 5: Point the frontend at Supabase (2 min)

Edit `frontend/.env.development.local` so it contains exactly:

```
VITE_API_URL=http://localhost:8000
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<the publishable / anon key>
```

(Remove `VITE_DEV_AUTH=1`.) Only the publishable/anon key goes in the frontend, never the secret key.

## Part 6: Try it

```bash
backend/.venv/Scripts/python backend/scripts/check_setup.py
```

Start the backend and frontend (two terminals, from `kaushaldub/`):

```bash
backend/.venv/Scripts/python backend/scripts/dev.py
```

```bash
cd frontend && npm run dev
```

Open http://localhost:5173 → Trainer → **Continue with Google**. After sign-in you land on My videos, and Supabase
**Table Editor → users** has your row with role `trainer`. http://localhost:8000/health shows `"store": "supabase"`.

## Part 7 (only for the free local models): Upstash Redis (5 min)

Needed when the Kaggle GPU notebook runs jobs. Not needed for Sarvam mode on your laptop.

1. https://console.upstash.com → sign in → **Create database** → Redis, name `kaushaldub`, region Mumbai (ap-south-1),
   Free plan.
2. On the database page copy the **TCP / redis-cli URL** (starts with `rediss://default:…@…upstash.io:6379`) into
   `REDIS_URL`, and set `GPU_QUEUE_ENABLED=true`.
3. With `REDIS_URL` set, jobs wait in Redis, so also start a CPU worker next to the backend:

```bash
cd backend && .venv/Scripts/python -m app.worker --queues cpu
```

## Key checklist

| `.env` key | Where to get it | Needed for |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` | Supabase → Project Settings → API Keys | sign-in, database, files |
| `SUPABASE_JWT_SECRET` | Supabase → JWT Keys (only if legacy) | verifying sign-in |
| `KEY_ENCRYPTION_SECRET` | the command above | saving users' own keys |
| `SARVAM_API_KEY` | dashboard.sarvam.ai → API Keys | Sarvam mode |
| `GEMINI_API_KEY` | aistudio.google.com/apikey | step text + quiz |
| `GROQ_API_KEY` | console.groq.com/keys | backup LLM |
| `HF_TOKEN` | huggingface.co/settings/tokens (read); accept the licences of `ai4bharat/indic-parler-tts`, `ai4bharat/indictrans2-en-indic-dist-200M`, `ai4bharat/indic-conformer-600m-multilingual` | local models |
| `REDIS_URL` | Upstash | GPU worker / deployment |

Good to know: a free Supabase project pauses after a week without activity. Open the dashboard and click "Restore"
if the app suddenly can't connect, and open it the day before your demo.
