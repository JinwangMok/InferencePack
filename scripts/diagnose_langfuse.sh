#!/usr/bin/env bash
# LangFuse tracing diagnostic script

set -e

echo "========================================"
echo "  LangFuse Tracing Diagnostics"
echo "========================================"
echo ""

# 1. Check LangFuse container status
echo "[1] LangFuse container status:"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "langfuse|inferencepack" || true
echo ""

# 2. Check vLLM environment variables (OTEL related)
echo "[2] vLLM OTEL environment variables:"
docker exec inferencepack-vllm env | grep -iE "OTEL|LANGFUSE" || echo "  (none found)"
echo ""

# 3. Check if vLLM can reach LangFuse OTLP endpoint
echo "[3] Network connectivity test:"
docker exec inferencepack-vllm wget -qO- http://langfuse-web:3000/api/public/health 2>/dev/null || echo "  LangFuse health check failed"
echo ""

# 4. Check .env file for LangFuse keys
echo "[4] .env file LangFuse configuration:"
if [ -f .env ]; then
    grep -E "LANGFUSE|OTEL" .env || echo "  (no LangFuse/OTEL vars found)"
else
    echo "  .env file not found"
fi
echo ""

# 5. Check LangFuse project settings via API (if keys are available)
echo "[5] LangFuse API test (if keys configured):"
if [ -f .env ]; then
    PK=$(grep "^LANGFUSE_PUBLIC_KEY=" .env | cut -d= -f2 | tr -d '"')
    SK=$(grep "^LANGFUSE_SECRET_KEY=" .env | cut -d= -f2 | tr -d '"')
    if [ -n "$PK" ] && [ -n "$SK" ]; then
        curl -s -u "${PK}:${SK}" http://localhost:3000/api/public/projects 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  LangFuse API call failed (check keys)"
    else
        echo "  LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set in .env"
    fi
fi
echo ""

# 6. Test OTLP endpoint directly with auth
echo "[6] OTLP endpoint test:"
if [ -f .env ]; then
    PK=$(grep "^LANGFUSE_PUBLIC_KEY=" .env | cut -d= -f2 | tr -d '"')
    SK=$(grep "^LANGFUSE_SECRET_KEY=" .env | cut -d= -f2 | tr -d '"')
    if [ -n "$PK" ] && [ -n "$SK" ]; then
        AUTH=$(echo -n "${PK}:${SK}" | base64 -w0)
        curl -s -o /dev/null -w "%{http_code}" \
            -H "Content-Type: application/x-protobuf" \
            -H "Authorization: Basic ${AUTH}" \
            http://localhost:3000/api/public/otel/v1/traces || echo "  OTLP endpoint test failed"
        echo " (HTTP status code above)"
    else
        echo "  Keys not configured, skipping"
    fi
fi
echo ""

# 7. Recent vLLM OTLP export errors
echo "[7] Recent vLLM OTLP errors:"
docker logs inferencepack-vllm --since 5m 2>&1 | grep -iE "export span|Unauthorized|otlp|trace" | tail -10 || echo "  No OTLP errors in last 5 minutes"
echo ""

# 8. Check if LangFuse web has OTLP endpoint enabled
echo "[8] LangFuse web environment (OTLP related):"
docker exec inferencepack-langfuse-web env | grep -iE "OTEL|OTLP" || echo "  (no OTLP-specific env vars)"
echo ""

# 9. Check if traces are being generated in LangFuse DB
echo "[9] LangFuse traces in database (last 10):"
docker exec inferencepack-postgres psql -U postgres -d langfuse -t -c "
    SELECT COUNT(*) FROM traces WHERE created_at > NOW() - INTERVAL '1 hour';
" 2>/dev/null || echo "  DB query failed"
echo ""

echo "========================================"
echo "  Diagnostics complete"
echo "========================================"
