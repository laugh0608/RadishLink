#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
  exec python3 "${repo_root}/scripts/check-repo.py" "$@"
fi

if command -v python >/dev/null 2>&1; then
  exec python "${repo_root}/scripts/check-repo.py" "$@"
fi

echo "Python 3 is required to run repository baseline checks." >&2
exit 1
