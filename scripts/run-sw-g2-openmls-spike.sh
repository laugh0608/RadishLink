#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
spike_root="${repo_root}/tools/spikes/sw-g2-openmls"
artifact_parent="${repo_root}/artifacts"
artifact_root="${artifact_parent}/sw-g2-openmls"
image_digest="sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663"
image_ref="rust:1.96.1-bookworm@${image_digest}"
expected_platform="linux/arm64"
scenario_id="phase-a-dependency-audit"

usage() {
  echo "usage: $0 prepare" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

action=$1
if [ "${action}" != "prepare" ]; then
  echo "only Phase A 'prepare' is implemented; Phase B remains blocked" >&2
  exit 2
fi

for command_name in awk basename cp date docker find git id jq mkdir mktemp mv rg shasum tee uname; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

required_inputs=(
  "${repo_root}/LICENSE"
  "${spike_root}/Cargo.toml"
  "${spike_root}/Cargo.lock"
  "${spike_root}/deny.toml"
  "${spike_root}/src/evidence.rs"
  "${spike_root}/src/main.rs"
  "${spike_root}/src/scenario.rs"
  "${spike_root}/src/store.rs"
)
for required_input in "${required_inputs[@]}"; do
  if [ ! -f "${required_input}" ] || [ -L "${required_input}" ]; then
    echo "required regular input is missing or is a symbolic link: ${required_input}" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is unavailable; no Phase A resources were created." >&2
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
container_name="radishlink-sw-g2-openmls-prepare-${run_id}"
run_log="${run_dir}/run.log"
start_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
end_time="unavailable"
current_stage="preflight"
final_stage=""
git_revision="unavailable"
git_status=""
git_dirty="unknown"
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

mkdir -p \
  "${work_dir}/cargo-home" \
  "${work_dir}/cargo-target" \
  "${work_dir}/audit-tools" \
  "${prepared_repo}/tools/spikes/sw-g2-openmls/src"

write_manifest() {
  local manifest_exit_code=$1
  local manifest_outcome=$2
  local manifest_stage=$3
  local manifest_tmp="${run_dir}/manifest.json.tmp"

  jq -n \
    --arg schema_version "2" \
    --arg evidence_id "SW-EXP-002" \
    --arg phase "phase-a" \
    --arg scenario_id "${scenario_id}" \
    --arg run_id "${run_id}" \
    --arg outcome "${manifest_outcome}" \
    --arg stage "${manifest_stage}" \
    --arg start_time "${start_time}" \
    --arg end_time "${end_time}" \
    --arg git_revision "${git_revision}" \
    --arg git_dirty "${git_dirty}" \
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
    --arg cargo_lock_sha256 "${lock_sha}" \
    --arg advisory_db_revision "${advisory_db_revision}" \
    --arg exit_code "${manifest_exit_code}" \
    '{
      schema_version: ($schema_version | tonumber),
      evidence_id: $evidence_id,
      phase: $phase,
      scenario_id: $scenario_id,
      run_id: $run_id,
      outcome: $outcome,
      stage: $stage,
      start_time: $start_time,
      end_time: $end_time,
      git_revision: $git_revision,
      git_dirty: (
        if $git_dirty == "true" then true
        elif $git_dirty == "false" then false
        else null
        end
      ),
      image_ref: $image_ref,
      image_index_digest: $image_index_digest,
      image_platform_id: $image_platform_id,
      image_preexisting: (
        if $image_preexisting == "true" then true
        elif $image_preexisting == "false" then false
        else null
        end
      ),
      host_arch: $host_arch,
      daemon_arch: $daemon_arch,
      container_arch: $container_arch,
      target_platform: $target_platform,
      rust_version: $rust_version,
      cargo_version: $cargo_version,
      cargo_lock_sha256: $cargo_lock_sha256,
      advisory_db_revision: $advisory_db_revision,
      exit_code: ($exit_code | tonumber)
    }' > "${manifest_tmp}"
  mv "${manifest_tmp}" "${run_dir}/manifest.json"
}

append_checksum() {
  local checksum_path=$1
  local checksum_label=$2
  local checksum_output=$3
  local checksum_value

  if [ -f "${checksum_path}" ]; then
    checksum_value="$(shasum -a 256 "${checksum_path}" | awk '{print $1}')"
    printf '%s  %s\n' "${checksum_value}" "${checksum_label}" >> "${checksum_output}"
  fi
}

