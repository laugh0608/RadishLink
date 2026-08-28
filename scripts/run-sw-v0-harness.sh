#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "usage: $0 run" >&2
  echo "Docker execution is L3 and requires separate current-task authorization." >&2
}

if [[ $# -ne 1 || "$1" != "run" ]]; then
  usage
  exit 2
fi

umask 077

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
ARTIFACT_ROOT="${REPO_ROOT}/artifacts/sw-v/sw-v0-${RUN_ID}"
mkdir -p "${ARTIFACT_ROOT}"
WORK_DIR="$(mktemp -d "${ARTIFACT_ROOT}/.work.XXXXXX")"
BUILD_CONTEXT="${WORK_DIR}/build-context"
BINARY_PATH="${BUILD_CONTEXT}/sw-v0-harness"
IMAGE_NAME="radishlink/sw-v0:${RUN_ID}"
RUN_LABEL="org.radishlink.sw-v0.run=${RUN_ID}"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
GIT_REVISION="$(git -C "${REPO_ROOT}" rev-parse HEAD)"
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]]; then
  GIT_DIRTY=true
else
  GIT_DIRTY=false
fi

CONTAINERS=()
NETWORKS=()
CLEANUP_INVALID=0
IMAGE_DIGEST="unavailable"
BINARY_DIGEST="unavailable"
PROFILE_TOPOLOGY_DIGEST="$(shasum -a 256 "${REPO_ROOT}/tools/t0/profiles/sw-v0-topology-001.json" | awk '{print $1}')"
PROFILE_FAULT_DIGEST="$(shasum -a 256 "${REPO_ROOT}/tools/t0/profiles/sw-v0-fault-hit-001.json" | awk '{print $1}')"
PROFILE_EVIDENCE_DIGEST="$(shasum -a 256 "${REPO_ROOT}/tools/t0/profiles/sw-v0-evidence-001.json" | awk '{print $1}')"
PROFILE_CLOCK_DIGEST="$(shasum -a 256 "${REPO_ROOT}/tools/t0/profiles/sw-v0-clock-001.json" | awk '{print $1}')"

resource_label() {
  local kind="$1"
  local name="$2"
  case "${kind}" in
    container)
      docker inspect --format '{{ index .Config.Labels "org.radishlink.sw-v0.run" }}' "${name}" 2>/dev/null || true
      ;;
    network)
      docker network inspect --format '{{ index .Labels "org.radishlink.sw-v0.run" }}' "${name}" 2>/dev/null || true
      ;;
    image)
      docker image inspect --format '{{ index .Config.Labels "org.radishlink.sw-v0.run" }}' "${name}" 2>/dev/null || true
      ;;
    *)
      return 2
      ;;
  esac
}

remove_container_exact() {
  local name="$1"
  local actual
  actual="$(resource_label container "${name}")"
  if [[ -z "${actual}" ]]; then
    return 0
  fi
  if [[ "${actual}" != "${RUN_ID}" ]]; then
    echo "refusing to remove container ${name}: run label is ${actual}" >&2
    CLEANUP_INVALID=1
    return 0
  fi
  docker rm -f "${name}" >/dev/null || CLEANUP_INVALID=1
}

remove_network_exact() {
  local name="$1"
  local actual
  actual="$(resource_label network "${name}")"
  if [[ -z "${actual}" ]]; then
    return 0
  fi
  if [[ "${actual}" != "${RUN_ID}" ]]; then
    echo "refusing to remove network ${name}: run label is ${actual}" >&2
    CLEANUP_INVALID=1
    return 0
  fi
  docker network rm "${name}" >/dev/null || CLEANUP_INVALID=1
}

remove_image_exact() {
  local actual
  actual="$(resource_label image "${IMAGE_NAME}")"
  if [[ -z "${actual}" ]]; then
    return 0
  fi
  if [[ "${actual}" != "${RUN_ID}" ]]; then
    echo "refusing to remove image ${IMAGE_NAME}: run label is ${actual}" >&2
    CLEANUP_INVALID=1
    return 0
  fi
  docker image rm "${IMAGE_NAME}" >/dev/null || CLEANUP_INVALID=1
}

