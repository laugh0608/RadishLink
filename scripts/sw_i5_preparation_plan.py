"""Review-only initialization and capacity declarations. No CLI or environment I/O.

These schemas are independent of operation v1-v4 and resource config v1.
Synthetic observations check consistency, never filesystem or kernel truth.
All paths are lexical. No declaration authorizes execution or proves capacity.
"""

import hashlib
import json
from pathlib import PurePosixPath
import re

import sw_i5_apt as apt
import sw_i5_preparation_isolation as isolation
import sw_i5_preparation_lifecycle as lifecycle
from sw_i5_preparation_rpc import REQUEST_LIMIT
from sw_i5_preparation_transport import SLOT_BYTES
from sw_i5_preparation_evidence import STORE_LIMIT
from sw_i5_resources import CAPS

MIB = apt.MIB
NODE_BYTES = 768 * MIB - sum(CAPS.values())
FLAGS = ("authorized", "install_authorized", "i5_ready", "physical_verified")
EXECUTION_BLOCKERS = (
    "review-only: no current execution authorization",
    "actual path ancestry, no-symlink and independent identity readback unverified",
    "actual kernel limits, complete physical backing and rejection behavior unverified",
    "real Linux/UTM initialization, recovery and new execution-source contract absent",
)
INIT_TASKS = ("jxa_parent", "evidence_parent", "attempt_create_readback")
READY_TASKS = ("guest_directories", "cgroup_hierarchy", "control_slots", "readonly_input", "independent_readback")
ACTIVE_ORDER = ("open_lease", "open_ack", "execute_once")
COMMON_SURFACES = (
    "guest_root_var", "efi_firmware", "guest_swap", "guest_system_tmpfs",
    "utm_qemu_logs_state", "host_swap_crash", "host_jxa_source",
    "host_evidence_export_source", "host_evidence_retained",
)
PREP_SURFACES = COMMON_SURFACES + (
    "readonly_input", "input_media_creation", "input_media_staging_copy",
    "preparation_work", "preparation_result", "host_backing_metadata",
)
I5_SURFACES = COMMON_SURFACES + (
    "build", "daemon", "containerd", "builder", "evidence", "diagnostic", "node_tmpfs",
) + tuple("host_backing_" + domain for domain in CAPS)
PREP_CAPS = dict(isolation.STORAGE, host_retention=32 * MIB)
PREP_OWNERS = {
    "readonly_input": "input", "preparation_work": "work", "preparation_result": "result",
    "host_evidence_export_source": "host_retention", "host_evidence_retained": "host_retention",
}
I5_OWNERS = {
    "build": "build", "daemon": "daemon", "containerd": "daemon", "builder": "daemon",
    "evidence": "evidence", "diagnostic": "diagnostic", "node_tmpfs": "node_tmpfs",
    "host_jxa_source": "diagnostic", "host_evidence_export_source": "diagnostic",
    "host_evidence_retained": "evidence",
    **{"host_backing_" + domain: domain for domain in CAPS},
}
HARD_MECHANISMS = {
    "fixed-block": "fixed-block-device",
    "quota-filesystem": "aggregate-filesystem-hard-quota",
    "host-quota": "aggregate-host-hard-quota",
    "noswap-tmpfs": "kernel-size-and-noswap",
    "readonly-media": "existing-readonly-bound-input",
}
DISABLED = {"guest_swap": "guest-all-swap-disabled", "host_swap_crash": "host-swap-and-crash-disabled"}
HOST_COVERAGE_SCOPE = "i5-preparation-host-coverage-candidate"
# A fixed coverage inventory, not another capacity configuration. Each tuple
# names independently accountable components and their responsible owner.
COVERAGE_COMPONENTS = {
    "guest_root_var": {"root_var": "guest-system-owner"},
    "efi_firmware": {"guest_efi_firmware": "guest-system-owner"},
    "guest_swap": {"all_guest_swap": "guest-system-owner"},
    "guest_system_tmpfs": {"initialization_root": "guest-initializer", "other_system_tmpfs": "guest-system-owner"},
    "utm_qemu_logs_state": {"utm_qemu_state_logs": "host-vm-owner", "firmware_state": "host-vm-owner", "host_global_logs": "host-system-owner"},
    "host_swap_crash": {"host_swap": "host-system-owner", "host_crash": "host-system-owner"},
    "host_jxa_source": {"jxa_source": "evidence-worker", "library_source_assembly": "library-assembler"},
    "host_evidence_export_source": {"export_source": "evidence-worker"},
    "host_evidence_retained": {"retained_evidence": "evidence-owner"},
    "readonly_input": {"apt_media": "media-provisioner", "library_media": "media-provisioner"},
    "input_media_creation": {"apt_media_creation": "media-provisioner", "library_media_creation": "media-provisioner"},
    "input_media_staging_copy": {"apt_media_staging": "media-provisioner", "library_media_staging": "media-provisioner"},
    "preparation_work": {"work": "guest-worker"},
    "preparation_result": {"result": "guest-worker"},
    "host_backing_metadata": {"backing_snapshots_metadata": "host-vm-owner"},
}
MACOS_UNBOUNDED_SURFACES = ("utm_qemu_logs_state", "host_swap_crash")
COVERAGE_HOST_SURFACES = frozenset(("utm_qemu_logs_state", "host_swap_crash", "host_jxa_source",
    "host_evidence_export_source", "host_evidence_retained", "input_media_creation", "input_media_staging_copy", "host_backing_metadata"))


