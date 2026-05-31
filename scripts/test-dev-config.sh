#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

assert_eq() {
  local actual="$1" expected="$2" message="$3"
  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL: $message: got $actual, want $expected" >&2
    exit 1
  fi
}

assert_contains() {
  local file="$1" pattern="$2" message="$3"
  if ! grep -Fq "$pattern" "$file"; then
    echo "FAIL: $message" >&2
    exit 1
  fi
}

assert_not_contains() {
  local file="$1" pattern="$2" message="$3"
  if grep -Fq "$pattern" "$file"; then
    echo "FAIL: $message" >&2
    exit 1
  fi
}

assert_file_not_exists() {
  local file="$1" message="$2"
  if [[ -e "$file" ]]; then
    echo "FAIL: $message" >&2
    exit 1
  fi
}

assert_fails() {
  local message="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "FAIL: $message" >&2
    exit 1
  fi
}

assert_backend_failure_exits() {
  local block
  block="$(awk '/backend 启动失败/{ print; getline; print }' "$REPO_ROOT/scripts/dev-start.sh")"
  if [[ "$block" != *"exit 1"* ]]; then
    echo "FAIL: dev-start.sh must exit before printing success when backend fails" >&2
    exit 1
  fi
}

make_fake_bin() {
  local fake_bin="$1"
  mkdir -p "$fake_bin"
  cat >"$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${FAKE_SERVICE_MARKERS:-}" ]]; then
  mkdir -p "$FAKE_SERVICE_MARKERS"
  touch "$FAKE_SERVICE_MARKERS/docker"
fi
if [[ "${1:-}" == "compose" ]]; then
  exit 0
fi
if [[ "${1:-}" == "inspect" ]]; then
  echo "healthy"
  exit 0
fi
exit 0
EOF
  cat >"$fake_bin/go" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${FAKE_SERVICE_MARKERS:-}" ]]; then
  mkdir -p "$FAKE_SERVICE_MARKERS"
  touch "$FAKE_SERVICE_MARKERS/go"
fi
if [[ "${FAKE_BACKEND_MODE:-success}" == "fail" ]]; then
  exit 1
fi
sleep 30
EOF
  cat >"$fake_bin/pnpm" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${FAKE_SERVICE_MARKERS:-}" ]]; then
  mkdir -p "$FAKE_SERVICE_MARKERS"
  touch "$FAKE_SERVICE_MARKERS/pnpm"
fi
if [[ "${1:-}" == "install" ]]; then
  exit 0
fi
if [[ "${FAKE_WEB_MODE:-success}" == "fail" ]]; then
  exit 1
fi
sleep 30
EOF
  chmod +x "$fake_bin/docker" "$fake_bin/go" "$fake_bin/pnpm"
}

