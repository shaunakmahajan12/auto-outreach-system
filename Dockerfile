FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CREDENTIAL_STORE=deployment BIND_HOST=0.0.0.0
WORKDIR /app
COPY requirements.lock.txt requirements-aws.txt ./
ARG INSTALL_AWS_SECRETS=false
RUN pip install --no-cache-dir -r requirements.lock.txt && if [ "$INSTALL_AWS_SECRETS" = "true" ]; then pip install --no-cache-dir -r requirements-aws.txt; fi
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY --from=frontend /ui/dist ./frontend/dist/
RUN useradd --uid 10001 --create-home outreach && mkdir .local && chown outreach:outreach .local
USER outreach
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"
CMD ["python", "scripts/run.py"]