def check(ok, path, message):
    if not ok:
        raise ValueError(path + ": " + message)


def fields(value, names, path):
    check(type(value) is dict, path, "object required")
    expected = set(names.split())
    check(set(value) == expected, path,
          "unknown/missing fields " + repr(sorted(set(value) ^ expected)))


def integer(value, path, minimum=0, maximum=2**63 - 1):
    check(type(value) is int and minimum <= value <= maximum, path, "integer outside allowed range")


def decode(raw, scope):
    check(type(raw) is bytes, scope, "bytes required")
    try:
        check(len(raw) <= 256 * 1024, scope, "JSON byte limit")
        value = apt.decode(raw.decode("utf-8", errors="strict"), 256 * 1024)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError(scope + ": " + str(exc)) from exc
    return value


def binding(value, nonce, manifest_sha256, scope):
    check(type(value["schema_version"]) is int and value["schema_version"] == 1,
          scope + ".schema_version", "unsupported schema")
    check(value["scope"] == scope, scope + ".scope", "wrong scope")
    check(type(nonce) is str and re.fullmatch(r"[0-9a-f]{32}", nonce) is not None and value["nonce"] == nonce,
          scope + ".nonce", "nonce binding")
    check(value["uuid"] == apt.UUID, scope + ".uuid", "UUID binding")
    check(apt.digest(manifest_sha256) and value["manifest_sha256"] == manifest_sha256,
          scope + ".manifest_sha256", "manifest binding")
    check(value["kind"] in ("synthetic", "offline-candidate"), scope + ".kind", "offline kind required")
    for name in FLAGS:
        check(value[name] is False, scope + "." + name, "review-only flag must be false")


def lexical(value, path):
    check(type(value) is str and len(value) <= 1024 and re.fullmatch(r"/[A-Za-z0-9_./-]+", value) is not None,
          path, "absolute lexical path required")
    item = PurePosixPath(value)
    check(str(item) == value and value != "/" and ".." not in item.parts,
          path, "noncanonical path")
    return item


def source(value, path):
    fields(value, "kind reference", path)
    check(value["kind"] in ("synthetic", "offline-declaration"), path + ".kind", "offline source only")
    check(type(value["reference"]) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", value["reference"]) is not None,
          path + ".reference", "source reference required")


def report(scope, blockers, nonce, manifest_sha256, **extra):
    return dict(schema_version=1, scope=scope, review_only=True, review_passed=not blockers,
                uuid=apt.UUID, nonce=nonce, manifest_sha256=manifest_sha256,
                review_blockers=blockers, execution_blockers=list(EXECUTION_BLOCKERS),
                **{name: False for name in FLAGS}, **extra)


