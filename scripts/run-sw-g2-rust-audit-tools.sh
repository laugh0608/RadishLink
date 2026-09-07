#!/usr/bin/env bash
set -euo pipefail

umask 077
SECONDS=0

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runtime_control_helper="${repo_root}/scripts/monitor-sw-g2-dependency-audit-run.py"
builder_path="${repo_root}/scripts/run-sw-g2-rust-audit-tools.sh"
manifest_filter_path="${repo_root}/scripts/sw-g2-rust-audit-tools-manifest.jq"
offline_checker_path="${repo_root}/scripts/check-sw-g2-rust-audit-tools.sh"
artifact_parent="${repo_root}/artifacts"
artifact_root="${artifact_parent}/sw-g2-rust-audit-tools"
image_digest="sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663"
image_ref="rust:1.96.1-bookworm@${image_digest}"
expected_platform="linux/arm64"
label_key="org.radishlink.sw-g2.rust-audit-tools.run"
scenario_id="audit-tools-bundle-build"
bundle_contract="sw-g2-rust-audit-tools-v1"
cargo_audit_version="0.22.2"
cargo_deny_version="0.20.2"
minimum_disk_kib=5242880
runtime_timeout_seconds=5400
runtime_disk_budget_kib=5242880
runtime_poll_interval_seconds=5

usage() {
  echo "usage: $0 <prepare|self-test>" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi
action=$1
case "${action}" in
  prepare | self-test) ;;
  *)
    echo "only 'prepare' and the offline 'self-test' action are implemented" >&2
    exit 2
    ;;
esac

for command_name in awk basename chmod date dirname find git jq mkdir mktemp mv pwd python3 rg rm shasum sleep sort; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done
if [ "${action}" = "prepare" ]; then
  for command_name in df docker id tee uname; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      echo "required command is unavailable: ${command_name}" >&2
      exit 1
    fi
  done
fi

for required_input in \
  "${runtime_control_helper}" \
  "${builder_path}" \
  "${manifest_filter_path}" \
  "${offline_checker_path}"; do
  if [ ! -f "${required_input}" ] || [ -L "${required_input}" ]; then
    echo "required regular input is missing or is a symbolic link: ${required_input}" >&2
    exit 1
  fi
done

if [ "${action}" = "prepare" ]; then
  preflight_git_status="$(git -C "${repo_root}" status --short --untracked-files=all)"
  if [ -n "${preflight_git_status}" ]; then
    echo "STOP: audit tool bundle preparation requires a clean worktree" >&2
    exit 10
  fi
  for artifact_directory in "${artifact_parent}" "${artifact_root}"; do
    if [ -L "${artifact_directory}" ]; then
      echo "artifact directory must not be a symbolic link: ${artifact_directory}" >&2
      exit 1
    fi
    if [ -e "${artifact_directory}" ] && [ ! -d "${artifact_directory}" ]; then
      echo "artifact path exists but is not a directory: ${artifact_directory}" >&2
      exit 1
    fi
    mkdir -p "${artifact_directory}"
  done
  resolved_artifact_root="$(CDPATH= cd -- "${artifact_root}" && pwd -P)"
  if [ "${resolved_artifact_root}" != "${artifact_root}" ]; then
    echo "artifact directory resolves outside the expected repository path" >&2
    exit 1
  fi
  run_prefix="$(date -u +%Y%m%d-%H%M%S)-$$"
  run_dir="$(mktemp -d "${artifact_root}/${run_prefix}.XXXXXX")"
  run_id="$(basename -- "${run_dir}")"
  checksum_prefix="artifacts/sw-g2-rust-audit-tools/${run_id}"
  checksum_verify_root="${repo_root}"
else
  self_test_parent="${TMPDIR:-/tmp}"
  if [ ! -d "${self_test_parent}" ] || [ -L "${self_test_parent}" ]; then
    echo "self-test parent is missing or is a symbolic link: ${self_test_parent}" >&2
    exit 1
  fi
  resolved_self_test_parent="$(CDPATH= cd -- "${self_test_parent}" && pwd -P)"
  run_dir="$(mktemp -d "${resolved_self_test_parent}/radishlink-rust-audit-tools-self-test.XXXXXX")"
  run_id="self-test"
  checksum_prefix="$(basename -- "${run_dir}")"
  checksum_verify_root="$(dirname -- "${run_dir}")"
fi

work_dir="${run_dir}/.work"
bundle_root="${run_dir}/bundle"
bundle_bin="${bundle_root}/bin"
container_name="radishlink-sw-g2-rust-audit-tools-${run_id}"
run_log="${run_dir}/run.log"
start_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
end_time="unavailable"
current_stage="preflight"
final_stage=""
git_revision="unavailable"
git_status_before="unavailable"
git_status_after="unavailable"
host_arch="unavailable"
daemon_arch="unavailable"
container_arch="unavailable"
rust_version="unavailable"
cargo_version="unavailable"
image_preexisting="unknown"
resolved_index_digest="unavailable"
image_platform_id="unavailable"
container_residual_count="unavailable"
disk_available_kib="unavailable"
runtime_control_helper_sha="unavailable"
builder_sha="unavailable"
manifest_filter_sha="unavailable"
offline_checker_sha="unavailable"
cargo_audit_reported_version="unavailable"
cargo_deny_reported_version="unavailable"
cargo_audit_binary_sha="unavailable"
cargo_deny_binary_sha="unavailable"
runner_pid="${BASHPID:-$$}"
runtime_monitor_pid=""
controlled_child_pid=""
received_signal=""
runtime_control_status="unavailable"
runtime_termination_reason="unavailable"
runtime_elapsed_milliseconds="unavailable"
runtime_disk_current_kib="unavailable"
runtime_disk_peak_kib="unavailable"

