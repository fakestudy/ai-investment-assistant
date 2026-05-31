#!/usr/bin/env bash

backend_http_addr() {
  local addr="${1:-}"
  if [[ -z "$addr" ]]; then
    addr=":8081"
  fi
  if [[ "$addr" != :* && "$addr" != *:* ]]; then
    echo "BFF_HTTP_ADDR must be :port or host:port, got: $addr" >&2
    return 1
  fi
  local port
  if [[ "$addr" == :* ]]; then
    port="${addr#:}"
  else
    port="${addr##*:}"
  fi
  if [[ ! "$port" =~ ^[0-9]+$ ]]; then
    echo "BFF_HTTP_ADDR port must be numeric, got: $addr" >&2
    return 1
  fi
  printf '%s\n' "$addr"
}

backend_http_url() {
  local addr
  addr="$(backend_http_addr "${1:-}")" || return
  if [[ "$addr" == :* ]]; then
    printf 'http://localhost%s\n' "$addr"
    return
  fi
  printf 'http://%s\n' "$addr"
}

backend_http_port() {
  local addr
  addr="$(backend_http_addr "${1:-}")" || return
  if [[ "$addr" == :* ]]; then
    printf '%s\n' "${addr#:}"
    return
  fi
  printf '%s\n' "${addr##*:}"
}
