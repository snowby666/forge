#!/usr/bin/env bash
# Automated Daytona API key generation for self-hosted instances.
# Performs the full OIDC login flow against Dex, then creates an API key.
#
# Usage:  ./scripts/daytona-keygen.sh
# Requires: curl, python3

set -euo pipefail

DAYTONA_URL="${DAYTONA_API_URL:-http://localhost:3986}"
DAYTONA_URL="${DAYTONA_URL%/api}"
DAYTONA_API="${DAYTONA_URL}/api"
DEX_URL="${DAYTONA_DEX_URL:-http://localhost:5556}"
DEX_EMAIL="${DAYTONA_DEX_EMAIL:-dev@daytona.io}"
DEX_PASSWORD="${DAYTONA_DEX_PASSWORD:-password}"
CLIENT_ID="daytona"
REDIRECT_URI="${DAYTONA_URL}"
KEY_NAME="forge-auto-$(date +%s)"
COOKIE_JAR=$(mktemp)
VERBOSE="${VERBOSE:-0}"

cleanup() { rm -f "$COOKIE_JAR" /tmp/_dkgen_*.tmp; }
trap cleanup EXIT

info()  { echo -e "\033[0;36m[daytona-keygen]\033[0m $*"; }
err()   { echo -e "\033[0;31m[daytona-keygen]\033[0m $*" >&2; }
ok()    { echo -e "\033[0;32m[daytona-keygen]\033[0m $*"; }
dbg()   { [[ "$VERBOSE" == "1" ]] && echo -e "\033[0;33m[debug]\033[0m $*" >&2 || true; }

# ── Step 0: Verify services are reachable ────────────────────────────────────
info "Checking Daytona API at ${DAYTONA_API}..."
if ! curl -sf "${DAYTONA_API}/../health" >/dev/null 2>&1; then
  if ! curl -sf "${DAYTONA_URL}/health" >/dev/null 2>&1; then
    err "Daytona API is not reachable at ${DAYTONA_URL}"
    exit 1
  fi
fi
info "Checking Dex at ${DEX_URL}..."
if ! curl -sf "${DEX_URL}/dex/.well-known/openid-configuration" >/dev/null 2>&1; then
  err "Dex OIDC is not reachable at ${DEX_URL}"
  err "Make sure daytona-dex container is running on port 5556"
  exit 1
fi
info "Both services reachable."

# ── Step 1: Start OIDC auth flow ────────────────────────────────────────────
ENCODED_REDIRECT=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${REDIRECT_URI}'))")
AUTH_URL="${DEX_URL}/dex/auth?client_id=${CLIENT_ID}&redirect_uri=${ENCODED_REDIRECT}&response_type=code&scope=openid+email+profile&nonce=$(date +%s)"

info "Starting OIDC flow..."
dbg "AUTH_URL: $AUTH_URL"

# -L follows Dex's internal redirects (e.g. /dex/auth → /dex/auth/local)
AUTH_RESP=$(curl -sSL -c "$COOKIE_JAR" -D /tmp/_dkgen_auth_headers.tmp "$AUTH_URL" 2>&1)
AUTH_STATUS=$?
dbg "curl auth status: $AUTH_STATUS"
dbg "Auth response length: ${#AUTH_RESP}"

# Check if we got redirected to a local login page
LOGIN_URL=$(echo "$AUTH_RESP" | grep -oP 'action="([^"]+)"' | head -1 | sed 's/action="//;s/"//' || true)

if [[ -z "$LOGIN_URL" ]]; then
  # Maybe the form uses single quotes
  LOGIN_URL=$(echo "$AUTH_RESP" | grep -oE "action='([^']+)'" | head -1 | sed "s/action='//;s/'//" || true)
fi

if [[ -z "$LOGIN_URL" ]]; then
  # Try to find it differently — look for /dex/auth/local path
  LOGIN_URL=$(echo "$AUTH_RESP" | grep -oE '/dex/auth/[a-zA-Z0-9/_?&=%-]+' | head -1 || true)
fi

if [[ -z "$LOGIN_URL" ]]; then
  err "Could not find Dex login form."
  err "Dex response (first 500 chars):"
  echo "${AUTH_RESP:0:500}" >&2
  exit 1
fi