mkdir -p "${work_dir}/cargo-home" "${work_dir}/cargo-target" "${work_dir}/validation" "${bundle_bin}"
: > "${run_log}"

load_bundle_state() {
  if [ -f "${bundle_bin}/cargo-audit" ] && [ ! -L "${bundle_bin}/cargo-audit" ]; then
    cargo_audit_binary_sha="$(shasum -a 256 "${bundle_bin}/cargo-audit" | awk '{print $1}')"
  fi
  if [ -f "${bundle_bin}/cargo-deny" ] && [ ! -L "${bundle_bin}/cargo-deny" ]; then
    cargo_deny_binary_sha="$(shasum -a 256 "${bundle_bin}/cargo-deny" | awk '{print $1}')"
  fi
  if [ -f "${run_dir}/cargo-audit-version.txt" ] && [ ! -L "${run_dir}/cargo-audit-version.txt" ]; then
    cargo_audit_reported_version="$(awk 'NF { print; exit }' "${run_dir}/cargo-audit-version.txt")"
  fi
  if [ -f "${run_dir}/cargo-deny-version.txt" ] && [ ! -L "${run_dir}/cargo-deny-version.txt" ]; then
    cargo_deny_reported_version="$(awk 'NF { print; exit }' "${run_dir}/cargo-deny-version.txt")"
  fi
}

write_manifest() {
  local manifest_exit_code=$1
  local manifest_outcome=$2
  local manifest_stage=$3
  local manifest_tmp="${run_dir}/manifest.json.tmp"

  if [ -e "${run_dir}/manifest.json" ] || [ -L "${run_dir}/manifest.json" ]; then
    echo "STOP: manifest final path already exists" >&2
    return 1
  fi
  if [ -e "${manifest_tmp}" ] || [ -L "${manifest_tmp}" ]; then
    echo "STOP: manifest temporary path already exists" >&2
    return 1
  fi
  if ! jq -n \
    --arg schema_version "1" \
    --arg bundle_contract "${bundle_contract}" \
    --arg evidence_id "SW-G2-RUST-AUDIT-TOOLS" \
    --arg scenario_id "${scenario_id}" \
    --arg run_id "${run_id}" \
    --arg outcome "${manifest_outcome}" \
    --arg stage "${manifest_stage}" \
    --arg start_time "${start_time}" \
    --arg end_time "${end_time}" \
    --arg git_revision "${git_revision}" \
    --arg git_status_before "${git_status_before}" \
    --arg git_status_after "${git_status_after}" \
    --arg image_ref "${image_ref}" \
    --arg image_index_digest "${resolved_index_digest}" \
    --arg image_platform_id "${image_platform_id}" \
    --arg image_preexisting "${image_preexisting}" \
    --arg host_arch "${host_arch}" \
    --arg daemon_arch "${daemon_arch}" \
    --arg container_arch "${container_arch}" \
    --arg target_platform "${expected_platform}" \
    --arg rust_version "${rust_version}" \
    --arg cargo_version "${cargo_version}" \
    --arg cargo_audit_requested_version "${cargo_audit_version}" \
    --arg cargo_audit_reported_version "${cargo_audit_reported_version}" \
    --arg cargo_audit_binary_sha256 "${cargo_audit_binary_sha}" \
    --arg cargo_deny_requested_version "${cargo_deny_version}" \
    --arg cargo_deny_reported_version "${cargo_deny_reported_version}" \
    --arg cargo_deny_binary_sha256 "${cargo_deny_binary_sha}" \
    --arg runtime_control_helper_sha256 "${runtime_control_helper_sha}" \
    --arg builder_sha256 "${builder_sha}" \
    --arg manifest_filter_sha256 "${manifest_filter_sha}" \
    --arg offline_checker_sha256 "${offline_checker_sha}" \
    --arg container_residual_count "${container_residual_count}" \
    --arg disk_available_kib "${disk_available_kib}" \
    --arg runtime_control_status "${runtime_control_status}" \
    --arg runtime_termination_reason "${runtime_termination_reason}" \
    --arg runtime_elapsed_milliseconds "${runtime_elapsed_milliseconds}" \
    --arg runtime_timeout_seconds "${runtime_timeout_seconds}" \
    --arg runtime_disk_current_kib "${runtime_disk_current_kib}" \
    --arg runtime_disk_peak_kib "${runtime_disk_peak_kib}" \
    --arg runtime_disk_budget_kib "${runtime_disk_budget_kib}" \
    --arg runtime_poll_interval_seconds "${runtime_poll_interval_seconds}" \
    --arg received_signal "${received_signal}" \
    --arg exit_code "${manifest_exit_code}" \
    -f "${manifest_filter_path}" > "${manifest_tmp}"; then
    rm -f -- "${manifest_tmp}"
    return 1
  fi
  if [ ! -s "${manifest_tmp}" ] || [ -L "${manifest_tmp}" ] ||
    ! jq -e \
      --arg contract "${bundle_contract}" \
      --arg run_id "${run_id}" \
      --arg outcome "${manifest_outcome}" \
      --arg stage "${manifest_stage}" \
      --arg filter_sha "${manifest_filter_sha}" \
      --arg exit_code "${manifest_exit_code}" '
        .schema_version == 1
        and .bundle_contract == $contract
        and .run_id == $run_id
        and .outcome == $outcome
        and .stage == $stage
        and .input_sha256.manifest_filter == $filter_sha
        and .exit_code == ($exit_code | tonumber)
      ' "${manifest_tmp}" >/dev/null; then
    rm -f -- "${manifest_tmp}"
    return 1
  fi
  mv "${manifest_tmp}" "${run_dir}/manifest.json"
}