write_checksums() {
  local checksums_tmp="${run_dir}/checksums.sha256.tmp"
  local source_name
  local evidence_name
  : > "${checksums_tmp}"

  append_checksum "${repo_root}/LICENSE" "LICENSE" "${checksums_tmp}"
  append_checksum \
    "${spike_root}/Cargo.toml" \
    "tools/spikes/sw-g2-openmls/Cargo.toml" \
    "${checksums_tmp}"
  append_checksum \
    "${spike_root}/Cargo.lock" \
    "tools/spikes/sw-g2-openmls/Cargo.lock" \
    "${checksums_tmp}"
  append_checksum \
    "${spike_root}/deny.toml" \
    "tools/spikes/sw-g2-openmls/deny.toml" \
    "${checksums_tmp}"

  for source_name in evidence.rs main.rs scenario.rs store.rs; do
    append_checksum \
      "${spike_root}/src/${source_name}" \
      "tools/spikes/sw-g2-openmls/src/${source_name}" \
      "${checksums_tmp}"
  done

  for evidence_name in \
    advisory-db-revision.txt \
    audit-exit-codes.json \
    cargo-audit.json \
    cargo-deny.txt \
    cargo-metadata.json \
    cargo-tree.txt \
    container-toolchain.txt \
    generated-lock-sha256.txt \
    git-status.txt \
    image-index.txt \
    image-inspect.json \
    manifest.json; do
    append_checksum \
      "${run_dir}/${evidence_name}" \
      "artifacts/sw-g2-openmls/${run_id}/${evidence_name}" \
      "${checksums_tmp}"
  done

  mv "${checksums_tmp}" "${run_dir}/checksums.sha256"
}

cleanup() {
  local workflow_exit_code=$?
  local container_label=""
  local manifest_outcome
  local manifest_stage
  local manifest_status
  local checksum_status
  trap - EXIT INT TERM
  set +e

  if docker container inspect "${container_name}" >/dev/null 2>&1; then
    container_label="$(docker container inspect "${container_name}" \
      --format '{{ index .Config.Labels "org.radishlink.sw-g2-openmls.run" }}' 2>/dev/null)"
    if [ "${container_label}" = "${run_id}" ]; then
      docker rm -f "${container_name}" >/dev/null 2>&1 || true
    else
      echo "STOP: container name exists but its run label does not match; it was not removed" >&2
      if [ "${workflow_exit_code}" -eq 0 ]; then
        workflow_exit_code=1
        final_stage="container-cleanup"
      fi
    fi
  fi
  end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  if [ "${workflow_exit_code}" -eq 0 ]; then
    manifest_outcome="PASS"
  else
    manifest_outcome="STOP"
  fi
  manifest_stage="${final_stage:-${current_stage}}"

  write_manifest "${workflow_exit_code}" "${manifest_outcome}" "${manifest_stage}"
  manifest_status=$?
  if [ "${manifest_status}" -ne 0 ]; then
    echo "STOP: could not finalize manifest (exit ${manifest_status})" >&2
    workflow_exit_code=1
  else
    write_checksums
    checksum_status=$?
    if [ "${checksum_status}" -ne 0 ]; then
      echo "STOP: could not finalize checksums (exit ${checksum_status})" >&2
      if [ "${workflow_exit_code}" -eq 0 ]; then
        workflow_exit_code=1
        write_manifest "1" "STOP" "evidence-finalize" || true
      fi
    fi
  fi

  echo "SW-EXP-002 Phase A run: ${run_id}"
  echo "Evidence directory: ${run_dir}"
  echo "Prepared cache remains under: ${work_dir}"
  exit "${workflow_exit_code}"
}
trap cleanup EXIT INT TERM

exec > >(tee -a "${run_log}") 2>&1

current_stage="prepare-isolated-source"
cp "${repo_root}/LICENSE" "${prepared_repo}/LICENSE"
cp \
  "${spike_root}/Cargo.toml" \
  "${spike_root}/Cargo.lock" \
  "${spike_root}/deny.toml" \
  "${prepared_repo}/tools/spikes/sw-g2-openmls/"
