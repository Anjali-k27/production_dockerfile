#!/bin/sh
# healthcheck.sh — the orchestrator's only signal that this container is ready.
# Exit 0 = healthy. Any other exit = Docker marks the container unhealthy.

curl -f -s http://localhost:8000/health > /dev/null || exit 1