append_checksum() {
  local checksum_path=$1
  local checksum_label=$2
  local checksum_output=$3
  local checksum_value
  if [ -f "${checksum_path}" ] && [ ! -L "${checksum_path}" ]; then
    checksum_value="$(shasum -a 256 "${checksum_path}" | awk '{print $1}')"
    printf '%s  %s\n' "${checksum_value}" "${checksum_label}" >> "${checksum_output}"
  fi
}

write_checksums() {
  local checksums_tmp="${run_dir}/checksums.sha256.tmp"
  if [ -e "${run_dir}/checksums.sha256" ] || [ -L "${run_dir}/checksums.sha256" ]; then
    echo "STOP: checksum final path already exists" >&2
    return 1
  fi
  if [ ! -s "${run_dir}/manifest.json" ] || [ -L "${run_dir}/manifest.json" ] ||
    ! jq -e . "${run_dir}/manifest.json" >/dev/null 2>&1; then
    echo "STOP: checksum finalization requires a valid non-empty manifest" >&2
    return 1
  fi
  if [ -e "${checksums_tmp}" ] || [ -L "${checksums_tmp}" ]; then
    echo "STOP: checksum temporary path already exists" >&2
    return 1
  fi
  : > "${checksums_tmp}"
  append_checksum "${bundle_bin}/cargo-audit" "${checksum_prefix}/bundle/bin/cargo-audit" "${checksums_tmp}"
  append_checksum "${bundle_bin}/cargo-deny" "${checksum_prefix}/bundle/bin/cargo-deny" "${checksums_tmp}"
  for evidence_name in \
    cargo-audit-version.txt \
    cargo-deny-version.txt \
    container-toolchain.txt \
    git-status-after.txt \
    git-status-before.txt \
    image-index.txt \
    image-inspect.json \
    manifest.json \
    runtime-control.json \
    runtime-control-trigger.json; do
    append_checksum "${run_dir}/${evidence_name}" "${checksum_prefix}/${evidence_name}" "${checksums_tmp}"
  done
  mv "${checksums_tmp}" "${run_dir}/checksums.sha256"
}

expected_checksum_labels() {
  printf '%s\n' \
    "${checksum_prefix}/bundle/bin/cargo-audit" \
    "${checksum_prefix}/bundle/bin/cargo-deny" \
    "${checksum_prefix}/cargo-audit-version.txt" \
    "${checksum_prefix}/cargo-deny-version.txt" \
    "${checksum_prefix}/container-toolchain.txt" \
    "${checksum_prefix}/git-status-after.txt" \
    "${checksum_prefix}/git-status-before.txt" \
    "${checksum_prefix}/image-index.txt" \
    "${checksum_prefix}/image-inspect.json" \
    "${checksum_prefix}/manifest.json" \
    "${checksum_prefix}/runtime-control.json" | LC_ALL=C sort
}

verify_pass_bundle_contract() {
  local expected_labels
  local actual_labels
  if ! jq -e \
    --arg contract "${bundle_contract}" \
    --arg run_id "${run_id}" \
    --arg image_ref "${image_ref}" \
    --arg digest "${image_digest}" \
    --arg platform "${expected_platform}" \
    --arg audit_version "${cargo_audit_version}" \
    --arg deny_version "${cargo_deny_version}" \
    --arg audit_sha "${cargo_audit_binary_sha}" \
    --arg deny_sha "${cargo_deny_binary_sha}" \
    --arg helper_sha "${runtime_control_helper_sha}" \
    --arg builder_sha "${builder_sha}" \
    --arg filter_sha "${manifest_filter_sha}" \
    --arg checker_sha "${offline_checker_sha}" '
      .schema_version == 1
      and .bundle_contract == $contract
      and .run_id == $run_id
      and .outcome == "PASS"
      and .stage == "audit-tools-bundle-ready"
      and .exit_code == 0
      and .image.ref == $image_ref
      and .image.index_digest == $digest
      and (.image.platform_id | test("^sha256:[0-9a-f]{64}$"))
      and .platform.target == $platform
      and .platform.container_arch == "aarch64"
      and (.toolchain.rust | test("^rustc 1\\.96\\.1 "))
      and (.toolchain.cargo | test("^cargo 1\\.96\\.1 "))
      and .repository.git_status_before == ""
      and .repository.git_status_after == ""
      and .tools.cargo_audit.requested_version == $audit_version
      and .tools.cargo_audit.reported_version == ("cargo-audit " + $audit_version)
      and .tools.cargo_audit.binary_sha256 == $audit_sha
      and .tools.cargo_audit.mode == "0555"
      and .tools.cargo_deny.requested_version == $deny_version
      and .tools.cargo_deny.reported_version == ("cargo-deny " + $deny_version)
      and .tools.cargo_deny.binary_sha256 == $deny_sha
      and .tools.cargo_deny.mode == "0555"
      and .input_sha256.runtime_control_helper == $helper_sha
      and .input_sha256.builder == $builder_sha
      and .input_sha256.manifest_filter == $filter_sha
      and .input_sha256.offline_checker == $checker_sha
      and .runtime_controls.termination_reason == "completed"
      and .runtime_controls.timeout_seconds == 5400
      and .runtime_controls.disk_budget_kib == 5242880
      and .runtime_controls.poll_interval_seconds == 5
      and .runtime_controls.builder_network == "docker-default-network-no-domain-allowlist"
      and .runtime_controls.validation_network == "none"
      and .container_residual_count == 0
    ' "${run_dir}/manifest.json" >/dev/null; then
    echo "STOP: finalized manifest does not satisfy the PASS bundle contract" >&2
    return 1
  fi
  expected_labels="$(expected_checksum_labels)"
  actual_labels="$(awk 'NF == 2 { print $2 } NF != 2 { invalid = 1 } END { if (invalid) exit 1 }' \
    "${run_dir}/checksums.sha256" | LC_ALL=C sort)" || {
    echo "STOP: finalized checksum file has an invalid format" >&2
    return 1
  }
  if [ "${actual_labels}" != "${expected_labels}" ]; then
    echo "STOP: finalized checksum set does not match the PASS bundle contract" >&2
    return 1
  fi
  if ! (CDPATH= cd -- "${checksum_verify_root}" && shasum -a 256 -c "${run_dir}/checksums.sha256" >/dev/null); then
    echo "STOP: finalized checksum verification failed" >&2
    return 1
  fi
}

