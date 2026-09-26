# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

ARG ORT_FLAVOR=cpu
ENV ORT_FLAVOR=${ORT_FLAVOR} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 \
      libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$ORT_FLAVOR" = "gpu" ]; then \
         pip install --no-cache-dir onnxruntime-gpu==1.19.2 ; \
       else \
         pip install --no-cache-dir onnxruntime==1.19.2 ; \
       fi

FROM base AS dev
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
CMD ["python", "-m", "kiosk.main"]

FROM base AS runtime
COPY . .
RUN mkdir -p /models /data/queue
CMD ["python", "-m", "kiosk.main"]
