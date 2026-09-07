def number_or_null($value):
  if ($value | test("^[0-9]+$")) then ($value | tonumber) else null end;

def boolean_or_null($value):
  if $value == "true" then true
  elif $value == "false" then false
  else null
  end;

{
  schema_version: ($schema_version | tonumber),
  bundle_contract: $bundle_contract,
  evidence_id: $evidence_id,
  scenario_id: $scenario_id,
  run_id: $run_id,
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
  tools: {
    cargo_audit: {
      path: "bundle/bin/cargo-audit",
      mode: "0555",
      requested_version: $cargo_audit_requested_version,
      reported_version: $cargo_audit_reported_version,
      binary_sha256: $cargo_audit_binary_sha256
    },
    cargo_deny: {
      path: "bundle/bin/cargo-deny",
      mode: "0555",
      requested_version: $cargo_deny_requested_version,
      reported_version: $cargo_deny_reported_version,
      binary_sha256: $cargo_deny_binary_sha256
    }
  },
  input_sha256: {
    runtime_control_helper: $runtime_control_helper_sha256,
    builder: $builder_sha256,
    manifest_filter: $manifest_filter_sha256,
    offline_checker: $offline_checker_sha256
  },
  disk_available_kib: number_or_null($disk_available_kib),
  runtime_controls: {
    monitor_status: $runtime_control_status,
    termination_reason: $runtime_termination_reason,
    received_signal: (
      if $received_signal == "" then null else $received_signal end
    ),
    elapsed_milliseconds: number_or_null($runtime_elapsed_milliseconds),
    timeout_seconds: ($runtime_timeout_seconds | tonumber),
    deadline_enforcement: "periodic-monitor-and-parent-signal",
    disk_current_kib: number_or_null($runtime_disk_current_kib),
    disk_peak_kib: number_or_null($runtime_disk_peak_kib),
    disk_budget_kib: ($runtime_disk_budget_kib | tonumber),
    disk_enforcement: "periodic-apparent-size-monitor",
    poll_interval_seconds: ($runtime_poll_interval_seconds | tonumber),
    builder_network: "docker-default-network-no-domain-allowlist",
    validation_network: "none"
  },
  container_controls: {
    build_cpu_limit: 4,
    build_memory_limit: "4g",
    validation_cpu_limit: 1,
    validation_memory_limit: "512m",
    pids_limit: 512,
    read_only_root: true,
    cap_drop: "ALL",
    no_new_privileges: true,
    non_root: true
  },
  container_residual_count: number_or_null($container_residual_count),
  exit_code: ($exit_code | tonumber)
}
