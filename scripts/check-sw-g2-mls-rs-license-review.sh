#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runner_path="${repo_root}/scripts/run-sw-g2-mls-rs-license-review.py"
artifact_root="${repo_root}/artifacts/sw-g2-mls-rs-license-review"
self_test_parent="${TMPDIR:-/tmp}"

for command_name in bash cmp dirname find git mktemp python3 pwd rg rm sort; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done
if [ ! -f "${runner_path}" ] || [ -L "${runner_path}" ]; then
  echo "R1c helper is missing or is a symbolic link" >&2
  exit 1
fi
if [ ! -d "${self_test_parent}" ] || [ -L "${self_test_parent}" ]; then
  echo "self-test parent is missing or is a symbolic link" >&2
  exit 1
fi
self_test_parent="$(CDPATH= cd -- "${self_test_parent}" && pwd -P)"
self_test_dir="$(mktemp -d "${self_test_parent}/radishlink-mls-rs-license-review-check.XXXXXX")"

cleanup() {
  case "${self_test_dir}" in
    "${self_test_parent}"/radishlink-mls-rs-license-review-check.*)
      rm -rf -- "${self_test_dir}"
      ;;
    *)
      echo "refusing to remove unexpected self-test directory: ${self_test_dir}" >&2
      return 1
      ;;
  esac
}
trap cleanup EXIT INT TERM

python3 - "${runner_path}" "${repo_root}" <<'PY'
from pathlib import Path
import ast
import runpy
import sys

path = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
source = path.read_text(encoding="utf-8")
compile(source, str(path), "exec")
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

module = runpy.run_path(str(path), run_name="sw_g2_mls_rs_license_review_contract")
packages = module["PACKAGES"]
commits = module["COMMITS"]
assert len(packages) == 11
assert len({(item.name, item.version) for item in packages}) == 11
assert len(commits) == 6
assert len({item.repository for item in commits}) == 3
assert {(item.repository, item.commit) for item in commits} == {
    (item.repository, item.commit) for item in packages
}
assert all(len(item.checksum) == 64 for item in packages)
assert all(len(item.commit) == 40 for item in packages)
assert module["REQUEST_LIMIT"] == 40
assert module["DOWNLOAD_LIMIT_BYTES"] == 50 * 1024 * 1024
assert module["EVIDENCE_LIMIT_BYTES"] == 100 * 1024 * 1024
assert module["DEADLINE_SECONDS"] == 600
assert module["ALLOWED_BLOB_MODES"] == {"100644"}
assert module["SCHEMA_VERSION"] == 2
assert module["MANIFEST_CONTRACT"] == "sw-g2-mls-rs-license-review-v2"
assert module["LEGACY_SCHEMA_VERSION"] == 1
assert module["LEGACY_MANIFEST_CONTRACT"] == "sw-g2-mls-rs-license-review-v1"
assert module["API_HOST"] == "api.github.com"
assert module["LEGACY_RAW_HOST"] == "raw.githubusercontent.com"

d2_dir = repo_root / "artifacts" / "sw-g2-mls-rs" / module["D2_RUN_ID"]
manifest_path = d2_dir / "manifest.json"
checksums_path = d2_dir / "checksums.sha256"
assert module["sha256_file"](manifest_path) == module["D2_MANIFEST_SHA256"]
assert module["sha256_file"](checksums_path) == module["D2_CHECKSUMS_SHA256"]
module["validate_d2_manifest"](manifest_path)
module["parse_checksum_file"](repo_root, checksums_path)
lock_paths = (
    repo_root / "tools" / "spikes" / "sw-g2-mls-rs" / "Cargo.lock",
    repo_root / "artifacts" / "sw-g2-mls-rs" / "20260901-135918-13430.mvBCS2" / "Cargo.lock",
    d2_dir / "Cargo.lock",
)
assert all(module["sha256_file"](item) == module["LOCK_SHA256"] for item in lock_paths)
assert len({item.read_bytes() for item in lock_paths}) == 1
module["validate_lock_inventory"](lock_paths[0])
module["validate_metadata_inventory"](d2_dir / "cargo-metadata.json")
module["validate_audit_summary"](d2_dir / "cargo-audit.json")
cache_root = d2_dir / ".work" / "cargo-home" / "registry" / "cache"
archive_inventory = [
    module["validate_package_archive"](repo_root, cache_root, item)
    for item in packages
]
assert len(archive_inventory) == 11
archive_license_like = {
    (item["name"], item["version"]): item["license_like_files_in_archive"]
    for item in archive_inventory
    if item["license_like_files_in_archive"]
}
assert set(archive_license_like) == {("debug_tree", "0.4.0"), ("r-efi", "6.0.0")}
assert archive_license_like[("debug_tree", "0.4.0")][0]["path"] == "doc/build/LICENSE.adoc"
assert archive_license_like[("debug_tree", "0.4.0")][0][
    "detected_complete_license_texts"
] == ["MIT"]
assert archive_license_like[("debug_tree", "0.4.0")][0]["applicable_to_package"] is False
assert archive_license_like[("debug_tree", "0.4.0")][0]["covers_declared_expression"] is False
assert archive_license_like[("r-efi", "6.0.0")][0]["path"] == "AUTHORS"
assert archive_license_like[("r-efi", "6.0.0")][0][
    "detected_complete_license_texts"
] == ["MIT"]
assert archive_license_like[("r-efi", "6.0.0")][0]["applicable_to_package"] is True
assert archive_license_like[("r-efi", "6.0.0")][0]["covers_declared_expression"] is False

