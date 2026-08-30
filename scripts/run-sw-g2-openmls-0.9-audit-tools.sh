#!/usr/bin/env bash
set -euo pipefail

umask 077
SECONDS=0

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runtime_control_helper="${repo_root}/scripts/monitor-sw-g2-openmls-0.9-run.py"
builder_path="${repo_root}/scripts/run-sw-g2-openmls-0.9-audit-tools.sh"
artifact_parent="${repo_root}/artifacts"
artifact_root="${artifact_parent}/sw-g2-openmls-0.9-audit-tools"
image_digest="sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663"
image_ref="rust:1.96.1-bookworm@${image_digest}"
expected_platform="linux/arm64"
label_key="org.radishlink.sw-g2-openmls-0.9.audit-tools.run"
scenario_id="audit-tools-bundle-build"
bundle_contract="sw-exp-004-audit-tools-v1"
cargo_audit_version="0.22.2"
cargo_deny_version="0.20.2"
minimum_disk_kib=5242880
runtime_timeout_seconds=5400
runtime_disk_budget_kib=5242880
runtime_poll_interval_seconds=5

usage() {
  echo "usage: $0 prepare" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi
if [ "$1" != "prepare" ]; then
  echo "only the fixed audit tool bundle 'prepare' action is implemented" >&2
  exit 2
fi

for command_name in awk basename chmod date df docker du find git id jq mkdir mktemp mv pwd python3 rg shasum sleep tee uname; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

for required_input in "${runtime_control_helper}" "${builder_path}"; do
  if [ ! -f "${required_input}" ] || [ -L "${required_input}" ]; then
    echo "required regular input is missing or is a symbolic link: ${required_input}" >&2
    exit 1
  fi
done

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

number_or_null_jq='def number_or_null($value): if ($value | test("^[0-9]+$")) then ($value | tonumber) else null end; def boolean_or_null($value): if $value == "true" then true elif $value == "false" then false else null end;'

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

  jq -n \
    --arg schema_version "1" \
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
    "${number_or_null_jq}
    {
      schema_version: (\$schema_version | tonumber),
      bundle_contract: \$bundle_contract,
      evidence_id: \$evidence_id,
      scenario_id: \$scenario_id,
      run_id: \$run_id,
      outcome: \$outcome,
      stage: \$stage,
      start_time: \$start_time,
      end_time: \$end_time,
      git_revision: \$git_revision,
      git_dirty_before: (if \$git_status_before == "unavailable" then null else (\$git_status_before != "") end),
      git_status_before: \$git_status_before,
      git_status_after: \$git_status_after,
      image_ref: \$image_ref,
      image_index_digest: \$image_index_digest,
      image_platform_id: \$image_platform_id,
      image_preexisting: boolean_or_null(\$image_preexisting),
      host_arch: \$host_arch,
      daemon_arch: \$daemon_arch,
      container_arch: \$container_arch,
      target_platform: \$target_platform,
      rust_version: \$rust_version,
      cargo_version: \$cargo_version,
      tools: {
        cargo_audit: {
          requested_version: \$cargo_audit_requested_version,
          reported_version: \$cargo_audit_reported_version,
          binary_sha256: \$cargo_audit_binary_sha256
        },
        cargo_deny: {
          requested_version: \$cargo_deny_requested_version,
          reported_version: \$cargo_deny_reported_version,
          binary_sha256: \$cargo_deny_binary_sha256
        }
      },
      input_sha256: {
        runtime_control_helper: \$runtime_control_helper_sha256,
        builder: \$builder_sha256
      },
      disk_available_kib: number_or_null(\$disk_available_kib),
      runtime_controls: {
        monitor_status: \$runtime_control_status,
        termination_reason: \$runtime_termination_reason,
        received_signal: (if \$received_signal == "" then null else \$received_signal end),
        elapsed_milliseconds: number_or_null(\$runtime_elapsed_milliseconds),
        timeout_seconds: (\$runtime_timeout_seconds | tonumber),
        deadline_enforcement: "periodic-monitor-and-parent-signal",
        disk_current_kib: number_or_null(\$runtime_disk_current_kib),
        disk_peak_kib: number_or_null(\$runtime_disk_peak_kib),
        disk_budget_kib: (\$runtime_disk_budget_kib | tonumber),
        disk_enforcement: "periodic-apparent-size-monitor",
        poll_interval_seconds: (\$runtime_poll_interval_seconds | tonumber),
        network_egress_enforcement: "docker-default-network-no-domain-allowlist",
        validation_network: "none"
      },
      container_residual_count: number_or_null(\$container_residual_count),
      exit_code: (\$exit_code | tonumber)
    }" > "${manifest_tmp}"
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

inputs_unchanged() {
  [ "$(git -C "${repo_root}" rev-parse HEAD)" = "${git_revision}" ] &&
    [ "$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')" = "${runtime_control_helper_sha}" ] &&
    [ "$(shasum -a 256 "${builder_path}" | awk '{print $1}')" = "${builder_sha}" ]
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
  fi
  if ! write_checksums; then
    echo "STOP: could not finalize audit tool bundle checksums" >&2
    workflow_exit_code=1
    final_stage="evidence-finalize"
    write_manifest "${workflow_exit_code}" "STOP" "${final_stage}" || true
    write_checksums || true
  fi

  echo "SW-EXP-004 audit tool bundle run: ${run_id}"
  echo "Bundle directory: artifacts/sw-g2-openmls-0.9-audit-tools/${run_id}"
  echo "Build cache retained under the bundle run .work directory; Phase A must not mount it."
  exit "${workflow_exit_code}"
}
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
echo "SW-EXP-004 AUDIT TOOL BUNDLE PASS: fixed binaries are ready for checksum verification and read-only Phase A consumption."
