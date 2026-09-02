#!/usr/bin/env bash
set -euo pipefail

umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
repo_root="$(CDPATH= cd -- "${script_dir}/.." && pwd -P)"
runner_path="${repo_root}/scripts/run-sw-g2-mls-rs-spike.sh"
manifest_filter_path="${repo_root}/scripts/sw-g2-mls-rs-phase-a-manifest.jq"
monitor_path="${repo_root}/scripts/monitor-sw-g2-dependency-audit-run.py"
spike_root="${repo_root}/tools/spikes/sw-g2-mls-rs"
cargo_toml_path="${spike_root}/Cargo.toml"
deny_toml_path="${spike_root}/deny.toml"
main_rs_path="${spike_root}/src/main.rs"
repo_lock="${spike_root}/Cargo.lock"
artifact_root="${repo_root}/artifacts/sw-g2-mls-rs"
self_test_parent="${TMPDIR:-/tmp}"

for command_name in awk bash chmod dirname find jq mkdir mktemp pwd python3 rg rm shasum sort; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "required command is unavailable: ${command_name}" >&2
    exit 1
  fi
done
for required_input in \
  "${runner_path}" \
  "${manifest_filter_path}" \
  "${monitor_path}" \
  "${cargo_toml_path}" \
  "${deny_toml_path}" \
  "${main_rs_path}"; do
  if [ ! -f "${required_input}" ] || [ -L "${required_input}" ]; then
    echo "required regular input is missing or is a symbolic link: ${required_input}" >&2
    exit 1
  fi
done
if [ -e "${repo_lock}" ] || [ -L "${repo_lock}" ]; then
  echo "A1 must not add Cargo.lock" >&2
  exit 1
fi
if [ ! -d "${self_test_parent}" ] || [ -L "${self_test_parent}" ]; then
  echo "self-test parent is missing or is a symbolic link: ${self_test_parent}" >&2
  exit 1
fi
self_test_parent="$(CDPATH= cd -- "${self_test_parent}" && pwd -P)"
self_test_dir="$(mktemp -d "${self_test_parent}/radishlink-mls-rs-phase-a-check.XXXXXX")"

cleanup() {
  case "${self_test_dir}" in
    "${self_test_parent}"/radishlink-mls-rs-phase-a-check.*)
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

expected_spike_files="$(printf '%s\n' \
  "${cargo_toml_path}" \
  "${deny_toml_path}" \
  "${main_rs_path}" | LC_ALL=C sort)"
actual_spike_files="$(find "${spike_root}" -type f -print | LC_ALL=C sort)"
if [ "${actual_spike_files}" != "${expected_spike_files}" ]; then
  echo "A1 spike root contains an unexpected file" >&2
  exit 1
fi

python3 - "${cargo_toml_path}" "${deny_toml_path}" <<'PY'
from pathlib import Path
import sys
import tomllib

cargo = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
deny = tomllib.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

package = cargo["package"]
assert package["name"] == "radishlink-sw-g2-mls-rs-spike"
assert package["version"] == "0.0.0"
assert package["edition"] == "2021"
assert package["publish"] is False
assert package["license-file"] == "../../../LICENSE"
assert package["metadata"]["radishlink"] == {
    "candidate": "mls-rs-0.56.0",
    "phase": "phase-a-only",
    "phase-b-implemented": False,
}

dependencies = cargo["dependencies"]
assert set(dependencies) == {
    "mls-rs",
    "mls-rs-codec",
    "mls-rs-crypto-awslc",
    "mls-rs-provider-sqlite",
    "serde",
    "serde_json",
}
assert dependencies["mls-rs"] == {
    "version": "=0.56.0",
    "default-features": False,
    "features": ["std", "private_message", "out_of_order", "prior_epoch", "tree_index"],
}
assert dependencies["mls-rs-crypto-awslc"] == {
    "version": "=0.25.0",
    "default-features": False,
    "features": ["non-fips"],
}
assert dependencies["mls-rs-provider-sqlite"] == {
    "version": "=0.23.0",
    "default-features": False,
    "features": ["sqlite-bundled"],
}
assert dependencies["mls-rs-codec"] == "=0.7.0"
assert dependencies["serde"] == "=1.0.229"
assert dependencies["serde_json"] == "=1.0.151"
assert cargo["dev-dependencies"] == {"tempfile": "=3.27.0"}

