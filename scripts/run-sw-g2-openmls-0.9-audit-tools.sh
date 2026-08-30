#!/usr/bin/env bash
set -euo pipefail

umask 077
SECONDS=0

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runtime_control_helper="${repo_root}/scripts/monitor-sw-g2-openmls-0.9-run.py"
builder_path="${repo_root}/scripts/run-sw-g2-openmls-0.9-audit-tools.sh"
manifest_filter_path="${repo_root}/scripts/sw-g2-openmls-0.9-audit-tools-manifest.jq"
artifact_parent="${repo_root}/artifacts"
artifact_root="${artifact_parent}/sw-g2-openmls-0.9-audit-tools"
image_digest="sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663"
image_ref="rust:1.96.1-bookworm@${image_digest}"
expected_platform="linux/arm64"
label_key="org.radishlink.sw-g2-openmls-0.9.audit-tools.run"
scenario_id="audit-tools-bundle-build"
bundle_contract="sw-exp-004-audit-tools-v2"
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

for command_name in awk basename chmod date du find git jq mkdir mktemp mv pwd python3 rg rm shasum sleep sort; do
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

for required_input in "${runtime_control_helper}" "${builder_path}" "${manifest_filter_path}"; do
  if [ ! -f "${required_input}" ] || [ -L "${required_input}" ]; then
    echo "required regular input is missing or is a symbolic link: ${required_input}" >&2
    exit 1
  fi
done

if [ "${action}" = "prepare" ]; then
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
else
  self_test_parent="${TMPDIR:-/tmp}"
  if [ ! -d "${self_test_parent}" ] || [ -L "${self_test_parent}" ]; then
    echo "self-test parent is missing or is a symbolic link: ${self_test_parent}" >&2
    exit 1
  fi
  resolved_self_test_parent="$(CDPATH= cd -- "${self_test_parent}" && pwd -P)"
  run_dir="$(mktemp -d "${resolved_self_test_parent}/radishlink-audit-tools-self-test.XXXXXX")"
  run_id="self-test"
fi
work_dir="${run_dir}/.work"
bundle_root="${run_dir}/bundle"
bundle_bin="${bundle_root}/bin"
container_name="radishlink-sw-g2-openmls-0-9-audit-tools-${run_id}"
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

mkdir -p "${work_dir}/cargo-home" "${work_dir}/cargo-target" "${bundle_root}"
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
    --arg schema_version "2" \
    --arg bundle_contract "${bundle_contract}" \
    --arg evidence_id "SW-EXP-004-AUDIT-TOOLS" \
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
        .schema_version == 2
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
  local checksum_prefix="artifacts/sw-g2-openmls-0.9-audit-tools/${run_id}"

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