inputs_unchanged() {
  [ "$(git -C "${repo_root}" rev-parse HEAD)" = "${git_revision}" ] &&
    [ "$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')" = "${runtime_control_helper_sha}" ] &&
    [ "$(shasum -a 256 "${builder_path}" | awk '{print $1}')" = "${builder_sha}" ] &&
    [ "$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')" = "${manifest_filter_sha}" ] &&
    [ "$(shasum -a 256 "${offline_checker_path}" | awk '{print $1}')" = "${offline_checker_sha}" ]
}

run_controlled() {
  local command_status
  "$@" &
  controlled_child_pid=$!
  if wait "${controlled_child_pid}"; then
    command_status=0
  else
    command_status=$?
  fi
  controlled_child_pid=""
  return "${command_status}"
}

terminate_controlled_child() {
  local attempt
  if ! [[ "${controlled_child_pid}" =~ ^[0-9]+$ ]]; then
    controlled_child_pid=""
    return 0
  fi
  if kill -0 "${controlled_child_pid}" >/dev/null 2>&1; then
    kill -TERM "${controlled_child_pid}" >/dev/null 2>&1 || true
    for attempt in 1 2 3 4 5; do
      if ! kill -0 "${controlled_child_pid}" >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
    if kill -0 "${controlled_child_pid}" >/dev/null 2>&1; then
      kill -KILL "${controlled_child_pid}" >/dev/null 2>&1 || true
    fi
  fi
  wait "${controlled_child_pid}" >/dev/null 2>&1 || true
  controlled_child_pid=""
}

start_runtime_monitor() {
  local attempt
  python3 "${runtime_control_helper}" monitor \
    --run-dir "${run_dir}" \
    --runner-pid "${runner_pid}" \
    --timeout-seconds "${runtime_timeout_seconds}" \
    --disk-budget-kib "${runtime_disk_budget_kib}" \
    --poll-interval-seconds "${runtime_poll_interval_seconds}" \
    --elapsed-offset-seconds "${SECONDS}" &
  runtime_monitor_pid=$!
  for attempt in 1 2 3 4 5; do
    if [ -f "${run_dir}/runtime-control.json" ]; then
      return 0
    fi
    if ! kill -0 "${runtime_monitor_pid}" >/dev/null 2>&1; then
      wait "${runtime_monitor_pid}" || true
      runtime_monitor_pid=""
      echo "STOP: runtime control monitor exited during startup" >&2
      return 1
    fi
    sleep 1
  done
  echo "STOP: runtime control monitor did not produce its startup snapshot" >&2
  return 1
}

stop_runtime_monitor() {
  if [[ "${runtime_monitor_pid}" =~ ^[0-9]+$ ]]; then
    if kill -0 "${runtime_monitor_pid}" >/dev/null 2>&1; then
      kill -TERM "${runtime_monitor_pid}" >/dev/null 2>&1 || true
    fi
    wait "${runtime_monitor_pid}" >/dev/null 2>&1 || true
  fi
  runtime_monitor_pid=""
}

load_runtime_control_state() {
  local state_path="${run_dir}/runtime-control.json"
  if [ -f "${run_dir}/runtime-control-trigger.json" ] && [ ! -L "${run_dir}/runtime-control-trigger.json" ]; then
    state_path="${run_dir}/runtime-control-trigger.json"
  fi
  if [ ! -f "${state_path}" ] || [ -L "${state_path}" ] || ! jq -e . "${state_path}" >/dev/null 2>&1; then
    runtime_control_status="unavailable"
    runtime_termination_reason="monitor_error"
    return 1
  fi
  runtime_control_status="$(jq -r '.status // "unavailable"' "${state_path}")"
  runtime_termination_reason="$(jq -r '.stop_reason // "unavailable"' "${state_path}")"
  runtime_elapsed_milliseconds="$(jq -r '.elapsed_milliseconds // "unavailable"' "${state_path}")"
  runtime_disk_current_kib="$(jq -r '.disk_current_kib // "unavailable"' "${state_path}")"
  runtime_disk_peak_kib="$(jq -r '.disk_peak_kib // "unavailable"' "${state_path}")"
}

