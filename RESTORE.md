# Restore and run KaushalDub after a fresh clone

Use this when the project folder was deleted and you are starting again from GitHub.
Your keys and the trained model are **not** on GitHub; they come from your backup folder.

## What must be in your backup folder

| Backup file | Put it back at | What it is |
|---|---|---|
| `.env` | `kaushaldub\.env` | All backend keys (Sarvam, Gemini, Groq, Supabase, `KEY_ENCRYPTION_SECRET`) |
| `.env.development.local` | `kaushaldub\frontend\.env.development.local` | Frontend settings (API URL, Supabase URL, publishable key) |
| `model.pt` (or `kaushaldub_model.zip`) | `kaushaldub\ml\kaushaldub_model\model.pt` | The trained step model (about 4 MB) |
| demo videos (optional) | `kaushaldub\demo\live\` | The 4 live-demo videos |

> Keep the **same** `KEY_ENCRYPTION_SECRET`. User API keys saved in Supabase are encrypted with it; a new secret makes them unreadable.

The video library, users and dubbed outputs live in **Supabase (cloud)**, so they come back automatically.

## Steps (Windows PowerShell)

**1. Clone the code**

```powershell
git clone https://github.com/nitish2k27/KaushalDub.git D:\llm-project\kaushaldub
```

**2. Install the backend** (Python 3.11)

```powershell
cd D:\llm-project\kaushaldub\backend
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
```

**3. Install the frontend** (Node.js 18 or newer)

```powershell
cd D:\llm-project\kaushaldub\frontend
npm install
```

**4. Copy your backup files back** to the places in the table above.
If you only have `kaushaldub_model.zip`, unzip it and copy `model.pt` into `ml\kaushaldub_model\`
(the other files in that folder are already in the repo).

**5. Start the backend** (terminal 1, keep it open)

```powershell
cd D:\llm-project\kaushaldub
backend\.venv\Scripts\python backend\scripts\dev.py
```

Ready when it prints `Uvicorn running on ...:8000`. Check: http://localhost:8000/docs

**6. Start the frontend** (terminal 2, keep it open)

```powershell
cd D:\llm-project\kaushaldub\frontend
npm run dev
```

Open http://localhost:5173, sign in with Google, pick a role.
(The hosted frontend https://kaushal-dub.vercel.app also works while the backend runs on this laptop.)

**7. Optional check**

```powershell
cd D:\llm-project\kaushaldub
backend\.venv\Scripts\python -m pytest backend/tests -q
```

## Common mistakes

| You see | Fix |
|---|---|
| `Could not read package.json` | You ran `npm` outside `frontend\`. `cd` into `kaushaldub\frontend` first. |
| `The module 'backend' could not be loaded` | You are in `D:\llm-project`. `cd D:\llm-project\kaushaldub` first. |
| `can't open file ...app.py` | The script is `backend\scripts\dev.py`, not `app.py`. |
| A `>>>` prompt appears | You ran Python without the script. Type `exit()`, then run the full command. |
| `not a git repository` | Run git commands inside `D:\llm-project\kaushaldub`. |
| Step detection fails / model not found | `ml\kaushaldub_model\model.pt` is missing; copy it from the backup. |
| Sign-in or API calls fail | `.env` or `frontend\.env.development.local` missing or in the wrong folder. |
| Jobs stop with "needs credits" | Sarvam balance is empty; top up at dashboard.sarvam.ai, then press Resume. |

## If you lost the backup

- Rebuild `.env` from `.env.example` using your dashboards: Sarvam (dashboard.sarvam.ai), Gemini (aistudio.google.com),
  Groq (console.groq.com), Supabase (project settings → API). Generate a new encryption secret with:
  `backend\.venv\Scripts\python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  (users will need to re-enter their own API keys).
- Rebuild `frontend\.env.development.local` from `frontend\.env.example`.
- The model: re-download `kaushaldub_model.zip` from the Kaggle training notebook output, or re-run
  `notebooks/kaushaldub_train.ipynb` on Kaggle (T4 GPU).

More detail: [README.md](README.md) · [docs/SETUP.md](docs/SETUP.md) · [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md) · [deployedinfor.txt](deployedinfor.txt)
