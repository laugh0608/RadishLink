def number_or_null($value):
  if ($value | test("^[0-9]+$")) then ($value | tonumber) else null end;

def boolean_or_null($value):
  if $value == "true" then true
  elif $value == "false" then false
  else null
  end;

{
  schema_version: ($schema_version | tonumber),
  manifest_contract: $manifest_contract,
  evidence_id: $evidence_id,
  phase: $phase,
  scenario_id: $scenario_id,
  run_id: $run_id,
  outcome: $outcome,
  stage: $stage,
  start_time: $start_time,
  end_time: $end_time,
  git_revision: $git_revision,
  git_dirty_before: (
    if $git_status_before == "unavailable" then null
    else ($git_status_before != "")
    end
  ),
  git_status_before: $git_status_before,
  git_status_after: $git_status_after,
  image_ref: $image_ref,
  image_index_digest: $image_index_digest,
  image_platform_id: $image_platform_id,
  image_preexisting: boolean_or_null($image_preexisting),
  host_arch: $host_arch,
  daemon_arch: $daemon_arch,
  container_arch: $container_arch,
  target_platform: $target_platform,
  rust_version: $rust_version,
  cargo_version: $cargo_version,
  audit_tool_bundle: {
    contract: $audit_tool_bundle_contract,
    id: $audit_tool_bundle_id,
    manifest_sha256: $audit_tool_bundle_manifest_sha256,
    mount_mode: "read-only",
    cargo_audit: {
      requested_version: $cargo_audit_requested_version,
      reported_version: $cargo_audit_reported_version,
      binary_sha256: $cargo_audit_binary_sha256,
      invocation: ["audit", "--json"]
    },
    cargo_deny: {
      requested_version: $cargo_deny_requested_version,
      reported_version: $cargo_deny_reported_version,
      binary_sha256: $cargo_deny_binary_sha256
    }
  },
  direct_dependencies: {
    openmls: { version: "=0.9.0", default_features: false, features: ["fork-resolution"] },
    openmls_basic_credential: { version: "=0.6.0", features: [] },
    openmls_rust_crypto: { version: "=0.6.0", features: [] },
    openmls_sqlite_storage: { version: "=0.3.0", features: [] },
    openmls_traits: { version: "=0.6.0", features: [] },
    rusqlite: { version: "=0.37.0", features: ["bundled"] },
    serde: { version: "=1.0.229", features: ["derive"] },
    serde_json: { version: "=1.0.151", features: [] },
    tls_codec: { version: "=0.5.0", features: ["derive", "serde", "mls"] },
    tempfile: { version: "=3.27.0", dependency_kind: "dev", features: [] }
  },
  resolved_package_count: number_or_null($resolved_package_count),
  cargo_lock_sha256: $cargo_lock_sha256,
  expected_lock_sha256: $expected_lock_sha256,
  advisory_db_revision: $advisory_db_revision,
  gate_exit_codes: {
    source: number_or_null($source_exit_code),
    audit: number_or_null($audit_exit_code),
    deny: number_or_null($deny_exit_code),
    feature: number_or_null($feature_exit_code)
  },
  input_sha256: {
    license: $license_sha256,
    cargo_toml: $cargo_toml_sha256,
    deny_toml: $deny_toml_sha256,
    main_rs: $main_rs_sha256,
    runtime_control_helper: $runtime_control_helper_sha256,
    runner: $runner_sha256,
    phase_a_manifest_filter: $phase_a_manifest_filter_sha256,
    audit_tool_bundle_manifest: $audit_tool_bundle_manifest_sha256,
    cargo_audit_binary: $cargo_audit_binary_sha256,
    cargo_deny_binary: $cargo_deny_binary_sha256
  },
  lockfile_preexisting: ($lockfile_preexisting == "true"),
  lockfile_written: ($lockfile_written == "true"),
  disk_available_kib: number_or_null($disk_available_kib),
  runtime_controls: {
    monitor_status: $runtime_control_status,
    termination_reason: $runtime_termination_reason,
    received_signal: (if $received_signal == "" then null else $received_signal end),
    elapsed_milliseconds: number_or_null($runtime_elapsed_milliseconds),
    timeout_seconds: ($runtime_timeout_seconds | tonumber),
    deadline_enforcement: "periodic-monitor-and-parent-signal",
    disk_current_kib: number_or_null($runtime_disk_current_kib),
    disk_peak_kib: number_or_null($runtime_disk_peak_kib),
    disk_budget_kib: ($runtime_disk_budget_kib | tonumber),
    disk_enforcement: "periodic-apparent-size-monitor",
    poll_interval_seconds: ($runtime_poll_interval_seconds | tonumber),
    network_egress_enforcement: "docker-default-network-no-domain-allowlist"
  },
  container_residual_count: number_or_null($container_residual_count),
  exit_code: ($exit_code | tonumber)
}
