#!/bin/bash
set -euo pipefail
export AWS_DEFAULT_REGION='__REGION__'
until systemctl is-active --quiet docker; do sleep 5; done
mkdir -p /srv/outreach/release /srv/outreach/data /srv/outreach/models /srv/outreach/backups
aws s3 cp 's3://__BUCKET__/__KEY__' /srv/outreach/release.tar.gz
echo '__SHA__  /srv/outreach/release.tar.gz' | sha256sum --check
tar -xzf /srv/outreach/release.tar.gz -C /srv/outreach/release
if [ ! -f /srv/outreach/data/outreach.sqlite ]; then
  aws s3 cp 's3://__BUCKET__/workspace.tar.gz' /srv/outreach/workspace.tar.gz
  tar -xzf /srv/outreach/workspace.tar.gz -C /srv/outreach/data
  chmod 600 /srv/outreach/data/*
  rm /srv/outreach/workspace.tar.gz
fi
chown -R 10001:10001 /srv/outreach/data
chmod 700 /srv/outreach/data
cd /srv/outreach/release
docker build --build-arg INSTALL_AWS_SECRETS=true -t outreach:__SHA__ .
docker network inspect outreach >/dev/null 2>&1 || docker network create outreach
docker pull '__OLLAMA_IMAGE__'
docker run -d --name outreach-ollama --restart unless-stopped --network outreach -v /srv/outreach/models:/root/.ollama '__OLLAMA_IMAGE__'
docker exec outreach-ollama ollama pull qwen3:4b
docker exec outreach-ollama ollama pull nomic-embed-text
docker run -d --name outreach-app --restart unless-stopped --network outreach \
  -p 127.0.0.1:8765:8765 -v /srv/outreach/data:/app/.local \
  -e OUTREACH_DEMO=false -e OUTREACH_REMOTE=false \
  -e AWS_DEFAULT_REGION='__REGION__' -e AWS_CREDENTIAL_SECRET_ID='__SECRET__' \
  -e OLLAMA_URL=http://outreach-ollama:11434 -e OLLAMA_MODEL=qwen3:4b \
  -e OUTREACH_AUTO_RESEARCH=false -e OUTREACH_AUTO_ROLE_EXTRACTION=false \
  -e TSENTA_POLL_ENABLED=false -e TSENTA_CALLBACK_VERIFIED=false \
  -e TSENTA_OAUTH_CALLBACK=http://127.0.0.1:8765/api/tsenta/callback \
  -e LANGFUSE_ENABLED=false -e TRACE_RAW_CONTENT=false -e LANGSMITH_TRACING=false \
  outreach:__SHA__
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8765/ready; then break; fi
  sleep 5
done
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:8765/ready
docker inspect --format '{{.Image}}' outreach-app