verify_pass_bundle_contract() {
  local checksum_prefix="artifacts/sw-g2-openmls-0.9-audit-tools/${run_id}"
  local expected_checksum_labels
  local actual_checksum_labels

  if ! jq -e \
    --arg contract "${bundle_contract}" \
    --arg run_id "${run_id}" \
    --arg image_ref "${image_ref}" \
    --arg platform "${expected_platform}" \
    --arg audit_version "${cargo_audit_version}" \
    --arg deny_version "${cargo_deny_version}" \
    --arg audit_sha "${cargo_audit_binary_sha}" \
    --arg deny_sha "${cargo_deny_binary_sha}" \
    --arg filter_sha "${manifest_filter_sha}" '
      .schema_version == 2
      and .bundle_contract == $contract
      and .run_id == $run_id
      and .outcome == "PASS"
      and .stage == "audit-tools-bundle-ready"
      and .exit_code == 0
      and .image_ref == $image_ref
      and .image_index_digest == ($image_ref | split("@") | .[1])
      and .target_platform == $platform
      and (.image_platform_id | test("^sha256:[0-9a-f]{64}$"))
      and .container_arch == "aarch64"
      and (.rust_version | test("^rustc 1\\.96\\.1 "))
      and (.cargo_version | test("^cargo 1\\.96\\.1 "))
      and .git_status_before == ""
      and .git_status_after == ""
      and .tools.cargo_audit.requested_version == $audit_version
      and .tools.cargo_audit.reported_version == ("cargo-audit " + $audit_version)
      and .tools.cargo_audit.binary_sha256 == $audit_sha
      and .tools.cargo_deny.requested_version == $deny_version
      and .tools.cargo_deny.reported_version == ("cargo-deny " + $deny_version)
      and .tools.cargo_deny.binary_sha256 == $deny_sha
      and .input_sha256.manifest_filter == $filter_sha
      and .runtime_controls.termination_reason == "completed"
      and .runtime_controls.timeout_seconds == 5400
      and .runtime_controls.disk_budget_kib == 5242880
      and .runtime_controls.network_egress_enforcement == "docker-default-network-no-domain-allowlist"
      and .runtime_controls.validation_network == "none"
      and .container_residual_count == 0
    ' "${run_dir}/manifest.json" >/dev/null; then
    echo "STOP: finalized manifest does not satisfy the PASS bundle contract" >&2
    return 1
  fi

  expected_checksum_labels="$(printf '%s\n' \
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
    "${checksum_prefix}/runtime-control.json" | LC_ALL=C sort)"
  actual_checksum_labels="$(awk 'NF == 2 { print $2 } NF != 2 { invalid = 1 } END { if (invalid) exit 1 }' \
    "${run_dir}/checksums.sha256" | LC_ALL=C sort)" || {
    echo "STOP: finalized checksum file has an invalid format" >&2
    return 1
  }
  if [ "${actual_checksum_labels}" != "${expected_checksum_labels}" ]; then
    echo "STOP: finalized checksum set does not match the PASS bundle contract" >&2
    return 1
  fi
  if ! (CDPATH= cd -- "${repo_root}" && shasum -a 256 -c "${run_dir}/checksums.sha256" >/dev/null); then
    echo "STOP: finalized checksum verification failed" >&2
    return 1
  fi
}

inputs_unchanged() {
  [ "$(git -C "${repo_root}" rev-parse HEAD)" = "${git_revision}" ] &&
    [ "$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')" = "${runtime_control_helper_sha}" ] &&
    [ "$(shasum -a 256 "${builder_path}" | awk '{print $1}')" = "${builder_sha}" ] &&
    [ "$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')" = "${manifest_filter_sha}" ]
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
  local elapsed_offset_seconds=${SECONDS}

  python3 "${runtime_control_helper}" monitor \
    --run-dir "${run_dir}" \
    --runner-pid "${runner_pid}" \
    --timeout-seconds "${runtime_timeout_seconds}" \
    --disk-budget-kib "${runtime_disk_budget_kib}" \
    --poll-interval-seconds "${runtime_poll_interval_seconds}" \
    --elapsed-offset-seconds "${elapsed_offset_seconds}" &
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
  local runtime_state_path="${run_dir}/runtime-control.json"

  if [ -f "${run_dir}/runtime-control-trigger.json" ] &&
    [ ! -L "${run_dir}/runtime-control-trigger.json" ]; then
    runtime_state_path="${run_dir}/runtime-control-trigger.json"
  fi
  if [ ! -f "${runtime_state_path}" ] || [ -L "${runtime_state_path}" ] ||
    ! jq -e . "${runtime_state_path}" >/dev/null 2>&1; then
    runtime_control_status="unavailable"
    runtime_termination_reason="monitor_error"
    return 1
  fi
  runtime_control_status="$(jq -r '.status // "unavailable"' "${runtime_state_path}")"
  runtime_termination_reason="$(jq -r '.stop_reason // "unavailable"' "${runtime_state_path}")"
  runtime_elapsed_milliseconds="$(jq -r '.elapsed_milliseconds // "unavailable"' "${runtime_state_path}")"
  runtime_disk_current_kib="$(jq -r '.disk_current_kib // "unavailable"' "${runtime_state_path}")"
  runtime_disk_peak_kib="$(jq -r '.disk_peak_kib // "unavailable"' "${runtime_state_path}")"
}

handle_int() {
  received_signal="INT"
  exit 130
}

handle_term() {
  received_signal="TERM"
  exit 143
}

