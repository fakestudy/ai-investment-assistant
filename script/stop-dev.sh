#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/log/dev"

AGENT_PID_FILE="${RUNTIME_DIR}/agent.pid"
BFF_PID_FILE="${RUNTIME_DIR}/bff.pid"
FRONTED_PID_FILE="${RUNTIME_DIR}/fronted.pid"

read_pid() {
  local pid_file=$1
  if [[ -f "${pid_file}" ]]; then
    tr -d '[:space:]' <"${pid_file}"
  fi
}

is_pid_running() {
  local pid=$1
  kill -0 "${pid}" 2>/dev/null
}

stop_process() {
  local name=$1
  local pid_file=$2
  local pid

  pid="$(read_pid "${pid_file}")"
  if [[ -z "${pid}" ]]; then
    echo "[dev-stop] ${name} 未记录 PID，跳过。"
    rm -f "${pid_file}"
    return 0
  fi

  if ! is_pid_running "${pid}"; then
    echo "[dev-stop] ${name} PID=${pid} 已不存在，清理 PID 文件。"
    rm -f "${pid_file}"
    return 0
  fi

  echo "[dev-stop] 停止 ${name} (PID=${pid})..."
  kill "${pid}" 2>/dev/null || true

  for _ in {1..20}; do
    if ! is_pid_running "${pid}"; then
      rm -f "${pid_file}"
      echo "[dev-stop] ${name} 已停止。"
      return 0
    fi
    sleep 1
  done

  echo "[dev-stop] ${name} 超时未退出，发送 SIGKILL。"
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${pid_file}"
}

mkdir -p "${RUNTIME_DIR}"

stop_process "fronted" "${FRONTED_PID_FILE}"
stop_process "Go BFF" "${BFF_PID_FILE}"
stop_process "agent server" "${AGENT_PID_FILE}"

echo "[dev-stop] 本地开发服务已处理完毕。"
