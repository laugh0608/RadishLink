#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runner_path="${repo_root}/scripts/run-sw-g2-mls-rs-license-upstream-clarification.py"
plan_path="${repo_root}/docs/testing/sw-g2-mls-rs-debug-tree-upstream-clarification-plan.md"
artifact_root="${repo_root}/artifacts/sw-g2-mls-rs-license-upstream-clarification"
self_test_parent="${TMPDIR:-/tmp}"

for command_name in bash cmp dirname find git mktemp perl python3 pwd rg rm shasum sort; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done
for required_file in "${runner_path}" "${plan_path}"; do
  if [ ! -f "${required_file}" ] || [ -L "${required_file}" ]; then
    echo "required R1d-U file is missing or is a symbolic link: ${required_file}" >&2
    exit 1
  fi
done
if [ ! -d "${self_test_parent}" ] || [ -L "${self_test_parent}" ]; then
  echo "self-test parent is missing or is a symbolic link" >&2
  exit 1
fi
self_test_parent="$(CDPATH= cd -- "${self_test_parent}" && pwd -P)"
self_test_dir="$(mktemp -d "${self_test_parent}/radishlink-r1d-u-check.XXXXXX")"

cleanup() {
  case "${self_test_dir}" in
    "${self_test_parent}"/radishlink-r1d-u-check.*)
      rm -rf -- "${self_test_dir}"
      ;;
    *)
      echo "refusing to remove unexpected self-test directory: ${self_test_dir}" >&2
      return 1
      ;;
  esac
}
trap cleanup EXIT INT TERM

python3 - "${runner_path}" "${plan_path}" "${repo_root}" <<'PY'
from pathlib import Path
import ast
import runpy
import sys

runner_path = Path(sys.argv[1])
plan_path = Path(sys.argv[2])
repo_root = Path(sys.argv[3])
source = runner_path.read_text(encoding="utf-8")
compile(source, str(runner_path), "exec")
tree = ast.parse(source)
imports = {
    node.names[0].name
    for node in ast.walk(tree)
    if isinstance(node, ast.Import) and node.names
}
imports.update(
    node.module
    for node in ast.walk(tree)
    if isinstance(node, ast.ImportFrom) and node.module
)
assert not ({"requests", "httpx"} & imports)

module = runpy.run_path(str(runner_path), run_name="sw_g2_r1d_u_contract")
assert module["SCHEMA_VERSION"] == 1
assert module["MANIFEST_CONTRACT"] == "sw-g2-mls-rs-license-upstream-clarification-v1"
assert module["PLAN_REVISION"] == "2879dfb32f21107914073fc820cd2450ca3951dc"
assert module["PLAN_SHA256"] == "eaa3550927a44b910bc798563217d86146a77a66fd54bda00f708c0a26c4920d"
assert module["R1C_MANIFEST_SHA256"] == "f523347df20de4c654976f7b16107ad8e86227db90853327d36e225ce6270203"
assert module["PACKAGE"] == "debug_tree"
assert module["VERSION"] == "0.4.0"
assert module["REGISTRY_CHECKSUM"] == "2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57"
assert module["REPOSITORY"] == "martypapa/debug-tree"
assert module["COMMIT"] == "5b709de2d8872102b20b566c408d31d0662d7a9f"
assert module["TREE"] == "edc1ea9120f5d4070eb0fa60c77ab0da4c8a3e92"
assert module["TITLE_SHA256"] == "aa627aa1f8c9da8cac0805c5a28744bb76a1b8e123e3fbefdac296648ab3f01a"
assert module["BODY_SHA256"] == "38fd3a3115c216ec5455a7b0abd550e92676dc1345b20870b1006305c8a1bdb8"
assert module["CREATE_REQUEST_LIMIT"] == 20
assert module["READ_REQUEST_LIMIT"] == 10
assert module["POST_LIMIT"] == 1
assert module["DOWNLOAD_LIMIT_BYTES"] == 5 * 1024 * 1024
assert module["EVIDENCE_LIMIT_BYTES"] == 20 * 1024 * 1024
assert module["DEADLINE_SECONDS"] == 300
assert module["REQUEST_TIMEOUT_SECONDS"] == 30
assert module["API_HOST"] == "api.github.com"
assert len(source.splitlines()) < 1500

