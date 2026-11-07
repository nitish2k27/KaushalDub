"""Deploy the backend to a Hugging Face Docker Space (works on Windows; no rsync or git needed).

    backend/.venv/Scripts/python deploy/push_space.py <hf-username>/kaushaldub-api [--secrets]

Creates the Space if needed (Docker SDK, public so the browser can call the API; keys stay in Space secrets),
uploads Dockerfile + README + backend/ + ml/ code (no .venv, data, videos or model weights), and with --secrets copies
the needed values from ../.env into the Space's secrets (values are never printed).
Needs a Hugging Face token with WRITE access in HF_WRITE_TOKEN (or HF_TOKEN)."""
import os
import shutil
import sys
import tempfile

from huggingface_hub import HfApi

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
space = args[0] if args else sys.exit("usage: push_space.py <user>/<space> [--secrets]")
token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN") or sys.exit("set HF_WRITE_TOKEN (a write token)")
api = HfApi(token=token)
api.create_repo(space, repo_type="space", space_sdk="docker", private=False, exist_ok=True)

SKIP = shutil.ignore_patterns(".venv", "data", "data_live", "__pycache__", ".pytest_cache", "*.log", "*.pt", "*.mp4",
                              "*.wav", ".env", "*.sqlite", "testset")
with tempfile.TemporaryDirectory() as tmp:
    shutil.copy(os.path.join(ROOT, "deploy", "hf_space", "Dockerfile"), os.path.join(tmp, "Dockerfile"))
    shutil.copy(os.path.join(ROOT, "deploy", "hf_space", "README.md"), os.path.join(tmp, "README.md"))
    os.makedirs(os.path.join(tmp, "deploy", "hf_space"))
    shutil.copy(os.path.join(ROOT, "deploy", "hf_space", "start.sh"), os.path.join(tmp, "deploy", "hf_space", "start.sh"))
    shutil.copytree(os.path.join(ROOT, "backend"), os.path.join(tmp, "backend"), ignore=SKIP)
    shutil.copytree(os.path.join(ROOT, "ml"), os.path.join(tmp, "ml"), ignore=SKIP)
    # start.sh must keep Unix line endings or the container cannot run it
    p = os.path.join(tmp, "deploy", "hf_space", "start.sh")
    open(p, "wb").write(open(p, "rb").read().replace(b"\r\n", b"\n"))
    api.upload_folder(repo_id=space, repo_type="space", folder_path=tmp, commit_message="Deploy KaushalDub API",
                      delete_patterns=["backend/**", "ml/**"])
print(f"Code uploaded to https://huggingface.co/spaces/{space}")

if "--secrets" in sys.argv:
    env = {}
    for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip():
                env[k.strip()] = v.strip().strip('"').strip("'")
    SECRET = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_JWT_SECRET", "SARVAM_API_KEY",
              "GEMINI_API_KEY", "GROQ_API_KEY", "HF_TOKEN", "REDIS_URL", "KEY_ENCRYPTION_SECRET"]
    VARS = ["FREE_VIDEOS", "PLATFORM_BUDGET_INR", "RETRAIN_THRESHOLD", "ADMIN_EMAILS", "STEP_MODEL_REPO",
            "CORS_ORIGINS", "CORS_ORIGIN_REGEX", "GPU_QUEUE_ENABLED"]
    for k in SECRET:
        if env.get(k):
            api.add_space_secret(space, k, env[k])
    for k in VARS:
        if env.get(k):
            api.add_space_variable(space, k, env[k])
    for k, v in {"DEV_AUTH": "false", "MOCK_PROVIDERS": "false", "STEP_MODEL": "bundle"}.items():
        api.add_space_variable(space, k, v)
    print("Secrets set:", ", ".join(k for k in SECRET if env.get(k)))
    print("Variables set:", ", ".join([k for k in VARS if env.get(k)] + ["DEV_AUTH", "MOCK_PROVIDERS", "STEP_MODEL"]))
    missing = [k for k in ("STEP_MODEL_REPO", "CORS_ORIGINS") if not env.get(k)]
    if missing:
        print("Still to set in the Space settings:", ", ".join(missing))
print(f"Build logs: https://huggingface.co/spaces/{space}?logs=build  ·  API: https://{space.replace('/', '-').lower()}.hf.space/health")
