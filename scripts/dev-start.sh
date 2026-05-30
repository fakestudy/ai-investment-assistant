#!/usr/bin/env bash
# 启动本地开发环境：postgres (docker) + backend (go) + web (pnpm)
# 不再使用 backend / web 的 Docker 镜像，二者直接以脚本进程方式运行。

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RUN_DIR="$REPO_ROOT/.run"
LOG_DIR="$REPO_ROOT/.run/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
WEB_LOG="$LOG_DIR/web.log"

# ---- 输出辅助 ----
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'
  C_BLU=$'\033[34m'; C_BLD=$'\033[1m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_BLD=""; C_RST=""
fi

info()  { echo "${C_BLU}[dev-start]${C_RST} $*"; }
ok()    { echo "${C_GRN}[dev-start]${C_RST} $*"; }
warn()  { echo "${C_YLW}[dev-start]${C_RST} $*"; }
error() { echo "${C_RED}[dev-start]${C_RST} $*" 1>&2; }

# ---- 进程辅助 ----
is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

# ---- 1. 加载 .env ----
ENV_FILE="$REPO_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  error ".env 不存在，请先 cp .env.example .env 并填写配置"
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# 容器外开发：postgres 主机名应为 localhost
if [[ "${DATABASE_URL:-}" == *"@postgres:"* ]]; then
  export DATABASE_URL="${DATABASE_URL/@postgres:/@localhost:}"
  warn "DATABASE_URL 中的 host 已临时替换为 localhost（仅本进程生效）"
fi

# BFF_HTTP_ADDR 在 main.go 里会被拼成 ":" + cfg.Port，去掉前导冒号避免 ::8081
if [[ "${BFF_HTTP_ADDR:-}" == :* ]]; then
  export BFF_HTTP_ADDR="${BFF_HTTP_ADDR#:}"
fi

# ---- 2. 启动 postgres (docker compose) ----
info "启动 postgres 容器..."
if ! docker compose up -d postgres >/dev/null; then
  error "docker compose up postgres 失败"
  exit 1
fi

# 等待 postgres 健康
info "等待 postgres 就绪..."
for _ in $(seq 1 30); do
  status="$(docker inspect -f '{{.State.Health.Status}}' investment-postgres 2>/dev/null || echo "")"
  if [[ "$status" == "healthy" ]]; then
    ok "postgres 已就绪"
    break
  fi
  sleep 1
done
if [[ "$status" != "healthy" ]]; then
  warn "postgres 健康检查未通过，继续尝试启动后端"
fi

# ---- 3. 启动 backend ----
if is_running "$BACKEND_PID_FILE"; then
  warn "backend 已在运行 (pid=$(cat "$BACKEND_PID_FILE"))，跳过"
else
  info "启动 backend (go run ./cmd/server)..."
  (
    cd "$REPO_ROOT/backend"
    nohup go run ./cmd/server >"$BACKEND_LOG" 2>&1 &
    echo $! > "$BACKEND_PID_FILE"
  )
  sleep 1
  if is_running "$BACKEND_PID_FILE"; then
    ok "backend 已启动 (pid=$(cat "$BACKEND_PID_FILE"))，日志: $BACKEND_LOG"
  else
    error "backend 启动失败，请查看 $BACKEND_LOG"
  fi
fi

# ---- 4. 启动 web ----
if is_running "$WEB_PID_FILE"; then
  warn "web 已在运行 (pid=$(cat "$WEB_PID_FILE"))，跳过"
else
  if [[ ! -d "$REPO_ROOT/web/node_modules" ]]; then
    info "web/node_modules 不存在，先执行 pnpm install..."
    (cd "$REPO_ROOT/web" && pnpm install) || {
      error "pnpm install 失败"
      exit 1
    }
  fi
  info "启动 web (pnpm dev)..."
  (
    cd "$REPO_ROOT/web"
    nohup pnpm dev >"$WEB_LOG" 2>&1 &
    echo $! > "$WEB_PID_FILE"
  )
  sleep 1
  if is_running "$WEB_PID_FILE"; then
    ok "web 已启动 (pid=$(cat "$WEB_PID_FILE"))，日志: $WEB_LOG"
  else
    error "web 启动失败，请查看 $WEB_LOG"
  fi
fi

echo ""
ok "开发环境已启动"
echo "  - postgres : docker container investment-postgres (5432)"
echo "  - backend  : http://localhost:${BFF_HTTP_ADDR:-8081}  (log: $BACKEND_LOG)"
echo "  - web      : http://localhost:3000                    (log: $WEB_LOG)"
echo ""
echo "查看日志: tail -f $BACKEND_LOG | tail -f $WEB_LOG"
echo "停止环境: make dev-end"
