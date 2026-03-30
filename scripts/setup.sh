#!/usr/bin/env bash
# setup.sh — Bootstrap Forge (30 agents)
set -euo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log()  { echo -e "${GREEN}[setup]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "${RED}[error]${NC} $1"; exit 1; }

log "Forge — 30-agent autonomous hackathon swarm"

command -v docker &>/dev/null   || err "Docker not installed"
command -v python3 &>/dev/null  || err "Python 3.11+ required"
command -v node &>/dev/null     || err "Node.js 20+ required"
command -v ffmpeg &>/dev/null   || warn "ffmpeg not found — run: sudo apt install ffmpeg"

PY_VER=$(python3 -c "import sys; print(sys.version_info.minor)")
[ "$PY_VER" -ge 11 ] || err "Python 3.11+ required (found 3.$PY_VER)"

[ ! -f .env ] && cp .env.example .env && warn ".env created — fill in ELECTRONHUB_API_KEY + BROWSERBASE_API_KEY"

log "Creating infra directories..."
mkdir -p infra/postgres/data infra/redis/data infra/qdrant/data infra/temporal infra/n8n/data

cat > infra/qdrant/config.yaml << 'EOF'
service:
  host: 0.0.0.0
  http_port: 6333
  grpc_port: 6334
log_level: INFO
EOF

cat > infra/temporal/dynamicconfig.yaml << 'EOF'
system.forceSearchAttributesCacheRefreshOnRead:
  - value: true
    constraints: {}
EOF

cat > infra/postgres/init.sql << 'EOF'
CREATE DATABASE n8n;
GRANT ALL PRIVILEGES ON DATABASE n8n TO backbone;
\c backbone;

CREATE TABLE IF NOT EXISTS hackathons (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  platform TEXT,
  theme TEXT,
  deadline TIMESTAMPTZ,
  score INTEGER,
  status TEXT DEFAULT 'discovered',
  concept_json JSONB,
  project_url TEXT,
  submission_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id),
  agent_id TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  input_json JSONB,
  output_json JSONB,
  error TEXT,
  iterations INTEGER DEFAULT 0,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ux_audit_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id),
  preview_url TEXT,
  overall_score FLOAT,
  approved BOOLEAN,
  report_json JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
EOF

log "Installing Python dependencies..."
if command -v uv &>/dev/null; then
  uv pip install -e ".[dev]"
else
  pip3 install -e ".[dev]" --quiet
fi

log "Installing Playwright..."
python3 -m playwright install chromium --with-deps

log "Installing browser layer..."
cd agents/browser && npm install && cd ../..

log "Pulling Docker images..."
docker compose -f config/docker-compose.yml pull

if ! command -v daytona &>/dev/null; then
  log "Installing Daytona..."
  curl -sf -L https://download.daytona.io/daytona/install.sh | sudo bash
fi

log "Installing Lighthouse CLI..."
npm install -g lighthouse 2>/dev/null || warn "Lighthouse install failed — performance audit will use fallback"

log ""
log "✓ Setup complete!"
log ""
log "Next: edit .env, then run: bash scripts/start.sh"
