#!/usr/bin/env bash
set -euo pipefail
I5_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
case "${1:-}" in
  preflight) [[ $# == 1 ]] || exit 2 ;;
  run) [[ $# == 5 && $2 == --matrix && $3 == i5-seven-v1 && $4 == --repeats && $5 == 3 ]] || exit 2 ;;
  *) echo 'usage: run-sw-i5-harness.sh preflight | run --matrix i5-seven-v1 --repeats 3' >&2; exit 2 ;;
esac
[[ -z "$(git -C "${I5_ROOT}" status --porcelain)" ]] || { echo 'I5 requires a clean source tree' >&2; exit 2; }
mkdir -p "${I5_ROOT}/.tmp"
I5_BOOTSTRAP="$(mktemp -d "${I5_ROOT}/.tmp/i5-bootstrap.XXXXXX")"
# Both modes use the same contract checker; this bootstrap never invokes Docker.
python3 - "${I5_ROOT}" "${I5_BOOTSTRAP}/sw-v0-harness" <<'PYTHON'
import os
import subprocess
import sys
root, binary = sys.argv[1:]
env = dict(os.environ, GOTOOLCHAIN='local', GOPROXY='off', GOSUMDB='off')
subprocess.run(['go', 'build', '-trimpath', '-o', binary, './cmd/sw-v0-harness'], cwd=os.path.join(root, 'tools/t0'), env=env, check=True, timeout=300)
PYTHON
if [[ $1 == preflight ]]; then
  exec "${I5_BOOTSTRAP}/sw-v0-harness" synthetic-run --repo-root "${I5_ROOT}" --preflight
fi
exec "${I5_BOOTSTRAP}/sw-v0-harness" synthetic-run --repo-root "${I5_ROOT}" --matrix i5-seven-v1 --repeats 3