cleanup_resources() {
  local index
  for ((index=${#CONTAINERS[@]}-1; index>=0; index--)); do
    remove_container_exact "${CONTAINERS[index]}"
  done
  for ((index=${#NETWORKS[@]}-1; index>=0; index--)); do
    remove_network_exact "${NETWORKS[index]}"
  done
  remove_image_exact
}

count_labeled_resources() {
  local kind="$1"
  local count
  case "${kind}" in
    container)
      count="$(docker ps -aq --filter "label=${RUN_LABEL}" 2>/dev/null | awk 'NF {count++} END {print count+0}')"
      ;;
    network)
      count="$(docker network ls -q --filter "label=${RUN_LABEL}" 2>/dev/null | awk 'NF {count++} END {print count+0}')"
      ;;
    image)
      count="$(docker image ls -q --filter "label=${RUN_LABEL}" 2>/dev/null | awk 'NF {count++} END {print count+0}')"
      ;;
    *)
      return 2
      ;;
  esac
  echo "${count}"
}

write_overall_manifest() {
  local exit_code="$1"
  local container_count="$2"
  local network_count="$3"
  local image_count="$4"
  local result="INVALID"
  local ended_at
  ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ "${exit_code}" -eq 0 && "${CLEANUP_INVALID}" -eq 0 && "${container_count}" -eq 0 && "${network_count}" -eq 0 && "${image_count}" -eq 0 ]]; then
    result="PASS"
  fi
  printf '%s\n' \
    '{' \
    '  "schema_version": 1,' \
    "  \"run_id\": \"${RUN_ID}\"," \
    "  \"git_revision\": \"${GIT_REVISION}\"," \
    "  \"git_dirty\": ${GIT_DIRTY}," \
    "  \"started_at\": \"${STARTED_AT}\"," \
    "  \"ended_at\": \"${ended_at}\"," \
    "  \"binary_sha256\": \"${BINARY_DIGEST}\"," \
    "  \"image_digest\": \"${IMAGE_DIGEST}\"," \
    "  \"host_architecture\": \"$(uname -m)\"," \
    "  \"go_version\": \"$(go version | awk '{print $3}')\"," \
    "  \"go_architecture\": \"$(go env GOARCH)\"," \
    "  \"docker_architecture\": \"$(docker version --format '{{.Server.Arch}}' 2>/dev/null || echo unavailable)\"," \
    "  \"exit_code\": ${exit_code}," \
    "  \"result\": \"${result}\"," \
    '  "profiles": [' \
    '    "SW-V0-TOPOLOGY-001",' \
    '    "SW-V0-FAULT-HIT-001",' \
    '    "SW-V0-EVIDENCE-001",' \
    '    "SW-V0-CLOCK-001"' \
    '  ],' \
    '  "profile_sha256": {' \
    "    \"SW-V0-TOPOLOGY-001\": \"${PROFILE_TOPOLOGY_DIGEST}\"," \
    "    \"SW-V0-FAULT-HIT-001\": \"${PROFILE_FAULT_DIGEST}\"," \
    "    \"SW-V0-EVIDENCE-001\": \"${PROFILE_EVIDENCE_DIGEST}\"," \
    "    \"SW-V0-CLOCK-001\": \"${PROFILE_CLOCK_DIGEST}\"" \
    '  },' \
    '  "canonical_repeats": 3,' \
    "  \"residuals\": {\"containers\": ${container_count}, \"networks\": ${network_count}, \"images\": ${image_count}}" \
    '}' >"${ARTIFACT_ROOT}/manifest.json"
}