def validate_capacity(raw, profile, nonce, manifest_sha256):
    """Validate fixed write coverage and D+H arithmetic; never probe storage."""
    value = decode(raw, "i5-review-capacity")
    fields(value, "schema_version scope kind uuid nonce manifest_sha256 profile domains surfaces envelope_bytes "
           + " ".join(FLAGS), "capacity")
    binding(value, nonce, manifest_sha256, "i5-review-capacity")
    check(profile in ("preparation", "i5-runtime") and value["profile"] == profile,
          "capacity.profile", "profile mismatch")
    names = PREP_SURFACES if profile == "preparation" else I5_SURFACES
    caps = dict(PREP_CAPS, environment=None) if profile == "preparation" else dict(CAPS, node_tmpfs=NODE_BYTES)
    fields(value["domains"], " ".join(caps), "capacity.domains")
    fields(value["surfaces"], " ".join(names), "capacity.surfaces")
    blockers, domains = [], {}
    for name, fixed in caps.items():
        path, row = "capacity.domains." + name, value["domains"][name]
        fields(row, "cap_bytes guest_device_bytes", path)
        integer(row["cap_bytes"], path + ".cap_bytes", 1)
        integer(row["guest_device_bytes"], path + ".guest_device_bytes")
        if profile == "i5-runtime":
            check(row["cap_bytes"] == fixed, path + ".cap_bytes", "fixed I5 domain cap")
            check(row["guest_device_bytes"] > 0 if name in CAPS else row["guest_device_bytes"] == 0,
                  path + ".guest_device_bytes", "whole guest device required for each disk domain only")
        elif fixed is not None:
            check(row["cap_bytes"] <= fixed, path + ".cap_bytes", "preparation candidate ceiling")
        check(row["guest_device_bytes"] <= row["cap_bytes"], path, "device exceeds domain cap")
        domains[name] = dict(cap_bytes=row["cap_bytes"], guest_device_bytes=row["guest_device_bytes"],
                             device_surface_reserve_bytes=0, extra_reserve_bytes=0)
    integer(value["envelope_bytes"], "capacity.envelope_bytes", 1)
    total_cap = sum(row["cap_bytes"] for row in domains.values())
    check(total_cap <= value["envelope_bytes"], "capacity.envelope_bytes", "all domains must fit explicit complete envelope")
    if profile == "i5-runtime":
        check(value["envelope_bytes"] == 768 * MIB, "capacity.envelope_bytes", "fixed I5 768 MiB envelope")
    representations = set()
    owners = PREP_OWNERS if profile == "preparation" else I5_OWNERS
    for name in names:
        path, row = "capacity.surfaces." + name, value["surfaces"][name]
        fields(row, "owner_domain charge state logical_bytes copies peak_bytes hard_limit_bytes "
               "representation backing mechanism observation_source", path)
        owner = row["owner_domain"]
        check(type(owner) is str and owner in domains, path + ".owner_domain", "explicit domain ownership required")
        if name in owners:
            check(owner == owners[name], path + ".owner_domain", "fixed surface/domain ownership")
        if profile == "preparation" and name not in owners:
            check(owner == "environment", path + ".owner_domain", "complete system/host preparation budget required")
        check(row["charge"] in ("D", "H"), path + ".charge", "D or H required")
        if name.startswith("host_") or name in ("utm_qemu_logs_state", "input_media_creation", "input_media_staging_copy"):
            check(row["charge"] == "H", path + ".charge", "independent host writes must be extra reserves")
        if name in ("build", "daemon", "containerd", "builder", "evidence", "diagnostic", "readonly_input"):
            check(row["charge"] == "D", path + ".charge", "guest payload belongs inside full device D")
        if name in ("node_tmpfs", "guest_system_tmpfs", "preparation_work", "preparation_result"):
            check(row["charge"] == "H", path + ".charge", "noswap memory reservation is outside disk D")
        check(row["state"] in ("bounded", "disabled", "unknown"), path + ".state", "unknown state")
        if row["state"] == "unknown":
            check(all(row[k] is None for k in ("logical_bytes", "copies", "peak_bytes", "hard_limit_bytes", "representation"))
                  and row["backing"] == "unknown" and row["mechanism"] == "unknown", path, "unknown cannot be counted as zero or bounded")
            if row["observation_source"] is not None:
                source(row["observation_source"], path + ".observation_source")
            blockers.append(path + ": complete hard bound/backing unknown")
            continue
        source(row["observation_source"], path + ".observation_source")
        if row["state"] == "disabled":
            check(name in DISABLED and row["mechanism"] == DISABLED[name] and row["backing"] == "disabled"
                  and all(type(row[k]) is int and row[k] == 0 for k in ("logical_bytes", "copies", "peak_bytes", "hard_limit_bytes"))
                  and row["representation"] is None, path, "only independently declared swap/crash disablement may charge zero")
            continue
        for key in ("logical_bytes", "copies", "peak_bytes", "hard_limit_bytes"):
            integer(row[key], path + "." + key, 1, 16 if key == "copies" else 2**63 - 1)
        check(row["peak_bytes"] >= row["logical_bytes"] * row["copies"] and row["hard_limit_bytes"] >= row["peak_bytes"],
              path, "independent copy peak/reserve undercount")
        representation = row["representation"]
        check(type(representation) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", representation) is not None,
              path + ".representation", "physical charge identity required")
        check(representation not in representations, path + ".representation", "duplicate representation; aggregate same representation in one surface")
        representations.add(representation)
        check(type(row["backing"]) is str and row["backing"] in HARD_MECHANISMS
              and row["mechanism"] == HARD_MECHANISMS[row["backing"]], path, "complete hard mechanism/backing required; sampling/logical limits insufficient")
        check(row["backing"] != "readonly-media" or name == "readonly_input", path, "readonly cannot cover new media or other write surfaces")
        if name in ("guest_system_tmpfs", "node_tmpfs", "preparation_work", "preparation_result"):
            check(row["backing"] == "noswap-tmpfs", path + ".backing", "bounded noswap memory required")
        if name in ("preparation_work", "preparation_result"):
            check(row["hard_limit_bytes"] == isolation.STORAGE[name.removeprefix("preparation_")],
                  path + ".hard_limit_bytes", "existing preparation tmpfs size must be fully reserved")
        if name == "node_tmpfs":
            check(row["hard_limit_bytes"] == NODE_BYTES, path + ".hard_limit_bytes", "fixed three-node 48 MiB")
        target = "device_surface_reserve_bytes" if row["charge"] == "D" else "extra_reserve_bytes"
        domains[owner][target] += row["hard_limit_bytes"]
    for name, row in domains.items():
        path = "capacity.domains." + name
        check(row["device_surface_reserve_bytes"] <= row["guest_device_bytes"], path,
              "surface reservations exceed whole device D")
        check(row["guest_device_bytes"] + row["extra_reserve_bytes"] <= row["cap_bytes"], path,
              "whole guest device D plus extra hard reserves H exceeds C")
    return report("i5-review-capacity-report", blockers, nonce, manifest_sha256, profile=profile, domains=domains,
                  envelope_bytes=value["envelope_bytes"], budget_status="review-declaration-only")