handle_int() {
  received_signal="INT"
  exit 130
}

handle_term() {
  received_signal="TERM"
  exit 143
}

preserve_invalid_finalization() {
  if [ -f "${run_dir}/manifest.json" ] && [ ! -L "${run_dir}/manifest.json" ]; then
    mv "${run_dir}/manifest.json" "${run_dir}/manifest.invalid.json" || true
  fi
  if [ -f "${run_dir}/checksums.sha256" ] && [ ! -L "${run_dir}/checksums.sha256" ]; then
    mv "${run_dir}/checksums.sha256" "${run_dir}/checksums.invalid.sha256" || true
  fi
}

cleanup_prepare() {
  local workflow_exit_code=$?
  local manifest_outcome="STOP"
  local manifest_stage="${final_stage:-${current_stage}}"
  local container_label=""
  local residual_output=""
  trap - EXIT INT TERM
  set +e

  terminate_controlled_child
  stop_runtime_monitor
  if ! load_runtime_control_state; then
    workflow_exit_code=126
    manifest_stage="runtime-control"
  else
    case "${runtime_termination_reason}" in
      deadline_exceeded)
        workflow_exit_code=124
        manifest_stage="runtime-deadline"
        ;;
      disk_budget_exceeded)
        workflow_exit_code=125
        manifest_stage="runtime-disk-budget"
        ;;
      monitor_error)
        workflow_exit_code=126
        manifest_stage="runtime-control"
        ;;
    esac
  fi

  if docker container inspect "${container_name}" >/dev/null 2>&1; then
    container_label="$(docker container inspect "${container_name}" \
      --format "{{ index .Config.Labels \"${label_key}\" }}" 2>/dev/null)"
    if [ "${container_label}" = "${run_id}" ]; then
      docker rm -f "${container_name}" >/dev/null 2>&1 || workflow_exit_code=1
    else
      echo "STOP: container name exists with a different run label; it was not removed" >&2
      workflow_exit_code=1
      manifest_stage="container-cleanup"
    fi
  fi
  if residual_output="$(docker ps -a --filter "label=${label_key}=${run_id}" --format '{{.ID}}' 2>/dev/null)"; then
    container_residual_count="$(printf '%s\n' "${residual_output}" | awk 'NF { count += 1 } END { print count + 0 }')"
    if [ "${container_residual_count}" -ne 0 ]; then
      workflow_exit_code=1
      manifest_stage="container-cleanup"
    fi
  else
    container_residual_count="unavailable"
    workflow_exit_code=1
    manifest_stage="container-cleanup"
  fi

  git_status_after="$(git -C "${repo_root}" status --short --untracked-files=all 2>/dev/null)"
  printf '%s\n' "${git_status_after}" > "${run_dir}/git-status-after.txt"
  load_bundle_state
  end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [ "${workflow_exit_code}" -eq 0 ] && [ "${final_stage}" = "audit-tools-bundle-ready" ] &&
    [ "${git_status_before}" = "" ] && [ "${git_status_after}" = "" ] &&
    [ "${container_residual_count}" = "0" ] && inputs_unchanged; then
    runtime_control_status="stopped"
    runtime_termination_reason="completed"
    manifest_outcome="PASS"
    manifest_stage="audit-tools-bundle-ready"
  else
    if [ "${workflow_exit_code}" -eq 0 ]; then
      workflow_exit_code=1
    fi
    if [ "${runtime_termination_reason}" = "runner_requested_stop" ]; then
      runtime_termination_reason="workflow_stop"
    fi
  fi

  if ! write_manifest "${workflow_exit_code}" "${manifest_outcome}" "${manifest_stage}"; then
    echo "STOP: manifest finalization failed" >&2
    workflow_exit_code=1
    manifest_outcome="INVALID"
  elif ! write_checksums; then
    echo "STOP: checksum finalization failed" >&2
    workflow_exit_code=1
    manifest_outcome="INVALID"
    preserve_invalid_finalization
  elif [ "${manifest_outcome}" = "PASS" ]; then
    if verify_pass_bundle_contract; then
      echo "SW-G2 Rust audit tools bundle: PASS ${run_id}"
    else
      workflow_exit_code=1
      manifest_outcome="INVALID"
      preserve_invalid_finalization
    fi
  fi

  if [ "${manifest_outcome}" != "PASS" ]; then
    echo "SW-G2 Rust audit tools bundle: ${manifest_outcome} ${run_id}" >&2
  fi
  echo "Evidence retained at artifacts/sw-g2-rust-audit-tools/${run_id}"
  echo "Build cache retained under the run .work directory; consumers must not mount it."
  exit "${workflow_exit_code}"
}

cleanup_self_test() {
  case "${run_dir}" in
    "${resolved_self_test_parent}"/radishlink-rust-audit-tools-self-test.*)
      rm -rf -- "${run_dir}"
      ;;
    *)
      echo "STOP: refusing to remove unexpected self-test directory: ${run_dir}" >&2
      return 1
      ;;
  esac
}

