#!/usr/bin/env bash
# 停止本地开发环境：web (pnpm) + agent (FastAPI) + postgres/nginx/pgweb (docker)

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

RUN_DIR="$REPO_ROOT/.run"
AGENT_PID_FILE="$RUN_DIR/agent.pid"
LEGACY_BACKEND_PID_FILE="$RUN_DIR/backend.pid"
WEB_PID_FILE="$RUN_DIR/web.pid"

if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'
  C_BLU=$'\033[34m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_RST=""
fi

info()  { echo "${C_BLU}[dev-stop]${C_RST} $*"; }
ok()    { echo "${C_GRN}[dev-stop]${C_RST} $*"; }
warn()  { echo "${C_YLW}[dev-stop]${C_RST} $*"; }

# 终止 pid 文件指向的进程及其子进程
stop_pid_file() {
  local label="$1" pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    warn "$label 未在运行 (无 pid 文件)"
    return 0
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    warn "$label 进程不存在 (pid=$pid)，清理 pid 文件"
    rm -f "$pid_file"
    return 0
  fi

  info "停止 $label (pid=$pid)..."
  # 终止整个进程组（uv run / pnpm dev 会派生子进程）
  local pgid
  pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
  if [[ -n "$pgid" ]]; then
    kill -TERM "-$pgid" 2>/dev/null || true
  else
    kill -TERM "$pid" 2>/dev/null || true
  fi

  for _ in $(seq 1 10); do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done

  if kill -0 "$pid" 2>/dev/null; then
    warn "$label 未在 5s 内退出，强制 kill"
    if [[ -n "$pgid" ]]; then
      kill -KILL "-$pgid" 2>/dev/null || true
    else
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi

  rm -f "$pid_file"
  ok "$label 已停止"
}

stop_pid_file "web" "$WEB_PID_FILE"
stop_pid_file "agent" "$AGENT_PID_FILE"
if [[ -f "$LEGACY_BACKEND_PID_FILE" ]]; then
  stop_pid_file "legacy backend" "$LEGACY_BACKEND_PID_FILE"
fi

# 停止 docker compose 服务
info "停止 postgres、nginx 与 pgweb 容器..."
if docker compose stop nginx postgres pgweb >/dev/null 2>&1; then
  ok "postgres、nginx 与 pgweb 已停止"
else
  warn "docker compose stop nginx postgres pgweb 失败 (可能未在运行)"
fi

ok "开发环境已停止"