def object_specs(value):
    """Fixed roles and lexical paths, not a provisioning instruction language."""
    nonce = value["nonce"]
    host_uid, host_gid = value["host_uid"], value["host_gid"]
    staging = lexical(value["host_jxa_root"], "plan.host_jxa_root")
    parent = lexical(value["host_evidence_parent"], "plan.host_evidence_parent")
    check(staging.name == nonce, "plan.host_jxa_root", "fresh nonce staging root required")
    input_path = lexical(value["readonly_input"]["path"], "plan.readonly_input.path")
    # Existing Contract.parse is pure and retains the original identity/path rules.
    try:
        contract = isolation.Contract.parse(json.dumps(dict(schema_version=1, scope="i5-preparation-isolation",
            nonce=nonce, uuid=apt.UUID, manifest_sha256=value["manifest_sha256"],
            root="/run/radishlink-i5-preparation/" + nonce, input=str(input_path),
            uid=value["guest_uid"], gid=value["guest_gid"], i5_ready=False)).encode(), nonce, value["manifest_sha256"])
    except ValueError as exc:
        raise ValueError("plan.readonly_input: " + str(exc)) from exc
    rows = {}
    def add(role, path, realm, creator, consumers, stage, policy="fresh", kind="directory", uid=0, gid=0,
            mode=0o700, size=0, sha256=None, limits=None):
        rows[role] = dict(path=str(path), realm=realm, kind=kind, uid=uid, gid=gid, mode=mode,
                          creator=creator, consumers=consumers, before_stage=stage, policy=policy,
                          readback="independent-before-consumption", cleanup=("retain-consumed-attempt" if role == "host_attempt"
                          else "preserve-bound-input" if policy == "bind" else "identity-bound-after-reap"),
                          bytes=size, sha256=sha256, limits=None if limits is None else dict(limits))
    add("host_jxa_root", staging, "host", "host-initializer", ["rpc-stager"], "start", uid=host_uid, gid=host_gid)
    add("host_evidence_parent", parent, "host", "preexisting-owner", ["evidence-owner"], "start", "bind", uid=host_uid, gid=host_gid)
    add("host_attempt", parent / nonce, "host", "evidence-owner", ["evidence-reader"], "start", uid=host_uid, gid=host_gid)
    add("guest_root", contract.root, "guest", "guest-initializer", ["namespace-setup", "supervisor"], "transport-open")
    for name, path in (("work", contract.work), ("result", contract.result)):
        add(name, path, "guest", "guest-initializer", ["namespace-setup"], "transport-open")
    for role in isolation.LIMITS:
        path = contract.cgroup if role == "parent" else contract.cgroup / role
        add("cgroup_" + role, path, "guest", "guest-initializer", ["supervisor"], "transport-open", limits=isolation.LIMITS[role])
    add("control", contract.root / "control", "guest", "guest-initializer", ["supervisor", "host-transport"], "transport-open")
    for role in ("lease", "ack"):
        add(role, contract.root / "control" / (role + ".slot"), "guest", "guest-initializer",
            ["supervisor", "host-transport"], "transport-open", kind="regular", mode=0o600,
            size=SLOT_BYTES, sha256=hashlib.sha256(bytes(SLOT_BYTES)).hexdigest())
    add("readonly_input", input_path, "guest", "preexisting-owner", ["namespace-setup", "worker"], "transport-open",
        "bind", kind="readonly-tree", mode=0o555, size=value["readonly_input"]["bytes"], sha256=value["readonly_input"]["sha256"])
    # Only these containment edges are meaningful; realm separates host/guest.
    edges = {("host_evidence_parent", "host_attempt"), ("guest_root", "work"), ("guest_root", "result"),
             ("guest_root", "control"), ("guest_root", "lease"), ("guest_root", "ack"),
             ("control", "lease"), ("control", "ack"), ("cgroup_parent", "cgroup_worker"),
             ("cgroup_parent", "cgroup_supervisor")}
    for a, left in rows.items():
        for b, right in rows.items():
            if a == b or left["realm"] != right["realm"]:
                continue
            x, y = PurePosixPath(left["path"]), PurePosixPath(right["path"])
            check(x != y, "plan.objects." + b, "path aliases " + a)
            check(x not in y.parents or (a, b) in edges, "plan.objects." + b, "unexpected path overlap with " + a)
    return rows


