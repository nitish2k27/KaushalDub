"""Upload the trained step-model bundle to a private Hugging Face model repo (the hosted API downloads it at start).

    backend/.venv/Scripts/python deploy/push_model.py <hf-username>/kaushaldub-model

Needs a Hugging Face token with WRITE access in HF_WRITE_TOKEN (or HF_TOKEN). Uploads ml/kaushaldub_model/
(config.json, model.pt, kd_model.py, kd_metrics.py, results.*)."""
import os
import sys

from huggingface_hub import HfApi

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
repo = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: push_model.py <user>/<repo>")
token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN") or sys.exit("set HF_WRITE_TOKEN (a write token)")
bundle = os.path.join(ROOT, "ml", "kaushaldub_model")
if not os.path.exists(os.path.join(bundle, "model.pt")):
    sys.exit(f"no model.pt in {bundle}")
api = HfApi(token=token)
api.create_repo(repo, repo_type="model", private=True, exist_ok=True)
api.upload_folder(repo_id=repo, repo_type="model", folder_path=bundle, allow_patterns=["*.json", "*.pt", "*.py", "*.md", "testset/*"],
                  commit_message="KaushalDub step model bundle")
print(f"Uploaded. Set STEP_MODEL_REPO={repo} on the Space.")