cleanup_run_dir() {
  local run_dir="$1"
  for pid_file in "$run_dir"/*.pid; do
    [[ -f "$pid_file" ]] || continue
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}

run_dev_start() {
  local tmp_dir="$1" addr="$2" web_mode="$3" output_file="$4"
  local fake_bin="$tmp_dir/bin"
  local env_file="$tmp_dir/.env"
  local run_dir="$tmp_dir/run"
  local markers_dir="$tmp_dir/markers"
  make_fake_bin "$fake_bin"
  rm -rf "$markers_dir"
  cat >"$env_file" <<EOF
DEEPSEEK_API_KEY=test-key
BFF_HTTP_ADDR=$addr
EOF
  FAKE_WEB_MODE="$web_mode" \
    FAKE_SERVICE_MARKERS="$markers_dir" \
    DEV_ENV_FILE="$env_file" \
    DEV_RUN_DIR="$run_dir" \
    DEV_LOG_DIR="$run_dir/logs" \
    PATH="$fake_bin:$PATH" \
    bash "$REPO_ROOT/scripts/dev-start.sh" >"$output_file" 2>&1
  local status=$?
  cleanup_run_dir "$run_dir"
  return "$status"
}

source "$REPO_ROOT/scripts/dev-config.sh"

assert_eq "$(backend_http_url "")" "http://localhost:8081" \
  "empty backend address should render default URL"
assert_eq "$(backend_http_url ":8081")" "http://localhost:8081" \
  "colon backend address should render localhost URL"
assert_eq "$(backend_http_url "127.0.0.1:9090")" "http://127.0.0.1:9090" \
  "host:port backend address should render unchanged URL"
assert_fails "bare backend port must be rejected for URL formatting" backend_http_url "8081"
assert_fails "non-numeric colon port must be rejected for URL formatting" backend_http_url ":abcd"
assert_eq "$(backend_http_port "")" "8081" \
  "empty backend address should use default port"
assert_eq "$(backend_http_port ":9090")" "9090" \
  "colon backend address should parse port"
assert_eq "$(backend_http_port "127.0.0.1:9090")" "9090" \
  "host:port backend address should parse port"
assert_fails "bare backend port must be rejected for port parsing" backend_http_port "8081"
assert_fails "non-numeric host port must be rejected for port parsing" backend_http_port "127.0.0.1:abcd"

TMP_DIR="$(mktemp -d)"
trap 'cleanup_run_dir "$TMP_DIR/run"; rm -rf "$TMP_DIR"' EXIT
OUTPUT_FILE="$TMP_DIR/dev-start.out"
run_dev_start "$TMP_DIR" ":9090" "success" "$OUTPUT_FILE"
assert_contains "$OUTPUT_FILE" "backend  : http://localhost:9090" \
  "dev-start.sh must render :9090 as localhost URL"
if run_dev_start "$TMP_DIR" ":9090" "fail" "$OUTPUT_FILE"; then
  echo "FAIL: dev-start.sh must fail when web process exits during startup" >&2
  exit 1
fi
assert_contains "$OUTPUT_FILE" "web 启动失败" \
  "dev-start.sh must report web startup failure"
assert_not_contains "$OUTPUT_FILE" "开发环境已启动" \
  "dev-start.sh must not print success after web startup failure"
if run_dev_start "$TMP_DIR" "8081" "success" "$OUTPUT_FILE"; then
  echo "FAIL: dev-start.sh must reject bare BFF_HTTP_ADDR before startup" >&2
  exit 1
fi
assert_contains "$OUTPUT_FILE" "BFF_HTTP_ADDR 必须是 :port 或 host:port" \
  "dev-start.sh must report invalid bare BFF_HTTP_ADDR"
assert_file_not_exists "$TMP_DIR/markers/docker" \
  "dev-start.sh must validate BFF_HTTP_ADDR before starting docker"
assert_file_not_exists "$TMP_DIR/markers/go" \
  "dev-start.sh must validate BFF_HTTP_ADDR before starting backend"
assert_file_not_exists "$TMP_DIR/markers/pnpm" \
  "dev-start.sh must validate BFF_HTTP_ADDR before starting web"

assert_not_contains "$REPO_ROOT/scripts/dev-start.sh" '${BFF_HTTP_ADDR#:}' \
  "dev-start.sh must preserve leading colon in BFF_HTTP_ADDR"
assert_not_contains "$REPO_ROOT/scripts/dev-start.sh" 'cfg.Port' \
  "dev-start.sh comments must not describe removed cfg.Port behavior"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'backend_http_url "${BFF_HTTP_ADDR:-}"' \
  "dev-start.sh must use shared backend URL formatter"
assert_backend_failure_exits
assert_contains "$REPO_ROOT/scripts/check-dev.sh" 'DEEPSEEK_TIMEOUT_SECONDS' \
  "check-dev.sh must check DEEPSEEK_TIMEOUT_SECONDS"
assert_not_contains "$REPO_ROOT/scripts/check-dev.sh" 'HTTP_CLIENT_TIMEOUT_SECONDS' \
  "check-dev.sh must not check legacy HTTP_CLIENT_TIMEOUT_SECONDS"
assert_contains "$REPO_ROOT/scripts/check-dev.sh" 'backend_http_port' \
  "check-dev.sh must parse backend port from BFF_HTTP_ADDR"
assert_contains "$REPO_ROOT/Makefile" 'test-dev-config:' \
  "Makefile must expose test-dev-config target"
assert_contains "$REPO_ROOT/Makefile" 'bash scripts/test-dev-config.sh' \
  "Makefile test-dev-config target must run script test"

echo "PASS: dev config scripts"
