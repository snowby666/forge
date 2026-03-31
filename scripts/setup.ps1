# setup.ps1 -- Bootstrap Forge on Windows (PowerShell)
# Run from the forge directory:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\setup.ps1
#
# Requires: Docker Desktop, Python 3.11+, Node.js 20+

param(
    [switch]$DryRun,
    [switch]$SkipDocker
)

$ErrorActionPreference = "Stop"

function Write-Green($msg) { Write-Host "[setup] $msg" -ForegroundColor Green }
function Write-Yellow($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Cyan($msg)  { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Red($msg)   { Write-Host "[error] $msg" -ForegroundColor Red }

Write-Green "Forge -- 30-agent autonomous hackathon swarm"
Write-Green "Windows (PowerShell) setup"
Write-Host ""

# --- Check if running in WSL (shouldn't use this script then) ----------------
if ($env:WSLENV -ne $null) {
    Write-Yellow "Detected WSL environment. Use setup.sh instead: bash scripts/setup.sh"
    exit 0
}

# --- Python ------------------------------------------------------------------
Write-Cyan "Checking Python 3.11+..."
$PYTHON_CMD = $null

foreach ($cmd in @("python", "python3", "python3.12", "python3.11")) {
    try {
        $ver = & $cmd -c "import sys; v=sys.version_info; print(f'{v.major}.{v.minor}')" 2>$null
        if ($ver) {
            $parts = $ver.Split(".")
            if ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 11) {
                $PYTHON_CMD = $cmd
                Write-Green "Python: $($& $cmd --version)"
                break
            }
        }
    } catch {}
}

if (-not $PYTHON_CMD) {
    Write-Red @"
Python 3.11+ not found.

Install from: https://www.python.org/downloads/windows/
  - Check 'Add Python to PATH' during installation
  - Then restart this terminal and run setup.ps1 again

Or via winget:
  winget install Python.Python.3.12
"@
    exit 1
}

# --- Docker ------------------------------------------------------------------
Write-Cyan "Checking Docker..."
try {
    $dockerVer = docker --version 2>$null
    Write-Green "Docker: $dockerVer"
} catch {
    Write-Red @"
Docker not installed or not running.

Install Docker Desktop: https://www.docker.com/products/docker-desktop/
  - Enable WSL2 backend in Docker Desktop settings
  - Make sure Docker Desktop is running before continuing
"@
    exit 1
}

# --- Node.js -----------------------------------------------------------------
Write-Cyan "Checking Node.js..."
try {
    $nodeVer = node --version 2>$null
    Write-Green "Node.js: $nodeVer"
} catch {
    Write-Red @"
Node.js not installed.

Install LTS from: https://nodejs.org/
Or via winget:
  winget install OpenJS.NodeJS.LTS
"@
    exit 1
}

# --- ffmpeg (optional) -------------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Yellow @"
ffmpeg not found (optional -- only needed for demo video generation).
Install via winget:  winget install Gyan.FFmpeg
Or download from:    https://ffmpeg.org/download.html#build-windows
"@
}

# --- .env and forge.secrets --------------------------------------------------
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Yellow ".env created -- fill in ELECTRONHUB_API_KEY"
}
if (-not (Test-Path "forge.secrets")) {
    Copy-Item "forge.secrets.example" "forge.secrets"
    Write-Yellow "forge.secrets created -- add your API keys (gitignored)"
}

