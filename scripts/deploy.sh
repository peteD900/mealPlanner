#!/usr/bin/env bash
#
# deploy.sh — Pull latest master, rebuild, and verify.
# Auto-rolls back if the new container fails to start.
#
# This script is called by the forced-command SSH key from GitHub Actions.
# It should live on the VPS at the repo path and be executable.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="${REPO_DIR}/.last-good-sha"
COMPOSE_SERVICE="mealplanner"
HEALTH_WAIT=15
HEALTH_RETRIES=4

cd "$REPO_DIR"

# Save current commit as rollback point
PREV_SHA=$(git rev-parse HEAD)
echo "$PREV_SHA" > "$STATE_FILE"

echo "==> Current commit: ${PREV_SHA:0:7}"
echo "==> Pulling latest master..."
git fetch origin master
git reset --hard origin/master

NEW_SHA=$(git rev-parse HEAD)
echo "==> New commit: ${NEW_SHA:0:7}"

if [ "$PREV_SHA" = "$NEW_SHA" ]; then
    echo "==> Already up to date. Nothing to deploy."
    exit 0
fi

echo "==> Rebuilding container..."
docker compose up -d --build

# Wait for container to become healthy
echo "==> Waiting for container health check..."
for i in $(seq 1 $HEALTH_RETRIES); do
    sleep "$HEALTH_WAIT"
    STATUS=$(docker compose ps --format json | python3 -c "
import sys, json
for line in sys.stdin:
    data = json.loads(line)
    if data.get('Service') == '${COMPOSE_SERVICE}':
        print(data.get('Health', data.get('State', 'unknown')))
        break
" 2>/dev/null || echo "unknown")

    echo "==> Health check attempt ${i}/${HEALTH_RETRIES}: ${STATUS}"

    if [ "$STATUS" = "healthy" ]; then
        echo "==> Deploy successful!"
        exit 0
    fi

    # If container exited, no point retrying
    STATE=$(docker compose ps --format json | python3 -c "
import sys, json
for line in sys.stdin:
    data = json.loads(line)
    if data.get('Service') == '${COMPOSE_SERVICE}':
        print(data.get('State', 'unknown'))
        break
" 2>/dev/null || echo "unknown")

    if [ "$STATE" = "exited" ] || [ "$STATE" = "dead" ]; then
        echo "==> Container has stopped. Triggering rollback."
        break
    fi
done

# If we get here, the container is not healthy — rollback
echo "==> Deploy FAILED. Rolling back to ${PREV_SHA:0:7}..."
git checkout "$PREV_SHA"
docker compose up -d --build
echo "==> Rollback complete."
exit 1