cp \
  "${spike_root}/src/evidence.rs" \
  "${spike_root}/src/main.rs" \
  "${spike_root}/src/scenario.rs" \
  "${spike_root}/src/store.rs" \
  "${prepared_repo}/tools/spikes/sw-g2-openmls/src/"

echo "[1/7] record host, daemon, repository, and pre-existing image state"
current_stage="record-state"
git_revision="$(git -C "${repo_root}" rev-parse HEAD)"
git_status="$(git -C "${repo_root}" status --short)"
if [ -n "${git_status}" ]; then
  git_dirty=true
else
  git_dirty=false
fi
host_arch="$(uname -m)"
daemon_arch="$(docker info --format '{{.Architecture}}')"
lock_sha="$(shasum -a 256 "${spike_root}/Cargo.lock" | awk '{print $1}')"
if docker image inspect "${image_ref}" >/dev/null 2>&1; then
  image_preexisting=true
else
  image_preexisting=false
fi
printf '%s\n' "${git_status}" > "${run_dir}/git-status.txt"

echo "[2/7] verify immutable Docker image identity"
current_stage="image-index-inspect"
if [ "${image_preexisting}" = true ]; then
  docker image inspect "${image_ref}" > "${run_dir}/image-inspect.json"
  if ! jq -e --arg digest "${image_digest}" \
    'any(.[0].RepoDigests[]?; endswith("@" + $digest))' \
    "${run_dir}/image-inspect.json" >/dev/null; then
    echo "STOP: local image RepoDigests do not contain '${image_digest}'" >&2
    exit 1
  fi
  resolved_index_digest="${image_digest}"
  {
    echo "Source: local exact-digest image"
    echo "Digest: ${resolved_index_digest}"
    docker image inspect "${image_ref}" \
      --format 'Image-ID: {{.Id}}\nOS/Architecture: {{.Os}}/{{.Architecture}}\nRepoDigests: {{json .RepoDigests}}'
  } > "${run_dir}/image-index.txt"
else
  docker buildx imagetools inspect "${image_ref}" > "${run_dir}/image-index.txt"
  resolved_index_digest="$(awk '$1 == "Digest:" { print $2; exit }' "${run_dir}/image-index.txt")"
  if [ "${resolved_index_digest}" != "${image_digest}" ]; then
    echo "STOP: resolved image index digest '${resolved_index_digest}' does not match '${image_digest}'" >&2
    exit 1
  fi
fi

echo "[3/7] ensure fixed Linux ARM64 Rust image"
current_stage="image-pull"
if [ "${image_preexisting}" = true ]; then
  echo "fixed image already exists locally; skip redundant registry pull"
else
  docker pull --platform "${expected_platform}" "${image_ref}"
fi
docker image inspect "${image_ref}" > "${run_dir}/image-inspect.json"
if ! jq -e --arg digest "${image_digest}" \
  'any(.[0].RepoDigests[]?; endswith("@" + $digest))' \
  "${run_dir}/image-inspect.json" >/dev/null; then
  echo "STOP: prepared image RepoDigests do not contain '${image_digest}'" >&2
  exit 1
fi
if [ "$(docker image inspect "${image_ref}" --format '{{.Os}}/{{.Architecture}}')" != "${expected_platform}" ]; then
  echo "STOP: prepared local image is not ${expected_platform}" >&2
  exit 1
fi
image_platform_id="$(jq -r '.[0].Id // "unavailable"' "${run_dir}/image-inspect.json")"

echo "[4/7] verify container architecture and Rust toolchain"
current_stage="toolchain-verify"
docker run --rm \
  --name "${container_name}" \
  --label "org.radishlink.sw-g2-openmls.run=${run_id}" \
  --platform "${expected_platform}" \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  "${image_ref}" \
  sh -c 'uname -sm; rustc -vV; cargo -vV' > "${run_dir}/container-toolchain.txt"

if ! rg -q '^Linux aarch64$' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: container is not Linux aarch64" >&2
  exit 1
fi
if ! rg -q '^release: 1\.96\.1$' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: container rustc is not 1.96.1" >&2
  exit 1
fi
if ! rg -q '^cargo 1\.96\.1 ' "${run_dir}/container-toolchain.txt"; then
  echo "STOP: container cargo is not 1.96.1" >&2
  exit 1
