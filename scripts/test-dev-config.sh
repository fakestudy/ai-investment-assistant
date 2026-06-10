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

assert_banner_contains() {
  local file="$1" pattern="$2" message="$3"
  if ! awk '
    /╭/ { in_banner = 1 }
    in_banner && index($0, pattern) { found = 1 }
    /╰/ { in_banner = 0 }
    END { exit found ? 0 : 1 }
  ' pattern="$pattern" "$file"; then
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

assert_agent_failure_exits() {
  local block
  block="$(awk '/agent_claude 启动失败/{ print; getline; print }' "$REPO_ROOT/scripts/dev-start.sh")"
  if [[ "$block" != *"exit 1"* ]]; then
    echo "FAIL: dev-start.sh must exit before printing success when agent_claude fails" >&2
    exit 1
  fi
}

assert_health_failure_exits() {
  local label="$1"
  local block
  block="$(awk -v pattern="$label 健康检查未通过" '
    index($0, pattern) { print; getline; print }
  ' "$REPO_ROOT/scripts/dev-start.sh")"
  if [[ "$block" != *"exit 1"* ]]; then
    echo "FAIL: dev-start.sh must exit when $label health check fails" >&2
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
if [[ "${1:-}" == "exec" ]]; then
  # 模拟数据库已存在 (psql -tAc 返回 1)
  echo "1"
  exit 0
fi
exit 0
EOF
  cat >"$fake_bin/uv" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ -n "${FAKE_SERVICE_MARKERS:-}" ]]; then
  mkdir -p "$FAKE_SERVICE_MARKERS"
  touch "$FAKE_SERVICE_MARKERS/uv"
fi
# alembic migration 总是成功返回
for arg in "$@"; do
  if [[ "$arg" == "alembic" ]]; then
    exit 0
  fi
done
if [[ "${FAKE_AGENT_MODE:-success}" == "fail" ]]; then
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
  cat >"$fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exit 0
EOF
  chmod +x "$fake_bin/docker" "$fake_bin/uv" "$fake_bin/pnpm" "$fake_bin/curl"
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
  local agent_mode="${5:-success}"
  local fake_bin="$tmp_dir/bin"
  local env_file="$tmp_dir/.env"
  local run_dir="$tmp_dir/run"
  local markers_dir="$tmp_dir/markers"
  make_fake_bin "$fake_bin"
  rm -rf "$markers_dir"
  cat >"$env_file" <<EOF
ANTHROPIC_BASE_URL=https://example.com
ANTHROPIC_AUTH_TOKEN=test-token
ANTHROPIC_MODEL=test-model
DATABASE_URL=postgresql+psycopg://investment:investment@localhost:5432/agent_claude
BFF_HTTP_ADDR=$addr
EOF
  FAKE_AGENT_MODE="$agent_mode" \
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
assert_contains "$OUTPUT_FILE" "agent_claude api: http://localhost:9090" \
  "dev-start.sh must render :9090 as localhost URL"
assert_contains "$OUTPUT_FILE" "本地入口已就绪" \
  "dev-start.sh must print a prominent local entry banner"
assert_contains "$OUTPUT_FILE" "AIA" \
  "dev-start.sh must print the local app logo in the ready banner"
assert_contains "$OUTPUT_FILE" "AI Investment Assistant" \
  "dev-start.sh must print the product name in the ready banner"
assert_contains "$OUTPUT_FILE" "http://localhost:3000" \
  "dev-start.sh must print the nginx localhost entry URL"
assert_banner_contains "$OUTPUT_FILE" "服务明细:" \
  "dev-start.sh must print service details inside the ready banner"
if run_dev_start "$TMP_DIR" ":9090" "success" "$OUTPUT_FILE" "fail"; then
  echo "FAIL: dev-start.sh must fail when agent_claude process exits during startup" >&2
  exit 1
fi
assert_contains "$OUTPUT_FILE" "agent_claude 启动失败" \
  "dev-start.sh must report agent_claude startup failure"
assert_not_contains "$OUTPUT_FILE" "开发环境已启动" \
  "dev-start.sh must not print success after agent_claude startup failure"
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
assert_file_not_exists "$TMP_DIR/markers/uv" \
  "dev-start.sh must validate BFF_HTTP_ADDR before starting agent_claude"
assert_file_not_exists "$TMP_DIR/markers/pnpm" \
  "dev-start.sh must validate BFF_HTTP_ADDR before starting web"

