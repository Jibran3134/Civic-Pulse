#!/bin/bash
# Zero-Downtime Rollout Demo Script
# Usage: ./scripts/rollout-demo.sh <image-ref>

set -euo pipefail

# Configuration
CLUSTER_NAME="civicpulse-demo"
NAMESPACE="civicpulse"
BACKEND_DEPLOYMENT="backend"
# NEW_IMAGE_TAG should be a SHA-based tag (e.g., ghcr.io/username/civicpulse-backend:abc1234)
# Pass as first argument or set NEW_IMAGE_TAG env var
NEW_IMAGE_TAG="${1:-${NEW_IMAGE_TAG:-}}"
K6_SCRIPT="load/rollout-demo.js"
BASE_URL="${BASE_URL:-http://localhost:8000}"
# --summary-export writes ONE JSON document; `--out json=` writes a stream of one
# JSON object per metric sample, which `jq` cannot read as a single document.
K6_RESULTS="rollout-results.json"
HPA_OUTPUT="hpa-output.txt"
# Background PIDs, declared up front so `set -u` cannot blow up if a phase is skipped.
K6_PID=""
HPA_PID=""

# Validate NEW_IMAGE_TAG is provided and not a generic tag
if [ -z "$NEW_IMAGE_TAG" ]; then
    echo "❌ Error: NEW_IMAGE_TAG must be provided as first argument or env var"
    echo "   Usage: $0 ghcr.io/username/civicpulse-backend:<sha>"
    echo "   Example: $0 ghcr.io/jibran/civicpulse-backend:a1b2c3d"
    exit 1
fi
if [[ "$NEW_IMAGE_TAG" == *":latest" ]] || [[ "$NEW_IMAGE_TAG" == *":new-version" ]] || [[ "$NEW_IMAGE_TAG" == *":dev" ]]; then
    echo "❌ Error: Image tag must be a SHA-based tag (commit hash), not 'latest', 'new-version', or 'dev'"
    echo "   Provided: $NEW_IMAGE_TAG"
    exit 1
fi

echo "=========================================="
echo "Zero-Downtime Rollout Demo"
echo "=========================================="
echo "Cluster: $CLUSTER_NAME"
echo "Namespace: $NAMESPACE"
echo "Deployment: $BACKEND_DEPLOYMENT"
echo "New Image: $NEW_IMAGE_TAG"
echo "Base URL: $BASE_URL"
echo ""

# Always clean up the background k6/hpa watchers, even if the demo aborts early
# (otherwise a killed k6 keeps hammering the cluster after the script exits).
cleanup() {
    if [ -n "$K6_PID" ] && kill -0 "$K6_PID" 2>/dev/null; then
        kill -INT "$K6_PID" 2>/dev/null || true
        wait "$K6_PID" 2>/dev/null || true
    fi
    if [ -n "$HPA_PID" ] && kill -0 "$HPA_PID" 2>/dev/null; then
        kill "$HPA_PID" 2>/dev/null || true
        wait "$HPA_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Function to check prerequisites
check_prereqs() {
    echo "🔍 Checking prerequisites..."
    command -v kubectl >/dev/null 2>&1 || { echo "❌ kubectl not found"; exit 1; }
    command -v k6 >/dev/null 2>&1 || { echo "❌ k6 not found"; exit 1; }
    command -v k3d >/dev/null 2>&1 || { echo "❌ k3d not found"; exit 1; }
    # jq parses the k6 summary; awk does the division (bc is not always installed)
    command -v jq >/dev/null 2>&1 || { echo "❌ jq not found"; exit 1; }
    command -v awk >/dev/null 2>&1 || { echo "❌ awk not found"; exit 1; }
    echo "✅ All tools available"
}

# Function to start load test in background
start_load_test() {
    echo "🚀 Starting k6 load test (background)..."
    rm -f "$K6_RESULTS"
    BASE_URL=$BASE_URL k6 run --summary-export "$K6_RESULTS" "$K6_SCRIPT" &
    K6_PID=$!
    echo "   k6 PID: $K6_PID"
    sleep 10  # Let load stabilize
}

# Function to perform rollout
perform_rollout() {
    echo "🔄 Performing rolling update..."
    echo "   Current image: $(kubectl get deployment "$BACKEND_DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}')"

    # No --record: the flag was removed in kubectl 1.19 and now hard-errors, which
    # under `set -euo pipefail` aborted the demo right before the interesting part.
    kubectl set image deployment/"$BACKEND_DEPLOYMENT" -n "$NAMESPACE" \
        backend="$NEW_IMAGE_TAG"

    echo "⏳ Waiting for rollout to complete..."
    kubectl rollout status deployment/"$BACKEND_DEPLOYMENT" -n "$NAMESPACE" --timeout=300s

    echo "   New image: $(kubectl get deployment "$BACKEND_DEPLOYMENT" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].image}')"
}

