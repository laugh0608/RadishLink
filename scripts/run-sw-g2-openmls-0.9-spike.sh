#!/usr/bin/env bash
set -euo pipefail

umask 077
SECONDS=0

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runtime_control_helper="${repo_root}/scripts/monitor-sw-g2-openmls-0.9-run.py"
spike_relative="tools/spikes/sw-g2-openmls-0.9"
spike_root="${repo_root}/${spike_relative}"
lock_relative="${spike_relative}/Cargo.lock"
repo_lock="${repo_root}/${lock_relative}"
artifact_parent="${repo_root}/artifacts"
artifact_root="${artifact_parent}/sw-g2-openmls-0.9"
audit_tools_artifact_root="${artifact_parent}/sw-g2-openmls-0.9-audit-tools"
image_digest="sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663"
image_ref="rust:1.96.1-bookworm@${image_digest}"
expected_platform="linux/arm64"
label_key="org.radishlink.sw-g2-openmls-0.9.run"
scenario_id="phase-a-dependency-audit"
audit_tool_bundle_contract="sw-exp-004-audit-tools-v1"
cargo_audit_version="0.22.2"
cargo_deny_version="0.20.2"
minimum_disk_kib=5242880
runtime_timeout_seconds=2700
runtime_disk_budget_kib=5242880
runtime_poll_interval_seconds=5

usage() {
  echo "usage: $0 prepare <audit-tool-bundle-id>" >&2
}

if [ "$#" -ne 2 ]; then
  usage
  exit 2
fi

action=$1
audit_tool_bundle_id=$2
if [ "${action}" != "prepare" ]; then
  echo "only Phase A 'prepare' is implemented; Phase B remains blocked" >&2
  exit 2
fi
if ! [[ "${audit_tool_bundle_id}" =~ ^[0-9]{8}-[0-9]{6}-[0-9]+\.[A-Za-z0-9]{6}$ ]]; then
  echo "audit tool bundle ID does not match the fixed run ID format" >&2
  exit 2
fi

for command_name in awk basename chmod cp date df docker du find git id jq ln mkdir mktemp mv pwd python3 rg rm shasum sleep sort tee uname; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

if [ ! -d "${audit_tools_artifact_root}" ] || [ -L "${audit_tools_artifact_root}" ]; then
  echo "audit tool artifact root is missing or is a symbolic link: ${audit_tools_artifact_root}" >&2
  exit 2
fi
resolved_audit_tools_artifact_root="$(CDPATH= cd -- "${audit_tools_artifact_root}" && pwd -P)"
if [ "${resolved_audit_tools_artifact_root}" != "${audit_tools_artifact_root}" ]; then
  echo "audit tool artifact root resolves outside the expected repository path" >&2
  exit 2
fi

audit_tool_bundle_dir="${audit_tools_artifact_root}/${audit_tool_bundle_id}"
audit_tool_bundle_bin="${audit_tool_bundle_dir}/bundle/bin"
audit_tool_bundle_manifest="${audit_tool_bundle_dir}/manifest.json"
audit_tool_bundle_checksums="${audit_tool_bundle_dir}/checksums.sha256"
if [ ! -d "${audit_tool_bundle_dir}" ] || [ -L "${audit_tool_bundle_dir}" ]; then
  echo "requested audit tool bundle is missing or is a symbolic link: ${audit_tool_bundle_id}" >&2
  exit 2
fi
resolved_audit_tool_bundle_dir="$(CDPATH= cd -- "${audit_tool_bundle_dir}" && pwd -P)"
if [ "${resolved_audit_tool_bundle_dir}" != "${audit_tool_bundle_dir}" ]; then
  echo "audit tool bundle resolves outside the expected artifact root" >&2
  exit 2
fi
if find "${audit_tool_bundle_dir}/bundle" -type l -print -quit | rg -q .; then
  echo "audit tool bundle payload must not contain symbolic links" >&2
  exit 2
fi

bundle_required_files=(
  "${audit_tool_bundle_bin}/cargo-audit"
  "${audit_tool_bundle_bin}/cargo-deny"
  "${audit_tool_bundle_dir}/cargo-audit-version.txt"
  "${audit_tool_bundle_dir}/cargo-deny-version.txt"
  "${audit_tool_bundle_dir}/container-toolchain.txt"
  "${audit_tool_bundle_dir}/git-status-after.txt"
  "${audit_tool_bundle_dir}/git-status-before.txt"
  "${audit_tool_bundle_dir}/image-index.txt"
  "${audit_tool_bundle_dir}/image-inspect.json"
  "${audit_tool_bundle_manifest}"
  "${audit_tool_bundle_dir}/runtime-control.json"
  "${audit_tool_bundle_checksums}"
)
for bundle_required_file in "${bundle_required_files[@]}"; do
  if [ ! -f "${bundle_required_file}" ] || [ -L "${bundle_required_file}" ]; then
    echo "audit tool bundle file is missing or invalid: ${bundle_required_file}" >&2
    exit 2
  fi
