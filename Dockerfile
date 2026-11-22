FROM python:3.11-slim
# iputils-ping: PingSensor calls OS ping via subprocess
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PYTHONUNBUFFERED=1 DATABASE_URL=sqlite:////data/netmon.db
# 1 worker: MonitorScheduler is an in-process singleton; threads serve SocketIO (simple-websocket)
CMD gunicorn -w 1 --threads 64 -b 0.0.0.0:${PORT:-8000} run:app
