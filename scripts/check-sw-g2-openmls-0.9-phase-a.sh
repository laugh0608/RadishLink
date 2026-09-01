#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runner_path="${repo_root}/scripts/run-sw-g2-openmls-0.9-spike.sh"
manifest_filter_path="${repo_root}/scripts/sw-g2-openmls-0.9-phase-a-manifest.jq"
self_test_parent="${TMPDIR:-/tmp}"

for command_name in awk bash dirname jq mktemp pwd rg rm shasum; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done
for required_input in "${runner_path}" "${manifest_filter_path}"; do
  if [ ! -f "${required_input}" ] || [ -L "${required_input}" ]; then
    echo "required regular input is missing or is a symbolic link: ${required_input}" >&2
    exit 1
  fi
done
if [ ! -d "${self_test_parent}" ] || [ -L "${self_test_parent}" ]; then
  echo "self-test parent is missing or is a symbolic link: ${self_test_parent}" >&2
  exit 1
fi
self_test_parent="$(CDPATH= cd -- "${self_test_parent}" && pwd -P)"
self_test_dir="$(mktemp -d "${self_test_parent}/radishlink-phase-a-self-test.XXXXXX")"

cleanup() {
  case "${self_test_dir}" in
    "${self_test_parent}"/radishlink-phase-a-self-test.*)
      rm -rf -- "${self_test_dir}"
      ;;
    *)
      echo "refusing to remove unexpected self-test directory: ${self_test_dir}" >&2
      return 1
      ;;
  esac
}
trap cleanup EXIT INT TERM

bash -n "${runner_path}"

if ! rg -Fq "/audit-tools/bin/cargo-audit audit --json > /evidence/cargo-audit.json" \
  "${runner_path}"; then
  echo "runner does not use the cargo-audit subcommand invocation" >&2
  exit 1
fi
if rg -Fq "/audit-tools/bin/cargo-audit --json" "${runner_path}"; then
  echo "runner still contains the invalid direct cargo-audit invocation" >&2
  exit 1
fi
for required_guard in \
  'if [ ! -s "${manifest_tmp}" ]' \
  'if [ ! -s "${run_dir}/manifest.json" ]' \
  '-f "${manifest_filter_path}"' \
  'rm -f -- "${manifest_tmp}"' \
  'verify_pass_phase_a_contract' \
  'evidence finalization remains pending' \
  'phase_a_manifest_filter_sha256'; do
  if ! rg -Fq -- "${required_guard}" "${runner_path}"; then
    echo "runner is missing a required evidence finalizer guard: ${required_guard}" >&2
    exit 1
  fi
done
pass_message_count="$(rg -Fc 'SW-EXP-004 PHASE A PASS:' "${runner_path}")"
if [ "${pass_message_count}" -ne 1 ]; then
  echo "runner must contain exactly one post-finalization Phase A PASS message" >&2
  exit 1
fi