done
if [ ! -x "${audit_tool_bundle_bin}/cargo-audit" ] || [ ! -x "${audit_tool_bundle_bin}/cargo-deny" ]; then
  echo "audit tool bundle binaries must be executable" >&2
  exit 2
fi
if [ -w "${audit_tool_bundle_bin}/cargo-audit" ] || [ -w "${audit_tool_bundle_bin}/cargo-deny" ]; then
  echo "audit tool bundle binaries must not be host-writable" >&2
  exit 2
fi
if find "${audit_tool_bundle_bin}" -mindepth 1 -maxdepth 1 \
  ! -name cargo-audit ! -name cargo-deny -print -quit | rg -q .; then
  echo "audit tool bundle bin directory contains an unexpected entry" >&2
  exit 2
fi
if ! jq -e \
  --arg contract "${audit_tool_bundle_contract}" \
  --arg run_id "${audit_tool_bundle_id}" \
  --arg image_ref "${image_ref}" \
  --arg platform "${expected_platform}" \
  --arg audit_version "${cargo_audit_version}" \
  --arg deny_version "${cargo_deny_version}" '
    .schema_version == 1
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
    and .tools.cargo_deny.requested_version == $deny_version
    and .tools.cargo_audit.reported_version == ("cargo-audit " + $audit_version)
    and .tools.cargo_deny.reported_version == ("cargo-deny " + $deny_version)
    and .runtime_controls.termination_reason == "completed"
    and .runtime_controls.timeout_seconds == 5400
    and .runtime_controls.disk_budget_kib == 5242880
    and .runtime_controls.network_egress_enforcement == "docker-default-network-no-domain-allowlist"
    and .runtime_controls.validation_network == "none"
    and .container_residual_count == 0
  ' "${audit_tool_bundle_manifest}" >/dev/null; then
  echo "audit tool bundle manifest does not satisfy the fixed contract" >&2
  exit 2
fi

bundle_checksum_prefix="artifacts/sw-g2-openmls-0.9-audit-tools/${audit_tool_bundle_id}"
bundle_expected_checksum_labels="$(printf '%s\n' \
  "${bundle_checksum_prefix}/bundle/bin/cargo-audit" \
  "${bundle_checksum_prefix}/bundle/bin/cargo-deny" \
  "${bundle_checksum_prefix}/cargo-audit-version.txt" \
  "${bundle_checksum_prefix}/cargo-deny-version.txt" \
  "${bundle_checksum_prefix}/container-toolchain.txt" \
  "${bundle_checksum_prefix}/git-status-after.txt" \
  "${bundle_checksum_prefix}/git-status-before.txt" \
  "${bundle_checksum_prefix}/image-index.txt" \
  "${bundle_checksum_prefix}/image-inspect.json" \
  "${bundle_checksum_prefix}/manifest.json" \
  "${bundle_checksum_prefix}/runtime-control.json" | LC_ALL=C sort)"
bundle_actual_checksum_labels="$(awk 'NF == 2 { print $2 } NF != 2 { invalid = 1 } END { if (invalid) exit 1 }' \
  "${audit_tool_bundle_checksums}" | LC_ALL=C sort)" || {
  echo "audit tool bundle checksum file has an invalid format" >&2
  exit 2
}
if [ "${bundle_actual_checksum_labels}" != "${bundle_expected_checksum_labels}" ]; then
  echo "audit tool bundle checksum set does not match the fixed contract" >&2
  exit 2
fi
if ! (CDPATH= cd -- "${repo_root}" && shasum -a 256 -c "${audit_tool_bundle_checksums}" >/dev/null); then
  echo "audit tool bundle checksum verification failed" >&2
  exit 2
fi

audit_tool_bundle_manifest_sha="$(shasum -a 256 "${audit_tool_bundle_manifest}" | awk '{print $1}')"
cargo_audit_binary_sha="$(shasum -a 256 "${audit_tool_bundle_bin}/cargo-audit" | awk '{print $1}')"
cargo_deny_binary_sha="$(shasum -a 256 "${audit_tool_bundle_bin}/cargo-deny" | awk '{print $1}')"
if [ "$(jq -r '.tools.cargo_audit.binary_sha256' "${audit_tool_bundle_manifest}")" != "${cargo_audit_binary_sha}" ] ||
  [ "$(jq -r '.tools.cargo_deny.binary_sha256' "${audit_tool_bundle_manifest}")" != "${cargo_deny_binary_sha}" ]; then
  echo "audit tool bundle binary digest does not match its manifest" >&2
  exit 2
