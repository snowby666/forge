#!/usr/bin/env bash
# Automated Daytona API key generation for self-hosted instances.
# Performs the full OIDC login flow against Dex, then creates an API key.
#
# Usage:  ./scripts/daytona-keygen.sh
# Requires: curl, python3 (for URL parsing)

set -euo pipefail

DAYTONA_URL="${DAYTONA_API_URL:-http://localhost:3986}"
DAYTONA_URL="${DAYTONA_URL%/api}"  # strip /api suffix if present
DAYTONA_API="${DAYTONA_URL}/api"
DEX_URL="${DAYTONA_DEX_URL:-http://localhost:5556}"
DEX_EMAIL="${DAYTONA_DEX_EMAIL:-dev@daytona.io}"
DEX_PASSWORD="${DAYTONA_DEX_PASSWORD:-password}"
CLIENT_ID="daytona"
REDIRECT_URI="${DAYTONA_URL}"
KEY_NAME="forge-auto-$(date +%s)"
COOKIE_JAR=$(mktemp)

cleanup() { rm -f "$COOKIE_JAR"; }
trap cleanup EXIT

info()  { echo -e "\033[0;36m[daytona-keygen]\033[0m $*"; }
err()   { echo -e "\033[0;31m[daytona-keygen]\033[0m $*" >&2; }
ok()    { echo -e "\033[0;32m[daytona-keygen]\033[0m $*"; }

# ── Step 1: Start OIDC auth flow ────────────────────────────────────────────
info "Starting OIDC flow against Dex at ${DEX_URL}..."
AUTH_URL="${DEX_URL}/dex/auth?client_id=${CLIENT_ID}&redirect_uri=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${REDIRECT_URI}'))")&response_type=code&scope=openid+email+profile&nonce=$(date +%s)"

AUTH_RESP=$(curl -sSL -c "$COOKIE_JAR" -D - "$AUTH_URL" 2>/dev/null)

# Extract the login POST URL from the HTML form
LOGIN_URL=$(echo "$AUTH_RESP" | grep -oP 'action="([^"]+)"' | head -1 | sed 's/action="//;s/"//')
if [[ -z "$LOGIN_URL" ]]; then
  err "Could not find Dex login form. Is Dex running at ${DEX_URL}?"
  exit 1
fi

# Make login URL absolute
if [[ "$LOGIN_URL" == /* ]]; then
  LOGIN_URL="${DEX_URL}${LOGIN_URL}"
fi

info "Submitting credentials to Dex..."

# ── Step 2: Submit login form ────────────────────────────────────────────────
LOGIN_RESP=$(curl -sSL \
  -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -D - \
  -X POST \
  -d "login=${DEX_EMAIL}&password=${DEX_PASSWORD}" \
  "$LOGIN_URL" 2>/dev/null)

# ── Step 3: Follow approval/redirect to get the auth code ───────────────────
# Dex may show an approval page, or redirect directly.
# Look for a redirect with ?code= or an approval form.
APPROVAL_URL=$(echo "$LOGIN_RESP" | grep -oP 'action="([^"]+)"' | head -1 | sed 's/action="//;s/"//')
if [[ -n "$APPROVAL_URL" ]]; then
  if [[ "$APPROVAL_URL" == /* ]]; then
    APPROVAL_URL="${DEX_URL}${APPROVAL_URL}"
  fi
  info "Submitting approval..."
  APPROVAL_RESP=$(curl -sSL \
    -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
    -D - -w "\n%{url_effective}" \
    -X POST \
    -d "approval=approve" \
    "$APPROVAL_URL" 2>/dev/null)
  FINAL_URL=$(echo "$APPROVAL_RESP" | tail -1)
else
  # Try to extract redirect Location header
  FINAL_URL=$(echo "$LOGIN_RESP" | grep -i '^location:' | tail -1 | awk '{print $2}' | tr -d '\r')
  if [[ -z "$FINAL_URL" ]]; then
    # Maybe we got redirected all the way — try to find code in the response
    FINAL_URL=$(echo "$LOGIN_RESP" | grep -oP 'code=[a-zA-Z0-9_-]+' | head -1)
    if [[ -n "$FINAL_URL" ]]; then
      FINAL_URL="${REDIRECT_URI}?${FINAL_URL}"
    fi
  fi
fi

# Extract the authorization code
AUTH_CODE=$(echo "$FINAL_URL" | grep -oP 'code=([a-zA-Z0-9_-]+)' | head -1 | sed 's/code=//')
if [[ -z "$AUTH_CODE" ]]; then
  err "Could not extract authorization code from callback."
  err "Login may have failed. Check credentials: ${DEX_EMAIL}"
  exit 1
fi
info "Got authorization code: ${AUTH_CODE:0:12}..."

# ── Step 4: Exchange code for tokens ─────────────────────────────────────────
info "Exchanging code for access token..."
TOKEN_RESP=$(curl -sS -X POST "${DEX_URL}/dex/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=${AUTH_CODE}" \
  -d "client_id=${CLIENT_ID}" \
  -d "redirect_uri=${REDIRECT_URI}" 2>/dev/null)

ACCESS_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
ID_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id_token',''))" 2>/dev/null || true)

TOKEN="${ID_TOKEN:-$ACCESS_TOKEN}"
if [[ -z "$TOKEN" ]]; then
  err "Could not get access token from Dex."
  err "Response: $TOKEN_RESP"
  exit 1
fi
info "Got access token."

# ── Step 5: Create API key via Daytona API ───────────────────────────────────
info "Creating Daytona API key '${KEY_NAME}'..."
KEY_RESP=$(curl -sS -X POST "${DAYTONA_API}/api-keys" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${KEY_NAME}\"}" 2>/dev/null)

# The response should be the API key string directly, or a JSON object
API_KEY=$(echo "$KEY_RESP" | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
try:
    obj = json.loads(raw)
    print(obj.get('key', obj.get('apiKey', raw)))
except:
    print(raw)
" 2>/dev/null)

if [[ -z "$API_KEY" ]] || [[ "$API_KEY" == *"error"* ]] || [[ "$API_KEY" == *"Unauthorized"* ]]; then
  err "Failed to create API key."
  err "Response: $KEY_RESP"
  exit 1
fi

ok "API key created: ${API_KEY:0:16}..."

# ── Step 6: Store in .env ────────────────────────────────────────────────────
ENV_FILE="${ENV_FILE:-.env}"
if [[ -f "$ENV_FILE" ]]; then
  if grep -q '^DAYTONA_API_KEY=' "$ENV_FILE"; then
    # Update existing key
    if [[ "$(uname)" == "Darwin" ]]; then
      sed -i '' "s|^DAYTONA_API_KEY=.*|DAYTONA_API_KEY=${API_KEY}|" "$ENV_FILE"
    else
      sed -i "s|^DAYTONA_API_KEY=.*|DAYTONA_API_KEY=${API_KEY}|" "$ENV_FILE"
    fi
    ok "Updated DAYTONA_API_KEY in ${ENV_FILE}"
  else
    echo "" >> "$ENV_FILE"
    echo "DAYTONA_API_KEY=${API_KEY}" >> "$ENV_FILE"
    ok "Added DAYTONA_API_KEY to ${ENV_FILE}"
  fi
else
  echo "DAYTONA_API_KEY=${API_KEY}" > "$ENV_FILE"
  ok "Created ${ENV_FILE} with DAYTONA_API_KEY"
fi

ok "Done! Daytona API key is ready."
echo ""
echo "  DAYTONA_API_KEY=${API_KEY:0:16}..."
echo ""
