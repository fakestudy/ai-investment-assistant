#!/usr/bin/env bash
# 启动本地开发环境：postgres/nginx/pgweb (docker) + backend (go) + web (pnpm)
# 不再使用 backend / web 的 Docker 镜像，二者直接以脚本进程方式运行。

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/dev-config.sh"

RUN_DIR="${DEV_RUN_DIR:-$REPO_ROOT/.run}"
LOG_DIR="${DEV_LOG_DIR:-$RUN_DIR/logs}"
mkdir -p "$RUN_DIR" "$LOG_DIR"

BACKEND_PID_FILE="$RUN_DIR/backend.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
WEB_LOG="$LOG_DIR/web.log"

# ---- 输出辅助 ----
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'
  C_BLU=$'\033[34m'; C_MAG=$'\033[35m'; C_CYN=$'\033[36m'
  C_DIM=$'\033[2m'; C_BLD=$'\033[1m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_MAG=""; C_CYN=""
  C_DIM=""; C_BLD=""; C_RST=""
fi

info()  { echo "${C_BLU}[dev-start]${C_RST} $*"; }
ok()    { echo "${C_GRN}[dev-start]${C_RST} $*"; }
warn()  { echo "${C_YLW}[dev-start]${C_RST} $*"; }
error() { echo "${C_RED}[dev-start]${C_RST} $*" 1>&2; }

show_startup_animation() {
  [[ -t 1 ]] || return 0
  local frames=("✦" "✧" "✶" "✷" "✹" "✸")
  local frame
  for frame in "${frames[@]}" "${frames[@]}"; do
    printf "\r${C_MAG}%s${C_RST} ${C_BLD}AI Investment Assistant${C_RST} ${C_DIM}正在点亮本地入口...${C_RST}" "$frame"
    sleep 0.07
  done
  printf "\r%80s\r" ""
}

print_ready_banner() {
  show_startup_animation
  echo "${C_BLD}${C_CYN}╭────────────────────────────────────────────────────────╮${C_RST}"
  echo "${C_BLD}${C_CYN}│${C_RST} ${C_MAG}✦ AIA ✦${C_RST}  ${C_BLD}AI Investment Assistant${C_RST}                  ${C_BLD}${C_CYN}│${C_RST}"
  echo "${C_BLD}${C_CYN}│${C_RST} ${C_GRN}本地入口已就绪${C_RST}                                      ${C_BLD}${C_CYN}│${C_RST}"
  echo "${C_BLD}${C_CYN}│${C_RST}                                                        ${C_BLD}${C_CYN}│${C_RST}"
  echo "${C_BLD}${C_CYN}│${C_RST}  ${C_BLD}访问 / 登录${C_RST}  ${C_GRN}http://localhost:3000${C_RST}                 ${C_BLD}${C_CYN}│${C_RST}"
  echo "${C_BLD}${C_CYN}│${C_RST}  ${C_DIM}Nginx 3000 -> Web 3001 -> Backend 8081${C_RST}          ${C_BLD}${C_CYN}│${C_RST}"
  echo "${C_BLD}${C_CYN}╰────────────────────────────────────────────────────────╯${C_RST}"
}

# ---- 进程辅助 ----
is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

# ---- 1. 加载 .env ----
ENV_FILE="${DEV_ENV_FILE:-$REPO_ROOT/.env}"
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

if ! BACKEND_HTTP_URL="$(backend_http_url "${BFF_HTTP_ADDR:-}")"; then
  error "BFF_HTTP_ADDR 必须是 :port 或 host:port"
  exit 1
fi

# ---- 2. 启动 docker compose 服务 ----
info "启动 postgres、nginx 与 pgweb 容器..."
if ! docker compose up -d --remove-orphans postgres nginx pgweb >/dev/null; then
  error "docker compose up --remove-orphans postgres nginx pgweb 失败"
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
    exit 1
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
    exit 1
  fi
fi

echo ""
ok "开发环境已启动"
echo ""
print_ready_banner
echo ""
echo "服务明细:"
echo "  - postgres : docker container investment-postgres (5432)"
echo "  - pgweb    : http://localhost:8082"
echo "  - nginx    : http://localhost:3000"
echo "  - backend  : $BACKEND_HTTP_URL  (log: $BACKEND_LOG)"
echo "  - web      : http://localhost:3001                    (log: $WEB_LOG)"
echo ""
echo "查看日志: tail -f $BACKEND_LOG | tail -f $WEB_LOG"
echo "${C_YLW}${C_BLD}停止环境: make dev-stop${C_RST}"
