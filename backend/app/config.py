"""All settings come from environment variables (see ../.env.example). Nothing secret has a default."""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO = Path(__file__).resolve().parents[2]          # kaushaldub/
ML_DIR = REPO / "ml"


ENV_FILES = () if os.getenv("KD_IGNORE_ENV_FILE") else (str(REPO / ".env"), ".env")   # tests never read .env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, extra="ignore", env_ignore_empty=True)

    # --- Supabase (production). Leave SUPABASE_URL empty to run locally on SQLite + disk.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""          # legacy HS256 projects; empty = verify with the project's JWKS

    # --- platform provider keys (used only for free-trial jobs)
    sarvam_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    hf_token: str = ""

    # --- queue
    redis_url: str = ""                    # empty = run jobs in a background thread inside the API (dev only)
    gpu_queue_enabled: bool = False        # True when the Kaggle/Colab GPU worker is in use
    worker_kind: str = "cpu"               # cpu | gpu (set by the worker process)
    allow_local_on_cpu: bool = False       # let a CPU worker run Indic Parler-TTS / IndicConformer (very slow)

    # --- security
    key_encryption_secret: str = ""        # Fernet key for user API keys: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    file_url_secret: str = ""              # HMAC secret for local file URLs (dev storage only)
    dev_auth: bool = False                 # NEVER in production: enables /dev/login with locally signed tokens
    dev_jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"
    admin_emails: str = ""                 # comma separated; these users see the budget / low-balance panel
    cors_origins: str = "http://localhost:5173"

    # --- plans and budget
    free_videos: int = 5
    platform_budget_inr: float = 500.0     # monthly cap for jobs on the platform's keys
    low_balance_warn_ratio: float = 0.8
    retrain_threshold: int = 20

    # --- local paths
    data_dir: str = str(REPO / "backend" / "data")
    model_bundle_dir: str = str(ML_DIR / "kaushaldub_model")
    step_model_repo: str = ""              # optional HF repo id to download the bundle from at startup
    step_model: str = "bundle"             # bundle | mock (mock = fake recogniser for demos/tests)
    mock_providers: bool = False           # demo only: fake ASR/MT/TTS/LLM (no keys, no torch)
    public_api_url: str = "http://localhost:8000"

    # --- voices (check speaker names against Sarvam's docs for the model you use)
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_speaker_male: str = "shubh"
    sarvam_speaker_female: str = "ritu"

    retry_delays: str = "5,20,60"          # seconds between retries on HTTP 429

    @property
    def use_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def admins(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def delays(self) -> list[float]:
        return [float(x) for x in self.retry_delays.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings():
    get_settings.cache_clear()
