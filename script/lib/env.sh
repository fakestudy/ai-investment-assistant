#!/usr/bin/env bash

load_env_file() {
  local env_file=$1
  local line trimmed name value

  [[ -f "${env_file}" ]] || return 0

  while IFS= read -r line || [[ -n "${line}" ]]; do
    trimmed="${line#"${line%%[![:space:]]*}"}"
    trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"

    [[ -z "${trimmed}" || "${trimmed:0:1}" == "#" ]] && continue

    if [[ "${trimmed}" =~ ^export[[:space:]]+ ]]; then
      trimmed="${trimmed#export}"
      trimmed="${trimmed#"${trimmed%%[![:space:]]*}"}"
    fi

    [[ "${trimmed}" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue

    name="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"

    # Shell-provided env wins over .env so one-off overrides keep working.
    [[ -n "${!name+x}" ]] && continue

    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"

    if [[ "${value}" == \"*\" && "${value}" == *\" && "${#value}" -ge 2 ]]; then
      value="${value:1:${#value}-2}"
      value="${value//\\\"/\"}"
      value="${value//\\\\/\\}"
    elif [[ "${value}" == \'*\' && "${value}" == *\' && "${#value}" -ge 2 ]]; then
      value="${value:1:${#value}-2}"
    fi

    printf -v "${name}" '%s' "${value}"
    export "${name}"
  done <"${env_file}"
}
