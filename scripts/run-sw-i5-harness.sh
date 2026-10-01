#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  preflight) [[ $# == 1 ]] || exit 2 ;;
  run) [[ $# == 5 && $2 == --matrix && $3 == i5-seven-v1 && $4 == --repeats && $5 == 3 ]] || exit 2 ;;
  *) echo 'usage: run-sw-i5-harness.sh preflight | run --matrix i5-seven-v1 --repeats 3' >&2; exit 2 ;;
esac
# Even preflight used to build an unconfined bootstrap before checking resources.
# Keep this stop before any filesystem write or external command. Re-enabling
# requires the isolation implementation and evidence described in the design.
printf '%s\n' 'I5_RESOURCE_ISOLATION_REQUIRED: the 768 MiB batch storage boundary is not implemented; see docs/testing/sw-g4-synthetic-i5-resource-isolation.md' >&2
exit 2