fi
container_arch="$(awk 'NR == 1 { print $2; exit }' "${run_dir}/container-toolchain.txt")"
rust_version="$(awk '/^rustc / { print; exit }' "${run_dir}/container-toolchain.txt")"
cargo_version="$(awk '/^cargo / { print; exit }' "${run_dir}/container-toolchain.txt")"

echo "[5/7] regenerate the isolated lockfile, fetch the fixed graph, and run audits"
current_stage="dependency-audit"
host_user="$(id -u):$(id -g)"
set +e
docker run --rm \
  --name "${container_name}" \
  --label "org.radishlink.sw-g2-openmls.run=${run_id}" \
  --platform "${expected_platform}" \
  --read-only \
  --cpus 4 \
  --memory 4g \
  --user "${host_user}" \
  --tmpfs /tmp:rw,nosuid,size=256m \
  --env HOME=/tmp/home \
  --env CARGO_HOME=/evidence/.work/cargo-home \
  --env CARGO_TARGET_DIR=/evidence/.work/cargo-target \
  --env EXPECTED_LOCK_SHA256="${lock_sha}" \
  --mount "type=bind,source=${run_dir},target=/evidence" \
  --workdir /evidence/.work/repo/tools/spikes/sw-g2-openmls \
  "${image_ref}" \
  sh -euc '
    mkdir -p "$HOME" "$CARGO_HOME" "$CARGO_TARGET_DIR" /evidence/.work/audit-tools
    cargo generate-lockfile
    generated_lock_sha="$(sha256sum Cargo.lock | awk '\''{print $1}'\'')"
    printf "%s\n" "$generated_lock_sha" > /evidence/generated-lock-sha256.txt
    if [ "$generated_lock_sha" != "$EXPECTED_LOCK_SHA256" ]; then
      echo "STOP: regenerated Cargo.lock does not match the reviewed lockfile" >&2
      exit 21
    fi
    cargo fetch --locked --target aarch64-unknown-linux-gnu
    cargo install cargo-audit --version 0.22.2 --locked --root /evidence/.work/audit-tools
    cargo install cargo-deny --version 0.20.2 --locked --root /evidence/.work/audit-tools
    export PATH="/evidence/.work/audit-tools/bin:$PATH"
    cargo metadata --locked --format-version 1 > /evidence/cargo-metadata.json
    cargo tree --locked --target all > /evidence/cargo-tree.txt
    set +e
    cargo audit --json > /evidence/cargo-audit.json
    audit_status=$?
    cargo deny check advisories licenses sources > /evidence/cargo-deny.txt 2>&1
    deny_status=$?
    set -e
    printf "{\"cargo_audit\":%s,\"cargo_deny\":%s}\n" "$audit_status" "$deny_status" > /evidence/audit-exit-codes.json
    if [ "$audit_status" -ne 0 ] || [ "$deny_status" -ne 0 ]; then
      exit 20
    fi
  '
prepare_status=$?
set -e

current_lock_sha="$(shasum -a 256 "${spike_root}/Cargo.lock" | awk '{print $1}')"
if [ "${current_lock_sha}" != "${lock_sha}" ]; then
  echo "STOP: repository Cargo.lock changed during isolated preparation" >&2
  prepare_status=22
fi

echo "[6/7] record advisory database revision"
current_stage="evidence-finalize"
advisory_git_dir="$(find "${work_dir}/cargo-home" -type d -name .git -path '*/advisory-db*' -print -quit 2>/dev/null || true)"
if [ -n "${advisory_git_dir}" ]; then
  advisory_db_revision="$(git --git-dir "${advisory_git_dir}" rev-parse HEAD)"
fi
printf '%s\n' "${advisory_db_revision}" > "${run_dir}/advisory-db-revision.txt"

echo "[7/7] enforce Phase A stop gate"
if [ "${prepare_status}" -ne 0 ]; then
  final_stage="dependency-audit"
  echo "STOP: dependency or audit preparation failed with exit code ${prepare_status}" >&2
  exit "${prepare_status}"
fi

final_stage="phase-a-prepared"
echo "SW-EXP-002 PHASE A PASS: the isolated lockfile matched and audits returned zero."
echo "Phase B was not run and still requires separate authorization."