manifest_path="${self_test_dir}/manifest.json"
filter_sha="$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')"
jq -n \
  --arg schema_version "4" \
  --arg manifest_contract "sw-exp-004-phase-a-v4" \
  --arg evidence_id "SW-EXP-004" \
  --arg phase "phase-a" \
  --arg scenario_id "phase-a-dependency-audit" \
  --arg run_id "self-test" \
  --arg outcome "STOP" \
  --arg stage "evidence-finalize" \
  --arg start_time "2026-09-01T00:00:00Z" \
  --arg end_time "2026-09-01T00:00:01Z" \
  --arg git_revision "0123456789abcdef0123456789abcdef01234567" \
  --arg git_status_before "" \
  --arg git_status_after "?? tools/spikes/sw-g2-openmls-0.9/Cargo.lock" \
  --arg image_ref "rust:1.96.1-bookworm@sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663" \
  --arg image_index_digest "sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663" \
  --arg image_platform_id "sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663" \
  --arg image_preexisting "true" \
  --arg host_arch "arm64" \
  --arg daemon_arch "aarch64" \
  --arg container_arch "aarch64" \
  --arg target_platform "linux/arm64" \
  --arg rust_version "rustc 1.96.1 (self-test)" \
  --arg cargo_version "cargo 1.96.1 (self-test)" \
  --arg audit_tool_bundle_contract "sw-exp-004-audit-tools-v2" \
  --arg audit_tool_bundle_id "20260830-112214-39636.GpERrj" \
  --arg audit_tool_bundle_manifest_sha256 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
  --arg cargo_audit_requested_version "0.22.2" \
  --arg cargo_audit_reported_version "cargo-audit 0.22.2" \
  --arg cargo_audit_binary_sha256 "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" \
  --arg cargo_deny_requested_version "0.20.2" \
  --arg cargo_deny_reported_version "cargo-deny 0.20.2" \
  --arg cargo_deny_binary_sha256 "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
  --arg cargo_lock_sha256 "850c46666991222ccbd5d1e6c29a86ab78bd2c322fdd4cdaa933be890b067e49" \
  --arg expected_lock_sha256 "unavailable" \
  --arg advisory_db_revision "72f8b23d78ea6c4c9ded301a4c6ec4260e8b4c27" \
  --arg resolved_package_count "264" \
  --arg source_exit_code "0" \
  --arg audit_exit_code "2" \
  --arg deny_exit_code "4" \
  --arg feature_exit_code "0" \
  --arg lockfile_preexisting "false" \
  --arg lockfile_written "true" \
  --arg container_residual_count "0" \
  --arg disk_available_kib "6291456" \
  --arg runtime_control_status "stopped" \
  --arg runtime_termination_reason "workflow_stop" \
  --arg runtime_elapsed_milliseconds "36323" \
  --arg runtime_timeout_seconds "2700" \
  --arg runtime_disk_current_kib "192079" \
  --arg runtime_disk_peak_kib "192079" \
  --arg runtime_disk_budget_kib "5242880" \
  --arg runtime_poll_interval_seconds "5" \
  --arg received_signal "" \
  --arg license_sha256 "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
  --arg cargo_toml_sha256 "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee" \
  --arg deny_toml_sha256 "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff" \
  --arg main_rs_sha256 "1111111111111111111111111111111111111111111111111111111111111111" \
  --arg runtime_control_helper_sha256 "2222222222222222222222222222222222222222222222222222222222222222" \
  --arg runner_sha256 "3333333333333333333333333333333333333333333333333333333333333333" \
  --arg phase_a_manifest_filter_sha256 "${filter_sha}" \
  --arg exit_code "20" \
  -f "${manifest_filter_path}" > "${manifest_path}"

if [ ! -s "${manifest_path}" ] || ! jq -e \
  --arg filter_sha "${filter_sha}" '
    .schema_version == 4
    and .manifest_contract == "sw-exp-004-phase-a-v4"
    and .outcome == "STOP"
    and .audit_tool_bundle.mount_mode == "read-only"
    and .audit_tool_bundle.cargo_audit.invocation == ["audit", "--json"]
    and .input_sha256.phase_a_manifest_filter == $filter_sha
    and .runtime_controls.received_signal == null
    and .exit_code == 20
  ' "${manifest_path}" >/dev/null; then
  echo "Phase A manifest self-test did not preserve the fixed contract" >&2
  exit 1
fi

renderer_failure_path="${self_test_dir}/renderer-failure.json"
if jq -n -f "${self_test_dir}/missing-filter.jq" > "${renderer_failure_path}" 2>/dev/null; then
  echo "missing manifest filter unexpectedly rendered successfully" >&2
  exit 1
fi
if [ -s "${renderer_failure_path}" ]; then
  echo "renderer failure unexpectedly left non-empty output" >&2
  exit 1
fi

: > "${self_test_dir}/empty-manifest.json"
if [ -s "${self_test_dir}/empty-manifest.json" ] &&
  jq -e . "${self_test_dir}/empty-manifest.json" >/dev/null 2>&1; then
  echo "empty manifest unexpectedly satisfied the validity guard" >&2
  exit 1
fi
printf '%s\n' '{' > "${self_test_dir}/invalid-manifest.json"
if jq -e . "${self_test_dir}/invalid-manifest.json" >/dev/null 2>&1; then
  echo "invalid JSON unexpectedly satisfied the validity guard" >&2
  exit 1
fi

echo "SW-EXP-004 Phase A offline finalizer self-test: PASS"
