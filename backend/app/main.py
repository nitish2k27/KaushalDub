"""KaushalDub API. Long work happens in the worker; the API validates, enqueues and reports progress."""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .crypto import redact
from .routers import annotations, me, system, tickets, videos

log = logging.getLogger("kaushaldub")


def create_app() -> FastAPI:
    s = get_settings()

    @asynccontextmanager
    async def lifespan(app):
        startup(s)
        yield

    app = FastAPI(title="KaushalDub API", version="1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                       allow_origin_regex=os.getenv("CORS_ORIGIN_REGEX") or None,
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # never echo request bodies (they may carry API keys); redact anything key-like in the message
        log.error("unhandled error on %s %s: %s", request.method, request.url.path, redact(exc)[:300])
        return JSONResponse(status_code=500, content={"detail": "Server error: " + redact(exc)[:200]})

    for r in (system.router, me.router, videos.router, tickets.router, annotations.router):
        app.include_router(r)

    return app


def startup(s):
    if s.mock_providers:
        from .mock_providers import install
        install()
        log.warning("MOCK_PROVIDERS is on: transcripts, translations and voices are fake (demo mode).")
    if s.step_model_repo and not os.path.exists(os.path.join(s.model_bundle_dir, "model.pt")):
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(s.step_model_repo, local_dir=s.model_bundle_dir, token=s.hf_token or None)
        except Exception as e:
            log.error("could not download the step model bundle: %s", redact(e)[:200])
    if s.dev_auth and s.use_supabase:
        log.warning("DEV_AUTH is on while Supabase is configured. Turn it off in production.")


app = create_app()
