#!/usr/bin/env bash
# =============================================================================
# scripts/deploy.sh — ST-14
# Deploy GeoResQ / Malenadu Resilience Impact Agent to IBM Cloud Code Engine.
#
# Usage:
#   ./scripts/deploy.sh [--region us-south] [--skip-push]
#
# Required environment variables (set in CI secrets or export before running):
#   IBM_CLOUD_API_KEY     IBM Cloud API key (IAM)
#   ICR_NAMESPACE         IBM Container Registry namespace  (e.g. georesq)
#   CE_PROJECT            Code Engine project name         (e.g. georesq-prod)
#   DATABASE_URL          mysql+pymysql://...
#   SECRET_KEY            Flask secret key (32+ bytes)
#   WATSONX_API_KEY       IBM watsonx.ai API key
#   WATSONX_URL           https://us-south.ml.cloud.ibm.com
#   WATSONX_PROJECT_ID    watsonx project GUID
#   GOOGLE_MAPS_API_KEY   Google Maps JavaScript API key
#
# Optional:
#   REGION                IBM Cloud region  (default: us-south)
#   APP_NAME              Code Engine application name  (default: georesq)
#   IMAGE_TAG             Docker image tag  (default: git short SHA)
# =============================================================================
set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
REGION="${REGION:-us-south}"
APP_NAME="${APP_NAME:-georesq}"
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo "latest")}"
SKIP_PUSH="${SKIP_PUSH:-false}"

# ── Validate required vars ────────────────────────────────────────────────────
REQUIRED_VARS=(
    IBM_CLOUD_API_KEY
    ICR_NAMESPACE
    CE_PROJECT
    DATABASE_URL
    SECRET_KEY
    WATSONX_API_KEY
    WATSONX_URL
    WATSONX_PROJECT_ID
    GOOGLE_MAPS_API_KEY
)
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var:-}" ]]; then
        echo "ERROR: required environment variable '$var' is not set." >&2
        exit 1
    fi
done

ICR_REGISTRY="icr.io"
IMAGE_REF="${ICR_REGISTRY}/${ICR_NAMESPACE}/${APP_NAME}:${IMAGE_TAG}"

echo "============================================================"
echo "  GeoResQ — IBM Cloud Code Engine deployment"
echo "  Region   : ${REGION}"
echo "  Project  : ${CE_PROJECT}"
echo "  Image    : ${IMAGE_REF}"
echo "============================================================"

# ── Step 1: Log in to IBM Cloud ───────────────────────────────────────────────
echo ""
echo "▶  [1/6] Logging in to IBM Cloud..."
ibmcloud login --apikey "${IBM_CLOUD_API_KEY}" -r "${REGION}" --no-region -q
ibmcloud target -r "${REGION}"

# ── Step 2: Log in to IBM Container Registry ──────────────────────────────────
echo ""
echo "▶  [2/6] Logging in to IBM Container Registry..."
ibmcloud cr login
ibmcloud cr namespace-add "${ICR_NAMESPACE}" 2>/dev/null || true   # idempotent

# ── Step 3: Build & push Docker image ─────────────────────────────────────────
if [[ "${SKIP_PUSH}" == "false" ]]; then
    echo ""
    echo "▶  [3/6] Building Docker image..."
    docker build \
        --platform linux/amd64 \
        --tag "${IMAGE_REF}" \
        --file Dockerfile \
        .

    echo ""
    echo "▶  [4/6] Pushing image to ICR..."
    docker push "${IMAGE_REF}"
else
    echo ""
    echo "▶  [3/6] Skipping build (SKIP_PUSH=true)."
    echo "▶  [4/6] Skipping push  (SKIP_PUSH=true)."
fi

# ── Step 4: Target the Code Engine project ────────────────────────────────────
echo ""
echo "▶  [5/6] Targeting Code Engine project '${CE_PROJECT}'..."
ibmcloud ce project select --name "${CE_PROJECT}"

# ── Step 5: Upsert Code Engine secrets (never bake into image) ────────────────
echo ""
echo "▶  [5/6] Upserting Code Engine secrets..."

_ce_secret_set() {
    # Create the secret if it doesn't exist; update if it does.
    local name="$1" value="$2"
    if ibmcloud ce secret get --name "${name}" &>/dev/null; then
        ibmcloud ce secret update --name "${name}" --from-literal "value=${value}"
    else
        ibmcloud ce secret create --name "${name}" --from-literal "value=${value}"
    fi
}

_ce_secret_set "georesq-database-url"       "${DATABASE_URL}"
_ce_secret_set "georesq-secret-key"         "${SECRET_KEY}"
_ce_secret_set "georesq-watsonx-api-key"    "${WATSONX_API_KEY}"
_ce_secret_set "georesq-watsonx-project-id" "${WATSONX_PROJECT_ID}"
_ce_secret_set "georesq-google-maps-key"    "${GOOGLE_MAPS_API_KEY}"

# ── Step 6: Deploy / update the Code Engine application ──────────────────────
echo ""
echo "▶  [6/6] Deploying application '${APP_NAME}'..."

CE_COMMON_ARGS=(
    --name  "${APP_NAME}"
    --image "${IMAGE_REF}"
    --port  8080
    --cpu   1
    --memory 2G
    --min-scale 1
    --max-scale 5
    --probe-liveness type=http,path=/healthz,port=8080,initial-delay=20,interval=30,timeout=10,failure-threshold=3
    --env  FLASK_ENV=production
    --env  WATSONX_URL="${WATSONX_URL}"
    --env  WATSONX_MODEL_ID="${WATSONX_MODEL_ID:-ibm/granite-13b-instruct-v2}"
    --env  RATELIMIT_STORAGE_URI="${RATELIMIT_STORAGE_URI:-memory://}"
    --env-from-secret georesq-database-url:DATABASE_URL
    --env-from-secret georesq-secret-key:SECRET_KEY
    --env-from-secret georesq-watsonx-api-key:WATSONX_API_KEY
    --env-from-secret georesq-watsonx-project-id:WATSONX_PROJECT_ID
    --env-from-secret georesq-google-maps-key:GOOGLE_MAPS_API_KEY
)

if ibmcloud ce application get --name "${APP_NAME}" &>/dev/null; then
    echo "   Application exists — updating..."
    ibmcloud ce application update "${CE_COMMON_ARGS[@]}"
else
    echo "   Application does not exist — creating..."
    ibmcloud ce application create "${CE_COMMON_ARGS[@]}"
fi

# ── Wait for rollout ──────────────────────────────────────────────────────────
echo ""
echo "   Waiting for rollout to complete..."
ibmcloud ce application get --name "${APP_NAME}" --output yaml | grep -A5 "conditions:"

APP_URL=$(ibmcloud ce application get --name "${APP_NAME}" --output json \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status',{}).get('url',''))" 2>/dev/null || true)

echo ""
echo "============================================================"
echo "  ✅  Deployment complete!"
if [[ -n "${APP_URL}" ]]; then
    echo "  🌐  Application URL : ${APP_URL}"
    echo "  🩺  Health check    : ${APP_URL}/healthz"
fi
echo "  🏷   Image           : ${IMAGE_REF}"
echo "============================================================"