create_self_test_evidence() {
  printf '%s\n' 'cargo-audit fixture' > "${bundle_bin}/cargo-audit"
  printf '%s\n' 'cargo-deny fixture' > "${bundle_bin}/cargo-deny"
  chmod 0555 "${bundle_bin}/cargo-audit" "${bundle_bin}/cargo-deny"
  printf '%s\n' "cargo-audit ${cargo_audit_version}" > "${run_dir}/cargo-audit-version.txt"
  printf '%s\n' "cargo-deny ${cargo_deny_version}" > "${run_dir}/cargo-deny-version.txt"
  printf '%s\n' 'Linux aarch64' 'rustc 1.96.1 (self-test)' 'cargo 1.96.1 (self-test)' > "${run_dir}/container-toolchain.txt"
  : > "${run_dir}/git-status-before.txt"
  : > "${run_dir}/git-status-after.txt"
  printf '%s\n' "Digest: ${image_digest}" > "${run_dir}/image-index.txt"
  printf '%s\n' '[{"Id":"sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663"}]' > "${run_dir}/image-inspect.json"
  printf '%s\n' '{"schema_version":1,"status":"stopped","stop_reason":"runner_requested_stop","elapsed_milliseconds":1000,"disk_current_kib":1024,"disk_peak_kib":2048}' > "${run_dir}/runtime-control.json"
}

set_self_test_state() {
  start_time="2026-09-01T00:00:00Z"
  end_time="2026-09-01T00:00:01Z"
  git_revision="0123456789abcdef0123456789abcdef01234567"
  git_status_before=""
  git_status_after=""
  host_arch="arm64"
  daemon_arch="aarch64"
  container_arch="aarch64"
  rust_version="rustc 1.96.1 (self-test)"
  cargo_version="cargo 1.96.1 (self-test)"
  image_preexisting=true
  resolved_index_digest="${image_digest}"
  image_platform_id="${image_digest}"
  container_residual_count=0
  disk_available_kib=6291456
  runtime_control_helper_sha="$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')"
  builder_sha="$(shasum -a 256 "${builder_path}" | awk '{print $1}')"
  manifest_filter_sha="$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')"
  offline_checker_sha="$(shasum -a 256 "${offline_checker_path}" | awk '{print $1}')"
  load_bundle_state
  runtime_control_status="stopped"
  runtime_termination_reason="completed"
  runtime_elapsed_milliseconds=1000
  runtime_disk_current_kib=1024
  runtime_disk_peak_kib=2048
  received_signal=""
}

run_finalizer_self_test() {
  local original_manifest_filter_path="${manifest_filter_path}"
  local original_manifest_filter_sha

  create_self_test_evidence
  set_self_test_state
  original_manifest_filter_sha="${manifest_filter_sha}"
  write_manifest 0 PASS audit-tools-bundle-ready
  write_checksums
  verify_pass_bundle_contract

  chmod 0755 "${bundle_bin}/cargo-audit"
  printf '%s\n' 'tampered' >> "${bundle_bin}/cargo-audit"
  if (CDPATH= cd -- "${checksum_verify_root}" && shasum -a 256 -c "${run_dir}/checksums.sha256" >/dev/null 2>&1); then
    echo "STOP: checksum self-test did not detect payload tampering" >&2
    return 1
  fi
  printf '%s\n' 'cargo-audit fixture' > "${bundle_bin}/cargo-audit"
  chmod 0555 "${bundle_bin}/cargo-audit"
  rm -f -- "${run_dir}/manifest.json" "${run_dir}/checksums.sha256"

  printf '%s\n' '{}' > "${run_dir}/manifest.json"
  if write_manifest 0 PASS audit-tools-bundle-ready 2>/dev/null; then
    echo "STOP: manifest self-test accepted an existing final path" >&2
    return 1
  fi
  rm -f -- "${run_dir}/manifest.json"
  : > "${run_dir}/manifest.json.tmp"
  if write_manifest 0 PASS audit-tools-bundle-ready 2>/dev/null; then
    echo "STOP: manifest self-test accepted an existing temp path" >&2
    return 1
  fi
  rm -f -- "${run_dir}/manifest.json.tmp"

  manifest_filter_path="${run_dir}/missing-filter.jq"
  if write_manifest 0 PASS audit-tools-bundle-ready 2>/dev/null; then
    echo "STOP: manifest self-test did not propagate renderer failure" >&2
    return 1
  fi
  if [ -e "${run_dir}/manifest.json" ] || [ -e "${run_dir}/manifest.json.tmp" ]; then
    echo "STOP: renderer failure left a manifest output" >&2
    return 1
  fi

  manifest_filter_path="${run_dir}/empty-filter.jq"
  : > "${manifest_filter_path}"
  manifest_filter_sha="$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')"
  if write_manifest 0 PASS audit-tools-bundle-ready 2>/dev/null; then
    echo "STOP: manifest self-test accepted empty renderer output" >&2
    return 1
  fi
  manifest_filter_path="${run_dir}/invalid-filter.jq"
  printf '%s\n' '{' > "${manifest_filter_path}"
  manifest_filter_sha="$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')"
  if write_manifest 0 PASS audit-tools-bundle-ready 2>/dev/null; then
    echo "STOP: manifest self-test accepted invalid renderer output" >&2
    return 1
  fi

  manifest_filter_path="${original_manifest_filter_path}"
  manifest_filter_sha="${original_manifest_filter_sha}"
  write_manifest 0 PASS audit-tools-bundle-ready
  : > "${run_dir}/checksums.sha256"
  if write_checksums 2>/dev/null; then
    echo "STOP: checksum self-test accepted an existing final path" >&2
    return 1
  fi
  rm -f -- "${run_dir}/checksums.sha256"
  : > "${run_dir}/checksums.sha256.tmp"
  if write_checksums 2>/dev/null; then
    echo "STOP: checksum self-test accepted an existing temp path" >&2
    return 1
  fi
  rm -f -- "${run_dir}/checksums.sha256.tmp" "${run_dir}/manifest.json"
  : > "${run_dir}/manifest.json"
  if write_checksums 2>/dev/null; then
    echo "STOP: checksum self-test accepted an empty manifest" >&2
    return 1
  fi
  printf '%s\n' '{' > "${run_dir}/manifest.json"
  if write_checksums 2>/dev/null; then
    echo "STOP: checksum self-test accepted invalid JSON" >&2
    return 1
  fi
  rm -f -- "${run_dir}/manifest.json"
  echo "SW-G2 Rust audit tools offline self-test: PASS"
}

