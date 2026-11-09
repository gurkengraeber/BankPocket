# ---------- Oberfläche bauen ----------
FROM node:22-alpine AS oberflaeche
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- Server ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BANKPOCKET_DATA_DIR=/data \
    BANKPOCKET_FRONTEND_DIR=/app/frontend/dist \
    TZ=Europe/Berlin
WORKDIR /app
RUN useradd --create-home --uid 1000 bankpocket && mkdir -p /data && chown bankpocket /data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bankpocket/ bankpocket/
COPY --from=oberflaeche /fe/dist frontend/dist
COPY docker-entrypoint.sh /usr/local/bin/
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
# Startet als root, korrigiert die Rechte an /data und läuft dann als „bankpocket“ weiter
ENTRYPOINT ["docker-entrypoint.sh"]
# Genau ein Worker: Abrufe und Zeitplan laufen im Prozess
CMD ["uvicorn", "bankpocket.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