# Function to capture HPA status
capture_hpa() {
    echo "📊 Capturing HPA status..."
    # stdout AND stderr go to the file. `kubectl get -w` writes "Waiting for
    # condition"/"Metrics not available" progress to stderr, which otherwise
    # floods the demo log; the file keeps the evidence.
    kubectl get hpa -n "$NAMESPACE" -w > "$HPA_OUTPUT" 2>&1 &
    HPA_PID=$!
    sleep 2
    kill "$HPA_PID" 2>/dev/null || true
    wait "$HPA_PID" 2>/dev/null || true
    HPA_PID=""
    echo "   Saved to $HPA_OUTPUT"
}

# Function to stop load test and analyze
stop_and_analyze() {
    echo "🛑 Stopping load test..."
    sleep 30  # Let remaining requests complete
    # SIGINT (not SIGTERM) so k6 shuts down gracefully and still writes the
    # summary export we are about to read.
    if [ -n "$K6_PID" ]; then
        kill -INT "$K6_PID" 2>/dev/null || true
        wait "$K6_PID" 2>/dev/null || true
    fi
    K6_PID=""

    echo "📈 Analyzing results..."
    if [ ! -f "$K6_RESULTS" ]; then
        echo "❌ $K6_RESULTS was never written (k6 was killed before it could export a summary)"
        exit 1
    fi

    # http_req_failed is a Rate: `passes` is the count of requests that PASSED the
    # failure threshold, so the real number of failed requests is count - passes.
    TOTAL=$(jq -r '.metrics.http_reqs.values.count // 0' "$K6_RESULTS")
    PASSED=$(jq -r '.metrics.http_req_failed.values.passes // 0' "$K6_RESULTS")
    FAILED=$(( TOTAL > PASSED ? TOTAL - PASSED : 0 ))
    FAIL_RATE=$(awk -v f="$FAILED" -v t="$TOTAL" 'BEGIN { if (t > 0) printf "%.4f", f / t * 100; else print "0.0000" }')

    echo "=========================================="
    echo "RESULTS SUMMARY"
    echo "=========================================="
    echo "Total Requests: $TOTAL"
    echo "Failed Requests: $FAILED"
    echo "Failure Rate: ${FAIL_RATE}%"

    if [ "$TOTAL" -gt 0 ] && [ "$FAILED" -eq 0 ]; then
        echo "✅ ZERO-DOWNTIME: PASS (0 of $TOTAL requests failed during the rollout)"
    else
        echo "❌ ZERO-DOWNTIME: FAIL (${FAILED}/${TOTAL} requests failed, ${FAIL_RATE}%)"
    fi

    # Show HPA scaling
    echo ""
    echo "HPA Scaling Events:"
    kubectl get hpa -n "$NAMESPACE"

    # Fail the script when the rollout actually dropped requests, so the demo
    # cannot be recorded as a success on broken numbers.
    if [ "$TOTAL" -eq 0 ] || [ "$FAILED" -ne 0 ]; then
        exit 1
    fi
}

# Main execution
main() {
    check_prereqs

    # Check if cluster exists
    if ! k3d cluster list | grep -q "$CLUSTER_NAME"; then
        echo "📦 Creating k3d cluster..."
        k3d cluster create "$CLUSTER_NAME" \
            --servers 1 --agents 2 \
            --port "80:80@loadbalancer" \
            --wait
    fi

    # Deploy current version
    echo "📦 Deploying current version..."
    kubectl apply -k k8s/overlays/prod
    kubectl rollout status deployment/"$BACKEND_DEPLOYMENT" -n "$NAMESPACE" --timeout=300s

    # Start load test
    start_load_test

    # Perform rollout
    perform_rollout

    # Capture HPA
    capture_hpa

    # Stop and analyze
    stop_and_analyze

    echo ""
    echo "=========================================="
    echo "Demo complete. Evidence files:"
    echo "  - $K6_RESULTS (k6 summary export)"
    echo "  - $HPA_OUTPUT (HPA scaling log)"
    echo "=========================================="
}

main "$@"