cleanup() {
  local workflow_exit_code=$?
  local manifest_outcome
  local manifest_stage
  local container_label=""
  local residual_output=""
  local final_disk_kib="unavailable"
  local runtime_triggered=false
  local evidence_finalized=false
  trap - EXIT INT TERM
  set +e

  terminate_controlled_child
  stop_runtime_monitor
  if ! load_runtime_control_state; then
    workflow_exit_code=126
    final_stage="runtime-control"
    runtime_triggered=true
  else
    case "${runtime_termination_reason}" in
      deadline_exceeded)
        workflow_exit_code=124
        final_stage="runtime-deadline"
        runtime_triggered=true
        ;;
      disk_budget_exceeded)
        workflow_exit_code=125
        final_stage="runtime-disk-budget"
        runtime_triggered=true
        ;;
      monitor_error)
        workflow_exit_code=126
        final_stage="runtime-control"
        runtime_triggered=true
        ;;
    esac
  fi
  load_bundle_state

  if docker container inspect "${container_name}" >/dev/null 2>&1; then
    container_label="$(docker container inspect "${container_name}" \
      --format "{{ index .Config.Labels \"${label_key}\" }}" 2>/dev/null)"
    if [ "${container_label}" = "${run_id}" ]; then
      docker rm -f "${container_name}" >/dev/null 2>&1 || workflow_exit_code=1
    else
      echo "STOP: container name exists but its run label does not match; it was not removed" >&2
      workflow_exit_code=1
      final_stage="container-cleanup"
    fi
  fi
  if residual_output="$(docker ps -a --filter "label=${label_key}=${run_id}" --format '{{.ID}}' 2>/dev/null)"; then
    container_residual_count="$(printf '%s\n' "${residual_output}" | awk 'NF { count += 1 } END { print count + 0 }')"
    if [ "${container_residual_count}" -ne 0 ]; then
      workflow_exit_code=1
      final_stage="container-cleanup"
    fi
  else
    container_residual_count="unavailable"
    workflow_exit_code=1
    final_stage="container-cleanup"
  fi

  git_status_after="$(git -C "${repo_root}" status --short --untracked-files=all 2>/dev/null)"
  printf '%s\n' "${git_status_after}" > "${run_dir}/git-status-after.txt"
  if [ -n "${git_status_after}" ]; then
    workflow_exit_code=1
    final_stage="workspace-finalize"
  fi
  if [ "${workflow_exit_code}" -eq 0 ] && ! inputs_unchanged; then
    workflow_exit_code=1
    final_stage="input-stability"
  fi

  final_disk_kib="$(du -sk "${run_dir}" 2>/dev/null | awk 'NR == 1 { print $1; exit }')"
  if [[ "${final_disk_kib}" =~ ^[0-9]+$ ]]; then
    runtime_disk_current_kib="${final_disk_kib}"
    if ! [[ "${runtime_disk_peak_kib}" =~ ^[0-9]+$ ]] ||
      [ "${final_disk_kib}" -gt "${runtime_disk_peak_kib}" ]; then
      runtime_disk_peak_kib="${final_disk_kib}"
    fi
    if [ "${final_disk_kib}" -ge "${runtime_disk_budget_kib}" ]; then
      workflow_exit_code=125
      final_stage="runtime-disk-budget"
      runtime_termination_reason="disk_budget_exceeded"
      runtime_triggered=true
    fi
  else
    workflow_exit_code=126
    final_stage="runtime-control"
    runtime_termination_reason="monitor_error"
    runtime_triggered=true
  fi

  if [ "${runtime_triggered}" = false ]; then
    case "${received_signal}" in
      INT) runtime_termination_reason="external_interrupt" ;;
      TERM) runtime_termination_reason="external_termination" ;;
      *)
        if [ "${workflow_exit_code}" -eq 0 ]; then
          runtime_termination_reason="completed"
        else
          runtime_termination_reason="workflow_stop"
        fi
        ;;
    esac
  fi

  end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "${workflow_exit_code}" -eq 0 ]; then
    manifest_outcome="PASS"
  else
    manifest_outcome="STOP"
  fi
  manifest_stage="${final_stage:-${current_stage}}"
  if ! write_manifest "${workflow_exit_code}" "${manifest_outcome}" "${manifest_stage}"; then
    echo "STOP: could not finalize audit tool bundle manifest" >&2
    workflow_exit_code=1
    final_stage="evidence-finalize"
  elif ! write_checksums; then
    echo "STOP: could not finalize audit tool bundle checksums" >&2
    workflow_exit_code=1
    final_stage="evidence-finalize"
  elif [ "${workflow_exit_code}" -eq 0 ] && ! verify_pass_bundle_contract; then
    echo "STOP: finalized audit tool bundle did not satisfy its PASS contract" >&2
    workflow_exit_code=1
    final_stage="evidence-finalize"
  else
    evidence_finalized=true
  fi

  if [ "${evidence_finalized}" = false ]; then
    runtime_termination_reason="workflow_stop"
    rm -f -- \
      "${run_dir}/manifest.json" \
      "${run_dir}/manifest.json.tmp" \
      "${run_dir}/checksums.sha256" \
      "${run_dir}/checksums.sha256.tmp"
    if write_manifest "${workflow_exit_code}" "STOP" "${final_stage}" && write_checksums; then
      evidence_finalized=true
    else
      rm -f -- \
        "${run_dir}/manifest.json" \
        "${run_dir}/manifest.json.tmp" \
        "${run_dir}/checksums.sha256" \
        "${run_dir}/checksums.sha256.tmp"
      echo "STOP: fallback evidence finalization also failed" >&2
    fi
  fi

  if [ "${workflow_exit_code}" -eq 0 ] && [ "${evidence_finalized}" = true ]; then
    echo "SW-EXP-004 AUDIT TOOL BUNDLE PASS: manifest and checksums satisfy the fixed contract."
  else
    echo "SW-EXP-004 AUDIT TOOL BUNDLE STOP: the bundle is not eligible for Phase A."
  fi
  echo "SW-EXP-004 audit tool bundle run: ${run_id}"
  echo "Bundle directory: artifacts/sw-g2-openmls-0.9-audit-tools/${run_id}"
  echo "Build cache retained under the bundle run .work directory; Phase A must not mount it."
  exit "${workflow_exit_code}"
}

