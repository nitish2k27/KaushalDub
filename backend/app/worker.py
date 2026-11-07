"""Worker entry point: python -m app.worker [--queues cpu] [--kind cpu|gpu]

The same code runs next to the API on the Hugging Face Space (queue `cpu`) and in the Kaggle/Colab notebook
(queue `gpu`, WORKER_KIND=gpu) so the AI4Bharat models run where there is a GPU."""
import argparse
import os
import platform


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queues", default=os.getenv("WORKER_QUEUES", "cpu"))
    ap.add_argument("--kind", default=None, help="cpu or gpu (sets WORKER_KIND)")
    ap.add_argument("--burst", action="store_true", help="exit when the queues are empty")
    a = ap.parse_args()
    if a.kind:
        os.environ["WORKER_KIND"] = a.kind
    from rq import SimpleWorker, Worker
    from .config import get_settings
    from .queue import redis_conn
    s = get_settings()
    if not s.redis_url:
        raise SystemExit("REDIS_URL is not set")
    if s.mock_providers:
        from .mock_providers import install
        install()
    queues = [q.strip() for q in a.queues.split(",") if q.strip()]
    cls = SimpleWorker if platform.system() == "Windows" else Worker     # no fork() on Windows
    print(f"KaushalDub worker ({s.worker_kind}) listening on {queues}")
    cls(queues, connection=redis_conn()).work(burst=a.burst, with_scheduler=False)


if __name__ == "__main__":
    main()
