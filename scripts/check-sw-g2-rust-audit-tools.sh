#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
monitor_path="${repo_root}/scripts/monitor-sw-g2-dependency-audit-run.py"
builder_path="${repo_root}/scripts/run-sw-g2-rust-audit-tools.sh"
manifest_filter_path="${repo_root}/scripts/sw-g2-rust-audit-tools-manifest.jq"
artifact_root="${repo_root}/artifacts/sw-g2-rust-audit-tools"
self_test_parent="${TMPDIR:-/tmp}"

for command_name in awk bash chmod dirname jq mkdir mktemp pwd python3 rg rm shasum; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done
for required_input in "${monitor_path}" "${builder_path}" "${manifest_filter_path}"; do
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
self_test_dir="$(mktemp -d "${self_test_parent}/radishlink-rust-audit-tools-check.XXXXXX")"

cleanup() {
  case "${self_test_dir}" in
    "${self_test_parent}"/radishlink-rust-audit-tools-check.*)
      rm -rf -- "${self_test_dir}"
      ;;
    *)
      echo "refusing to remove unexpected self-test directory: ${self_test_dir}" >&2
      return 1
      ;;
  esac
}
trap cleanup EXIT INT TERM

bash -n "${builder_path}"
python3 "${monitor_path}" self-test

for required_value in \
  'bundle_contract="sw-g2-rust-audit-tools-v1"' \
  'image_ref="rust:1.96.1-bookworm@${image_digest}"' \
  'image_digest="sha256:a339861ae23e9abb272cea45dfafde21760d2ce6577a70f8a926153677902663"' \
  'expected_platform="linux/arm64"' \
  'cargo_audit_version="0.22.2"' \
  'cargo_deny_version="0.20.2"' \
  'runtime_timeout_seconds=5400' \
  'runtime_disk_budget_kib=5242880' \
  'runtime_poll_interval_seconds=5' \
  'label_key="org.radishlink.sw-g2.rust-audit-tools.run"' \
  'artifact_root="${artifact_parent}/sw-g2-rust-audit-tools"' \
  'cargo install cargo-audit --version "$CARGO_AUDIT_VERSION" --locked --root /evidence/bundle' \
  'cargo install cargo-deny --version "$CARGO_DENY_VERSION" --locked --root /evidence/bundle' \
  '--mount "type=bind,source=${bundle_bin},target=/audit-tools/bin,readonly"' \
  'chmod 0555 "${bundle_bin}/cargo-audit" "${bundle_bin}/cargo-deny"' \
  'evidence finalization remains pending' \
  'verify_pass_bundle_contract' \
  'if [ ! -s "${manifest_tmp}" ]' \
  'if [ ! -s "${run_dir}/manifest.json" ]'; do
  if ! rg -Fq -- "${required_value}" "${builder_path}"; then
    echo "builder is missing a fixed contract or finalizer guard: ${required_value}" >&2
    exit 1
  fi
done

for security_control in \
  '--read-only' \
  '--pids-limit 512' \
  '--cap-drop ALL' \
  '--security-opt no-new-privileges' \
  '--user "${host_user}"' \
  '--cpus 4' \
  '--memory 4g' \
  '--network none'; do
  if ! rg -Fq -- "${security_control}" "${builder_path}"; then
    echo "builder is missing a fixed container control: ${security_control}" >&2
    exit 1
  fi
done

build_block="$(awk '
  /echo "\[4\/6\] build exact cargo-audit/ { capture = 1 }
  /echo "\[5\/6\] validate bundle payload/ { capture = 0 }
  capture { print }
' "${builder_path}")"
if printf '%s\n' "${build_block}" | rg -Fq -- '--network'; then
  echo "builder must use Docker's default network without a domain allowlist" >&2
  exit 1
fi
if rg -Fq '/var/run/docker.sock' "${builder_path}" ||
  rg -Fq '/.ssh' "${builder_path}" ||
  rg -Fq 'source=${HOME}' "${builder_path}"; then
  echo "builder contains a prohibited host credential or Docker socket mount" >&2
  exit 1
fi
candidate_binding='open''mls'
if rg -Fiq 'latest' "${builder_path}" || rg -Fiq "${candidate_binding}" \
  "${builder_path}" "${monitor_path}" "${manifest_filter_path}" "$0"; then
  echo "candidate-neutral audit tool infrastructure contains a latest or candidate-specific binding" >&2
  exit 1
fi

pass_message_count="$(rg -Fc 'SW-G2 Rust audit tools bundle: PASS ' "${builder_path}")"
if [ "${pass_message_count}" -ne 1 ]; then
  echo "builder must contain exactly one post-finalization bundle PASS message" >&2
  exit 1
fi
network_none_count="$(rg -Fc -- '--network none' "${builder_path}")"
if [ "${network_none_count}" -ne 2 ]; then
  echo "toolchain and payload validation must each use --network none" >&2
  exit 1
fi

mkdir -p "${self_test_dir}/bin"
for prohibited_command in docker cargo curl wget; do
  printf '%s\n' '#!/usr/bin/env bash' 'touch "${SW_G2_PROHIBITED_MARKER}"' 'exit 97' \
    > "${self_test_dir}/bin/${prohibited_command}"
  chmod 0755 "${self_test_dir}/bin/${prohibited_command}"
done
prohibited_marker="${self_test_dir}/prohibited-command-used"
artifact_preexisting=false
if [ -e "${artifact_root}" ] || [ -L "${artifact_root}" ]; then
  artifact_preexisting=true
fi

assert_rejected_before_side_effects() {
  local rejection_name=$1
  shift
  local status
  set +e
  PATH="${self_test_dir}/bin:${PATH}" \
    SW_G2_PROHIBITED_MARKER="${prohibited_marker}" \
    "${builder_path}" "$@" >/dev/null 2>&1
  status=$?
  set -e
  if [ "${status}" -ne 2 ]; then
    echo "${rejection_name} returned ${status}, expected 2" >&2
    exit 1
  fi
  if [ -e "${prohibited_marker}" ] || [ -L "${prohibited_marker}" ]; then
    echo "${rejection_name} reached Docker, Cargo, or a network client" >&2
    exit 1
  fi
  if [ "${artifact_preexisting}" = false ] && { [ -e "${artifact_root}" ] || [ -L "${artifact_root}" ]; }; then
    echo "${rejection_name} created the artifact root" >&2
    exit 1
  fi
}

assert_rejected_before_side_effects "no arguments"
assert_rejected_before_side_effects "unknown action" unknown
assert_rejected_before_side_effects "run action" run

PATH="${self_test_dir}/bin:${PATH}" \
  SW_G2_PROHIBITED_MARKER="${prohibited_marker}" \
  TMPDIR="${self_test_dir}" \
  "${builder_path}" self-test
if [ -e "${prohibited_marker}" ] || [ -L "${prohibited_marker}" ]; then
  echo "offline builder self-test reached Docker, Cargo, or a network client" >&2
  exit 1
fi

echo "SW-G2 Rust audit tools offline check: PASS"
