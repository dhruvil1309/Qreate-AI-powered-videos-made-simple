FROM python:3.12-slim

# ffmpeg for video, espeak-ng as offline voice, Noto for Hindi captions, raqm for Devanagari shaping
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg espeak-ng fonts-dejavu-core fonts-noto-core libraqm0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV DATA_DIR=/app/data PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
