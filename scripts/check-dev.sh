#!/usr/bin/env bash
# 检测当前宿主机是否满足 ai-investment-assistant 的启动条件。
# 仅做检查，不做任何安装或修改操作。

set -u

# ---- 输出辅助 ----
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'
  C_BLU=$'\033[34m'; C_BLD=$'\033[1m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YLW=""; C_BLU=""; C_BLD=""; C_RST=""
fi

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

ok()   { echo "  ${C_GRN}✓${C_RST} $*"; PASS_COUNT=$((PASS_COUNT+1)); }
warn() { echo "  ${C_YLW}!${C_RST} $*"; WARN_COUNT=$((WARN_COUNT+1)); }
fail() { echo "  ${C_RED}✗${C_RST} $*"; FAIL_COUNT=$((FAIL_COUNT+1)); }
section() { echo ""; echo "${C_BLD}${C_BLU}== $* ==${C_RST}"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
source "$REPO_ROOT/scripts/dev-config.sh"

echo "${C_BLD}AI Investment Assistant - 开发环境检测${C_RST}"
echo "项目根目录: $REPO_ROOT"

# ---------------- 0. 平台检测 ----------------
section "0. 平台"

UNAME_S="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME_S" in
  Darwin|Linux)
    ok "操作系统: $UNAME_S"
    ;;
  MINGW*|MSYS*|CYGWIN*)
    fail "检测到原生 Windows 环境 ($UNAME_S)：本项目脚本依赖 bash / lsof / nohup / 进程组信号等 Unix 语义，不支持在 Git Bash / MSYS / Cygwin 下直接运行"
    echo ""
    echo "${C_YLW}请改用 WSL2 (Ubuntu 22.04+) 并在其中重新执行 make check-dev。${C_RST}"
    exit 1
    ;;
  *)
    warn "未识别的操作系统: $UNAME_S（仅在 macOS / Linux 上验证过）"
    ;;
esac

# ---------------- 1. 系统工具 ----------------
section "1. 系统工具"

for cmd in git make bash; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd 已安装 ($("$cmd" --version 2>/dev/null | head -n1))"
  else
    fail "$cmd 未安装"
  fi
done

if command -v docker >/dev/null 2>&1; then
  ok "docker 已安装 ($(docker --version 2>/dev/null))"
  if docker info >/dev/null 2>&1; then
    ok "docker daemon 正在运行"
  else
    fail "docker daemon 未运行 (请启动 Docker Desktop / dockerd)"
  fi
else
  fail "docker 未安装"
fi

if docker compose version >/dev/null 2>&1; then
  ok "docker compose 可用 ($(docker compose version --short 2>/dev/null))"
elif command -v docker-compose >/dev/null 2>&1; then
  warn "仅检测到旧版 docker-compose，建议升级到 docker compose v2"
else
  fail "docker compose 不可用"
fi

# ---------------- 2. 工具链版本 ----------------
section "2. 工具链版本"

# Node: 期望 == 22.22.2 (mise.toml)
NODE_EXPECT="22.22.2"
if command -v node >/dev/null 2>&1; then
  NODE_VER="$(node --version 2>/dev/null | sed 's/^v//')"
  if [[ "$NODE_VER" == "$NODE_EXPECT" ]]; then
    ok "node $NODE_VER"
  else
    warn "node $NODE_VER (期望 $NODE_EXPECT；可执行 'mise install' 同步)"
  fi
else
  fail "node 未安装 (期望 $NODE_EXPECT)"
fi

# pnpm: 期望 == 10.32.1
PNPM_EXPECT="10.32.1"
if command -v pnpm >/dev/null 2>&1; then
  PNPM_VER="$(pnpm --version 2>/dev/null)"
  if [[ "$PNPM_VER" == "$PNPM_EXPECT" ]]; then
    ok "pnpm $PNPM_VER"
  else
    warn "pnpm $PNPM_VER (期望 $PNPM_EXPECT)"
  fi
else
  fail "pnpm 未安装 (期望 $PNPM_EXPECT)"
fi

# uv: agent 依赖与启动入口
UV_EXPECT="0.11.7"
if command -v uv >/dev/null 2>&1; then
  UV_VER="$(uv --version 2>/dev/null | awk '{print $2}')"
  if [[ "$UV_VER" == "$UV_EXPECT" ]]; then
    ok "uv $UV_VER"
  else
    warn "uv $UV_VER (期望 $UV_EXPECT)"
  fi