assert_not_contains "$REPO_ROOT/scripts/dev-start.sh" '${BFF_HTTP_ADDR#:}' \
  "dev-start.sh must preserve leading colon in BFF_HTTP_ADDR"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'backend_http_url "${BFF_HTTP_ADDR:-}"' \
  "dev-start.sh must use shared backend URL formatter"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'docker compose up -d --remove-orphans postgres nginx pgweb' \
  "dev-start.sh must start nginx and pgweb with postgres"
assert_not_contains "$REPO_ROOT/scripts/dev-start.sh" 'rabbitmq' \
  "dev-start.sh must not reference rabbitmq"
assert_not_contains "$REPO_ROOT/scripts/dev-start.sh" 'worker.main' \
  "dev-start.sh must not start a worker"
assert_not_contains "$REPO_ROOT/scripts/dev-start.sh" 'outbox_publisher' \
  "dev-start.sh must not start an outbox publisher"
assert_not_contains "$REPO_ROOT/docker-compose.yml" 'rabbitmq:' \
  "docker-compose.yml must not define rabbitmq"
assert_health_failure_exits "postgres"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'show_startup_animation' \
  "dev-start.sh must include a terminal startup animation"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'cd "$REPO_ROOT/agent_claude"' \
  "dev-start.sh must use the agent_claude package dev entry"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'alembic upgrade head' \
  "dev-start.sh must run agent_claude alembic migration"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'nohup pnpm dev >"$WEB_LOG" 2>&1 &' \
  "dev-start.sh must use the web package dev script"
assert_not_contains "$REPO_ROOT/scripts/dev-start.sh" 'pnpm dev -- --port 3001' \
  "dev-start.sh must not override the web dev port"
assert_contains "$REPO_ROOT/web/package.json" '"dev": "next dev --port 3001"' \
  "web package dev script must default Next.js to port 3001"
assert_agent_failure_exits
assert_contains "$REPO_ROOT/scripts/dev-stop.sh" 'docker compose stop nginx postgres' \
  "dev-stop.sh must stop nginx with postgres"
assert_not_contains "$REPO_ROOT/scripts/dev-stop.sh" 'rabbitmq' \
  "dev-stop.sh must not reference rabbitmq"
assert_contains "$REPO_ROOT/scripts/check-dev.sh" 'REQUIRED_VARS=(ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL)' \
  "check-dev.sh must require ANTHROPIC env vars"
assert_not_contains "$REPO_ROOT/scripts/check-dev.sh" 'rabbitmq/amqp' \
  "check-dev.sh must not check rabbitmq ports"
assert_not_contains "$REPO_ROOT/scripts/check-dev.sh" 'DEEPSEEK_API_KEY' \
  "check-dev.sh must not require legacy DEEPSEEK_API_KEY"
assert_contains "$REPO_ROOT/scripts/check-dev.sh" 'backend_http_port' \
  "check-dev.sh must parse backend port from BFF_HTTP_ADDR"
assert_contains "$REPO_ROOT/scripts/check-dev.sh" 'check_port 3000 "nginx/reverse proxy" fail' \
  "check-dev.sh must check nginx reverse proxy port"
assert_contains "$REPO_ROOT/docker-compose.yml" 'image: nginx:1.27-alpine' \
  "docker-compose.yml must define nginx service"
assert_contains "$REPO_ROOT/docker-compose.yml" '"3000:80"' \
  "docker-compose.yml must expose nginx on localhost port 3000"
assert_contains "$REPO_ROOT/infra/nginx/local.conf" 'proxy_pass http://host.docker.internal:8081;' \
  "nginx local config must proxy API requests to host agent_claude"
assert_contains "$REPO_ROOT/infra/nginx/local.conf" 'proxy_pass http://host.docker.internal:3001;' \
  "nginx local config must proxy web requests to host frontend"
assert_contains "$REPO_ROOT/Makefile" 'test-dev-config:' \
  "Makefile must expose test-dev-config target"
assert_contains "$REPO_ROOT/Makefile" 'bash scripts/test-dev-config.sh' \
  "Makefile test-dev-config target must run script test"
assert_contains "$REPO_ROOT/Makefile" 'postgres + nginx + pgweb + agent_claude api + web' \
  "Makefile help must describe the dev-start processes"
assert_contains "$REPO_ROOT/scripts/dev-start.sh" 'tail -f $AGENT_API_LOG $WEB_LOG' \
  "dev-start.sh log hint must include api and web logs"

echo "PASS: dev config scripts"