cleanup_self_test() {
  case "${run_dir}" in
    "${resolved_self_test_parent}"/radishlink-audit-tools-self-test.*)
      rm -rf -- "${run_dir}"
      ;;
    *)
      echo "STOP: refusing to remove unexpected self-test directory: ${run_dir}" >&2
      return 1
      ;;
  esac
}

run_manifest_self_test() {
  local original_manifest_filter_path="${manifest_filter_path}"

  start_time="2026-08-30T00:00:00Z"
  end_time="2026-08-30T00:00:01Z"
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
  cargo_audit_reported_version="cargo-audit ${cargo_audit_version}"
  cargo_deny_reported_version="cargo-deny ${cargo_deny_version}"
  cargo_audit_binary_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  cargo_deny_binary_sha="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  runtime_control_status="stopped"
  runtime_termination_reason="completed"
  runtime_elapsed_milliseconds=1000
  runtime_disk_current_kib=1024
  runtime_disk_peak_kib=2048
  received_signal=""

  if ! write_manifest 0 PASS audit-tools-bundle-ready; then
    echo "STOP: manifest self-test could not render the valid fixture" >&2
    return 1
  fi
  if ! jq -e \
    --arg filter_sha "${manifest_filter_sha}" '
      .schema_version == 2
      and .outcome == "PASS"
      and .git_dirty_before == false
      and .runtime_controls.received_signal == null
      and .runtime_controls.deadline_enforcement == "periodic-monitor-and-parent-signal"
      and .runtime_controls.disk_enforcement == "periodic-apparent-size-monitor"
      and .runtime_controls.network_egress_enforcement == "docker-default-network-no-domain-allowlist"
      and .input_sha256.manifest_filter == $filter_sha
    ' "${run_dir}/manifest.json" >/dev/null; then
    echo "STOP: manifest self-test fixture does not preserve the fixed contract values" >&2
    return 1
  fi
  if ! write_checksums; then
    echo "STOP: manifest self-test could not finalize checksums for valid JSON" >&2
    return 1
  fi
  if ! awk -v expected="artifacts/sw-g2-openmls-0.9-audit-tools/${run_id}/manifest.json" \
    'NF == 2 && $2 == expected { found = 1 } END { exit(found ? 0 : 1) }' \
    "${run_dir}/checksums.sha256"; then
    echo "STOP: manifest self-test checksum set does not include the manifest" >&2
    return 1
  fi

  rm -f -- "${run_dir}/manifest.json" "${run_dir}/checksums.sha256"
  manifest_filter_path="${run_dir}/missing-manifest-filter.jq"
  if write_manifest 0 PASS audit-tools-bundle-ready 2>/dev/null; then
    echo "STOP: manifest self-test did not propagate renderer failure" >&2
    return 1
  fi
  if [ -e "${run_dir}/manifest.json" ] || [ -L "${run_dir}/manifest.json" ] ||
    [ -e "${run_dir}/manifest.json.tmp" ] || [ -L "${run_dir}/manifest.json.tmp" ]; then
    echo "STOP: manifest self-test left output after renderer failure" >&2
    return 1
  fi
  manifest_filter_path="${original_manifest_filter_path}"

  : > "${run_dir}/manifest.json"
  if write_checksums 2>/dev/null; then
    echo "STOP: manifest self-test allowed checksums for an empty manifest" >&2
    return 1
  fi
  printf '%s\n' '{' > "${run_dir}/manifest.json"
  if write_checksums 2>/dev/null; then
    echo "STOP: manifest self-test allowed checksums for invalid JSON" >&2
    return 1
  fi

  echo "SW-EXP-004 audit tool manifest self-test: PASS"
}

