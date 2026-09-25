# ── 1. build the React + TypeScript UI ──────────────────────
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── 2. Python app (web API, notifier, auto-trader) ─────────
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=ui /ui/dist ./frontend/dist
ENV PYTHONUNBUFFERED=1 TZ=Asia/Kolkata
EXPOSE 8000
CMD ["python", "-m", "server.app"]