review_root = repo_root / "artifacts" / "sw-g2-mls-rs-license-review"
run_dirs = sorted(
    path
    for path in review_root.iterdir()
    if path.is_dir() and not path.is_symlink() and not path.name.startswith(".")
)
assert set(module["HISTORICAL_SCHEMA1_RUNS"]) <= {path.name for path in run_dirs}
for run_dir in run_dirs:
    reviewed = module["validate_review_evidence"](repo_root, run_dir)
    schema = module["manifest_schema"](reviewed)
    if schema == 1:
        expected = module["HISTORICAL_SCHEMA1_RUNS"][run_dir.name]
        assert reviewed["outcome"] == "STOP"
        assert reviewed["stage"] == "license-evidence"
        assert reviewed["network"]["request_count"] == expected["request_count"]
        assert reviewed["network"]["downloaded_bytes"] == expected["downloaded_bytes"]
    else:
        assert schema == 2
        assert reviewed["network"]["transport"] == "git-blobs-api"
        assert reviewed["network"]["allowed_hosts"] == [module["API_HOST"]]
PY

for required_guard in \
  'ProxyHandler({})' \
  'NoRedirectHandler' \
  'api.github.com' \
  '/git/blobs/' \
  'git-blobs-api' \
  'base64.b64decode' \
  'git_blob_sha1' \
  'usedforsecurity=False' \
  'HISTORICAL_SCHEMA1_RUNS' \
  'R0_REVISION = "147462a2d91c5bb3eae4a0985aa8ddf1fc658199"' \
  'D2_REVISION = "64cf079a7b14a3ce90be92b93e56e2ad80555d80"' \
  'D2_RUN_ID = "20260902-130415-49997.8P5Td6"' \
  'LOCK_SHA256 = "c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7"'; do
  if ! rg -Fq -- "${required_guard}" "${runner_path}"; then
    echo "R1c helper guard is missing: ${required_guard}" >&2
    exit 1
  fi
done
if [ "$(rg -Foc -- 'raw.githubusercontent.com' "${runner_path}")" -ne 1 ]; then
  echo "R1c helper must retain raw.githubusercontent.com only for frozen schema 1 validation" >&2
  exit 1
fi
if rg -n \
  -- 'def raw_url|\bRAW_HOST\b|session\.get\([^)]*, "raw"\)' \
  "${runner_path}" >/dev/null; then
  echo "R1c helper retains an active raw transport path" >&2
  exit 1
fi
if rg -n \
  -- 'Authorization|Cookie|Bearer|urlretrieve|requests\.|httpx\.' \
  "${runner_path}" >/dev/null; then
  echo "R1c helper contains a prohibited credential or network-client pattern" >&2
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
    echo "artifact root is not a regular directory" >&2
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
expect_exit 2 python3 "${runner_path}" collect INVALID
expect_exit 10 python3 "${runner_path}" collect 0000000000000000000000000000000000000000
snapshot_artifacts "${self_test_dir}/artifacts.after"
if ! cmp -s "${self_test_dir}/artifacts.before" "${self_test_dir}/artifacts.after"; then
  echo "rejected invocations changed the R1c artifact root" >&2
  exit 1
fi

echo "SW-EXP-003 mls-rs license review helper check: PASS"
