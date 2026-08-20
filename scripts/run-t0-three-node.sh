#!/usr/bin/env bash
set -euo pipefail

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd)"

for command_name in go docker mktemp; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is unavailable; no resources were created." >&2
  exit 1
fi

run_id="$(date +%Y%m%d%H%M%S)-$$"
run_root="$(mktemp -d "${TMPDIR:-/tmp}/radishlink-t0-${run_id}.XXXXXX")"
build_context="${run_root}/build"
state_root="${run_root}/state"
image="radishlink/t0-node:${run_id}"
network_ab="radishlink-t0-ab-${run_id}"
network_bc="radishlink-t0-bc-${run_id}"
container_a="radishlink-t0-a-${run_id}"
container_b="radishlink-t0-b-${run_id}"
container_c="radishlink-t0-c-${run_id}"

mkdir -p "${build_context}" "${state_root}/a" "${state_root}/b" "${state_root}/c"

cleanup() {
  exit_code=$?
  trap - EXIT INT TERM
  if [ "${exit_code}" -ne 0 ]; then
    echo "T0 failed; node logs follow." >&2
    docker logs "${container_a}" 2>&1 || true
    docker logs "${container_b}" 2>&1 || true
    docker logs "${container_c}" 2>&1 || true
  fi
  docker rm -f "${container_a}" "${container_b}" "${container_c}" >/dev/null 2>&1 || true
  docker network rm "${network_ab}" "${network_bc}" >/dev/null 2>&1 || true
  docker image rm "${image}" >/dev/null 2>&1 || true
  rm -rf "${run_root}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

go_arch="$(go env GOARCH)"
(
  cd "${repo_root}/tools/t0"
  CGO_ENABLED=0 GOOS=linux GOARCH="${go_arch}" GOCACHE="${run_root}/go-cache" GOTOOLCHAIN=local \
    go build -trimpath -o "${build_context}/t0node" ./cmd/t0node
)

docker build \
  --network=none \
  --label "org.radishlink.t0.run=${run_id}" \
  --tag "${image}" \
  --file "${repo_root}/tools/t0/Dockerfile" \
  "${build_context}" >/dev/null

docker network create --internal --label "org.radishlink.t0.run=${run_id}" "${network_ab}" >/dev/null
docker network create --internal --label "org.radishlink.t0.run=${run_id}" "${network_bc}" >/dev/null

host_user="$(id -u):$(id -g)"

docker run -d \
  --name "${container_a}" \
  --label "org.radishlink.t0.run=${run_id}" \
  --network "${network_ab}" \
  --network-alias a \
  --read-only \
  --user "${host_user}" \
  --mount "type=bind,source=${state_root}/a,target=/data" \
  "${image}" serve --id A --listen :7000 --routes C=b:7000 --data-dir /data >/dev/null

docker run -d \
  --name "${container_b}" \
  --label "org.radishlink.t0.run=${run_id}" \
  --network "${network_ab}" \
  --network-alias b \
  --read-only \
  --user "${host_user}" \
  --mount "type=bind,source=${state_root}/b,target=/data" \
  "${image}" serve --id B --listen :7000 --routes A=a:7000,C=c:7000 --data-dir /data >/dev/null
docker network connect --alias b "${network_bc}" "${container_b}"

docker run -d \
  --name "${container_c}" \
  --label "org.radishlink.t0.run=${run_id}" \
  --network "${network_bc}" \
  --network-alias c \
  --read-only \
  --user "${host_user}" \
  --mount "type=bind,source=${state_root}/c,target=/data" \
  "${image}" serve --id C --listen :7000 --routes A=b:7000 --data-dir /data >/dev/null

node_exec() {
  target_container=$1
  shift
  docker exec "${target_container}" /t0node "$@"
}

for target_container in "${container_a}" "${container_b}" "${container_c}"; do
  node_exec "${target_container}" wait --condition ready --timeout 5s
done

echo "[1/5] topology: A and C have no shared network; B reaches both"
node_exec "${container_a}" probe --address c:7000 --expect unreachable
node_exec "${container_c}" probe --address a:7000 --expect unreachable
node_exec "${container_b}" probe --address a:7000 --expect reachable
node_exec "${container_b}" probe --address c:7000 --expect reachable

echo "[2/5] baseline: A sends through B and receives destination acknowledgement"
node_exec "${container_a}" submit --origin A --destination C --id baseline --hop-limit 2 --lifetime 10s
node_exec "${container_a}" wait --condition acked --id baseline --timeout 5s
node_exec "${container_c}" check --delivered-id baseline --delivery-count 1

echo "[3/5] duplicate: replay is acknowledged without a second delivery"
node_exec "${container_a}" submit --origin A --destination C --id baseline --hop-limit 2 --lifetime 10s --force
node_exec "${container_a}" wait --condition acked --id baseline --timeout 5s
node_exec "${container_c}" check --delivered-id baseline --delivery-count 1 --duplicate-min 1

echo "[4/5] hop limit and lifetime: one forwarding hop cannot reach C"
node_exec "${container_a}" submit --origin A --destination C --id one-hop-only --hop-limit 1 --lifetime 1500ms
node_exec "${container_c}" ensure-absent --delivered-id one-hop-only --duration 900ms
node_exec "${container_b}" check --drop-reason hop_limit_exhausted --drop-min 1
node_exec "${container_a}" wait --condition not-pending --id one-hop-only --timeout 3s

echo "[5/5] store-forward: C disconnects, B persists custody across restart, then delivery resumes"
docker network disconnect "${network_bc}" "${container_c}"
node_exec "${container_a}" submit --origin A --destination C --id stored-after-restart --hop-limit 2 --lifetime 15s
node_exec "${container_b}" wait --condition pending --id stored-after-restart --timeout 5s
docker network disconnect "${network_ab}" "${container_a}"
docker restart --time 1 "${container_b}" >/dev/null
node_exec "${container_b}" wait --condition ready --timeout 5s
node_exec "${container_b}" wait --condition pending --id stored-after-restart --timeout 2s
docker network connect --alias a "${network_ab}" "${container_a}"
docker network connect --alias c "${network_bc}" "${container_c}"
node_exec "${container_a}" wait --condition acked --id stored-after-restart --timeout 5s
node_exec "${container_c}" check --delivered-id stored-after-restart --delivery-count 1
node_exec "${container_b}" wait --condition not-pending --id stored-after-restart --timeout 5s

echo "T0 PASS: isolated A-B-C relay, de-duplication, hop/lifetime limits, destination ACK semantics, store-forward, and B restart recovery."
echo "Evidence scope: Docker/Ethernet simulation with unencrypted synthetic payloads; not HaLow, E2EE, range, media, power, or regulatory validation."
