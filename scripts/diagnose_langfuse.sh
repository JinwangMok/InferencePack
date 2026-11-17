#!/usr/bin/env bash
# Read-only diagnostics. Do not dump container environments, auth headers or logs.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
printf '%s\n' 'Langfuse diagnostics (no credentials or trace contents printed)'
python3 scripts/configure_env.py --check
printf '\nContainer status:\n'
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E 'NAMES|langfuse|inferencepack' || true
printf '\nLangfuse health HTTP status:\n'
curl --silent --show-error --max-time 10 --output /dev/null --write-out '%{http_code}\n' \
  http://127.0.0.1:3000/api/public/health
printf '\nFor detailed debugging, inspect logs locally and redact credentials and user data before sharing.\n'
