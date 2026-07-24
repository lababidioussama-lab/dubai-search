FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_PATH=/usr/bin/chromium
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY webapp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install chromium

COPY scripts/ ./scripts/
COPY webapp/ ./webapp/

EXPOSE 5000
CMD ["gunicorn", "--chdir", "webapp", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "0", "app:app"]