def validate_stages(value):
    fields(value, "init readiness active", "plan.stage_allocations")
    for phase, tasks in (("init", INIT_TASKS), ("readiness", READY_TASKS)):
        row, path = value[phase], "plan.stage_allocations." + phase
        fields(row, " ".join(tasks), path)
        for task in tasks:
            integer(row[task], path + "." + task, 1, lifecycle.CAPS[phase])
        check(sum(row.values()) <= lifecycle.CAPS[phase], path, "shared existing phase ceiling exceeded")
    active = value["active"]
    fields(active, "order rpc_seconds close_seconds output_seconds work_seconds source_policy", "plan.stage_allocations.active")
    check(active["order"] == list(ACTIVE_ORDER), "plan.stage_allocations.active.order", "slots open before single execute")
    for name, fixed in (("rpc_seconds", 2), ("close_seconds", 4), ("output_seconds", 2),
                        ("work_seconds", lifecycle.CAPS["active"] - 6)):
        integer(active[name], "plan.stage_allocations.active." + name, 1, fixed)
    check(active["source_policy"] == "exclusive-per-rpc-create-readback-cleanup-inside-rpc-deadline",
          "plan.stage_allocations.active.source_policy", "per-RPC staging obligation required")
    check(active["work_seconds"] + active["close_seconds"] + active["output_seconds"] <= lifecycle.CAPS["active"],
          "plan.stage_allocations.active", "active subwindows exceed existing phase")
    budget = lifecycle.Budget()
    return dict(worst_seconds=budget.worst_seconds, absolute_seconds=budget.total,
                stage_allocations_are_subsets=True)


def observation(value, spec, role, nonce, manifest_sha256, path):
    fields(value, "observer realm role path nonce manifest_sha256 dev ino uid gid mode kind nlink bytes sha256 symlink limits", path)
    check(value["observer"] in ("creator", "independent-reader", "preexisting-observer"), path + ".observer", "fixed observer role")
    for name in ("realm", "path", "uid", "gid", "mode", "kind", "bytes", "sha256", "limits"):
        check(type(value[name]) is type(spec[name]) and value[name] == spec[name], path + "." + name, "object declaration mismatch")
    check(value["role"] == role and value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256,
          path, "observation role/nonce/manifest binding")
    integer(value["dev"], path + ".dev", 1)
    integer(value["ino"], path + ".ino", 1)
    integer(value["nlink"], path + ".nlink", 1)
    check(value["kind"] != "regular" or value["nlink"] == 1, path + ".nlink", "slot must have one link")
    check(value["symlink"] is False, path + ".symlink", "declared symlink rejected; actual ancestry unverified")
    return value["realm"], value["dev"], value["ino"]


def validate_plan(raw, nonce, manifest_sha256):
    """Validate initialization roles, lexical references and offline readbacks."""
    value = decode(raw, "i5-review-initialization")
    fields(value, "schema_version scope kind uuid nonce manifest_sha256 capacity_sha256 host_uid host_gid guest_uid guest_gid "
           "host_jxa_root host_evidence_parent readonly_input jxa_source objects stage_allocations offline_observations used_nonces "
           + " ".join(FLAGS), "plan")
    binding(value, nonce, manifest_sha256, "i5-review-initialization")
    check(apt.digest(value["capacity_sha256"]), "plan.capacity_sha256", "ledger digest required")
    for name, minimum in (("host_uid", 1), ("host_gid", 0), ("guest_uid", 1000), ("guest_gid", 1000)):
        integer(value[name], "plan." + name, minimum, 65533)
    fields(value["readonly_input"], "path bytes sha256", "plan.readonly_input")
    integer(value["readonly_input"]["bytes"], "plan.readonly_input.bytes", 1, isolation.STORAGE["input"])
    check(apt.digest(value["readonly_input"]["sha256"]), "plan.readonly_input.sha256", "input digest required")
    fields(value["jxa_source"], "bytes sha256", "plan.jxa_source")
    integer(value["jxa_source"]["bytes"], "plan.jxa_source.bytes", 1, 128 * 1024)
    check(apt.digest(value["jxa_source"]["sha256"]), "plan.jxa_source.sha256", "reviewed source digest required")
    check(type(value["used_nonces"]) is list and len(value["used_nonces"]) <= 1024
          and all(type(n) is str and re.fullmatch(r"[0-9a-f]{32}", n) is not None for n in value["used_nonces"]),
          "plan.used_nonces", "bounded consumed nonce list required")
    check(len(set(value["used_nonces"])) == len(value["used_nonces"]) and nonce not in value["used_nonces"],
          "plan.used_nonces", "duplicate or consumed nonce")
    specs = object_specs(value)
    fields(value["objects"], " ".join(specs), "plan.objects")
    for role, spec in specs.items():
        fields(value["objects"][role], " ".join(spec), "plan.objects." + role)
        check(value["objects"][role] == spec and all(type(value["objects"][role][key]) is type(expected) for key, expected in spec.items()),
              "plan.objects." + role, "fixed role/path/identity/stage/readback/cleanup declaration mismatch")
    timing = validate_stages(value["stage_allocations"])
    fields(value["offline_observations"], "kind objects", "plan.offline_observations")
    check(value["offline_observations"]["kind"] == "synthetic", "plan.offline_observations.kind", "synthetic only; self-report is no proof")
    observations = value["offline_observations"]["objects"]
    fields(observations, " ".join(specs), "plan.offline_observations.objects")
    blockers, identities = [], set()
    for role, spec in specs.items():
        path, row = "plan.offline_observations.objects." + role, observations[role]
        fields(row, "before after independent_readback", path)
        if spec["policy"] == "fresh":
            check(row["before"] is None, path + ".before", "fresh object already exists; do not resume/overwrite")
        for phase in ("before", "after", "independent_readback"):
            snapshot = row[phase]
            if snapshot is None:
                if phase != "before" or spec["policy"] == "bind":
                    blockers.append(path + "." + phase + ": offline identity/readback missing")
                continue
            identity = observation(snapshot, spec, role, nonce, manifest_sha256, path + "." + phase)
            expected_observer = "independent-reader" if phase == "independent_readback" else "preexisting-observer" if phase == "before" else "creator"
            check(snapshot["observer"] == expected_observer, path + "." + phase, "independent reader/creator roles required")
            if phase == "after":
                check(identity not in identities, path, "object inode aliases another role in same realm")
                identities.add(identity)
        def comparable(snapshot):
            return None if snapshot is None else {k: v for k, v in snapshot.items() if k != "observer"}
        if row["after"] is not None and row["independent_readback"] is not None:
            check(comparable(row["after"]) == comparable(row["independent_readback"]), path, "independent readback identity replacement")
        if spec["policy"] == "bind" and row["before"] is not None and row["after"] is not None:
            check(comparable(row["before"]) == comparable(row["after"]), path, "bound existing object replaced")
    return report("i5-review-initialization-report", blockers, nonce, manifest_sha256, timing=timing,
                  capacity_sha256=value["capacity_sha256"], object_count=len(specs),
                  jxa_assembled_source_bytes_upper_bound=assembled_source_bound(value["jxa_source"]["bytes"]))