if [ "${action}" = "self-test" ]; then
  trap cleanup_self_test EXIT INT TERM
  run_manifest_self_test
  trap - EXIT INT TERM
  cleanup_self_test
  exit 0
fi

trap handle_int INT
trap handle_term TERM
trap cleanup EXIT

if ! start_runtime_monitor; then
  final_stage="runtime-control"
  exit 126
fi

exec > >(tee -a "${run_log}") 2>&1

echo "[1/7] record repository, host, daemon, disk, and image pre-state"
current_stage="record-state"
runtime_control_helper_sha="$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')"
builder_sha="$(shasum -a 256 "${builder_path}" | awk '{print $1}')"
manifest_filter_sha="$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')"
git_revision="$(git -C "${repo_root}" rev-parse HEAD)"
git_status_before="$(git -C "${repo_root}" status --short --untracked-files=all)"
printf '%s\n' "${git_status_before}" > "${run_dir}/git-status-before.txt"
if [ -n "${git_status_before}" ]; then
  echo "STOP: audit tool bundle preparation requires a clean worktree" >&2
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
if ! run_controlled docker ps -a --filter "label=${label_key}=${run_id}" --format '{{.ID}}' \
  > "${work_dir}/preexisting-containers.txt"; then
  echo "STOP: could not inspect exact audit tool bundle run residuals" >&2
  exit 10
fi
if [ -s "${work_dir}/preexisting-containers.txt" ]; then
  echo "STOP: exact audit tool bundle run label already has residual containers" >&2
  exit 10
fi

echo "[2/7] verify immutable Docker image identity"
current_stage="image-index-inspect"
if [ "${image_preexisting}" = true ]; then
  run_controlled docker image inspect "${image_ref}" > "${run_dir}/image-inspect.json"
  if ! jq -e --arg digest "${image_digest}" \
    'any(.[0].RepoDigests[]?; endswith("@" + $digest))' \
    "${run_dir}/image-inspect.json" >/dev/null; then
    echo "STOP: local image RepoDigests do not contain the fixed digest" >&2
    exit 11
  fi
  resolved_index_digest="${image_digest}"
  {
    echo "Source: local exact-digest image"
    echo "Digest: ${resolved_index_digest}"
    jq -r '.[0] | "Image-ID: \(.Id)\nOS/Architecture: \(.Os)/\(.Architecture)\nRepoDigests: \(.RepoDigests | tojson)"' \
      "${run_dir}/image-inspect.json"
  } > "${run_dir}/image-index.txt"
else
  run_controlled docker buildx imagetools inspect "${image_ref}" > "${run_dir}/image-index.txt"
  resolved_index_digest="$(awk '$1 == "Digest:" { print $2; exit }' "${run_dir}/image-index.txt")"
  if [ "${resolved_index_digest}" != "${image_digest}" ]; then
    echo "STOP: resolved image index digest does not match the fixed digest" >&2
    exit 11
  fi
