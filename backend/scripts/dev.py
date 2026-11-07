"""Local demo server without any cloud service: SQLite + disk storage, in-process jobs, dev sign-in, mock step
model and mock providers. Values from ../.env (if present) win over these demo defaults, so once you fill .env
the same command uses your real keys.

    python backend/scripts/dev.py            (then run the frontend with VITE_DEV_AUTH=1)"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

data = BACKEND / "data"
data.mkdir(exist_ok=True)
keyfile = data / "dev_fernet.key"            # local dev only; production uses KEY_ENCRYPTION_SECRET from the env
if not keyfile.exists():
    from cryptography.fernet import Fernet
    keyfile.write_text(Fernet.generate_key().decode())

envfile = BACKEND.parent / ".env"
if envfile.exists():                          # real settings first ...
    for line in envfile.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# ... then demo defaults for whatever is still unset
for k, v in {"DEV_AUTH": "true", "STEP_MODEL": "mock", "MOCK_PROVIDERS": "true", "SUPABASE_URL": "", "REDIS_URL": "",
             "KEY_ENCRYPTION_SECRET": keyfile.read_text().strip(), "CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
             "PUBLIC_API_URL": "http://localhost:8000", "SARVAM_API_KEY": "demo-not-a-real-key"}.items():
    os.environ.setdefault(k, v)

import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), reload=False)