if [[ "$LOGIN_URL" == /* ]]; then
  LOGIN_URL="${DEX_URL}${LOGIN_URL}"
fi
dbg "LOGIN_URL: $LOGIN_URL"

# ── Step 2: Submit login credentials ─────────────────────────────────────────
info "Submitting credentials..."
LOGIN_RESP=$(curl -sS \
  -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
  -D /tmp/_dkgen_login_headers.tmp \
  -X POST \
  -d "login=${DEX_EMAIL}&password=${DEX_PASSWORD}" \
  "$LOGIN_URL" 2>&1)

dbg "Login response length: ${#LOGIN_RESP}"

# ── Step 3: Handle approval page or extract code ─────────────────────────────
# Check headers for a redirect with code=
REDIRECT_LOC=$(grep -i '^location:' /tmp/_dkgen_login_headers.tmp 2>/dev/null | tail -1 | awk '{print $2}' | tr -d '\r\n' || true)
dbg "Redirect location: $REDIRECT_LOC"

AUTH_CODE=""

if [[ -n "$REDIRECT_LOC" ]] && echo "$REDIRECT_LOC" | grep -q 'code='; then
  AUTH_CODE=$(echo "$REDIRECT_LOC" | grep -oE 'code=[a-zA-Z0-9_-]+' | head -1 | sed 's/code=//')
fi

if [[ -z "$AUTH_CODE" ]]; then
  # Look for approval form
  APPROVAL_URL=$(echo "$LOGIN_RESP" | grep -oP 'action="([^"]+)"' | head -1 | sed 's/action="//;s/"//' || true)
  if [[ -n "$APPROVAL_URL" ]]; then
    if [[ "$APPROVAL_URL" == /* ]]; then
      APPROVAL_URL="${DEX_URL}${APPROVAL_URL}"
    fi
    dbg "APPROVAL_URL: $APPROVAL_URL"
    info "Submitting approval..."
    APPROVAL_RESP_HEADERS=$(mktemp)
    APPROVAL_RESP=$(curl -sS \
      -b "$COOKIE_JAR" -c "$COOKIE_JAR" \
      -D "$APPROVAL_RESP_HEADERS" \
      -X POST \
      -d "approval=approve&req=$(echo "$LOGIN_RESP" | grep -oE 'name="req" value="[^"]+"' | head -1 | sed 's/.*value="//;s/"//')" \
      "$APPROVAL_URL" 2>&1)
    REDIRECT_LOC=$(grep -i '^location:' "$APPROVAL_RESP_HEADERS" 2>/dev/null | tail -1 | awk '{print $2}' | tr -d '\r\n' || true)
    dbg "Approval redirect: $REDIRECT_LOC"
    rm -f "$APPROVAL_RESP_HEADERS"

    if echo "$REDIRECT_LOC" | grep -q 'code='; then
      AUTH_CODE=$(echo "$REDIRECT_LOC" | grep -oE 'code=[a-zA-Z0-9_-]+' | head -1 | sed 's/code=//')
    fi
  fi
fi

if [[ -z "$AUTH_CODE" ]]; then
  # Last resort: scan all responses for code=
  AUTH_CODE=$(echo "$LOGIN_RESP" | grep -oE 'code=[a-zA-Z0-9_-]+' | head -1 | sed 's/code=//' || true)
fi

if [[ -z "$AUTH_CODE" ]]; then
  # Follow the redirect manually if we got one without code
  if [[ -n "$REDIRECT_LOC" ]]; then
    dbg "Following redirect: $REDIRECT_LOC"
    FOLLOW_RESP=$(curl -sS -b "$COOKIE_JAR" -c "$COOKIE_JAR" -D /tmp/_dkgen_follow_headers.tmp -L "$REDIRECT_LOC" 2>&1)
    FINAL_LOC=$(grep -i '^location:' /tmp/_dkgen_follow_headers.tmp 2>/dev/null | tail -1 | awk '{print $2}' | tr -d '\r\n' || true)
    AUTH_CODE=$(echo "$FINAL_LOC" | grep -oE 'code=[a-zA-Z0-9_-]+' | head -1 | sed 's/code=//' || true)
    if [[ -z "$AUTH_CODE" ]]; then
      AUTH_CODE=$(echo "$FOLLOW_RESP" | grep -oE 'code=[a-zA-Z0-9_-]+' | head -1 | sed 's/code=//' || true)
    fi
  fi
fi

if [[ -z "$AUTH_CODE" ]]; then
  err "Could not extract authorization code."
  err "Login headers:"
  cat /tmp/_dkgen_login_headers.tmp >&2 2>/dev/null || true
  err "Login response (first 500 chars):"
  echo "${LOGIN_RESP:0:500}" >&2
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
  -d "redirect_uri=${REDIRECT_URI}" 2>&1)

dbg "Token response: ${TOKEN_RESP:0:200}"

ACCESS_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || true)
ID_TOKEN=$(echo "$TOKEN_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id_token',''))" 2>/dev/null || true)

TOKEN="${ID_TOKEN:-$ACCESS_TOKEN}"
if [[ -z "$TOKEN" ]]; then
  err "Could not get access token from Dex."
  err "Token response: $TOKEN_RESP"
  exit 1
fi
info "Got token (${#TOKEN} chars)."

# ── Step 5: Create API key via Daytona API ───────────────────────────────────
info "Creating Daytona API key '${KEY_NAME}'..."
KEY_RESP=$(curl -sS -w "\n%{http_code}" -X POST "${DAYTONA_API}/api-keys" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${KEY_NAME}\"}" 2>&1)

HTTP_CODE=$(echo "$KEY_RESP" | tail -1)
BODY=$(echo "$KEY_RESP" | sed '$d')
dbg "Create key HTTP code: $HTTP_CODE"
dbg "Create key body: ${BODY:0:200}"

API_KEY=$(echo "$BODY" | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
# Strip quotes if the API returns a plain quoted string
if raw.startswith('\"') and raw.endswith('\"'):
    raw = raw[1:-1]
try:
    obj = json.loads(raw)
    print(obj.get('key', obj.get('apiKey', raw)))
except:
    print(raw)
" 2>/dev/null)

if [[ -z "$API_KEY" ]] || [[ "$API_KEY" == *"error"* ]] || [[ "$API_KEY" == *"Unauthorized"* ]] || [[ "$HTTP_CODE" -ge 400 ]]; then
  err "Failed to create API key (HTTP $HTTP_CODE)."
  err "Response: $BODY"
  exit 1
fi

ok "API key created: ${API_KEY:0:20}..."

# ── Step 6: Store in .env ────────────────────────────────────────────────────
ENV_FILE="${ENV_FILE:-.env}"
if [[ -f "$ENV_FILE" ]]; then
  if grep -q '^DAYTONA_API_KEY=' "$ENV_FILE"; then
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
echo "  DAYTONA_API_KEY=${API_KEY:0:20}..."
echo ""
