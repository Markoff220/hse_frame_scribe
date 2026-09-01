# VideoNotes: видео -> .md нейроконспект (web-сервис)
# CPU-сборка (по умолчанию):  docker compose build
# GPU-сборка (ПК с NVIDIA):   PYTORCH_INDEX=https://download.pytorch.org/whl/cu124 docker compose build
FROM python:3.11-slim

ARG PYTORCH_INDEX=https://pypi.org/simple

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url ${PYTORCH_INDEX} torch==2.11.0 torchaudio==2.11.0 \
    && pip install --no-cache-dir -r requirements.txt

COPY app/pipeline/ ./pipeline/
COPY app/web.py ./web.py
COPY app/web/ ./web/

EXPOSE 8090
CMD ["python", "web.py", "8090"]