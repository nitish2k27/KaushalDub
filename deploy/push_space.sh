#!/usr/bin/env bash
# Assemble backend/ + ml/ + the Space Dockerfile into a temp folder and push it to your Hugging Face Space.
#   bash deploy/push_space.sh <hf-username>/<space-name>
# Needs: git, and `huggingface-cli login` (or a token with write access) done beforehand.
set -euo pipefail
SPACE="${1:?usage: deploy/push_space.sh <user>/<space>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
git clone "https://huggingface.co/spaces/$SPACE" "$TMP/space"
cd "$TMP/space"
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
mkdir -p deploy/hf_space
cp "$ROOT/deploy/hf_space/Dockerfile" Dockerfile
cp "$ROOT/deploy/hf_space/README.md" README.md
cp "$ROOT/deploy/hf_space/start.sh" deploy/hf_space/start.sh
rsync -a --exclude .venv --exclude data --exclude __pycache__ --exclude .pytest_cache "$ROOT/backend" .
rsync -a --exclude __pycache__ --exclude '*.pt' "$ROOT/ml" .
git add -A
git commit -m "Deploy KaushalDub API" || echo "nothing to commit"
git push
echo "Pushed. Build logs: https://huggingface.co/spaces/$SPACE?logs=build"
