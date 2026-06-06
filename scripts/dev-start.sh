#!/usr/bin/env bash
# 启动本地开发环境：postgres/nginx/pgweb (docker) + agent (FastAPI) + web (pnpm)
# 不再使用 agent / web 的 Docker 镜像，二者直接以脚本进程方式运行。

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/dev-config.sh"

RUN_DIR="${DEV_RUN_DIR:-$REPO_ROOT/.run}"
LOG_DIR="${DEV_LOG_DIR:-$RUN_DIR/logs}"
mkdir -p "$RUN_DIR" "$LOG_DIR"

AGENT_PID_FILE="$RUN_DIR/agent.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"
AGENT_LOG="$LOG_DIR/agent.log"
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
  local -a plain_lines=(
    "✦ AIA ✦  AI Investment Assistant"
    "本地入口已就绪"
    ""
    "  访问 / 登录  http://localhost:3000"
    "  Nginx 3000 -> Web 3001 -> Agent 8081"
    ""
    "服务明细:"
    "  - postgres : docker container investment-postgres (5432)"
    "  - pgweb    : http://localhost:8082"
    "  - nginx    : http://localhost:3000"
    "  - agent    : $AGENT_HTTP_URL  (log: $AGENT_LOG)"
    "  - web      : http://localhost:3001  (log: $WEB_LOG)"
  )
  local -a styled_lines=(
    "${C_MAG}✦ AIA ✦${C_RST}  ${C_BLD}AI Investment Assistant${C_RST}"
    "${C_GRN}本地入口已就绪${C_RST}"
    ""
    "  ${C_BLD}访问 / 登录${C_RST}  ${C_GRN}http://localhost:3000${C_RST}"
    "  ${C_DIM}Nginx 3000 -> Web 3001 -> Agent 8081${C_RST}"
    ""
    "${C_BLD}服务明细:${C_RST}"
    "  - postgres : docker container investment-postgres (5432)"
    "  - pgweb    : http://localhost:8082"
    "  - nginx    : http://localhost:3000"
    "  - agent    : $AGENT_HTTP_URL  ${C_DIM}(log: $AGENT_LOG)${C_RST}"
    "  - web      : http://localhost:3001  ${C_DIM}(log: $WEB_LOG)${C_RST}"
  )
  local width=56 line border pad i
  for line in "${plain_lines[@]}"; do
    (( ${#line} > width )) && width=${#line}
  done
  printf -v border '%*s' "$width" ''
  border="${border// /─}"
  echo "${C_BLD}${C_CYN}╭${border}╮${C_RST}"
  for i in "${!plain_lines[@]}"; do
    printf -v pad '%*s' "$((width - ${#plain_lines[$i]}))" ''
    echo "${C_BLD}${C_CYN}│${C_RST}${styled_lines[$i]}${pad}${C_BLD}${C_CYN}│${C_RST}"
  done
  echo "${C_BLD}${C_CYN}╰${border}╯${C_RST}"
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

if ! AGENT_HTTP_URL="$(backend_http_url "${BFF_HTTP_ADDR:-}")"; then
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
  warn "postgres 健康检查未通过，继续尝试启动 agent"
fi

# ---- 3. 启动 agent ----
if is_running "$AGENT_PID_FILE"; then
  warn "agent 已在运行 (pid=$(cat "$AGENT_PID_FILE"))，跳过"
else
  info "启动 agent (uv run python main.py)..."
  (
    cd "$REPO_ROOT/agent"
    nohup env PYTHONPYCACHEPREFIX=../.pycache uv run python main.py >"$AGENT_LOG" 2>&1 &
    echo $! > "$AGENT_PID_FILE"
  )
  sleep 1
  if ! is_running "$AGENT_PID_FILE"; then
    error "agent 启动失败，请查看 $AGENT_LOG"
    exit 1
  fi
  ok "agent 进程已拉起 (pid=$(cat "$AGENT_PID_FILE"))，日志: $AGENT_LOG"

  info "等待 agent HTTP 就绪 ($AGENT_HTTP_URL/api/health)..."
  agent_ready=0
  for _ in $(seq 1 60); do
    if ! is_running "$AGENT_PID_FILE"; then
      error "agent 进程已退出，请查看 $AGENT_LOG"
      exit 1
    fi
    if curl -fsS -o /dev/null "$AGENT_HTTP_URL/api/health" 2>/dev/null; then
      agent_ready=1
      break
    fi
    sleep 1
  done
  if [[ "$agent_ready" == "1" ]]; then
    ok "agent HTTP 已就绪"
  else
    error "agent HTTP 未在超时时间内就绪，请查看 $AGENT_LOG"
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
  if ! is_running "$WEB_PID_FILE"; then
    error "web 启动失败，请查看 $WEB_LOG"
    exit 1
  fi
  ok "web 进程已拉起 (pid=$(cat "$WEB_PID_FILE"))，日志: $WEB_LOG"

  # Next.js dev 首次访问路由才会现场编译，这里预热 /chat 并等待首屏可访问，
  # 避免「脚本提示已启动但刷新拿不到页面/数据」的竞态。
  info "等待 web 首屏就绪并预热 /chat..."
  web_ready=0
  for _ in $(seq 1 120); do
    if ! is_running "$WEB_PID_FILE"; then
      error "web 进程已退出，请查看 $WEB_LOG"
      exit 1
    fi
    if curl -fsS -o /dev/null "http://localhost:3001/chat" 2>/dev/null; then
      web_ready=1
      break
    fi
    sleep 1
  done
  if [[ "$web_ready" == "1" ]]; then
    ok "web 首屏已就绪"
  else
    error "web 首屏未在超时时间内就绪，请查看 $WEB_LOG"
    exit 1
  fi
fi

echo ""
ok "开发环境已启动"
echo ""
print_ready_banner
echo ""
echo "查看日志: tail -f $AGENT_LOG | tail -f $WEB_LOG"
echo "${C_YLW}${C_BLD}停止环境: make dev-stop${C_RST}"
