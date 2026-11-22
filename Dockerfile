FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
COPY netmon/web/static/css/netmon.css /build/netmon/web/static/css/netmon.css
RUN npm run build

FROM python:3.11-slim
# iputils-ping: PingSensor calls OS ping; DejaVu supports Vietnamese PDF reports.
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist
ENV PYTHONUNBUFFERED=1 DATABASE_URL=sqlite:////data/netmon.db
# 1 worker: MonitorScheduler is an in-process singleton; threads serve SocketIO (simple-websocket)
CMD gunicorn -w 1 --threads 64 -b 0.0.0.0:${PORT:-8000} run:app
