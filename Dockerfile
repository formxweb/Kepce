FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

RUN useradd --create-home kepce && mkdir -p /tmp/kepce-data && chown kepce /tmp/kepce-data
USER kepce

ENV DATA_DIR=/tmp/kepce-data \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# Tek işçi: liste durumu bellekte tutuluyor, birden fazla işçi birbirini görmez.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
