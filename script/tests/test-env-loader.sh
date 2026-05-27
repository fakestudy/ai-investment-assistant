#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

source "${ROOT_DIR}/script/lib/env.sh"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

ENV_FILE="${TMP_DIR}/.env"
cat >"${ENV_FILE}" <<'ENV'
# local development settings
DEEPSEEK_API_KEY=from-env-file
DEEPSEEK_MODEL=deepseek-test
QUOTED_VALUE="hello world"
export EXPORTED_VALUE=from-export
ENV

unset DEEPSEEK_API_KEY DEEPSEEK_MODEL QUOTED_VALUE EXPORTED_VALUE

load_env_file "${ENV_FILE}"

[[ "${DEEPSEEK_API_KEY}" == "from-env-file" ]]
[[ "${DEEPSEEK_MODEL}" == "deepseek-test" ]]
[[ "${QUOTED_VALUE}" == "hello world" ]]
[[ "${EXPORTED_VALUE}" == "from-export" ]]

DEEPSEEK_MODEL=from-shell
load_env_file "${ENV_FILE}"

[[ "${DEEPSEEK_MODEL}" == "from-shell" ]]
