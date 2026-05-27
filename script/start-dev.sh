#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/log/dev"

source "${ROOT_DIR}/script/lib/env.sh"
load_env_file "${ROOT_DIR}/.env"

PYTHON_BIN="${PYTHON_BIN:-python3}"
GO_BIN="${GO_BIN:-go}"
PNPM_BIN="${PNPM_BIN:-pnpm}"

PYTHON_CMD="$(command -v "${PYTHON_BIN}")"
GO_CMD="$(command -v "${GO_BIN}")"
PNPM_CMD="$(command -v "${PNPM_BIN}")"

AGENT_GRPC_HOST="${AGENT_GRPC_HOST:-127.0.0.1}"
AGENT_GRPC_PORT="${AGENT_GRPC_PORT:-9010}"
AGENT_GRPC_BIND_ADDR="${AGENT_GRPC_BIND_ADDR:-${AGENT_GRPC_HOST}:${AGENT_GRPC_PORT}}"
AGENT_GRPC_ADDR="${AGENT_GRPC_ADDR:-${AGENT_GRPC_HOST}:${AGENT_GRPC_PORT}}"
BFF_PORT="${BFF_PORT:-8081}"
FRONTED_PORT="${FRONTED_PORT:-3000}"
NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://127.0.0.1:${BFF_PORT}}"

AGENT_PID_FILE="${RUNTIME_DIR}/agent.pid"
BFF_PID_FILE="${RUNTIME_DIR}/bff.pid"
FRONTED_PID_FILE="${RUNTIME_DIR}/fronted.pid"

AGENT_LOG_FILE="${RUNTIME_DIR}/agent.log"
BFF_LOG_FILE="${RUNTIME_DIR}/bff.log"
FRONTED_LOG_FILE="${RUNTIME_DIR}/fronted.log"

BFF_BIN_DIR="${RUNTIME_DIR}/bin"
BFF_BIN="${BFF_BIN_DIR}/bff"

STARTUP_COMPLETE=0
STARTED_PID_FILES=()

mkdir -p "${RUNTIME_DIR}"

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

is_pid_running() {
  local pid=$1
  kill -0 "${pid}" 2>/dev/null
}

read_pid() {
  local pid_file=$1
  if [[ -f "${pid_file}" ]]; then
    tr -d '[:space:]' <"${pid_file}"
  fi
}

ensure_not_running() {
  local name=$1
  local pid_file=$2
  local pid

  pid="$(read_pid "${pid_file}")"
  if [[ -n "${pid}" ]] && is_pid_running "${pid}"; then
    echo "[start-dev] ${name} 已在运行，PID=${pid}。如需重启请先执行 make dev-stop。" >&2
    exit 1
  fi

  rm -f "${pid_file}"
}

