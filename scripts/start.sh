#!/usr/bin/env bash
set -euo pipefail
GREEN='\033[0;32m'; NC='\033[0m'
log() { echo -e "${GREEN}[start]${NC} $1"; }

set -a; source .env; set +a

log "Starting Docker services..."
docker compose -f config/docker-compose.yml up -d

log "Waiting for services..."
until docker exec forge-postgres pg_isready -U "${POSTGRES_USER:-backbone}" &>/dev/null; do sleep 1; done
log "✓ PostgreSQL"
until docker exec forge-redis redis-cli -a "${REDIS_PASSWORD}" ping &>/dev/null 2>&1; do sleep 1; done
log "✓ Redis"
until curl -sf http://localhost:6333/readyz &>/dev/null; do sleep 2; done
log "✓ Qdrant"

log "Initializing Qdrant collections..."
python3 -c "
import asyncio
from agents.python.infra.memory_keeper import ensure_collections
asyncio.run(ensure_collections())
print('Collections ready')
"

log "Starting browser layer..."
cd agents/browser && npm start &
cd ../..
sleep 3
curl -sf http://localhost:${BROWSER_SERVER_PORT:-3100}/health &>/dev/null && log "✓ Browser layer"

log ""
log "All services running:"
log "  n8n:          http://localhost:5678"
log "  Temporal UI:  http://localhost:8080"
log "  Qdrant:       http://localhost:6333"
log "  Browser:      http://localhost:${BROWSER_SERVER_PORT:-3100}"
log ""
log "Test: python scripts/test_run.py --dry-run"