plan_text = plan_path.read_text(encoding="utf-8")
begin = plan_text.index("<!-- R1D_U_ISSUE_BODY_BEGIN -->")
end = plan_text.index("<!-- R1D_U_ISSUE_BODY_END -->")
body_block = plan_text[begin:end].split("```text\n", 1)[1].rsplit("```", 1)[0]
assert body_block == module["ISSUE_BODY"]
assert module["sha256_bytes"](module["ISSUE_TITLE"].encode("utf-8")) == module["TITLE_SHA256"]
assert module["sha256_bytes"](module["ISSUE_BODY"].encode("utf-8")) == module["BODY_SHA256"]
module["validate_plan_inputs"](repo_root)

artifact_root = repo_root / module["ARTIFACT_RELATIVE"]
if artifact_root.exists():
    assert artifact_root.is_dir() and not artifact_root.is_symlink()
    for child in sorted(artifact_root.iterdir()):
        assert child.is_dir() and not child.is_symlink()
        assert not child.name.startswith(".") and module["RUN_ID"].fullmatch(child.name)
        module["validate_evidence"](repo_root, child)
PY

for required_guard in \
  'ProxyHandler({})' \
  'NoRedirectHandler' \
  'gh", "auth", "token"' \
  'Authorization": f"Bearer {self.token}"' \
  'post-intent.json' \
  'ambiguous-external-write' \
  'retry_count": 0' \
  'background_processes_started": 0' \
  'FORBIDDEN_EVIDENCE' \
  'SAFE_RESPONSE_HEADERS' \
  'filter_account=True' \
  'response_records' \
  'validate_response_assessment' \
  'R1d-U-X' \
  'R1d-U-R'; do
  if ! rg -Fq -- "${required_guard}" "${runner_path}"; then
    echo "R1d-U helper guard is missing: ${required_guard}" >&2
    exit 1
  fi
done
if rg -n -- 'requests\.|httpx\.|urlretrieve|os\.environ|os\.getenv|PATCH|PUT|DELETE|GraphQL' "${runner_path}" >/dev/null; then
  echo "R1d-U helper contains a prohibited client, credential source, or write method" >&2
  exit 1
fi
if [ "$(rg -Foc -- 'self.opener.open(' "${runner_path}")" -ne 1 ]; then
  echo "R1d-U helper must keep one bounded network call site" >&2
  exit 1
fi
if [ "$(rg -Foc -- '"POST"' "${runner_path}")" -lt 1 ]; then
  echo "R1d-U helper lacks its single-POST contract" >&2
  exit 1
fi

python3 "${runner_path}" self-test

snapshot_artifacts() {
  local output_path="$1"
  if [ -d "${artifact_root}" ] && [ ! -L "${artifact_root}" ]; then
    find "${artifact_root}" -mindepth 1 -maxdepth 1 -print | LC_ALL=C sort >"${output_path}"
  elif [ ! -e "${artifact_root}" ] && [ ! -L "${artifact_root}" ]; then
    printf '%s\n' '<absent>' >"${output_path}"
  else
    echo "clarification artifact root is not a regular directory" >&2
    return 1
  fi
}

expect_exit() {
  local expected="$1"
  shift
  set +e
  "$@" >"${self_test_dir}/stdout" 2>"${self_test_dir}/stderr"
  local actual="$?"
  set -e
  if [ "${actual}" -ne "${expected}" ]; then
    echo "expected exit ${expected}, received ${actual}: $*" >&2
    return 1
  fi
}

snapshot_artifacts "${self_test_dir}/artifacts.before"
expect_exit 2 python3 "${runner_path}"
expect_exit 2 python3 "${runner_path}" unknown
expect_exit 2 python3 "${runner_path}" preflight INVALID
expect_exit 10 python3 "${runner_path}" preflight 0000000000000000000000000000000000000000
expect_exit 2 python3 "${runner_path}" create-issue 0000000000000000000000000000000000000000 bad_login
expect_exit 10 python3 "${runner_path}" create-issue 0000000000000000000000000000000000000000 radish-test --authorized-r1d-u-x
expect_exit 2 python3 "${runner_path}" collect-response 0000000000000000000000000000000000000000 INVALID radish-test --authorized-r1d-u-r
snapshot_artifacts "${self_test_dir}/artifacts.after"
if ! cmp -s "${self_test_dir}/artifacts.before" "${self_test_dir}/artifacts.after"; then
  echo "rejected/offline invocations changed the clarification artifact root" >&2
  exit 1
fi

echo "SW-EXP-003 debug_tree upstream clarification helper check: PASS"