fi

echo "[3/7] ensure the fixed Linux ARM64 Rust image"
current_stage="image-pull"
if [ "${image_preexisting}" = false ]; then
  run_controlled docker pull --platform "${expected_platform}" "${image_ref}"
fi
run_controlled docker image inspect "${image_ref}" > "${run_dir}/image-inspect.json"
if ! jq -e --arg digest "${image_digest}" \
  'any(.[0].RepoDigests[]?; endswith("@" + $digest))' \
  "${run_dir}/image-inspect.json" >/dev/null; then
  echo "STOP: prepared image RepoDigests do not contain the fixed digest" >&2
  exit 11
fi
if [ "$(jq -r '.[0] | "\(.Os)/\(.Architecture)"' "${run_dir}/image-inspect.json")" != "${expected_platform}" ]; then
  echo "STOP: prepared image is not ${expected_platform}" >&2
  exit 11
fi
image_platform_id="$(jq -r '.[0].Id // "unavailable"' "${run_dir}/image-inspect.json")"
host_user="$(id -u):$(id -g)"

echo "[4/7] verify container architecture and Rust toolchain without network"
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
  sh -euc 'mkdir -p "$HOME"; uname -sm; rustc -vV; cargo -vV' \
  > "${run_dir}/container-toolchain.txt"
if ! rg -q '^Linux aarch64$' "${run_dir}/container-toolchain.txt" ||
  ! rg -q '^release: 1\.96\.1$' "${run_dir}/container-toolchain.txt" ||
  ! rg -q '^cargo 1\.96\.1 ' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: fixed container architecture or Rust toolchain verification failed" >&2
  exit 12
fi
container_arch="$(awk 'NR == 1 { print $2; exit }' "${run_dir}/container-toolchain.txt")"
rust_version="$(awk '/^rustc / { print; exit }' "${run_dir}/container-toolchain.txt")"
cargo_version="$(awk '/^cargo / { print; exit }' "${run_dir}/container-toolchain.txt")"

echo "[5/7] build exact cargo-audit and cargo-deny binaries in the isolated bundle"
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

echo "[6/7] validate the bundle binaries in the fixed image without network"
current_stage="audit-tools-validate"
if [ ! -x "${bundle_bin}/cargo-audit" ] || [ -L "${bundle_bin}/cargo-audit" ] ||
  [ ! -x "${bundle_bin}/cargo-deny" ] || [ -L "${bundle_bin}/cargo-deny" ]; then
  echo "STOP: audit tool bundle binaries are missing, non-executable, or symbolic links" >&2
  exit 13
fi
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
  --mount "type=bind,source=${run_dir},target=/evidence" \
  --mount "type=bind,source=${bundle_bin},target=/audit-tools/bin,readonly" \
  "${image_ref}" \
  sh -euc '
    mkdir -p "$HOME"
    /audit-tools/bin/cargo-audit --version > /evidence/cargo-audit-version.txt
    /audit-tools/bin/cargo-deny --version > /evidence/cargo-deny-version.txt
  '
load_bundle_state
if [ "${cargo_audit_reported_version}" != "cargo-audit ${cargo_audit_version}" ] ||
  [ "${cargo_deny_reported_version}" != "cargo-deny ${cargo_deny_version}" ]; then
  echo "STOP: audit tool bundle reported versions do not match the fixed versions" >&2
  exit 13
fi

echo "[7/7] finalize the immutable bundle contract"
current_stage="bundle-finalize"
if find "${bundle_bin}" -mindepth 1 -maxdepth 1 ! -name cargo-audit ! -name cargo-deny -print -quit | rg -q .; then
  echo "STOP: audit tool bundle bin directory contains an unexpected entry" >&2
  exit 13
fi
chmod 0555 "${bundle_bin}/cargo-audit" "${bundle_bin}/cargo-deny"
if ! inputs_unchanged; then
  echo "STOP: HEAD or fixed audit tool bundle inputs changed during preparation" >&2
  exit 14
fi
final_stage="audit-tools-bundle-ready"
echo "SW-EXP-004 audit tool binaries are ready; evidence finalization remains pending."