def assembled_source_bound(source_bytes):
    """Bound source + JSON-escaped request + wrapper; no request execution."""
    integer(source_bytes, "plan.jxa_source.bytes", 1, 128 * 1024)
    return source_bytes + 6 * REQUEST_LIMIT + 4096


def review(plan_raw, ledger_raw, nonce, manifest_sha256):
    """Bind exact ledger bytes and return one review report, with STOP retained."""
    plan = validate_plan(plan_raw, nonce, manifest_sha256)
    check(type(ledger_raw) is bytes and hashlib.sha256(ledger_raw).hexdigest() == plan["capacity_sha256"],
          "plan.capacity_sha256", "exact ledger bytes changed")
    capacity = validate_capacity(ledger_raw, "preparation", nonce, manifest_sha256)
    # Input and source copies must fit their declared peaks, independent of quotas.
    declaration = decode(plan_raw, "i5-review-initialization")
    ledger = decode(ledger_raw, "i5-review-capacity")
    for surface, size in (("readonly_input", declaration["readonly_input"]["bytes"]),
                          ("input_media_creation", declaration["readonly_input"]["bytes"]),
                          ("input_media_staging_copy", declaration["readonly_input"]["bytes"]),
                          ("host_jxa_source", assembled_source_bound(declaration["jxa_source"]["bytes"])),
                          ("guest_system_tmpfs", 2 * SLOT_BYTES),
                          ("host_evidence_export_source", STORE_LIMIT),
                          ("host_evidence_retained", STORE_LIMIT)):
        row = ledger["surfaces"][surface]
        check(row["state"] == "unknown" or row["logical_bytes"] >= size,
              "capacity.surfaces." + surface, "bound source/input bytes exceed declared copy peak")
    return report("i5-review-preparation-report", plan["review_blockers"] + capacity["review_blockers"], nonce, manifest_sha256,
                  initialization=plan, capacity=capacity)


