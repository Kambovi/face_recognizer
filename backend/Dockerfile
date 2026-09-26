# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

# ORT_FLAVOR selects which onnxruntime wheel is installed. This is the ONE
# build-time switch between the CPU and GPU images — no other code or config
# changes between the two. See README "Upgrading to GPU".
ARG ORT_FLAVOR=cpu
ENV ORT_FLAVOR=${ORT_FLAVOR} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# libgl1/libglib2.0-0 are needed by opencv-python-headless's ONNX/image codecs
# at import time even in headless mode; libpq5 for psycopg2.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 \
      libglib2.0-0 \
      libpq5 \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$ORT_FLAVOR" = "gpu" ]; then \
         pip install --no-cache-dir onnxruntime-gpu==1.19.2 ; \
       else \
         pip install --no-cache-dir onnxruntime==1.19.2 ; \
       fi

# Dev image target used by `make test` / CI keeps pytest etc. installed.
FROM base AS dev
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Slim runtime image is the default `docker compose up` target.
FROM base AS runtime
COPY . .
RUN mkdir -p /data/media /models
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
