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
  candidate: {
    name: "mls-rs",
    version: "0.56.0",
    crypto_provider: "mls-rs-crypto-awslc-0.25.0/non-fips",
    storage_provider: "mls-rs-provider-sqlite-0.23.0/sqlite-bundled"
  },
  outcome: $outcome,
  stage: $stage,
  start_time: $start_time,
  end_time: $end_time,
  repository: {
    git_revision: $git_revision,
    git_dirty_before: (
      if $git_status_before == "unavailable" then null
      else ($git_status_before != "")
      end
    ),
    git_status_before: $git_status_before,
    git_status_after: $git_status_after
  },
  image: {
    ref: $image_ref,
    index_digest: $image_index_digest,
    platform_id: $image_platform_id,
    preexisting: boolean_or_null($image_preexisting)
  },
  platform: {
    target: $target_platform,
    host_arch: $host_arch,
    daemon_arch: $daemon_arch,
    container_arch: $container_arch
  },
  toolchain: {
    rust: $rust_version,
    cargo: $cargo_version
  },
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
      binary_sha256: $cargo_deny_binary_sha256,
      invocations: [["check", "sources"], ["check", "advisories", "licenses"]]
    }
  },
  direct_dependencies: {
    mls_rs: {
      version: "=0.56.0",
      default_features: false,
      features: ["std", "private_message", "out_of_order", "prior_epoch", "tree_index"]
    },
    mls_rs_crypto_awslc: {
      version: "=0.25.0",
      default_features: false,
      features: ["non-fips"]
    },
    mls_rs_provider_sqlite: {
      version: "=0.23.0",
      default_features: false,
      features: ["sqlite-bundled"]
    },
    mls_rs_codec: { version: "=0.7.0", features: [] },
    serde: { version: "=1.0.229", features: [] },
    serde_json: { version: "=1.0.151", features: [] },
    tempfile: { version: "=3.27.0", dependency_kind: "dev", features: [] }
  },
  resolved_package_count: number_or_null($resolved_package_count),
  cargo_lock_sha256: $cargo_lock_sha256,
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
    offline_checker: $offline_checker_sha256,
    audit_tool_bundle_manifest: $audit_tool_bundle_manifest_sha256,
    cargo_audit_binary: $cargo_audit_binary_sha256,
    cargo_deny_binary: $cargo_deny_binary_sha256
  },
  lockfile_preexisting: boolean_or_null($lockfile_preexisting),
  lockfile_written: boolean_or_null($lockfile_written),
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
    candidate_network: "docker-default-network-no-domain-allowlist",
    toolchain_validation_network: "none"
  },
  container_controls: {
    candidate_cpu_limit: 4,
    candidate_memory_limit: "4g",
    toolchain_cpu_limit: 1,
    toolchain_memory_limit: "512m",
    pids_limit: 512,
    read_only_root: true,
    cap_drop: "ALL",
    no_new_privileges: true,
    non_root: true
  },
  container_residual_count: number_or_null($container_residual_count),
  exit_code: ($exit_code | tonumber)
}