if [ "${action}" = "self-test" ]; then
  trap cleanup_self_test EXIT INT TERM
  run_finalizer_self_test
  trap - EXIT INT TERM
  cleanup_self_test
  exit 0
fi

trap handle_int INT
trap handle_term TERM
trap cleanup_prepare EXIT

if ! start_runtime_monitor; then
  final_stage="runtime-control"
  exit 126
fi

exec > >(tee -a "${run_log}") 2>&1

echo "[1/6] record repository, host, daemon, disk, and image pre-state"
current_stage="record-state"
runtime_control_helper_sha="$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')"
builder_sha="$(shasum -a 256 "${builder_path}" | awk '{print $1}')"
manifest_filter_sha="$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')"
offline_checker_sha="$(shasum -a 256 "${offline_checker_path}" | awk '{print $1}')"
git_revision="$(git -C "${repo_root}" rev-parse HEAD)"
git_status_before="$(git -C "${repo_root}" status --short --untracked-files=all)"
printf '%s\n' "${git_status_before}" > "${run_dir}/git-status-before.txt"
if [ -n "${git_status_before}" ]; then
  echo "STOP: worktree changed after the clean preflight" >&2
  exit 10
fi
host_arch="$(uname -m)"
disk_available_kib="$(df -Pk "${artifact_root}" | awk 'NR == 2 { print $4; exit }')"
if ! [[ "${disk_available_kib}" =~ ^[0-9]+$ ]] || [ "${disk_available_kib}" -lt "${minimum_disk_kib}" ]; then
  echo "STOP: less than 5 GiB is available for the isolated audit tool bundle build" >&2
  exit 10
fi
if ! run_controlled docker info --format '{{.Architecture}}' > "${work_dir}/daemon-architecture.txt"; then
  echo "STOP: Docker daemon is unavailable" >&2
  exit 10
fi
daemon_arch="$(awk 'NF { print; exit }' "${work_dir}/daemon-architecture.txt")"
if run_controlled docker image inspect "${image_ref}" >/dev/null 2>&1; then
  image_preexisting=true
else
  image_preexisting=false
fi
if ! run_controlled docker ps -a --filter "label=${label_key}=${run_id}" --format '{{.ID}}' > "${work_dir}/preexisting-containers.txt"; then
  echo "STOP: could not inspect exact bundle run residuals" >&2
  exit 10
fi
if [ -s "${work_dir}/preexisting-containers.txt" ]; then
  echo "STOP: exact bundle run label already has residual containers" >&2
  exit 10
fi

echo "[2/6] verify immutable Docker image identity"
current_stage="image-inspect"
if [ "${image_preexisting}" = false ]; then
  if ! run_controlled docker buildx imagetools inspect "${image_ref}" > "${run_dir}/image-index.txt"; then
    echo "STOP: fixed image index inspection failed" >&2
    exit 11
  fi
  resolved_index_digest="$(awk '$1 == "Digest:" { print $2; exit }' "${run_dir}/image-index.txt")"
  if [ "${resolved_index_digest}" != "${image_digest}" ]; then
    echo "STOP: resolved image index digest does not match the fixed digest" >&2
    exit 11
  fi
  run_controlled docker pull --platform "${expected_platform}" "${image_ref}"
else
  resolved_index_digest="${image_digest}"
  printf '%s\n' 'Source: local exact-digest image' "Digest: ${resolved_index_digest}" > "${run_dir}/image-index.txt"
fi
run_controlled docker image inspect "${image_ref}" > "${run_dir}/image-inspect.json"
if ! jq -e --arg digest "${image_digest}" 'any(.[0].RepoDigests[]?; endswith("@" + $digest))' \
  "${run_dir}/image-inspect.json" >/dev/null; then
  echo "STOP: local image does not retain the fixed RepoDigest" >&2
  exit 11
fi
if [ "$(jq -r '.[0] | "\(.Os)/\(.Architecture)"' "${run_dir}/image-inspect.json")" != "${expected_platform}" ]; then
  echo "STOP: prepared image is not ${expected_platform}" >&2
  exit 11
fi
image_platform_id="$(jq -r '.[0].Id // "unavailable"' "${run_dir}/image-inspect.json")"
host_uid="$(id -u)"
if [ "${host_uid}" = "0" ]; then
  echo "STOP: bundle preparation requires a non-root host user" >&2
  exit 12