cleanup_on_error() {
  local exit_code=$?

  if [[ "${STARTUP_COMPLETE}" -eq 1 ]]; then
    exit "${exit_code}"
  fi

  for ((idx = ${#STARTED_PID_FILES[@]} - 1; idx >= 0; idx -= 1)); do
    local pid_file="${STARTED_PID_FILES[idx]}"
    local pid
    pid="$(read_pid "${pid_file}")"
    if [[ -n "${pid}" ]] && is_pid_running "${pid}"; then
      kill "${pid}" 2>/dev/null || true
    fi
    rm -f "${pid_file}"
  done

  exit "${exit_code}"
}

trap cleanup_on_error EXIT INT TERM

wait_for_tcp() {
  local host=$1
  local port=$2
  local name=$3
  local pid=$4
  local retries=${5:-60}

  for ((i = 1; i <= retries; i += 1)); do
    if ! is_pid_running "${pid}"; then
      echo "[start-dev] ${name} 进程已退出，请查看日志。" >&2
      return 1
    fi

    if nc -z "${host}" "${port}" >/dev/null 2>&1; then
      return 0
    fi

    sleep 1
  done

  echo "[start-dev] ${name} 未在 ${host}:${port} 就绪。" >&2
  return 1
}

wait_for_http() {
  local url=$1
  local name=$2
  local pid=$3
  local retries=${4:-60}

  for ((i = 1; i <= retries; i += 1)); do
    if ! is_pid_running "${pid}"; then
      echo "[start-dev] ${name} 进程已退出，请查看日志。" >&2
      return 1
    fi

    if curl --silent --fail "${url}" >/dev/null 2>&1; then
      return 0
    fi

    sleep 1
  done

  echo "[start-dev] ${name} 健康检查失败：${url}" >&2
  return 1
}

start_process() {
  local name=$1
  local pid_file=$2
  local log_file=$3
  shift 3

  printf '[%s] %s\n' "$(timestamp)" "starting ${name}" >>"${log_file}"
  nohup "$@" >>"${log_file}" 2>&1 &
  local pid=$!
  echo "${pid}" >"${pid_file}"
  STARTED_PID_FILES+=("${pid_file}")
  echo "${pid}"
}

build_bff_binary() {
  mkdir -p "${BFF_BIN_DIR}"
  echo "[start-dev] 构建 Go BFF..."
  (
    cd "${ROOT_DIR}/backend"
    "${GO_CMD}" build -o "${BFF_BIN}" ./cmd/bff
  )
}

ensure_not_running "agent server" "${AGENT_PID_FILE}"
ensure_not_running "Go BFF" "${BFF_PID_FILE}"
ensure_not_running "fronted" "${FRONTED_PID_FILE}"

echo "[start-dev] 启动 agent server (${AGENT_GRPC_BIND_ADDR})..."
AGENT_PID="$(start_process \
  "agent" \
  "${AGENT_PID_FILE}" \
  "${AGENT_LOG_FILE}" \
  env \
  "PYTHONPATH=${ROOT_DIR}/agent/app/gen${PYTHONPATH:+:${PYTHONPATH}}" \
  "AGENT_GRPC_BIND_ADDR=${AGENT_GRPC_BIND_ADDR}" \
  "PWD=${ROOT_DIR}/agent" \
  bash -c "cd '${ROOT_DIR}/agent' && exec '${PYTHON_CMD}' -m app.server")"

wait_for_tcp "${AGENT_GRPC_HOST}" "${AGENT_GRPC_PORT}" "agent server" "${AGENT_PID}"

build_bff_binary

echo "[start-dev] 启动 Go BFF (http://127.0.0.1:${BFF_PORT})..."
BFF_PID="$(start_process \
  "bff" \
  "${BFF_PID_FILE}" \
  "${BFF_LOG_FILE}" \
  env \
  "AGENT_GRPC_ADDR=${AGENT_GRPC_ADDR}" \
  "BFF_HTTP_ADDR=127.0.0.1:${BFF_PORT}" \
  "PWD=${ROOT_DIR}/backend" \
  bash -c "cd '${ROOT_DIR}/backend' && exec '${BFF_BIN}'")"

wait_for_http "http://127.0.0.1:${BFF_PORT}/healthz" "Go BFF" "${BFF_PID}"

echo "[start-dev] 启动 fronted (http://127.0.0.1:${FRONTED_PORT})..."
FRONTED_PID="$(start_process \
  "fronted" \
  "${FRONTED_PID_FILE}" \
  "${FRONTED_LOG_FILE}" \
  env \
  "NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}" \
  "PWD=${ROOT_DIR}/fronted" \
  bash -c "cd '${ROOT_DIR}/fronted' && exec '${PNPM_CMD}' dev")"

wait_for_http "http://127.0.0.1:${FRONTED_PORT}" "fronted" "${FRONTED_PID}" 90

STARTUP_COMPLETE=1

echo "[start-dev] 全部服务已启动。"
echo "[start-dev] agent   PID=${AGENT_PID} log=${AGENT_LOG_FILE}"
echo "[start-dev] bff     PID=${BFF_PID} log=${BFF_LOG_FILE}"
echo "[start-dev] fronted PID=${FRONTED_PID} log=${FRONTED_LOG_FILE}"
echo "[start-dev] 停止服务请执行: make dev-stop"
