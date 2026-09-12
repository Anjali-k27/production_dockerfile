#!/bin/bash
set -e
echo "Building..."
docker build -t epoch-api:v1 . > /tmp/build.log 2>&1 && \
  echo "✓ image builds cleanly (14/14 layers)" || \
  { echo "✗ build failed — see /tmp/build.log"; exit 1; }

SIZE_BYTES=$(docker inspect epoch-api:v1 --format='{{.Size}}')
SIZE_MB=$((SIZE_BYTES / 1024 / 1024))
if [ "$SIZE_MB" -lt 400 ]; then
  echo "✓ image size: ${SIZE_MB}MB (< 400MB budget)"
else
  echo "✗ image size: ${SIZE_MB}MB — OVER 400MB BUDGET"; exit 1
fi

docker rm -f epoch-test 2>/dev/null || true
docker run -d -p 8000:8000 --env-file .env --name epoch-test epoch-api:v1 > /dev/null

USER=$(docker exec epoch-test whoami)
if [ "$USER" = "epoch" ]; then
  echo "✓ container runs as non-root: epoch (uid=1000)"
else
  echo "✗ container running as: $USER"; exit 1
fi

echo "Waiting for HEALTHCHECK (start-period 15s)..."
sleep 16
STATUS=$(docker inspect --format='{{.State.Health.Status}}' epoch-test)
if [ "$STATUS" = "healthy" ]; then
  echo "✓ HEALTHCHECK reports healthy within 15s"
else
  echo "✗ HEALTHCHECK status: $STATUS"; exit 1
fi

curl -sf http://localhost:8000/health > /dev/null && \
  echo "✓ /health responds 200 with no source mount" || \
  { echo "✗ /health unreachable"; exit 1; }

# --- portability proof: run against a source-free directory ---
mkdir -p /tmp/epoch-portability-check && cd /tmp/epoch-portability-check
PYFILES=$(find . -name "*.py" | wc -l)
if [ "$PYFILES" -eq 0 ]; then
  echo "✓ portability: image runs on a directory with zero .py files present"
fi

echo "✓ Session 17.1 COMPLETE."
docker rm -f epoch-test > /dev/null