def review_host_coverage(raw, capacity_raw, nonce, manifest_sha256, *, blobs):
    """Bind a fixed write inventory to the existing preparation ledger only.

    No I/O, provisioning, native authentication or authorization occurs here.
    The macOS/UTM backend has no complete system write boundary in this package;
    synthetic JSON cannot turn that engineering decision into a physical PASS.
    """
    value = decode(raw, HOST_COVERAGE_SCOPE)
    fields(value, "schema_version scope kind uuid nonce manifest_sha256 capacity backend surfaces " + " ".join(FLAGS), "coverage")
    binding(value, nonce, manifest_sha256, HOST_COVERAGE_SCOPE)
    fields(value["capacity"], "bytes sha256", "coverage.capacity")
    integer(value["capacity"]["bytes"], "coverage.capacity.bytes", 1, 256 * 1024)
    check(type(capacity_raw) is bytes and value["capacity"] == dict(bytes=len(capacity_raw), sha256=hashlib.sha256(capacity_raw).hexdigest()),
          "coverage.capacity", "exact capacity bytes required")
    capacity_report = validate_capacity(capacity_raw, "preparation", nonce, manifest_sha256)
    ledger = decode(capacity_raw, "i5-review-capacity")
    check(value["backend"] in ("macos-utm", "injected-offline"), "coverage.backend", "reviewed backend required")
    fields(value["surfaces"], " ".join(PREP_SURFACES), "coverage.surfaces")
    check(type(blobs) is dict and all(type(k) is str and type(v) is bytes for k, v in blobs.items()),
          "coverage.blobs", "explicit raw bytes mapping required")
    check(sum(map(len, blobs.values())) + len(raw) + len(capacity_raw) <= 32 * MIB,
          "coverage.blobs", "aggregate candidate input limit")
    used_blobs, physical_ids, identities, devices, roots, mounts = set(), set(), set(), set(), [], set()
    whole_devices = {name: 0 for name in ledger["domains"]}
    blockers = list(capacity_report["review_blockers"])

    def fact(ref, name):
        fields(ref, "bytes sha256", name)
        integer(ref["bytes"], name + ".bytes", 1, 256 * 1024)
        check(apt.digest(ref["sha256"]), name, "raw fact digest required")
        check(name in blobs and ref == dict(bytes=len(blobs[name]), sha256=hashlib.sha256(blobs[name]).hexdigest()),
              name, "raw fact fingerprint mismatch")
        used_blobs.add(name)
        return decode(blobs[name], name)

    for name in PREP_SURFACES:
        path, row, budget = "coverage.surfaces." + name, value["surfaces"][name], ledger["surfaces"][name]
        fields(row, "owner_domain charge state components physical_domains configuration observation", path)
        for key in ("owner_domain", "charge", "state"):
            check(type(row[key]) is type(budget[key]) and row[key] == budget[key], path + "." + key, "existing capacity projection required")
        fields(row["components"], " ".join(COVERAGE_COMPONENTS[name]), path + ".components")
        logical, copy_bytes, peak = 0, 0, 0
        for component, owner in COVERAGE_COMPONENTS[name].items():
            part, prefix = row["components"][component], path + ".components." + component
            fields(part, "owner logical_bytes copies peak_bytes physical_domain", prefix)
            check(part["owner"] == owner, prefix + ".owner", "fixed responsible owner required")
            if row["state"] == "unknown":
                check(all(part[k] is None for k in ("logical_bytes", "copies", "peak_bytes")), prefix, "unknown component cannot be charged zero")
            else:
                minimum = 0 if row["state"] == "disabled" else 1
                integer(part["logical_bytes"], prefix + ".logical_bytes", minimum)
                integer(part["copies"], prefix + ".copies", minimum, 16)
                integer(part["peak_bytes"], prefix + ".peak_bytes", minimum)
                check(part["peak_bytes"] >= part["logical_bytes"] * part["copies"], prefix, "copy peak undercount")
                if row["state"] == "disabled":
                    check(all(part[k] == 0 for k in ("logical_bytes", "copies", "peak_bytes")), prefix, "disabled component must be zero")
                logical += part["logical_bytes"]
                copy_bytes += part["logical_bytes"] * part["copies"]
                peak += part["peak_bytes"]
            check(part["physical_domain"] is None if row["state"] != "bounded" else
                  type(part["physical_domain"]) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", part["physical_domain"]) is not None,
                  prefix + ".physical_domain", "bounded components require an explicit physical domain; other states cannot claim one")
        if value["backend"] == "macos-utm" and name in MACOS_UNBOUNDED_SURFACES:
            check(row["state"] == "unknown", path, "current macOS/UTM system writes have no complete hard boundary")
        if row["state"] == "unknown":
            check(row["physical_domains"] == {} and all(row[k] is None for k in ("configuration", "observation")), path, "unknown boundary cannot carry completion facts")
            continue
        check(logical <= budget["logical_bytes"] and copy_bytes <= budget["logical_bytes"] * budget["copies"] and peak <= budget["peak_bytes"],
              path, "component copy peaks exceed existing capacity surface")
        domains = row["physical_domains"]
        check(type(domains) is dict and set(domains) == {part["physical_domain"] for part in row["components"].values() if part["physical_domain"] is not None},
              path + ".physical_domains", "exact referenced physical domains required")
        if row["state"] == "disabled":
            check(domains == {}, path + ".physical_domains", "disabled surface has no physical write domain")
        if name == "readonly_input" and row["state"] == "bounded":
            check(len(domains) == 2, path, "APT and library media require distinct physical domains")
        reserved = 0
        for domain_id, domain in domains.items():
            fields(domain, "realm path dev ino mount_id filesystem_id representation hard_reserve_bytes whole_device_bytes inode_limit", path + ".physical_domains." + domain_id)
            for key in ("filesystem_id",):
                check(type(domain[key]) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", domain[key]) is not None,
                      path + ".physical_domains." + key, "stable physical identity required")
            check(domain["realm"] == ("host" if name in COVERAGE_HOST_SURFACES else "guest"), path, "fixed physical realm required")
            if domain["realm"] == "guest":
                integer(domain["mount_id"], path + ".physical_domains.mount_id", 1)
                check(domain["mount_id"] not in mounts, path, "guest physical mount identity reused")
                mounts.add(domain["mount_id"])
            else:
                check(domain["mount_id"] is None, path, "host mount identity is represented by filesystem ID, not a Linux mount ID")
            root = lexical(domain["path"], path + ".physical_domains.path")
            for key in ("dev", "ino"): integer(domain[key], path + ".physical_domains." + key, 1)
            if budget["backing"] == "noswap-tmpfs":
                integer(domain["inode_limit"], path + ".physical_domains.inode_limit", 1)
            else:
                check(domain["inode_limit"] is None, path, "inode quota declaration is reserved for bounded tmpfs")
            integer(domain["hard_reserve_bytes"], path + ".physical_domains.hard_reserve_bytes", 1)
            integer(domain["whole_device_bytes"], path + ".physical_domains.whole_device_bytes", 0 if row["charge"] == "H" else 1)
            check(domain["whole_device_bytes"] == 0 if row["charge"] == "H" else domain["whole_device_bytes"] >= domain["hard_reserve_bytes"],
                  path, "D requires the complete physical device; H cannot hide another device charge")
            check(sum(part["peak_bytes"] for part in row["components"].values() if part["physical_domain"] == domain_id) <= domain["hard_reserve_bytes"],
                  path, "domain component peaks exceed its share of the existing hard reserve")
            reserved += domain["hard_reserve_bytes"]
            whole_devices[row["owner_domain"]] += domain["whole_device_bytes"]
            check(domain["representation"] == budget["representation"], path, "physical representation must bind existing capacity surface")
            identity, device = (domain["realm"], domain["dev"], domain["ino"]), (domain["realm"], domain["dev"])
            check(domain_id not in physical_ids and identity not in identities and device not in devices,
                  path, "physical domains cannot alias or share a filesystem quota")
            check(all(realm != domain["realm"] or fsid != domain["filesystem_id"] for realm, _, fsid in roots),
                  path, "physical filesystem identity reused")
            check(all(realm != domain["realm"] or (root != other and root not in other.parents and other not in root.parents)
                      for realm, other, _ in roots), path, "physical roots overlap; aggregate or remain unknown")
            physical_ids.add(domain_id)
            identities.add(identity)
            devices.add(device)
            roots.append((domain["realm"], root, domain["filesystem_id"]))
        check(reserved <= budget["hard_limit_bytes"], path, "physical reserves exceed existing capacity surface")
        expected = dict(schema_version=1, scope="i5-preparation-boundary-configuration-claim", uuid=apt.UUID,
                        nonce=nonce, manifest_sha256=manifest_sha256, capacity=value["capacity"], surface=name,
                        owner_domain=row["owner_domain"], charge=row["charge"], state=row["state"],
                        mechanism=budget["mechanism"], hard_limit_bytes=budget["hard_limit_bytes"],
                        components=row["components"], physical_domains=domains, configured_before_start=True)
        configured = fact(row["configuration"], "configuration." + name)
        check(json.dumps(configured, sort_keys=True, separators=(",", ":"), allow_nan=False) ==
              json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False),
              path + ".configuration", "configuration claim does not match exact existing boundary")
        observed = fact(row["observation"], "observation." + name)
        expected.update(scope="i5-preparation-boundary-observation-claim", configuration=row["configuration"], evidence_kind="injected-offline")
        check(json.dumps(observed, sort_keys=True, separators=(",", ":"), allow_nan=False) ==
              json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False),
              path + ".observation", "independent observation claim must bind configuration and same physical identity")
    for name, size in whole_devices.items():
        check(size <= ledger["domains"][name]["guest_device_bytes"], "coverage.domains." + name,
              "complete physical devices exceed existing D allocation")
    check(set(blobs) == used_blobs, "coverage.blobs", "exact fact set required; extra unbound facts rejected")
    blockers.append("physical identities, hard limits and independent observation provenance remain unverified")
    if value["backend"] == "macos-utm":
        blockers.append("macos-utm: host swap, crash and global logs lack a complete hard boundary; APFS volume quotas cannot close this gate")
    else:
        blockers.append("injected-offline: synthetic coverage cannot admit a native backend")
    result = report("i5-preparation-host-coverage-review", blockers, nonce, manifest_sha256,
                    backend=value["backend"], capacity=value["capacity"], complete_write_boundary=False,
                    feasibility="blocked-host-system-writes" if value["backend"] == "macos-utm" else "injected-offline-only",
                    authenticity_verified=False, execution_authorized=False)
    return result