fi
cargo_audit_reported_version="$(jq -r '.tools.cargo_audit.reported_version' "${audit_tool_bundle_manifest}")"
cargo_deny_reported_version="$(jq -r '.tools.cargo_deny.reported_version' "${audit_tool_bundle_manifest}")"

required_inputs=(
  "${repo_root}/LICENSE"
  "${spike_root}/Cargo.toml"
  "${spike_root}/deny.toml"
  "${spike_root}/src/main.rs"
  "${runtime_control_helper}"
  "${repo_root}/scripts/run-sw-g2-openmls-0.9-spike.sh"
)
for required_input in "${required_inputs[@]}"; do
  if [ ! -f "${required_input}" ] || [ -L "${required_input}" ]; then
    echo "required regular input is missing or is a symbolic link: ${required_input}" >&2
    exit 1
  fi
done

if [ -L "${spike_root}" ]; then
  echo "spike root must not be a symbolic link: ${spike_root}" >&2
  exit 1
fi
resolved_spike_root="$(CDPATH= cd -- "${spike_root}" && pwd -P)"
if [ "${resolved_spike_root}" != "${spike_root}" ]; then
  echo "spike root resolves outside the expected repository path" >&2
  exit 1
fi
if [ -L "${repo_lock}" ]; then
  echo "repository Cargo.lock must not be a symbolic link" >&2
  exit 1
fi
if [ -e "${repo_lock}" ] && [ ! -f "${repo_lock}" ]; then
  echo "repository Cargo.lock exists but is not a regular file" >&2
  exit 1
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
work_dir="${run_dir}/.work"
prepared_repo="${work_dir}/repo"
prepared_spike="${prepared_repo}/${spike_relative}"
container_name="radishlink-sw-g2-openmls-0-9-${run_id}"
run_log="${run_dir}/run.log"
promotion_temp="${spike_root}/.Cargo.lock.${run_id}.tmp"
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
lock_sha="unavailable"
advisory_db_revision="unavailable"
resolved_package_count="unavailable"
source_status="unavailable"
audit_status="unavailable"
deny_status="unavailable"
feature_status="unavailable"
lockfile_preexisting=false
lockfile_written=false
container_residual_count="unavailable"
disk_available_kib="unavailable"
license_sha="unavailable"
cargo_toml_sha="unavailable"
deny_toml_sha="unavailable"
main_rs_sha="unavailable"
runtime_control_helper_sha="unavailable"
runner_sha="unavailable"
expected_lock_sha="unavailable"
runner_pid="${BASHPID:-$$}"
runtime_monitor_pid=""
controlled_child_pid=""
received_signal=""
runtime_control_status="unavailable"
runtime_termination_reason="unavailable"
runtime_elapsed_milliseconds="unavailable"
runtime_disk_current_kib="unavailable"
runtime_disk_peak_kib="unavailable"

mkdir -p \
  "${work_dir}/cargo-home" \
  "${work_dir}/cargo-target" \
  "${prepared_spike}/src"
: > "${run_log}"

number_or_null_jq='def number_or_null($value): if ($value | test("^[0-9]+$")) then ($value | tonumber) else null end; def boolean_or_null($value): if $value == "true" then true elif $value == "false" then false else null end;'

