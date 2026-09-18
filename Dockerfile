FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend
WORKDIR /app/backend

EXPOSE 8000
# Startup applies Alembic migrations (AUTO_MIGRATE) and creates the first
# SUPER_ADMIN if missing. Nothing is ever wiped - the old image re-seeded
# (dropped every table) on every start.
# One worker on purpose: the WebSocket hub and per-team locks live in-process.
# X-Forwarded-For is trusted only from 127.0.0.1 by default. If your HTTPS proxy
# runs elsewhere, set FORWARDED_ALLOW_IPS to *its* address - never "*", or
# clients could spoof their IP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