else
  fail "uv 未安装 (agent 启动必需)"
fi

# ---------------- 3. 环境变量 ----------------
section "3. 环境变量 (.env)"

ENV_FILE="$REPO_ROOT/.env"
ENV_FILE_EXISTS=0
if [[ -f "$ENV_FILE" ]]; then
  ok ".env 文件存在"
  ENV_FILE_EXISTS=1
  # 安全加载 .env（只读取键值，不执行）
  load_env_value() {
    local key="$1"
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -n1 | sed -E "s/^${key}=//; s/^['\"]//; s/['\"]$//"
  }
else
  fail ".env 文件不存在 (必需)，请参考 .env.example 创建: cp .env.example .env"
  load_env_value() { echo ""; }
fi

# 必填
REQUIRED_VARS=(DEEPSEEK_API_KEY TAVILY_API_KEY)
for var in "${REQUIRED_VARS[@]}"; do
  val="${!var:-}"
  [[ -z "$val" ]] && val="$(load_env_value "$var")"
  if [[ -n "$val" ]]; then
    ok "$var 已设置"
  else
    if (( ENV_FILE_EXISTS == 1 )); then
      fail "$var 未设置 (必填，需在 .env 中填入有效 key)"
    else
      fail "$var 未设置 (必填，请先创建 .env 并填入有效 key)"
    fi
  fi
done

# 提示性
OPTIONAL_VARS=(
  DATABASE_URL
  DEEPSEEK_BASE_URL
  DEEPSEEK_MODEL
  DEEPSEEK_TIMEOUT_SECONDS
  BFF_HTTP_ADDR
  TAVILY_BASE_URL
  FETCH_ALLOW_PRIVATE
)
for var in "${OPTIONAL_VARS[@]}"; do
  val="${!var:-}"
  [[ -z "$val" ]] && val="$(load_env_value "$var")"
  if [[ -n "$val" ]]; then
    ok "$var 已设置"
  else
    warn "$var 未设置 (可使用代码内默认值)"
  fi
done

# ---------------- 4. 端口占用 ----------------
section "4. 端口占用"

check_port() {
  local port="$1" label="$2" level="$3" # level: fail|warn
  local pid=""
  if command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n1)"
  elif command -v ss >/dev/null 2>&1; then
    pid="$(ss -ltnp "sport = :$port" 2>/dev/null | awk 'NR>1 {print $0}' | head -n1)"
  fi

  if [[ -z "$pid" ]]; then
    ok "端口 $port ($label) 空闲"
  else
    if [[ "$level" == "warn" ]]; then
      warn "端口 $port ($label) 已被占用 (pid=$pid)"
    else
      fail "端口 $port ($label) 已被占用 (pid=$pid)"
    fi
  fi
}

if ! BACKEND_HTTP_PORT="$(backend_http_port "${BFF_HTTP_ADDR:-$(load_env_value BFF_HTTP_ADDR)}")"; then
  fail "BFF_HTTP_ADDR 格式无效，必须是 :port 或 host:port"
  BACKEND_HTTP_PORT=""
fi

check_port 3001 "web/Next.js"       fail
if [[ -n "$BACKEND_HTTP_PORT" ]]; then
  check_port "$BACKEND_HTTP_PORT" "agent/FastAPI" fail
fi
check_port 3000 "nginx/reverse proxy" fail
check_port 5432 "postgres"          warn

# ---------------- 5. 汇总 ----------------
section "汇总"
echo "  通过: ${C_GRN}${PASS_COUNT}${C_RST}   警告: ${C_YLW}${WARN_COUNT}${C_RST}   失败: ${C_RED}${FAIL_COUNT}${C_RST}"

if (( FAIL_COUNT > 0 )); then
  echo ""
  echo "${C_RED}存在阻断项，请先修复后再启动项目。${C_RST}"
  exit 1
fi

if (( WARN_COUNT > 0 )); then
  echo ""
  echo "${C_YLW}存在警告项，可以启动但建议关注。${C_RST}"
  exit 0
fi

echo ""
echo "${C_GRN}环境检测全部通过，可以启动项目。${C_RST}"
exit 0