on_exit() {
  local exit_code=$?
  set +e
  cleanup_resources
  local container_count
  local network_count
  local image_count
  container_count="$(count_labeled_resources container)"
  network_count="$(count_labeled_resources network)"
  image_count="$(count_labeled_resources image)"
  write_overall_manifest "${exit_code}" "${container_count}" "${network_count}" "${image_count}"
  echo "SW-V0 artifacts: ${ARTIFACT_ROOT}"
  if [[ "${exit_code}" -eq 0 && "${CLEANUP_INVALID}" -eq 0 && "${container_count}" -eq 0 && "${network_count}" -eq 0 && "${image_count}" -eq 0 ]]; then
    echo "SW-V0 PASS"
    exit 0
  fi
  echo "SW-V0 INVALID (exit=${exit_code}, cleanup=${CLEANUP_INVALID}, containers=${container_count}, networks=${network_count}, images=${image_count})" >&2
  if [[ "${exit_code}" -eq 0 ]]; then
    exit 1
  fi
  exit "${exit_code}"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "${BUILD_CONTEXT}"
cp -R "${REPO_ROOT}/tools/t0/profiles" "${BUILD_CONTEXT}/profiles"

GO_ARCH="$(go env GOARCH)"
GOCACHE="${WORK_DIR}/go-cache" \
GOTOOLCHAIN=local \
CGO_ENABLED=0 \
GOOS=linux \
GOARCH="${GO_ARCH}" \
  go -C "${REPO_ROOT}/tools/t0" build -trimpath -o "${BINARY_PATH}" ./cmd/sw-v0-harness
BINARY_DIGEST="$(shasum -a 256 "${BINARY_PATH}" | awk '{print $1}')"

docker build \
  --network=none \
  --build-arg "RUN_ID=${RUN_ID}" \
  --label "${RUN_LABEL}" \
  --file "${REPO_ROOT}/tools/t0/Dockerfile.sw-v0" \
  --tag "${IMAGE_NAME}" \
  "${BUILD_CONTEXT}"
IMAGE_DIGEST="$(docker image inspect --format '{{.Id}}' "${IMAGE_NAME}")"
HOST_ARCH="$(uname -m)"
DAEMON_ARCH="$(docker version --format '{{.Server.Arch}}')"

container_base_args=(
  --read-only
  --tmpfs /tmp:rw,noexec,nosuid,size=16m
  --user "${HOST_UID}:${HOST_GID}"
  --cpus 0.5
  --memory 256m
  --pids-limit 64
  --cap-drop ALL
  --security-opt no-new-privileges
  --label "${RUN_LABEL}"
  --env "SW_V0_RUN_ID=${RUN_ID}"
  --env "SW_V0_GIT_REVISION=${GIT_REVISION}"
  --env "SW_V0_GIT_DIRTY=${GIT_DIRTY}"
  --env "SW_V0_HOST_ARCH=${HOST_ARCH}"
  --env "SW_V0_DAEMON_ARCH=${DAEMON_ARCH}"
  --env "SW_V0_BINARY_SHA256=${BINARY_DIGEST}"
  --env "SW_V0_IMAGE_DIGEST=${IMAGE_DIGEST}"
)

run_finalizer() {
  local profile_file="$1"
  local profile_dir="$2"
  local repeat="$3"
  local probe_file="${4:-}"
  local name="sw-v0-${RUN_ID}-finalize-${repeat}-$(basename "${profile_file}" .json)"
  CONTAINERS+=("${name}")
  local args=(
    docker run --rm --name "${name}"
    "${container_base_args[@]}"
    --network none
    --volume "${profile_dir}:/evidence-root"
  )
  if [[ -n "${probe_file}" ]]; then
    args+=(--volume "${WORK_DIR}:/work:ro")
  fi
  args+=(
    "${IMAGE_NAME}"
    finalize
    --profile-root /profiles
    --profile "${profile_file}"
    --evidence-dir "/evidence-root/${repeat}"
    --repeat "${repeat}"
  )
  if [[ -n "${probe_file}" ]]; then
    args+=(--probe-file "${probe_file}")
  fi
  "${args[@]}"
}

wait_for_reachable() {
  local container="$1"
  local from="$2"
  local to="$3"
  local address="$4"
  local output="$5"
  local attempt
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if docker exec "${container}" /sw-v0-harness probe --from "${from}" --to "${to}" --address "${address}" --expect reachable --timeout 500ms --output "${output}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  echo "endpoint readiness probe failed: ${from}->${to}" >&2
  return 1
}

run_topology_repeat() {
  local profile_file="$1"
  local profile_dir="$2"
  local repeat="$3"
  local suffix="${RUN_ID}-${repeat}"
  local network_ab="sw-v0-ab-${suffix}"
  local network_bc="sw-v0-bc-${suffix}"
  local node_a="sw-v0-a-${suffix}"
  local node_b="sw-v0-b-${suffix}"
  local node_c="sw-v0-c-${suffix}"
  local probe_path="${WORK_DIR}/topology-${repeat}.ndjson"
  local readiness_path="${WORK_DIR}/readiness-${repeat}.ndjson"

  NETWORKS+=("${network_ab}" "${network_bc}")
  CONTAINERS+=("${node_a}" "${node_b}" "${node_c}")
  docker network create --internal --label "${RUN_LABEL}" "${network_ab}" >/dev/null
  docker network create --internal --label "${RUN_LABEL}" "${network_bc}" >/dev/null

  docker run -d --name "${node_a}" "${container_base_args[@]}" --network "${network_ab}" --network-alias a --volume "${WORK_DIR}:/work" "${IMAGE_NAME}" endpoint --listen :7000 >/dev/null
  docker run -d --name "${node_b}" "${container_base_args[@]}" --network "${network_ab}" --network-alias b --volume "${WORK_DIR}:/work" "${IMAGE_NAME}" endpoint --listen :7000 >/dev/null
  docker network connect --alias b "${network_bc}" "${node_b}"
  docker run -d --name "${node_c}" "${container_base_args[@]}" --network "${network_bc}" --network-alias c --volume "${WORK_DIR}:/work" "${IMAGE_NAME}" endpoint --listen :7000 >/dev/null

  wait_for_reachable "${node_b}" B A a:7000 "/work/$(basename "${readiness_path}")"
  wait_for_reachable "${node_b}" B C c:7000 "/work/$(basename "${readiness_path}")"
  docker exec "${node_a}" /sw-v0-harness probe --from A --to C --address c:7000 --expect unreachable --timeout 500ms --output "/work/$(basename "${probe_path}")"
  docker exec "${node_c}" /sw-v0-harness probe --from C --to A --address a:7000 --expect unreachable --timeout 500ms --output "/work/$(basename "${probe_path}")"
  docker exec "${node_b}" /sw-v0-harness probe --from B --to A --address a:7000 --expect reachable --timeout 500ms --output "/work/$(basename "${probe_path}")"
  docker exec "${node_b}" /sw-v0-harness probe --from B --to C --address c:7000 --expect reachable --timeout 500ms --output "/work/$(basename "${probe_path}")"

  remove_container_exact "${node_c}"
  remove_container_exact "${node_b}"
  remove_container_exact "${node_a}"
  remove_network_exact "${network_bc}"
  remove_network_exact "${network_ab}"

  run_finalizer "${profile_file}" "${profile_dir}" "${repeat}" "/work/$(basename "${probe_path}")"
}

compare_repeats() {
  local profile_dir="$1"
  local name="sw-v0-${RUN_ID}-compare-$(basename "${profile_dir}")"
  CONTAINERS+=("${name}")
  docker run --rm --name "${name}" \
    "${container_base_args[@]}" \
    --network none \
    --volume "${profile_dir}:/compare:ro" \
    "${IMAGE_NAME}" finalize --compare-profile-dir /compare
}

profiles=(
  sw-v0-topology-001.json
  sw-v0-fault-hit-001.json
  sw-v0-evidence-001.json
  sw-v0-clock-001.json
)

for profile_file in "${profiles[@]}"; do
  case "${profile_file}" in
    sw-v0-topology-001.json) profile_id="SW-V0-TOPOLOGY-001" ;;
    sw-v0-fault-hit-001.json) profile_id="SW-V0-FAULT-HIT-001" ;;
    sw-v0-evidence-001.json) profile_id="SW-V0-EVIDENCE-001" ;;
    sw-v0-clock-001.json) profile_id="SW-V0-CLOCK-001" ;;
    *) echo "unknown canonical profile file: ${profile_file}" >&2; exit 2 ;;
  esac
  profile_dir="${ARTIFACT_ROOT}/${profile_id}"
  mkdir -p "${profile_dir}"
  for repeat in 1 2 3; do
    if [[ "${profile_file}" == "sw-v0-topology-001.json" ]]; then
      run_topology_repeat "${profile_file}" "${profile_dir}" "${repeat}"
    else
      run_finalizer "${profile_file}" "${profile_dir}" "${repeat}"
    fi
  done
  compare_repeats "${profile_dir}"
done
