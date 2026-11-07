# KaushalDub API + CPU worker for a Hugging Face Docker Space (free CPU basic: 2 vCPU, 16 GB RAM).
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git libsndfile1 && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
WORKDIR /app

COPY --chown=user backend/requirements.txt backend/requirements-ml.txt backend/
RUN pip install --no-cache-dir -r backend/requirements-ml.txt

COPY --chown=user backend backend
COPY --chown=user ml ml
COPY --chown=user deploy/hf_space/start.sh start.sh
RUN chmod +x start.sh && mkdir -p /app/ml/kaushaldub_model && chown -R user /app

USER user
ENV HOME=/home/user PYTHONUNBUFFERED=1 PORT=7860 DATA_DIR=/tmp/kd_data WORKER_KIND=cpu HF_HOME=/tmp/hf
EXPOSE 7860
CMD ["./start.sh"]