assert deny["graph"] == {"targets": ["aarch64-unknown-linux-gnu"]}
assert deny["advisories"] == {"ignore": [], "yanked": "deny"}
assert set(deny["licenses"]["allow"]) == {
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "MIT",
    "Unicode-3.0",
    "Zlib",
}
assert deny["licenses"]["confidence-threshold"] == 0.93
assert deny["licenses"]["private"] == {"ignore": True}
assert deny["bans"] == {"multiple-versions": "warn", "wildcards": "deny"}
assert deny["sources"] == {"unknown-registry": "deny", "unknown-git": "deny"}
PY

for main_guard in \
  '#![forbid(unsafe_code)]' \
  'Phase B is not implemented' \
  'std::process::exit(2)'; do
  if ! rg -Fq -- "${main_guard}" "${main_rs_path}"; then
    echo "Phase B rejection entry is missing: ${main_guard}" >&2
    exit 1
  fi
done
if rg -q 'mls_rs::|awslc|sqlite|IdentityProvider|CipherSuite|Group' "${main_rs_path}"; then
  echo "A1 main.rs initializes candidate functionality" >&2
  exit 1
fi

feature_filter_path="${self_test_dir}/feature-gate.jq"
awk '
  /^evaluate_feature_gate\(\) \{/ { in_function = 1 }
  in_function && /^  jq -e / { capture = 1; next }
  capture && /cargo-metadata\.json" >\/dev\/null$/ { exit }
  capture { print }
' "${runner_path}" > "${feature_filter_path}"
if [ ! -s "${feature_filter_path}" ]; then
  echo "could not extract the runner feature gate" >&2
  exit 1
fi

feature_fixture_path="${self_test_dir}/feature-fixture.json"
jq -n '
  def registry: "registry+https://github.com/rust-lang/crates.io-index";
  {
    packages: [
      {
        id: "path#radishlink-sw-g2-mls-rs-spike@0.0.0",
        name: "radishlink-sw-g2-mls-rs-spike",
        version: "0.0.0",
        source: null,
        features: {},
        dependencies: []
      },
      {
        id: "registry#mls-rs@0.56.0",
        name: "mls-rs",
        version: "0.56.0",
        source: registry,
        features: {},
        dependencies: []
      },
      {
        id: "registry#mls-rs-core@0.27.0",
        name: "mls-rs-core",
        version: "0.27.0",
        source: registry,
        features: {
          default: ["std", "rfc_compliant", "fast_serialize"],
          fast_serialize: ["mls-rs-codec/preallocate"],
          rfc_compliant: ["x509"]
        },
        dependencies: []
      },
      {
        id: "registry#mls-rs-codec@0.7.0",
        name: "mls-rs-codec",
        version: "0.7.0",
        source: registry,
        features: {default: ["std", "preallocate"]},
        dependencies: []
      },
      {
        id: "registry#mls-rs-identity-x509@0.21.0",
        name: "mls-rs-identity-x509",
        version: "0.21.0",
        source: registry,
        features: {default: ["std"]},
        dependencies: [{
          name: "mls-rs-core",
          source: registry,
          req: "^0.27.0",
          kind: null,
          rename: null,
          optional: false,
          uses_default_features: false,
          features: ["x509"],
          target: null,
          registry: null
        }]
      },
      {
        id: "registry#mls-rs-crypto-awslc@0.25.0",
        name: "mls-rs-crypto-awslc",
        version: "0.25.0",
        source: registry,
        features: {default: ["non-fips"]},
        dependencies: [
          {
            name: "mls-rs-core",
            source: registry,
            req: "^0.27.0",
            kind: null,
            rename: null,
            optional: false,
            uses_default_features: true,
            features: [],
            target: null,
            registry: null
          },
          {
            name: "mls-rs-identity-x509",
            source: registry,
            req: "^0.21.0",
            kind: null,
            rename: null,
            optional: false,
            uses_default_features: true,
            features: [],
            target: null,
            registry: null
          }
        ]
      },
      {
        id: "registry#mls-rs-provider-sqlite@0.23.0",
        name: "mls-rs-provider-sqlite",
        version: "0.23.0",
        source: registry,
        features: {default: ["sqlcipher-bundled"]},
        dependencies: [{
          name: "mls-rs-core",
          source: registry,
          req: "^0.27.0",
          kind: null,
          rename: null,
          optional: false,
          uses_default_features: true,
          features: [],
          target: null,
          registry: null
        }]
      }
    ],
    resolve: {
      nodes: [
        {id: "path#radishlink-sw-g2-mls-rs-spike@0.0.0", features: []},
        {id: "registry#mls-rs@0.56.0", features: ["std", "private_message", "out_of_order", "prior_epoch", "tree_index"]},
        {id: "registry#mls-rs-core@0.27.0", features: ["default", "std", "rfc_compliant", "fast_serialize", "x509"]},
        {id: "registry#mls-rs-codec@0.7.0", features: ["default", "std", "preallocate"]},
        {id: "registry#mls-rs-identity-x509@0.21.0", features: ["default", "std"]},
        {id: "registry#mls-rs-crypto-awslc@0.25.0", features: ["non-fips"]},
        {id: "registry#mls-rs-provider-sqlite@0.23.0", features: ["sqlite", "sqlite-bundled"]}
      ]
    }
  }
' > "${feature_fixture_path}"
if ! jq -e -f "${feature_filter_path}" "${feature_fixture_path}" >/dev/null; then
  echo "feature gate rejected the fixed positive fixture" >&2
  exit 1
fi
if jq '.resolve.nodes |= map(if .id | contains("#mls-rs@0.56.0") then .features += ["rfc_compliant"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted the prohibited top-level rfc_compliant feature" >&2
  exit 1
fi
if jq '.resolve.nodes |= map(if .id | contains("#mls-rs@0.56.0") then .features += ["fast_serialize"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted the prohibited top-level fast_serialize feature" >&2
  exit 1
fi
if jq '.resolve.nodes |= map(if .id | contains("#mls-rs-core@0.27.0") then .features += ["serde"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted an unexpected mls-rs-core feature" >&2
  exit 1
fi
if jq '.packages |= map(if .id | contains("#mls-rs-core@0.27.0") then .features.fast_serialize = ["unexpected"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted a changed fast_serialize alias" >&2
  exit 1
fi
if jq '.packages |= map(if .id | contains("#mls-rs-core@0.27.0") then .features.rfc_compliant = ["unexpected"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted a changed rfc_compliant alias" >&2
  exit 1
fi
if jq '.packages |= map(if .id | contains("#mls-rs-crypto-awslc@0.25.0") then .dependencies |= map(if .name == "mls-rs-core" and .kind == null then .uses_default_features = false else . end) else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted a changed AWS-LC core dependency edge" >&2
  exit 1
fi
if jq '.resolve.nodes |= map(if .id | contains("#mls-rs-crypto-awslc@0.25.0") then .features += ["default"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted the AWS-LC provider default feature" >&2
  exit 1
fi
if jq '.resolve.nodes |= map(if .id | contains("#mls-rs-crypto-awslc@0.25.0") then .features += ["fips"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted the prohibited fips feature" >&2
  exit 1
fi
if jq '.resolve.nodes |= map(if .id | contains("#mls-rs-crypto-awslc@0.25.0") then .features += ["post-quantum"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted the prohibited post-quantum feature" >&2
  exit 1
fi
if jq '.resolve.nodes |= map(if .id | contains("#mls-rs-provider-sqlite@0.23.0") then .features += ["default", "sqlcipher-bundled"] else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted the SQLite provider default feature" >&2
  exit 1
fi
if jq '.packages += [{id: "other", name: "mls-rs-crypto-rustcrypto", version: "0.20.0", source: "registry+https://github.com/rust-lang/crates.io-index"}]' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted a second crypto provider" >&2
  exit 1
fi
if jq '.packages += [{id: "ffi", name: "mls-rs-ffi", version: "0.1.0", source: "registry+https://github.com/rust-lang/crates.io-index"}]' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted an FFI package" >&2
  exit 1
fi
if jq '.packages += [{id: "path#unexpected@0.1.0", name: "unexpected-path-dependency", version: "0.1.0", source: null}]' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted an unexpected path source" >&2
  exit 1
fi
if jq '.packages |= map(if .id | contains("#mls-rs-codec@0.7.0") then .source = "git+https://example.invalid/repo" else . end)' \
  "${feature_fixture_path}" | jq -e -f "${feature_filter_path}" >/dev/null; then
  echo "feature gate accepted a git source" >&2
  exit 1
fi

for required_contract in \
  'manifest_contract="sw-g2-candidate-phase-a-v1"' \
  'audit_tool_bundle_contract="sw-g2-rust-audit-tools-v1"' \
  'artifact_root="${artifact_parent}/sw-g2-mls-rs"' \
  'audit_tools_artifact_root="${artifact_parent}/sw-g2-rust-audit-tools"' \
  'image_ref="rust:1.96.1-bookworm@${image_digest}"' \
  'expected_platform="linux/arm64"' \
  'runtime_timeout_seconds=2700' \
  'runtime_disk_budget_kib=5242880' \
  'runtime_poll_interval_seconds=5' \
  'label_key="org.radishlink.sw-g2.mls-rs.run"' \
  '--mount "type=bind,source=${audit_tool_bundle_bin},target=/audit-tools/bin,readonly"' \
  '/audit-tools/bin/cargo-audit audit --json > /evidence/cargo-audit.json' \
  '/audit-tools/bin/cargo-deny check sources > /evidence/cargo-deny-sources.txt' \
  '/audit-tools/bin/cargo-deny check advisories licenses > /evidence/cargo-deny.txt' \
  'cargo generate-lockfile' \
  'cargo fetch --locked --target aarch64-unknown-linux-gnu' \
  'cargo metadata --locked --format-version 1' \
  'evaluate_feature_gate' \
  'promote_lockfile' \
  'preserve_invalid_finalization' \
  'verify_pass_phase_a_contract' \
  'evidence finalization remains pending'; do
  if ! rg -Fq -- "${required_contract}" "${runner_path}"; then
    echo "runner is missing a fixed contract or stop guard: ${required_contract}" >&2
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
  if ! rg -Fq -- "${security_control}" "${runner_path}"; then
    echo "runner is missing a fixed container control: ${security_control}" >&2
    exit 1
  fi
done

candidate_block="$(awk '
  /echo "\[5\/8\] resolve and download/ { capture = 1 }
  /echo "\[6\/8\] evaluate fixed source/ { capture = 0 }
  capture { print }
' "${runner_path}")"
if printf '%s\n' "${candidate_block}" | rg -Fq -- '--network'; then
  echo "candidate resolution must use Docker's default network without a domain allowlist" >&2
  exit 1
fi
if printf '%s\n' "${candidate_block}" | rg -q 'cargo (build|test|run)( |$)'; then
  echo "Phase A candidate block must not compile or run the candidate" >&2
  exit 1
fi
if [ "$(rg -Fc -- '--network none' "${runner_path}")" -ne 1 ]; then
  echo "only toolchain validation may use --network none" >&2
  exit 1
fi
if rg -Fq '/var/run/docker.sock' "${runner_path}" ||
  rg -Fq '/.ssh' "${runner_path}" ||
  rg -Fq 'source=${HOME}' "${runner_path}"; then
  echo "runner contains a prohibited host credential or Docker socket mount" >&2
  exit 1
fi

pass_message_count="$(rg -Fc 'SW-EXP-003 PHASE A PASS:' "${runner_path}")"
if [ "${pass_message_count}" -ne 1 ]; then
  echo "runner must contain exactly one post-finalization Phase A PASS message" >&2
  exit 1
fi
candidate_binding='open''mls'
if rg -Fiq "${candidate_binding}" \
  "${runner_path}" "${manifest_filter_path}" "${cargo_toml_path}" "${deny_toml_path}" "${main_rs_path}" "$0"; then
  echo "mls-rs A1 contains a binding to another candidate" >&2
  exit 1
fi

manifest_path="${self_test_dir}/manifest.json"
filter_sha="$(shasum -a 256 "${manifest_filter_path}" | awk '{print $1}')"
jq -n \
  --arg schema_version "1" \
  --arg manifest_contract "sw-g2-candidate-phase-a-v1" \
  --arg evidence_id "SW-EXP-003" \
  --arg phase "phase-a" \
  --arg scenario_id "phase-a-dependency-audit" \
  --arg run_id "self-test" \
  --arg outcome "STOP" \
  --arg stage "dependency-audit" \
  --arg start_time "2026-09-01T00:00:00Z" \
  --arg end_time "2026-09-01T00:00:01Z" \
  --arg git_revision "0123456789abcdef0123456789abcdef01234567" \
  --arg git_status_before "" \
  --arg git_status_after "?? tools/spikes/sw-g2-mls-rs/Cargo.lock" \
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
  --arg audit_tool_bundle_contract "sw-g2-rust-audit-tools-v1" \
  --arg audit_tool_bundle_id "20260901-000000-12345.Abc123" \
  --arg audit_tool_bundle_manifest_sha256 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" \
  --arg cargo_audit_requested_version "0.22.2" \
  --arg cargo_audit_reported_version "cargo-audit 0.22.2" \
  --arg cargo_audit_binary_sha256 "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" \
  --arg cargo_deny_requested_version "0.20.2" \
  --arg cargo_deny_reported_version "cargo-deny 0.20.2" \
  --arg cargo_deny_binary_sha256 "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc" \
  --arg cargo_lock_sha256 "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd" \
  --arg advisory_db_revision "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee" \
  --arg resolved_package_count "321" \
  --arg source_exit_code "0" \
  --arg audit_exit_code "0" \
  --arg deny_exit_code "4" \
  --arg feature_exit_code "0" \
  --arg lockfile_preexisting "false" \
  --arg lockfile_written "true" \
  --arg disk_available_kib "6291456" \
  --arg runtime_control_status "stopped" \
  --arg runtime_termination_reason "workflow_stop" \
  --arg runtime_elapsed_milliseconds "15000" \
  --arg runtime_timeout_seconds "2700" \
  --arg runtime_disk_current_kib "200000" \
  --arg runtime_disk_peak_kib "210000" \
  --arg runtime_disk_budget_kib "5242880" \
  --arg runtime_poll_interval_seconds "5" \
  --arg received_signal "" \
  --arg license_sha256 "1111111111111111111111111111111111111111111111111111111111111111" \
  --arg cargo_toml_sha256 "2222222222222222222222222222222222222222222222222222222222222222" \
  --arg deny_toml_sha256 "3333333333333333333333333333333333333333333333333333333333333333" \
  --arg main_rs_sha256 "4444444444444444444444444444444444444444444444444444444444444444" \
  --arg runtime_control_helper_sha256 "5555555555555555555555555555555555555555555555555555555555555555" \
  --arg runner_sha256 "6666666666666666666666666666666666666666666666666666666666666666" \
  --arg phase_a_manifest_filter_sha256 "${filter_sha}" \
  --arg offline_checker_sha256 "7777777777777777777777777777777777777777777777777777777777777777" \
  --arg container_residual_count "0" \
  --arg exit_code "20" \
  -f "${manifest_filter_path}" > "${manifest_path}"

if [ ! -s "${manifest_path}" ] || ! jq -e --arg filter_sha "${filter_sha}" '
  .schema_version == 1
  and .manifest_contract == "sw-g2-candidate-phase-a-v1"
  and .candidate == {
    name: "mls-rs",
    version: "0.56.0",
    crypto_provider: "mls-rs-crypto-awslc-0.25.0/non-fips",
    storage_provider: "mls-rs-provider-sqlite-0.23.0/sqlite-bundled"
  }
  and .outcome == "STOP"
  and .audit_tool_bundle.contract == "sw-g2-rust-audit-tools-v1"
  and .audit_tool_bundle.mount_mode == "read-only"
  and .audit_tool_bundle.cargo_audit.invocation == ["audit", "--json"]
  and .direct_dependencies.mls_rs.features == ["std", "private_message", "out_of_order", "prior_epoch", "tree_index"]
  and .direct_dependencies.mls_rs_crypto_awslc.features == ["non-fips"]
  and .direct_dependencies.mls_rs_provider_sqlite.features == ["sqlite-bundled"]
  and .input_sha256.phase_a_manifest_filter == $filter_sha
  and .runtime_controls.received_signal == null
  and .runtime_controls.candidate_network == "docker-default-network-no-domain-allowlist"
  and .runtime_controls.toolchain_validation_network == "none"
  and .exit_code == 20
' "${manifest_path}" >/dev/null; then
  echo "mls-rs Phase A manifest self-test did not preserve the fixed contract" >&2
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
fixture_bundle_id="20260901-000000-12345.Abc123"

assert_rejected_before_side_effects() {
  local rejection_name=$1
  shift
  local status
  set +e
  PATH="${self_test_dir}/bin:${PATH}" \
    SW_G2_PROHIBITED_MARKER="${prohibited_marker}" \
    "${runner_path}" "$@" >/dev/null 2>&1
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
assert_rejected_before_side_effects "missing bundle ID" prepare
assert_rejected_before_side_effects "unknown action" unknown "${fixture_bundle_id}"
assert_rejected_before_side_effects "run action" run "${fixture_bundle_id}"
assert_rejected_before_side_effects "Phase B action" phase-b "${fixture_bundle_id}"
assert_rejected_before_side_effects "latest selector" prepare latest
assert_rejected_before_side_effects "path selector" prepare ../bundle
assert_rejected_before_side_effects "absolute selector" prepare /tmp/bundle

echo "SW-EXP-003 mls-rs Phase A offline check: PASS"