fi
host_user="${host_uid}:$(id -g)"

echo "[3/6] verify Linux ARM64 Rust toolchain without network"
current_stage="toolchain-verify"
run_controlled docker run --rm \
  --name "${container_name}" \
  --label "${label_key}=${run_id}" \
  --platform "${expected_platform}" \
  --network none \
  --read-only \
  --cpus 1 \
  --memory 512m \
  --pids-limit 512 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "${host_user}" \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env HOME=/tmp/home \
  "${image_ref}" \
  sh -euc 'mkdir -p "$HOME"; uname -sm; rustc --version; cargo --version' \
  > "${run_dir}/container-toolchain.txt"
if ! rg -q '^Linux aarch64$' "${run_dir}/container-toolchain.txt" ||
  ! rg -q '^rustc 1\.96\.1 ' "${run_dir}/container-toolchain.txt" ||
  ! rg -q '^cargo 1\.96\.1 ' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: fixed container architecture or Rust toolchain verification failed" >&2
  exit 12
fi
container_arch="$(awk 'NR == 1 { print $2; exit }' "${run_dir}/container-toolchain.txt")"
rust_version="$(awk '/^rustc / { print; exit }' "${run_dir}/container-toolchain.txt")"
cargo_version="$(awk '/^cargo / { print; exit }' "${run_dir}/container-toolchain.txt")"

echo "[4/6] build exact cargo-audit and cargo-deny binaries"
current_stage="audit-tools-build"
run_controlled docker run --rm \
  --name "${container_name}" \
  --label "${label_key}=${run_id}" \
  --platform "${expected_platform}" \
  --read-only \
  --cpus 4 \
  --memory 4g \
  --pids-limit 512 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "${host_user}" \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  --env HOME=/tmp/home \
  --env CARGO_HOME=/evidence/.work/cargo-home \
  --env CARGO_TARGET_DIR=/evidence/.work/cargo-target \
  --env CARGO_INCREMENTAL=0 \
  --env CARGO_TERM_COLOR=never \
  --env CARGO_AUDIT_VERSION="${cargo_audit_version}" \
  --env CARGO_DENY_VERSION="${cargo_deny_version}" \
  --mount "type=bind,source=${run_dir},target=/evidence" \
  "${image_ref}" \
  sh -euc '
    mkdir -p "$HOME" "$CARGO_HOME" "$CARGO_TARGET_DIR" /evidence/bundle
    cargo install cargo-audit --version "$CARGO_AUDIT_VERSION" --locked --root /evidence/bundle
    cargo install cargo-deny --version "$CARGO_DENY_VERSION" --locked --root /evidence/bundle
  '

echo "[5/6] validate bundle payload without network"
current_stage="audit-tools-validate"
if [ ! -x "${bundle_bin}/cargo-audit" ] || [ -L "${bundle_bin}/cargo-audit" ] ||
  [ ! -x "${bundle_bin}/cargo-deny" ] || [ -L "${bundle_bin}/cargo-deny" ]; then
  echo "STOP: bundle binaries are missing, non-executable, or symbolic links" >&2
  exit 13
fi
chmod 0555 "${bundle_bin}/cargo-audit" "${bundle_bin}/cargo-deny"
run_controlled docker run --rm \
  --name "${container_name}" \
  --label "${label_key}=${run_id}" \
  --platform "${expected_platform}" \
  --network none \
  --read-only \
  --cpus 1 \
  --memory 512m \
  --pids-limit 512 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "${host_user}" \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --env HOME=/tmp/home \
  --mount "type=bind,source=${work_dir}/validation,target=/evidence" \
  --mount "type=bind,source=${bundle_bin},target=/audit-tools/bin,readonly" \
  "${image_ref}" \
  sh -euc '
    mkdir -p "$HOME"
    /audit-tools/bin/cargo-audit --version > /evidence/cargo-audit-version.txt
    /audit-tools/bin/cargo-deny --version > /evidence/cargo-deny-version.txt
  '
mv "${work_dir}/validation/cargo-audit-version.txt" "${run_dir}/cargo-audit-version.txt"
mv "${work_dir}/validation/cargo-deny-version.txt" "${run_dir}/cargo-deny-version.txt"
load_bundle_state
if [ "${cargo_audit_reported_version}" != "cargo-audit ${cargo_audit_version}" ] ||
  [ "${cargo_deny_reported_version}" != "cargo-deny ${cargo_deny_version}" ]; then
  echo "STOP: bundle versions do not match the fixed versions" >&2
  exit 13
fi

echo "[6/6] prepare immutable bundle finalization"
current_stage="bundle-finalize"
if find "${bundle_bin}" -mindepth 1 -maxdepth 1 ! -name cargo-audit ! -name cargo-deny -print -quit | rg -q .; then
  echo "STOP: bundle bin directory contains an unexpected entry" >&2
  exit 13
fi
if [ "$(find "${bundle_bin}" -mindepth 1 -maxdepth 1 -type f | awk 'END { print NR + 0 }')" -ne 2 ]; then
  echo "STOP: bundle must contain exactly two regular files" >&2
  exit 13
fi
if ! inputs_unchanged; then
  echo "STOP: HEAD or fixed bundle inputs changed during preparation" >&2
  exit 14
fi
final_stage="audit-tools-bundle-ready"
echo "SW-G2 Rust audit tool binaries are ready; evidence finalization remains pending."
