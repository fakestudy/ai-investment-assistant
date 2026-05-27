#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
START_DEV="${ROOT_DIR}/script/start-dev.sh"

if grep -q " run ./cmd/bff" "${START_DEV}"; then
  echo "start-dev.sh must not launch the long-running BFF with go run." >&2
  exit 1
fi

grep -q 'build -o "${BFF_BIN}" ./cmd/bff' "${START_DEV}"
grep -q '"${BFF_BIN}"' "${START_DEV}"
grep -q 'BFF_PORT="${BFF_PORT:-8081}"' "${START_DEV}"
grep -q '"BFF_HTTP_ADDR=127.0.0.1:${BFF_PORT}"' "${START_DEV}"
grep -q '启动 agent server (${AGENT_GRPC_BIND_ADDR})' "${START_DEV}"
grep -q '启动 Go BFF (http://127.0.0.1:${BFF_PORT})' "${START_DEV}"
grep -q '启动 fronted (http://127.0.0.1:${FRONTED_PORT})' "${START_DEV}"