write_manifest() {
  local manifest_exit_code=$1
  local manifest_outcome=$2
  local manifest_stage=$3
  local manifest_tmp="${run_dir}/manifest.json.tmp"

  jq -n \
    --arg schema_version "3" \
    --arg evidence_id "SW-EXP-004" \
    --arg phase "phase-a" \
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
    --arg audit_tool_bundle_contract "${audit_tool_bundle_contract}" \
    --arg audit_tool_bundle_id "${audit_tool_bundle_id}" \
    --arg audit_tool_bundle_manifest_sha256 "${audit_tool_bundle_manifest_sha}" \
    --arg cargo_audit_requested_version "${cargo_audit_version}" \
    --arg cargo_audit_reported_version "${cargo_audit_reported_version}" \
    --arg cargo_audit_binary_sha256 "${cargo_audit_binary_sha}" \
    --arg cargo_deny_requested_version "${cargo_deny_version}" \
    --arg cargo_deny_reported_version "${cargo_deny_reported_version}" \
    --arg cargo_deny_binary_sha256 "${cargo_deny_binary_sha}" \
    --arg cargo_lock_sha256 "${lock_sha}" \
    --arg expected_lock_sha256 "${expected_lock_sha}" \
    --arg advisory_db_revision "${advisory_db_revision}" \
    --arg resolved_package_count "${resolved_package_count}" \
    --arg source_exit_code "${source_status}" \
    --arg audit_exit_code "${audit_status}" \
    --arg deny_exit_code "${deny_status}" \
    --arg feature_exit_code "${feature_status}" \
    --arg lockfile_preexisting "${lockfile_preexisting}" \
    --arg lockfile_written "${lockfile_written}" \
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
    --arg license_sha256 "${license_sha}" \
    --arg cargo_toml_sha256 "${cargo_toml_sha}" \
    --arg deny_toml_sha256 "${deny_toml_sha}" \
    --arg main_rs_sha256 "${main_rs_sha}" \
    --arg runtime_control_helper_sha256 "${runtime_control_helper_sha}" \
    --arg runner_sha256 "${runner_sha}" \
    --arg exit_code "${manifest_exit_code}" \
    "${number_or_null_jq}
    {
      schema_version: (\$schema_version | tonumber),
      evidence_id: \$evidence_id,
      phase: \$phase,
      scenario_id: \$scenario_id,
      run_id: \$run_id,
      outcome: \$outcome,
      stage: \$stage,
      start_time: \$start_time,
      end_time: \$end_time,
      git_revision: \$git_revision,
      git_dirty_before: (if \$git_status_before == \"unavailable\" then null else (\$git_status_before != \"\") end),
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
      audit_tool_bundle: {
        contract: \$audit_tool_bundle_contract,
        id: \$audit_tool_bundle_id,
        manifest_sha256: \$audit_tool_bundle_manifest_sha256,
        mount_mode: "read-only",
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
      direct_dependencies: {
        openmls: { version: \"=0.9.0\", default_features: false, features: [\"fork-resolution\"] },
        openmls_basic_credential: { version: \"=0.6.0\", features: [] },
        openmls_rust_crypto: { version: \"=0.6.0\", features: [] },
        openmls_sqlite_storage: { version: \"=0.3.0\", features: [] },
        openmls_traits: { version: \"=0.6.0\", features: [] },
        rusqlite: { version: \"=0.37.0\", features: [\"bundled\"] },
        serde: { version: \"=1.0.229\", features: [\"derive\"] },
        serde_json: { version: \"=1.0.151\", features: [] },
        tls_codec: { version: \"=0.5.0\", features: [\"derive\", \"serde\", \"mls\"] },
        tempfile: { version: \"=3.27.0\", dependency_kind: \"dev\", features: [] }
      },
      resolved_package_count: number_or_null(\$resolved_package_count),
      cargo_lock_sha256: \$cargo_lock_sha256,
      expected_lock_sha256: \$expected_lock_sha256,
      advisory_db_revision: \$advisory_db_revision,
      gate_exit_codes: {
        source: number_or_null(\$source_exit_code),
        audit: number_or_null(\$audit_exit_code),
        deny: number_or_null(\$deny_exit_code),
        feature: number_or_null(\$feature_exit_code)
      },
      input_sha256: {
        license: \$license_sha256,
        cargo_toml: \$cargo_toml_sha256,
        deny_toml: \$deny_toml_sha256,
        main_rs: \$main_rs_sha256,
        runtime_control_helper: \$runtime_control_helper_sha256,
        runner: \$runner_sha256,
        audit_tool_bundle_manifest: \$audit_tool_bundle_manifest_sha256,
        cargo_audit_binary: \$cargo_audit_binary_sha256,
        cargo_deny_binary: \$cargo_deny_binary_sha256
      },
      lockfile_preexisting: (\$lockfile_preexisting == \"true\"),
      lockfile_written: (\$lockfile_written == \"true\"),
      disk_available_kib: number_or_null(\$disk_available_kib),
      runtime_controls: {
        monitor_status: \$runtime_control_status,
        termination_reason: \$runtime_termination_reason,
        received_signal: (if \$received_signal == \"\" then null else \$received_signal end),
        elapsed_milliseconds: number_or_null(\$runtime_elapsed_milliseconds),
        timeout_seconds: (\$runtime_timeout_seconds | tonumber),
        deadline_enforcement: \"periodic-monitor-and-parent-signal\",
        disk_current_kib: number_or_null(\$runtime_disk_current_kib),
        disk_peak_kib: number_or_null(\$runtime_disk_peak_kib),
        disk_budget_kib: (\$runtime_disk_budget_kib | tonumber),
        disk_enforcement: \"periodic-apparent-size-monitor\",
        poll_interval_seconds: (\$runtime_poll_interval_seconds | tonumber),
        network_egress_enforcement: \"docker-default-network-no-domain-allowlist\"
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
  local evidence_name
  : > "${checksums_tmp}"

  append_checksum "${repo_root}/LICENSE" "LICENSE" "${checksums_tmp}"
  append_checksum "${spike_root}/Cargo.toml" "${spike_relative}/Cargo.toml" "${checksums_tmp}"
  append_checksum "${spike_root}/deny.toml" "${spike_relative}/deny.toml" "${checksums_tmp}"
  append_checksum "${spike_root}/src/main.rs" "${spike_relative}/src/main.rs" "${checksums_tmp}"
  append_checksum \
    "${runtime_control_helper}" \
    "scripts/monitor-sw-g2-openmls-0.9-run.py" \
    "${checksums_tmp}"
  append_checksum \
    "${repo_root}/scripts/run-sw-g2-openmls-0.9-spike.sh" \
    "scripts/run-sw-g2-openmls-0.9-spike.sh" \
    "${checksums_tmp}"
  append_checksum "${repo_lock}" "${lock_relative}" "${checksums_tmp}"

  for evidence_name in \
    Cargo.lock \
    advisory-db-revision.txt \
    audit-exit-codes.json \
    cargo-audit.json \
    cargo-deny-sources.txt \
    cargo-deny.txt \
    cargo-metadata.json \
    cargo-tree-duplicates.txt \
    cargo-tree-features.txt \
    cargo-tree.txt \
    container-toolchain.txt \
    generated-lock-sha256.txt \
    git-status-after.txt \
    git-status-before.txt \
    image-index.txt \
    image-inspect.json \
    manifest.json \
    runtime-control-trigger.json \
    runtime-control.json; do
    append_checksum \
      "${run_dir}/${evidence_name}" \
      "artifacts/sw-g2-openmls-0.9/${run_id}/${evidence_name}" \
      "${checksums_tmp}"
  done

  mv "${checksums_tmp}" "${run_dir}/checksums.sha256"
}

inputs_unchanged() {
  [ "$(git -C "${repo_root}" rev-parse HEAD)" = "${git_revision}" ] &&
    [ "$(shasum -a 256 "${repo_root}/LICENSE" | awk '{print $1}')" = "${license_sha}" ] &&
    [ "$(shasum -a 256 "${spike_root}/Cargo.toml" | awk '{print $1}')" = "${cargo_toml_sha}" ] &&
    [ "$(shasum -a 256 "${spike_root}/deny.toml" | awk '{print $1}')" = "${deny_toml_sha}" ] &&
    [ "$(shasum -a 256 "${spike_root}/src/main.rs" | awk '{print $1}')" = "${main_rs_sha}" ] &&
    [ "$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')" = "${runtime_control_helper_sha}" ] &&
    [ "$(shasum -a 256 "${repo_root}/scripts/run-sw-g2-openmls-0.9-spike.sh" | awk '{print $1}')" = "${runner_sha}" ] &&
    [ "$(shasum -a 256 "${audit_tool_bundle_manifest}" | awk '{print $1}')" = "${audit_tool_bundle_manifest_sha}" ] &&
    [ "$(shasum -a 256 "${audit_tool_bundle_bin}/cargo-audit" | awk '{print $1}')" = "${cargo_audit_binary_sha}" ] &&
    [ "$(shasum -a 256 "${audit_tool_bundle_bin}/cargo-deny" | awk '{print $1}')" = "${cargo_deny_binary_sha}" ]
}

promote_lockfile() {
  local current_repo_status
  local current_lock_sha

  if [ ! -f "${run_dir}/Cargo.lock" ] || [ -L "${run_dir}/Cargo.lock" ]; then
    echo "STOP: generated Cargo.lock evidence is missing or is a symbolic link" >&2
    return 25
  fi
  if ! inputs_unchanged; then
    echo "STOP: HEAD or fixed inputs changed during Phase A" >&2
    return 25
  fi

  current_repo_status="$(git -C "${repo_root}" status --short --untracked-files=all)"
  if [ -n "${current_repo_status}" ]; then
    echo "STOP: unexpected workspace change appeared before lockfile promotion" >&2
    return 25
  fi

  if [ "${lockfile_preexisting}" = true ]; then
    current_lock_sha="$(shasum -a 256 "${repo_lock}" | awk '{print $1}')"
    if [ "${current_lock_sha}" != "${lock_sha}" ] || [ "${current_lock_sha}" != "${expected_lock_sha}" ]; then
      echo "STOP: regenerated Cargo.lock does not match the reviewed repository lockfile" >&2
      return 21
    fi
    return 0
  fi

  if [ -e "${repo_lock}" ] || [ -L "${repo_lock}" ] || [ -e "${promotion_temp}" ] || [ -L "${promotion_temp}" ]; then
    echo "STOP: lockfile promotion target changed during Phase A" >&2
    return 25
  fi

  cp "${run_dir}/Cargo.lock" "${promotion_temp}"
  chmod 0644 "${promotion_temp}"
  if ! ln "${promotion_temp}" "${repo_lock}"; then
    rm -f -- "${promotion_temp}"
    echo "STOP: repository Cargo.lock appeared during atomic promotion" >&2
    return 25
  fi
  rm -f -- "${promotion_temp}"
  lockfile_written=true

  current_repo_status="$(git -C "${repo_root}" status --short --untracked-files=all)"
  if [ "${current_repo_status}" != "?? ${lock_relative}" ]; then
    echo "STOP: workspace contains changes other than the generated Cargo.lock" >&2
    return 25
  fi
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

load_partial_dependency_state() {
  local advisory_git_dir=""

  if [ -f "${run_dir}/Cargo.lock" ] && [ ! -L "${run_dir}/Cargo.lock" ]; then
    lock_sha="$(shasum -a 256 "${run_dir}/Cargo.lock" | awk '{print $1}')"
  fi
  if [ -f "${run_dir}/cargo-metadata.json" ] && [ ! -L "${run_dir}/cargo-metadata.json" ] &&
    jq -e '.packages | type == "array"' "${run_dir}/cargo-metadata.json" >/dev/null 2>&1; then
    resolved_package_count="$(jq '.packages | length' "${run_dir}/cargo-metadata.json")"
  fi
  if [ -f "${run_dir}/audit-exit-codes.json" ] && [ ! -L "${run_dir}/audit-exit-codes.json" ] &&
    jq -e . "${run_dir}/audit-exit-codes.json" >/dev/null 2>&1; then
    source_status="$(jq -r '.source // "unavailable"' "${run_dir}/audit-exit-codes.json")"
    audit_status="$(jq -r '.audit // "unavailable"' "${run_dir}/audit-exit-codes.json")"
    deny_status="$(jq -r '.deny // "unavailable"' "${run_dir}/audit-exit-codes.json")"
    feature_status="$(jq -r '.feature // "unavailable"' "${run_dir}/audit-exit-codes.json")"
  fi
  if [ -f "${run_dir}/advisory-db-revision.txt" ] &&
    [ ! -L "${run_dir}/advisory-db-revision.txt" ]; then
    advisory_db_revision="$(awk 'NF { print; found = 1; exit } END { if (!found) exit 1 }' \
      "${run_dir}/advisory-db-revision.txt" 2>/dev/null || printf '%s' unavailable)"
  elif [ -d "${work_dir}/cargo-home" ] && [ ! -L "${work_dir}/cargo-home" ]; then
    advisory_git_dir="$(find "${work_dir}/cargo-home" -type d -name .git -path '*/advisory-db*' -print -quit 2>/dev/null || true)"
    if [ -n "${advisory_git_dir}" ]; then
      advisory_db_revision="$(git --git-dir "${advisory_git_dir}" rev-parse HEAD 2>/dev/null || printf '%s' unavailable)"
    fi
  fi
}

evaluate_feature_gate() {
  if [ ! -f "${run_dir}/cargo-metadata.json" ] || [ -L "${run_dir}/cargo-metadata.json" ] ||
    ! jq -e . "${run_dir}/cargo-metadata.json" >/dev/null 2>&1; then
    feature_status="unavailable"
    return 0
  fi

  set +e
  jq -e '
    . as $metadata
    | [$metadata.packages[] | select(.name == "hpke-rs" and (.version | startswith("0.7."))) | .id] as $hpke_ids
    | [$metadata.packages[] | select(.name | startswith("openmls")) | .id] as $openmls_ids
    | ($hpke_ids | length) > 0
      and ($openmls_ids | length) > 0
      and all($hpke_ids[];
        . as $package_id
        | any($metadata.resolve.nodes[];
            .id == $package_id and (.features | index("experimental") != null)))
      and all($openmls_ids[];
        . as $package_id
        | any($metadata.resolve.nodes[];
            .id == $package_id
            and ([.features[] | select(
              . == "content-debug"
              or . == "crypto-debug"
              or . == "test-utils"
              or . == "backtrace"
              or . == "migration-import"
              or . == "migration-export"
              or . == "0-8-1-storage-format"
            )] | length) == 0))
  ' "${run_dir}/cargo-metadata.json" >/dev/null
  feature_status=$?
  set -e
}

write_gate_exit_codes() {
  jq -n \
    --arg source "${source_status}" \
    --arg audit "${audit_status}" \
    --arg deny "${deny_status}" \
    --arg feature "${feature_status}" \
    "${number_or_null_jq}
    {
      source: number_or_null(\$source),
      audit: number_or_null(\$audit),
      deny: number_or_null(\$deny),
      feature: number_or_null(\$feature)
    }" > "${run_dir}/audit-exit-codes.json.tmp"
  mv "${run_dir}/audit-exit-codes.json.tmp" "${run_dir}/audit-exit-codes.json"
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
  local expected_status=""
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

  # Signals and runtime stops bypass the normal post-container path. Recover only
  # evidence that was already written; do not run or imply an unexecuted gate.
  load_partial_dependency_state

  if [ -e "${promotion_temp}" ] && [ -f "${promotion_temp}" ] && [ ! -L "${promotion_temp}" ]; then
    rm -f -- "${promotion_temp}"
  fi

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
  if [ "${lockfile_written}" = true ]; then
    expected_status="?? ${lock_relative}"
  fi
  if [ "${git_status_after}" != "${expected_status}" ]; then
    workflow_exit_code=1
    final_stage="workspace-finalize"
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
      INT)
        runtime_termination_reason="external_interrupt"
        ;;
      TERM)
        runtime_termination_reason="external_termination"
        ;;
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
    echo "STOP: could not finalize manifest" >&2
    workflow_exit_code=1
    final_stage="evidence-finalize"
  fi
  if ! write_checksums; then
    echo "STOP: could not finalize checksums" >&2
    workflow_exit_code=1
    final_stage="evidence-finalize"
    write_manifest "${workflow_exit_code}" "STOP" "${final_stage}" || true
    write_checksums || true
  fi

  echo "SW-EXP-004 Phase A run: ${run_id}"
  echo "Evidence directory: artifacts/sw-g2-openmls-0.9/${run_id}"
  echo "Prepared cache retained under the run .work directory."
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

echo "[1/8] record repository, host, daemon, disk, and image pre-state"
current_stage="record-state"
license_sha="$(shasum -a 256 "${repo_root}/LICENSE" | awk '{print $1}')"
cargo_toml_sha="$(shasum -a 256 "${spike_root}/Cargo.toml" | awk '{print $1}')"
deny_toml_sha="$(shasum -a 256 "${spike_root}/deny.toml" | awk '{print $1}')"
main_rs_sha="$(shasum -a 256 "${spike_root}/src/main.rs" | awk '{print $1}')"
runtime_control_helper_sha="$(shasum -a 256 "${runtime_control_helper}" | awk '{print $1}')"
runner_sha="$(shasum -a 256 "${repo_root}/scripts/run-sw-g2-openmls-0.9-spike.sh" | awk '{print $1}')"
if [ -f "${repo_lock}" ]; then
  lockfile_preexisting=true
  expected_lock_sha="$(shasum -a 256 "${repo_lock}" | awk '{print $1}')"
fi
git_revision="$(git -C "${repo_root}" rev-parse HEAD)"
git_status_before="$(git -C "${repo_root}" status --short --untracked-files=all)"
printf '%s\n' "${git_status_before}" > "${run_dir}/git-status-before.txt"
if [ -n "${git_status_before}" ]; then
  echo "STOP: Phase A requires a clean worktree" >&2
  exit 10
fi
host_arch="$(uname -m)"
disk_available_kib="$(df -Pk "${artifact_root}" | awk 'NR == 2 { print $4; exit }')"
if ! [[ "${disk_available_kib}" =~ ^[0-9]+$ ]] || [ "${disk_available_kib}" -lt "${minimum_disk_kib}" ]; then
  echo "STOP: less than 5 GiB is available for the isolated Phase A run" >&2
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
if ! run_controlled docker ps -a \
  --filter "label=${label_key}=${run_id}" \
  --format '{{.ID}}' > "${work_dir}/preexisting-containers.txt"; then
  echo "STOP: could not inspect exact run label residuals" >&2
  exit 10
fi
if [ -s "${work_dir}/preexisting-containers.txt" ]; then
  echo "STOP: exact run label already has residual containers" >&2
  exit 10
fi

echo "[2/8] copy fixed inputs into the isolated run directory"
current_stage="prepare-isolated-source"
cp "${repo_root}/LICENSE" "${prepared_repo}/LICENSE"
cp "${spike_root}/Cargo.toml" "${spike_root}/deny.toml" "${prepared_spike}/"
cp "${spike_root}/src/main.rs" "${prepared_spike}/src/main.rs"
if [ "${lockfile_preexisting}" = true ]; then
  cp "${repo_lock}" "${prepared_spike}/Cargo.lock"
fi

echo "[3/8] verify immutable Docker image identity"
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
    jq -r \
      '.[0] | "Image-ID: \(.Id)\nOS/Architecture: \(.Os)/\(.Architecture)\nRepoDigests: \(.RepoDigests | tojson)"' \
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

echo "[4/8] ensure the fixed Linux ARM64 Rust image"
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

echo "[5/8] verify container architecture and Rust toolchain without network"
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

if ! rg -q '^Linux aarch64$' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: container is not Linux aarch64" >&2
  exit 12
fi
if ! rg -q '^release: 1\.96\.1$' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: container rustc is not 1.96.1" >&2
  exit 12
fi
if ! rg -q '^cargo 1\.96\.1 ' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: container cargo is not 1.96.1" >&2
  exit 12
fi
container_arch="$(awk 'NR == 1 { print $2; exit }' "${run_dir}/container-toolchain.txt")"
rust_version="$(awk '/^rustc / { print; exit }' "${run_dir}/container-toolchain.txt")"
cargo_version="$(awk '/^cargo / { print; exit }' "${run_dir}/container-toolchain.txt")"

echo "[6/8] generate the independent lockfile and run gates with the verified read-only audit tool bundle"
current_stage="dependency-audit"
set +e
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
  --mount "type=bind,source=${run_dir},target=/evidence" \
  --mount "type=bind,source=${audit_tool_bundle_bin},target=/audit-tools/bin,readonly" \
  --workdir "/evidence/.work/repo/${spike_relative}" \
  "${image_ref}" \
  sh -euc '
    mkdir -p "$HOME" "$CARGO_HOME" "$CARGO_TARGET_DIR"
    cargo generate-lockfile
    cp Cargo.lock /evidence/Cargo.lock
    generated_lock_sha="$(sha256sum Cargo.lock | awk '\''{print $1}'\'')"
    printf "%s\n" "$generated_lock_sha" > /evidence/generated-lock-sha256.txt
    cargo fetch --locked --target aarch64-unknown-linux-gnu
    cargo metadata --locked --format-version 1 > /evidence/cargo-metadata.json
    cargo tree --locked --target all > /evidence/cargo-tree.txt
    cargo tree --locked --target all --edges features > /evidence/cargo-tree-features.txt
    cargo tree --locked --duplicates > /evidence/cargo-tree-duplicates.txt
    set +e
    /audit-tools/bin/cargo-deny check sources > /evidence/cargo-deny-sources.txt 2>&1
    source_status=$?
    /audit-tools/bin/cargo-audit --json > /evidence/cargo-audit.json
    audit_status=$?
    /audit-tools/bin/cargo-deny check advisories licenses > /evidence/cargo-deny.txt 2>&1
    deny_status=$?
    set -e
    printf "{\"source\":%s,\"audit\":%s,\"deny\":%s}\n" \
      "$source_status" "$audit_status" "$deny_status" \
      > /evidence/audit-exit-codes.json
    if [ "$source_status" -ne 0 ]; then
      exit 23
    fi
    if [ "$audit_status" -ne 0 ] || [ "$deny_status" -ne 0 ]; then
      exit 20
    fi
  '
prepare_status=$?
set -e

load_partial_dependency_state
evaluate_feature_gate
write_gate_exit_codes

echo "[7/8] record advisory revision and apply feature/source promotion gates"
current_stage="gate-finalize"
load_partial_dependency_state
printf '%s\n' "${advisory_db_revision}" > "${run_dir}/advisory-db-revision.txt"

if [[ "${feature_status}" =~ ^[0-9]+$ ]] && [ "${feature_status}" -ne 0 ]; then
  final_stage="feature-gate"
  echo "STOP: hpke-rs/OpenMLS feature resolution did not match the accepted gate" >&2
  exit 24
fi
if [ "${source_status}" = "0" ]; then
  set +e
  promote_lockfile
  promotion_status=$?
  set -e
  if [ "${promotion_status}" -ne 0 ]; then
    final_stage="lockfile-promotion"
    exit "${promotion_status}"
  fi
fi

echo "[8/8] enforce the Phase A stop gate"
if [ "${prepare_status}" -ne 0 ]; then
  final_stage="dependency-audit"
  echo "STOP: dependency or audit preparation failed with exit code ${prepare_status}" >&2
  exit "${prepare_status}"
fi
if [ "${feature_status}" != "0" ]; then
  final_stage="feature-gate"
  echo "STOP: feature gate result is unavailable or non-zero" >&2
  exit 24
fi
if [ "${source_status}" != "0" ] || [ "${audit_status}" != "0" ] || [ "${deny_status}" != "0" ]; then
  final_stage="dependency-audit"
  echo "STOP: one or more Phase A gate results are unavailable or non-zero" >&2
  exit 20
fi

final_stage="phase-a-prepared"
echo "SW-EXP-004 PHASE A PASS: source, feature, license, and advisory gates returned zero."
echo "Phase B was not run and still requires a separate authorization package."