# --- Infrastructure directories ----------------------------------------------
Write-Green "Creating infra directories..."
$dirs = @(
    "infra/postgres/data", "infra/redis/data", "infra/qdrant/data",
    "infra/temporal", "infra/n8n/data", "infra/searxng"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

# qdrant config
@"
service:
  host: 0.0.0.0
  http_port: 6333
  grpc_port: 6334
log_level: INFO
"@ | Set-Content "infra/qdrant/config.yaml" -Encoding UTF8

# temporal config
@"
system.forceSearchAttributesCacheRefreshOnRead:
  - value: true
    constraints: {}
"@ | Set-Content "infra/temporal/dynamicconfig.yaml" -Encoding UTF8

# postgres init
@"
CREATE DATABASE n8n;
GRANT ALL PRIVILEGES ON DATABASE n8n TO backbone;
\c backbone;

CREATE TABLE IF NOT EXISTS hackathons (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL,
  platform TEXT, theme TEXT, deadline TIMESTAMPTZ, score INTEGER,
  status TEXT DEFAULT 'discovered', concept_json JSONB,
  project_url TEXT, submission_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id), agent_id TEXT NOT NULL,
  status TEXT DEFAULT 'pending', input_json JSONB, output_json JSONB,
  error TEXT, iterations INTEGER DEFAULT 0,
  started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ux_audit_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hackathon_id TEXT REFERENCES hackathons(id), preview_url TEXT,
  overall_score FLOAT, approved BOOLEAN, report_json JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
"@ | Set-Content "infra/postgres/init.sql" -Encoding UTF8

# --- Python version check ----------------------------------------------------
$PyMinor = (& $PYTHON_CMD -c "import sys; print(sys.version_info.minor)" 2>$null)
$PyMajor = (& $PYTHON_CMD -c "import sys; print(sys.version_info.major)" 2>$null)
if ([int]$PyMajor -eq 3 -and [int]$PyMinor -ge 13) {
    Write-Yellow @"
Python 3.$PyMinor detected. Some wheels (torch, temporalio, daytona-sdk)
may not have pre-built binaries for Python 3.$PyMinor yet.
Forge core will work. For maximum compatibility use Python 3.11 or 3.12.
"@
}

# --- Python dependencies (staged) --------------------------------------------
Write-Green "Installing Python core dependencies..."
if (-not $DryRun) {
    $installed = $false
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        try { uv pip install -e ".[dev]"; $installed = $true } catch {}
    }
    if (-not $installed) {
        try {
            & $PYTHON_CMD -m pip install -e ".[dev]" --quiet
            $installed = $true
        } catch {
            Write-Yellow "Full install failed -- trying core only (common on Python 3.13+)"
            & $PYTHON_CMD -m pip install -e "." --quiet
            & $PYTHON_CMD -m pip install pytest pytest-asyncio --quiet
        }
    }

    # Optional heavy deps
    Write-Green "Installing optional deps (crawl4ai, sentence-transformers)..."
    try { & $PYTHON_CMD -m pip install "crawl4ai>=0.4.0" --quiet } catch {
        Write-Yellow "crawl4ai install failed -- web crawling will use fallback HTTP extractor"
    }
    try { & $PYTHON_CMD -m pip install "sentence-transformers>=3.0.0" --quiet } catch {
        Write-Yellow "sentence-transformers install failed -- semantic reranking will be skipped"
    }

    # PyTorch CPU build
    $hasTorch = & $PYTHON_CMD -c "import torch; print('ok')" 2>$null
    if ($hasTorch -ne "ok") {
        Write-Green "Installing PyTorch (CPU build)..."
        try {
            & $PYTHON_CMD -m pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
        } catch {
            Write-Yellow @"
PyTorch CPU install failed.
GPU (CUDA 12.x): pip install torch --index-url https://download.pytorch.org/whl/cu121
CPU only:        pip install torch --index-url https://download.pytorch.org/whl/cpu
"@
        }
    }
}

# --- Playwright browsers -----------------------------------------------------
Write-Green "Installing Playwright (Chromium)..."
if (-not $DryRun) {
    try {
        & $PYTHON_CMD -m playwright install chromium
        Write-Green "Playwright: OK"
    } catch {
        Write-Yellow @"
Playwright browser install failed.
Try in an elevated PowerShell:
  python -m playwright install chromium --with-deps
"@
    }
}

# --- Browser layer (Node.js) -------------------------------------------------
Write-Green "Installing browser layer (Node.js)..."
if (-not $DryRun) {
    Push-Location "agents/browser"
    npm install --silent
    Pop-Location
}

# --- Docker images -----------------------------------------------------------
if (-not $SkipDocker) {
    Write-Green "Pulling Docker images (this may take a minute)..."
    if (-not $DryRun) {
        try {
            docker compose -f config/docker-compose.yml pull
        } catch {
            Write-Yellow "Docker pull had errors -- ensure Docker Desktop is running"
        }
    }
}

# --- Lighthouse CLI ----------------------------------------------------------
Write-Green "Installing Lighthouse CLI..."
if (-not $DryRun) {
    try {
        npm install -g lighthouse 2>$null
    } catch {
        Write-Yellow "Lighthouse install failed (non-critical)"
    }
}

# --- Crawl4AI first-run -----------------------------------------------------
Write-Green "Setting up Crawl4AI..."
if (-not $DryRun) {
    try {
        & $PYTHON_CMD -c @"
import asyncio, sys
async def s():
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler() as _: pass
        print('[setup] Crawl4AI: OK')
    except Exception as e:
        print(f'[warn] Crawl4AI: {e}', file=sys.stderr)
asyncio.run(s())
"@
    } catch {
        Write-Yellow "Crawl4AI first-run setup had errors (non-critical)"
    }
}

# --- Windows-specific notes --------------------------------------------------
Write-Host ""
Write-Green "Setup complete!"
Write-Host ""
Write-Cyan "Next steps:"
Write-Cyan "  1. Edit forge.secrets -- add your ELECTRONHUB_API_KEY"
Write-Cyan "  2. Ensure Docker Desktop is running"
Write-Cyan "  3. Start services: bash scripts/start.sh"
Write-Cyan "     (or in PowerShell: docker compose -f config/docker-compose.yml up -d)"
Write-Cyan "  4. Test: $PYTHON_CMD scripts/test_run.py --dry-run"
Write-Host ""
Write-Yellow "Daytona CLI is not available on native Windows."
Write-Yellow "For full GPU + Daytona support, run Forge in WSL2:"
Write-Yellow "  https://docs.microsoft.com/windows/wsl/install"
