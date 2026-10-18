"""Deterministic native library artifact and unauthenticated fact binding.

Only caller-provided bytes are parsed, hashed or packaged. This module has no
CLI, file discovery, launcher, VM operation or APT runner. AST checks describe
reviewed static dependency shapes, not a proof that arbitrary Python is safe.
The legacy candidate contract stays an unmodified historical declaration.
"""

import ast
import io
import json
import stat
import zipfile

import sw_i5_apt as apt
import sw_i5_preparation_execution as execution
import sw_i5_preparation_isolation as isolation
import sw_i5_preparation_plan as plan
from sw_i5_preparation_rpc import validate_invocation_descriptor

SCOPE = "i5-preparation-native-binding-candidate"
BUNDLE_SCOPE = "i5-preparation-native-library-artifact"
NATIVE = "scripts/sw_i5_preparation_native.py"
BUILDER = "scripts/sw_i5_preparation_bundle.py"
TEST = "scripts/test_sw_i5_bundle.py"
NATIVE_TEST = "scripts/test_sw_i5_native.py"
RUNTIME = ("scripts/sw_i5_apt.py", "scripts/sw_i5_preparation_isolation.py",
           "scripts/sw_i5_resources.py", NATIVE)
EXTENSIONS = (NATIVE, BUILDER, TEST, NATIVE_TEST)
GUEST_ROLES = ("guest_root", "work", "result", "cgroup_parent", "cgroup_supervisor", "cgroup_worker",
               "control", "lease", "ack", "readonly_input")
HOST_ROLES = ("host_jxa_root", "host_evidence_parent", "host_attempt")
FALSE = dict.fromkeys(execution.FLAGS, False)
NATIVE_FALSE = dict(authorized=False, install_authorized=False, physical_verified=False, i5_ready=False)
POLICY = {
    "execution": "explicit-same-process-bootstrap-owner-call-only",
    "default_launcher": False,
    "automatic_main": False,
    "external_supervision": "caller-must-enforce-absolute-deadline-kill-and-reap-in-existing-phase-budgets",
    "task_boundary": "one-explicit-caller-callback-no-worker-isolation-or-native-apt-admission-implied",
    "cleanup": "finally-identity-bound-native-cleanup-with-independent-cleanup-deadline",
    "input": "native-tree-includes-by-hash-copies-manifest-digest-not-media-digest",
    "source_review": "fixed-static-import-shape-and-bytes-only-not-arbitrary-python-safety",
}
# This reviewed entry is bytes in the artifact, never compiled/imported here.
# The caller owns all supervision around this same-process function. A callback
# that blocks cannot be bounded by in-process deadline checks alone.
BOOTSTRAP = b'''"""Explicit same-process native owner; external kill/reap supervision required."""
from sw_i5_preparation_native import NativeGuestInitialization


def bootstrap_owner(contract_raw, manifest_raw, *, expected, deadline,
                    cleanup_deadline, register, task, syscalls=None):
    if not callable(register) or not callable(task):
        raise ValueError("explicit registration and single task callback required")
    owner = NativeGuestInitialization(contract_raw, manifest_raw,
                                      expected=expected, syscalls=syscalls)
    result = dict(outcome="failure", first_error=None, cleanup_errors=[],
                  initialization=None, independent_readback=None,
                  cleanup=None, task_calls=0,
                  execution_authorized=False, install_authorized=False,
                  physical_verified=False, i5_ready=False)
    try:
        result["initialization"] = owner.initialize(deadline=deadline, register=register)
        result["independent_readback"] = owner.readback(deadline=deadline)
        result["task_calls"] = 1
        task(owner, result["initialization"], result["independent_readback"])
        result["outcome"] = "success"
    except BaseException as exc:
        result["first_error"] = (type(exc).__name__ + ": " + str(exc))[:1536]
        result["outcome"] = "cancelled" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failure"
    finally:
        try:
            result["cleanup"] = owner.cleanup(deadline=cleanup_deadline, register=register)
            result["cleanup_errors"].extend(result["cleanup"]["errors"])
            if result["cleanup"]["pending"]:
                result["cleanup_errors"].append("native cleanup retains pending objects")
        except BaseException as exc:
            result["cleanup_errors"].append((type(exc).__name__ + ": " + str(exc))[:768])
        finally:
            try:
                owner.close()
            except BaseException as exc:
                result["cleanup_errors"].append((type(exc).__name__ + ": " + str(exc))[:768])
    if result["cleanup_errors"]:
        result["outcome"] = "failure"
        if result["first_error"] is None:
            result["first_error"] = "native cleanup failed; inspect cleanup_errors"
    return result
'''
ENTRY = "i5_bootstrap.py"
MANIFEST = "i5_bundle_manifest.json"
ZIP_LIMIT = 8 * apt.MIB
LIFECYCLE_SOURCE = "scripts/sw_i5_preparation_native_lifecycle.py"
LIFECYCLE_RUNTIME = RUNTIME + (LIFECYCLE_SOURCE, "scripts/sw_i5_preparation_supervisor.py", "scripts/sw_i5_preparation_channels.py")
LIFECYCLE_SCOPE = "i5-preparation-native-lifecycle-library-artifact"
DELIVERY_SCOPE = "i5-preparation-native-library-delivery-candidate"
INVOCATION_SCOPE = "i5-preparation-native-library-invocation"
LIBRARY_ROOT = "/opt/radishlink/i5-native-library"
DELIVERY_FILES = ("library.zip", "library-manifest.json", "isolation.json", "apt-manifest.json", "expected.json", "delivery.json")
LIFECYCLE_ENTRY = dict(module="sw_i5_preparation_native_lifecycle", function="run_native_guest")
BLOCKERS = (
    "library artifact and facts are consistency candidates, never native provenance authentication",
    "legacy core remains historical schema 1/native_backend absent; no consumer is upgraded",
    "external absolute-deadline kill/reap supervision and public lifecycle integration remain absent",
    "all current UTM/preparation-apt/I5-R entry points remain STOP",
    "physical limits, external tools, current authorization and real input authenticity remain unverified",
)


def same(left, right):
    return execution.same(left, right)


def checked_sources(sources):
    """Finite closure for the four native-library modules, including nested imports."""
    return _checked_sources(sources, RUNTIME, NATIVE)


def _checked_sources(sources, runtime, entry_source):
    execution.require(type(sources) is dict and set(sources) == set(runtime), "exact native runtime source closure")
    local = {name.removeprefix("scripts/").removesuffix(".py"): name for name in runtime}
    graph = {}
    for name in runtime:
        raw = sources[name]
        execution.require(type(raw) is bytes and 0 < len(raw) <= 2 * apt.MIB, "bounded immutable runtime source")
        try:
            tree = ast.parse(raw.decode("utf-8", "strict"), filename=name)
        except (UnicodeError, SyntaxError, RecursionError) as exc:
            raise ValueError("runtime source AST: " + name + ": " + str(exc)) from exc
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                execution.require(node.id not in {"exec", "eval", "compile", "__import__", "__builtins__", "globals", "locals"},
                                  "unreviewed dynamic runtime builtin")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                execution.require(not isinstance(node, ast.ImportFrom) or node.level == 0, "relative runtime import")
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for module in names:
                    root = module.split(".")[0]
                    execution.require(root != "importlib" and (root in local or root in execution.STDLIB),
                                      "unknown/dynamic runtime import: " + module)
                    if root in local:
                        execution.require(module == root, "unknown runtime local submodule")
                        imports.add(local[root])
            if isinstance(node, ast.Attribute):
                execution.require(node.attr not in {"exec", "eval", "compile", "__import__", "import_module", "run_path", "run_module",
                                                    "load_module", "spec_from_file_location", "module_from_spec", "exec_module"},
                                  "unreviewed dynamic runtime loader")
        graph[name] = sorted(imports)
    reachable, pending = set(), [entry_source]
    while pending:
        name = pending.pop()
        if name not in reachable:
            reachable.add(name)
            pending.extend(graph[name])
    execution.require(reachable == set(runtime), "unreachable/missing native runtime dependency")
    return graph


def zip_bytes(members):
    """Canonical library ZIP: no compression, executable main, timestamps or extras."""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, allowZip64=False) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, members[name])
    raw = stream.getvalue()
    execution.require(0 < len(raw) <= ZIP_LIMIT, "bounded native library ZIP")
    return raw


def assemble(sources):
    """Return manifest/program/bootstrap bytes without executing supplied sources."""
    graph = checked_sources(sources)
    members = {name.removeprefix("scripts/"): raw for name, raw in sources.items()}
    members[ENTRY] = BOOTSTRAP
    manifest = dict(schema_version=1, scope=BUNDLE_SCOPE, format="canonical-uncompressed-library-zip-v1",
                    runtime_sources={name: execution.fingerprint(sources[name]) for name in RUNTIME},
                    members={name: execution.fingerprint(raw) for name, raw in members.items()},
                    entry=dict(member=ENTRY, function="bootstrap_owner", source=execution.fingerprint(BOOTSTRAP)),
                    local_graph=graph, policy=dict(POLICY), **FALSE)
    manifest_raw = execution.encode(manifest)
    members[MANIFEST] = manifest_raw
    return dict(manifest=manifest_raw, program=zip_bytes(members), bootstrap=BOOTSTRAP)


def validate_artifact(manifest_raw, program, bootstrap, sources):
    """Exact byte comparison also rejects duplicate members and alternate ZIP metadata."""
    execution.require(type(program) is bytes and 0 < len(program) <= ZIP_LIMIT, "bounded immutable library program")
    expected = assemble(sources)
    execution.require(manifest_raw == expected["manifest"] and program == expected["program"] and
                      bootstrap == expected["bootstrap"], "native artifact is not the deterministic reviewed assembly")
    return dict(scope="i5-preparation-native-library-review", schema_version=1,
                program=execution.fingerprint(program), manifest=execution.fingerprint(manifest_raw),
                bootstrap=execution.fingerprint(bootstrap), consistency_passed=True,
                authenticity_verified=False, blockers=list(BLOCKERS), **FALSE)


def assemble_lifecycle(sources):
    """New finite guest closure; the historical four-source ZIP is unchanged."""
    graph = _checked_sources(sources, LIFECYCLE_RUNTIME, LIFECYCLE_SOURCE)
    members = {name.removeprefix("scripts/"): raw for name, raw in sources.items()}
    manifest = dict(schema_version=1, scope=LIFECYCLE_SCOPE, format="canonical-uncompressed-lifecycle-library-zip-v1",
        runtime_sources={name: execution.fingerprint(sources[name]) for name in LIFECYCLE_RUNTIME},
        members={name: execution.fingerprint(raw) for name, raw in members.items()}, local_graph=graph,
        entry=dict(LIFECYCLE_ENTRY), automatic_main=False, default_launcher=False,
        loading="fixed-readonly-fd-loader-not-implemented-or-verified", **FALSE)
    manifest_raw = execution.encode(manifest)
    members[MANIFEST] = manifest_raw
    return dict(manifest=manifest_raw, program=zip_bytes(members))


def validate_lifecycle_artifact(manifest_raw, program, sources):
    execution.require(type(program) is bytes and 0 < len(program) <= ZIP_LIMIT, "bounded immutable lifecycle library")
    expected = assemble_lifecycle(sources)
    execution.require(manifest_raw == expected["manifest"] and program == expected["program"],
                      "lifecycle library is not the exact deterministic reviewed assembly")
    return dict(schema_version=1, scope="i5-preparation-native-lifecycle-library-review", consistency_passed=True,
                program=execution.fingerprint(program), manifest=execution.fingerprint(manifest_raw),
                authenticity_verified=False, loader_verified=False, **FALSE)


def invocation_descriptor(delivery_raw):
    value = execution.decode(delivery_raw)
    execution.header(value, DELIVERY_SCOPE)
    execution.false_flags(value)
    return validate_invocation_descriptor(dict(schema_version=1, scope=INVOCATION_SCOPE, uuid=apt.UUID,
        nonce=value["nonce"], manifest_sha256=value["manifest_sha256"], delivery_sha256=execution.fingerprint(delivery_raw)["sha256"]),
        value["nonce"], value["manifest_sha256"])


def validate_delivery(raw, *, files, sources, plan_raw, capacity_raw, coverage_raw, coverage_blobs, descriptor):
    """Check immutable supplied bytes only; never mount, pin, import or run them.

    delivery.json contains references to the other five fixed members. The
    separately derived invocation hashes delivery.json, avoiding a self-hash.
    Real media loading and native origin remain external unverified obligations.
    """
    value = execution.decode(raw)
    execution.fields(value, "schema_version scope kind uuid nonce manifest_sha256 plan capacity host_coverage library_expected library_filesystem native_expected members " + " ".join(FALSE), "delivery")
    execution.header(value, DELIVERY_SCOPE)
    execution.false_flags(value)
    execution.require(value["kind"] == "offline-candidate", "offline delivery candidate required")
    nonce, manifest_hash = value["nonce"], value["manifest_sha256"]
    execution.require(apt.digest(manifest_hash), "delivery manifest digest")
    execution.require(type(files) is dict and set(files) == set(DELIVERY_FILES) and all(type(v) is bytes for v in files.values()),
                      "exact six immutable library delivery files required")
    execution.bounded_inputs(dict(files, plan=plan_raw, capacity=capacity_raw, coverage=coverage_raw, **coverage_blobs), sources)
    execution.require(files["delivery.json"] == raw, "delivery member must be the exact candidate bytes")
    execution.fields(value["members"], " ".join(DELIVERY_FILES[:-1]), "delivery members")
    for name in DELIVERY_FILES[:-1]:
        execution.blob(value["members"][name], "delivery member " + name)
        execution.require(value["members"][name] == execution.fingerprint(files[name]), "delivery member fingerprint mismatch: " + name)
    for name, provided in (("plan", plan_raw), ("capacity", capacity_raw), ("host_coverage", coverage_raw)):
        execution.blob(value[name], "delivery " + name)
        execution.require(value[name] == execution.fingerprint(provided), "delivery raw binding: " + name)
    validated = validate_lifecycle_artifact(files["library-manifest.json"], files["library.zip"], sources)
    initialization = plan.decode(plan_raw, "i5-review-initialization")
    plan.review(plan_raw, capacity_raw, nonce, manifest_hash)
    execution.require(initialization["capacity_sha256"] == value["capacity"]["sha256"], "delivery plan/capacity mismatch")
    coverage = plan.review_host_coverage(coverage_raw, capacity_raw, nonce, manifest_hash, blobs=coverage_blobs)
    tree_manifest = apt.validate_manifest(files["apt-manifest.json"], nonce)
    execution.require(execution.fingerprint(files["apt-manifest.json"])["sha256"] == manifest_hash, "delivery actual APT manifest mismatch")
    contract = isolation.Contract.parse(files["isolation.json"], nonce, manifest_hash)
    execution.require(str(contract.root) == initialization["objects"]["guest_root"]["path"] and
        str(contract.input) == initialization["readonly_input"]["path"] and contract.uid == initialization["guest_uid"] and contract.gid == initialization["guest_gid"],
        "delivery native contract differs from reviewed plan")
    native_expected = execution.decode(files["expected.json"])
    execution.fields(native_expected, "root_parent cgroup_root readonly_input", "delivery native expected")
    execution.require(same(native_expected, value["native_expected"]), "delivery actual native expected mismatch")
    execution.fields(value["library_expected"], "dev ino mount_id", "delivery library expected")
    native_ids, devices, mounts = set(), set(), set()
    for identity in list(native_expected.values()) + [value["library_expected"]]:
        execution.fields(identity, "dev ino mount_id", "delivery expected identity")
        for name in identity: execution.integer(identity[name], "delivery expected " + name, 1)
        native_ids.add((identity["dev"], identity["ino"]))
        devices.add(identity["dev"])
        mounts.add(identity["mount_id"])
    execution.require(len(native_ids) == len(devices) == len(mounts) == 4, "library and native prerequisite devices/mounts must be distinct")
    fs = value["library_filesystem"]
    execution.fields(fs, "path filesystem filesystem_magic mount_options super_options capacity_bytes inodes", "delivery library filesystem")
    execution.require(fs["path"] == LIBRARY_ROOT, "fixed library root required")
    magic = {"iso9660": 0x9660, "squashfs": 0x73717368}
    execution.require(type(fs["filesystem"]) is str and fs["filesystem"] in magic and type(fs["filesystem_magic"]) is int and fs["filesystem_magic"] == magic[fs["filesystem"]],
                      "library requires immutable readonly media")
    for name in ("mount_options", "super_options"):
        options = fs[name]
        execution.require(type(options) is list and all(type(x) is str and 0 < len(x) <= 256 for x in options) and options == sorted(set(options)) and
            "ro" in options and "rw" not in options, "library readonly mount/super options")
    execution.integer(fs["capacity_bytes"], "library whole filesystem bytes", 1, 256 * apt.MIB)
    execution.integer(fs["inodes"], "library filesystem inodes", 6)
    file_bytes = sum(map(len, files.values()))
    execution.require(file_bytes <= fs["capacity_bytes"], "all six library files, including delivery itself, must fit the complete media")
    declaration = execution.decode(coverage_raw)
    input_row = declaration["surfaces"]["readonly_input"]
    execution.require(input_row["state"] == "bounded", "delivery requires both input media physical declarations")
    library_part = input_row["components"]["library_media"]
    library_domain = input_row["physical_domains"][library_part["physical_domain"]]
    execution.require(all(same(library_domain[key], value["library_expected"][key]) for key in ("dev", "ino", "mount_id")) and
                      library_domain["path"] == LIBRARY_ROOT and library_domain["whole_device_bytes"] >= fs["capacity_bytes"] and
                      library_domain["hard_reserve_bytes"] >= fs["capacity_bytes"] and library_part["logical_bytes"] >= fs["capacity_bytes"],
                      "library identity and complete media bytes must bind existing input D")
    apt_part = input_row["components"]["apt_media"]
    apt_domain = input_row["physical_domains"][apt_part["physical_domain"]]
    execution.require(all(same(apt_domain[key], native_expected["readonly_input"][key]) for key in ("dev", "ino", "mount_id")) and
                      apt_domain["path"] == str(contract.input), "APT media identity differs from native expected input")
    input_files = dict(tree_manifest["files"])
    for source in apt.SOURCES.values():
        _, index, _ = apt.source_paths(source)
        item = input_files[index]
        input_files[index.rsplit("/", 1)[0] + "/by-hash/SHA256/" + item["sha256"]] = dict(item)
    input_tree_bytes = sum(item["bytes"] for item in input_files.values())
    input_image_bytes = initialization["readonly_input"]["bytes"]
    execution.require(input_tree_bytes <= input_image_bytes <= min(apt_domain["whole_device_bytes"], apt_domain["hard_reserve_bytes"], apt_part["logical_bytes"]),
                      "complete APT tree and by-hash copies must fit the input image and full input D allocation")
    execution.require(apt_domain["whole_device_bytes"] <= min(apt_domain["hard_reserve_bytes"], apt_part["logical_bytes"]),
                      "the complete APT device, not only its payload, must fit hard and logical reserves")
    for surface, component, size in (("input_media_creation", "library_media_creation", fs["capacity_bytes"]),
            ("input_media_staging_copy", "library_media_staging", fs["capacity_bytes"]),
            ("input_media_creation", "apt_media_creation", apt_domain["whole_device_bytes"]),
            ("input_media_staging_copy", "apt_media_staging", apt_domain["whole_device_bytes"])):
        part = declaration["surfaces"][surface]["components"][component]
        execution.require(declaration["surfaces"][surface]["state"] == "bounded" and part["logical_bytes"] >= size,
                          "complete media creation/staging copy must be independently charged: " + component)
    root_row = declaration["surfaces"]["guest_system_tmpfs"]
    execution.require(root_row["state"] == "bounded", "native root requires bounded system tmpfs")
    root_part = root_row["components"]["initialization_root"]
    root_domain = root_row["physical_domains"][root_part["physical_domain"]]
    execution.require(all(same(root_domain[key], native_expected["root_parent"][key]) for key in ("dev", "ino", "mount_id")) and
        root_domain["path"] == "/run/radishlink-i5-preparation" and root_domain["hard_reserve_bytes"] == isolation.NATIVE_ROOT_BYTES and
        root_part["logical_bytes"] >= isolation.NATIVE_ROOT_BYTES and root_domain["inode_limit"] == isolation.NATIVE_ROOT_INODES and
        all(name == "initialization_root" or part["physical_domain"] != root_part["physical_domain"] for name, part in root_row["components"].items()),
        "native root expected identity and complete byte/inode reserve must bind its independent system tmpfs domain")
    assembly = declaration["surfaces"]["host_jxa_source"]["components"]["library_source_assembly"]
    jxa = declaration["surfaces"]["host_jxa_source"]["components"]["jxa_source"]
    source_bytes = sum(map(len, sources.values()))
    # The immutable sources, uncompressed member bytes, ZIP output and six-file
    # delivery coexist in the conservative assembler model. No phase max trick.
    assembly_peak = source_bytes + source_bytes + len(files["library-manifest.json"]) + len(files["library.zip"]) + file_bytes
    execution.require(declaration["surfaces"]["host_jxa_source"]["state"] == "bounded" and
        assembly["logical_bytes"] >= source_bytes and assembly["peak_bytes"] >= assembly_peak, "library source/ZIP/member/delivery concurrent assembly peak undercount")
    execution.require(jxa["logical_bytes"] >= initialization["jxa_source"]["bytes"] and
        jxa["peak_bytes"] >= plan.assembled_source_bound(initialization["jxa_source"]["bytes"]), "JXA component cannot borrow the library assembly reservation")
    checked_descriptor = validate_invocation_descriptor(descriptor, nonce, manifest_hash)
    execution.require(same(checked_descriptor, invocation_descriptor(raw)), "invocation must reference exact delivery bytes")
    return dict(schema_version=1, scope="i5-preparation-native-library-delivery-review", nonce=nonce, uuid=apt.UUID,
        consistency_passed=True, authenticity_verified=False, loader_verified=False, complete_write_boundary=False,
        delivery=execution.fingerprint(raw), descriptor=checked_descriptor, artifact=validated,
        config_fingerprints={name: execution.fingerprint(files[name]) for name in ("isolation.json", "apt-manifest.json", "expected.json")},
        library_file_bytes=file_bytes, library_assembly_peak_bytes=assembly_peak, host_feasibility=coverage["feasibility"],
        apt_tree_bytes=input_tree_bytes,
        blockers=coverage["review_blockers"] + ["fixed readonly FD loader and true media provenance remain unimplemented/unverified"], **FALSE)


def project_status(raw, expected):
    """Guest-side pure semantic projection; raw private status is never returned.

    The caller must perform the real bounded/identity-pinned guest read and
    pre/post baseline checks. A supplied digest cannot authenticate that read.
    """
    execution.blob(expected, "status", 16 * apt.MIB)
    execution.require(type(raw) is bytes and len(raw) <= 16 * apt.MIB and execution.fingerprint(raw) == expected,
                      "status bytes do not match bound guest baseline")
    installed = apt.installed_packages(raw)
    return execution.encode(dict(schema_version=1, scope="i5-preparation-status-projection", status=expected,
                                 installed=installed, source_authenticity_verified=False, **FALSE))


def validate_projection(raw, baseline):
    value = execution.decode(raw)
    execution.fields(value, "schema_version scope status installed source_authenticity_verified " + " ".join(FALSE), "status projection")
    execution.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                      value["scope"] == "i5-preparation-status-projection" and value["status"] == baseline["status"] and
                      value["source_authenticity_verified"] is False, "status projection baseline/scope")
    execution.false_flags(value)
    execution.require(type(value["installed"]) is dict and 0 < len(value["installed"]) <= 8192, "bounded installed semantic projection")
    # Reuse the same package/version parser, without requiring or reconstructing
    # the original private status database. This cannot prove its provenance.
    records = []
    for name, version in value["installed"].items():
        execution.require(type(name) is str and name.endswith(":arm64") and type(version) is str and
                          apt.version(version), "status projection package identity/version")
        records.append("Package: " + name.removesuffix(":arm64") + "\nArchitecture: arm64\nStatus: install ok installed\nVersion: " + version + "\n")
    execution.require(same(apt.installed_packages("\n".join(records).encode()), value["installed"]), "invalid installed semantic projection")
    return value


def native_header(value, scope, nonce, manifest_hash):
    execution.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["scope"] == scope and
                      value["uuid"] == apt.UUID and value["nonce"] == nonce and value["manifest_sha256"] == manifest_hash,
                      "native fact scope/run binding")
    for name in NATIVE_FALSE:
        execution.require(value[name] is False, "native candidate flag must remain false: " + name)


def native_objects(value, initialization, manifest_raw, expected):
    """Bind native readbacks; readonly tree uses its own manifest/tree semantics."""
    nonce, manifest_hash = initialization["nonce"], execution.fingerprint(manifest_raw)["sha256"]
    execution.fields(value, "schema_version scope uuid nonce manifest_sha256 backend_kind objects input_bytes input_files_sha256 cgroup_snapshots prerequisite_observations " +
                     " ".join(NATIVE_FALSE), "native initialization")
    native_header(value, "i5-preparation-native-initialization", nonce, manifest_hash)
    execution.require(value["backend_kind"] in ("kernel", "injected-offline"), "explicit native backend kind")
    execution.fields(value["objects"], " ".join(GUEST_ROLES), "native guest objects")
    execution.integer(value["input_bytes"], "native input tree bytes", 1, 256 * apt.MIB)
    execution.require(apt.digest(value["input_files_sha256"]), "native input file inventory digest")
    files = dict(apt.validate_manifest(manifest_raw, nonce)["files"])
    for source in apt.SOURCES.values():
        _, index, _ = apt.source_paths(source)
        item = files[index]
        files[index.rsplit("/", 1)[0] + "/by-hash/SHA256/" + item["sha256"]] = dict(item)
    execution.require(value["input_bytes"] == sum(item["bytes"] for item in files.values()) and
                      value["input_files_sha256"] == execution.fingerprint(execution.encode(files))["sha256"],
                      "native full input inventory/bytes mismatch")
    specs = plan.object_specs(initialization)
    specs["readonly_input"] = dict(specs["readonly_input"], bytes=value["input_bytes"], sha256=manifest_hash)
    identities = set()
    for role in GUEST_ROLES:
        row = value["objects"][role]
        execution.fields(row, "before after independent_readback", "native object." + role)
        execution.require(row["before"] is not None if role == "readonly_input" else row["before"] is None,
                          "native fresh/bound object policy")
        for phase, observer in (("before", "preexisting-observer"), ("after", "creator"), ("independent_readback", "independent-reader")):
            snapshot = row[phase]
            if snapshot is None:
                execution.require(phase == "before" and role != "readonly_input", "missing native initialization observation")
                continue
            ident = plan.observation(snapshot, specs[role], role, nonce, manifest_hash, "native." + role + "." + phase)
            execution.require(snapshot["observer"] == observer, "native observation reader/creator role")
        comparable = lambda snapshot: {k: v for k, v in snapshot.items() if k != "observer"}
        execution.require(same(comparable(row["after"]), comparable(row["independent_readback"])), "native independent identity/readback changed")
        if role == "readonly_input":
            execution.require(same(comparable(row["before"]), comparable(row["after"])), "bound readonly input changed")
        execution.require(ident not in identities, "native guest object identity alias")
        identities.add(ident)
    execution.fields(value["cgroup_snapshots"], "parent supervisor worker", "native raw cgroup snapshots")
    for kind, raw_snapshot in value["cgroup_snapshots"].items():
        snapshot = dict(raw_snapshot)
        execution.require(type(snapshot["identity"]) is list and len(snapshot["identity"]) == 2 and
                          all(type(n) is int and n > 0 for n in snapshot["identity"]), "native raw cgroup identity integers")
        observed = value["objects"]["cgroup_" + kind]["independent_readback"]
        execution.require(snapshot["path"] == observed["path"] and same(snapshot["identity"], [observed["dev"], observed["ino"]]),
                          "native raw cgroup path/identity binding")
        for counter_name in ("events", "memory_events", "pids_events"):
            counters = snapshot[counter_name]
            execution.require(type(counters) is dict and len(counters) <= 32 and
                              all(type(k) is str and type(n) is int and 0 <= n < 2**63 for k, n in counters.items()),
                              "native raw cgroup strict counters")
        execution.require(snapshot["procs"] == [] and snapshot["events"].get("populated") == 0, "native initial cgroup must be empty/reaped")
        snapshot["identity"] = tuple(snapshot["identity"])
        isolation.verify_cgroup(snapshot, kind)
    native_prerequisites(value["prerequisite_observations"], expected, initialization, value["objects"]["readonly_input"])
    for role in GUEST_ROLES[:-1]:
        parent_role = "cgroup_root" if role.startswith("cgroup_") else "root_parent"
        execution.require(value["objects"][role]["after"]["dev"] == expected[parent_role]["dev"],
                          "native created object uses another prerequisite device")
    execution.require(value["input_bytes"] <= value["prerequisite_observations"]["readonly_input"]["capacity_bytes"],
                      "native input tree exceeds observed filesystem capacity")
    return identities


def native_prerequisites(observations, expected, initialization, input_object):
    roles = "root_parent cgroup_root readonly_input"
    execution.fields(expected, roles, "native expected identities")
    execution.fields(observations, roles, "native prerequisite raw observations")
    paths = dict(root_parent="/run/radishlink-i5-preparation", cgroup_root="/sys/fs/cgroup/radishlink-i5-preparation",
                 readonly_input=initialization["readonly_input"]["path"])
    identities, devices, mounts = set(), set(), set()
    for role in roles.split():
        identity, row = expected[role], observations[role]
        execution.fields(identity, "dev ino mount_id", "native expected prerequisite")
        for name in identity: execution.integer(identity[name], "native expected." + name, 1)
        execution.fields(row, "dev ino mount_id path device filesystem filesystem_magic mount_options super_options capacity_bytes inodes", "native prerequisite")
        execution.require(all(same(row[name], identity[name]) for name in identity), "native prerequisite expected identity mismatch")
        execution.require(row["path"] == paths[role], "native prerequisite path mismatch")
        execution.integer(row["filesystem_magic"], "native prerequisite filesystem magic", 1)
        execution.require((identity["dev"], identity["ino"]) not in identities, "native prerequisite identity alias")
        identities.add((identity["dev"], identity["ino"]))
        devices.add(identity["dev"])
        mounts.add(identity["mount_id"])
        dev = identity["dev"]
        major, minor = ((dev >> 8) & 0xfff) | ((dev >> 32) & ~0xfff), (dev & 0xff) | ((dev >> 12) & ~0xff)
        execution.require(row["device"] == str(major) + ":" + str(minor), "native Linux device/mount binding")
        for name in ("mount_options", "super_options"):
            options = row[name]
            execution.require(type(options) is list and len(options) <= 128 and
                              all(type(option) is str and 0 < len(option) <= 256 for option in options) and options == sorted(set(options)),
                              "bounded unique native mount options")
        mount, super_options = set(row["mount_options"]), set(row["super_options"])
        if role == "cgroup_root":
            execution.require(row["filesystem"] == "cgroup2" and row["filesystem_magic"] == 0x63677270 and
                              "rw" in mount and "rw" in super_options and row["capacity_bytes"] is None and row["inodes"] is None,
                              "native cgroup prerequisite must be actual cgroup2 claim")
        else:
            execution.integer(row["capacity_bytes"], "native prerequisite capacity", 1, apt.MIB if role == "root_parent" else 256 * apt.MIB)
            execution.integer(row["inodes"], "native prerequisite inodes", 1, 1024 if role == "root_parent" else 2**63 - 1)
            if role == "root_parent":
                execution.require(row["filesystem"] == "tmpfs" and row["filesystem_magic"] == 0x01021994 and
                                  {"rw", "nosuid", "nodev", "noexec"} <= mount and {"rw", "noswap"} <= super_options and
                                  "ro" not in mount | super_options, "native bounded noswap root prerequisite")
            else:
                magic = {"iso9660": 0x9660, "squashfs": 0x73717368}
                execution.require(row["filesystem"] in magic and row["filesystem_magic"] == magic[row["filesystem"]] and
                                  "ro" in mount and "ro" in super_options and "rw" not in mount | super_options and
                                  same([row["dev"], row["ino"]], [input_object["after"]["dev"], input_object["after"]["ino"]]),
                                  "native immutable readonly input prerequisite")

    execution.require(len(devices) == len(mounts) == 3, "three distinct native prerequisite devices/mounts required")


def native_capacity(observations, capacity):
    root = capacity["surfaces"]["guest_system_tmpfs"]
    execution.require(root["state"] == "bounded", "native root parent requires a declared bounded tmpfs reserve")
    for key in ("hard_limit_bytes", "logical_bytes"):
        execution.integer(root[key], "declared system tmpfs." + key, 1)
        execution.require(observations["root_parent"]["capacity_bytes"] <= root[key],
                          "native root parent exceeds declared environment tmpfs reserve")
    domain = capacity["domains"]["input"]
    for key in ("guest_device_bytes", "cap_bytes"):
        execution.integer(domain[key], "declared input domain." + key, 1)
        execution.require(observations["readonly_input"]["capacity_bytes"] <= domain[key],
                          "native input filesystem exceeds declared input domain/device")


def host_objects(value, initialization):
    execution.fields(value, "schema_version scope uuid nonce manifest_sha256 evidence_kind objects " + " ".join(NATIVE_FALSE), "host initialization")
    native_header(value, "i5-preparation-host-initialization-facts", initialization["nonce"], initialization["manifest_sha256"])
    execution.require(value["evidence_kind"] in ("native-claim-unverified", "injected-offline"), "explicit host observation provenance claim")
    execution.fields(value["objects"], " ".join(HOST_ROLES), "provided host initialization objects")
    identities, specs = set(), plan.object_specs(initialization)
    for role in HOST_ROLES:
        row = value["objects"][role]
        execution.fields(row, "before after independent_readback", "host object." + role)
        execution.require((row["before"] is not None) == (role == "host_evidence_parent"), "host fresh/bound policy")
        for phase, observer in (("before", "preexisting-observer"), ("after", "creator"), ("independent_readback", "independent-reader")):
            snapshot = row[phase]
            if snapshot is None:
                execution.require(phase == "before" and role != "host_evidence_parent", "missing host initialization observation")
                continue
            ident = plan.observation(snapshot, specs[role], role, initialization["nonce"], initialization["manifest_sha256"], "host." + role)
            execution.require(snapshot["observer"] == observer, "host creator/independent reader role")
        comparable = lambda snapshot: {k: v for k, v in snapshot.items() if k != "observer"}
        execution.require(same(comparable(row["after"]), comparable(row["independent_readback"])), "host identity/readback changed")
        if role == "host_evidence_parent":
            execution.require(same(comparable(row["before"]), comparable(row["after"])), "host bound parent changed")
        execution.require(ident not in identities, "host object identity alias")
        identities.add(ident)
    return identities


def validate_binding(raw, core_raw, blobs, sources, *, now):
    """Validate separate native/artifact facts, never upgrade the legacy core.

    Complete native/host observations are required. Failed or partial native
    initialization belongs in its original failure record, not a fabricated
    thirteen-object binding. No lifecycle events or cgroup values are invented.
    """
    execution.bounded_inputs(blobs, sources)
    value = execution.decode(raw)
    names = "native_contract bundle_manifest program bootstrap native_initialization native_readback native_cleanup host_initialization status_projection"
    execution.fields(value, "schema_version scope uuid nonce core source_extensions native_expected " + names + " " + " ".join(FALSE), "native binding")
    execution.header(value, SCOPE)
    execution.false_flags(value)
    execution.require(value["core"] == execution.fingerprint(core_raw), "historical core bytes changed")
    core = execution.decode(core_raw)
    legacy_names = set(execution.PYTHON_SOURCES) | {execution.JXA, execution.VALIDATOR} | set(execution.REVIEW_TESTS)
    execution.require(set(sources) == legacy_names | set(EXTENSIONS), "exact legacy plus native extension sources")
    execution.fields(value["source_extensions"], " ".join(EXTENSIONS), "native source extensions")
    for name in EXTENSIONS:
        execution.blob(value["source_extensions"][name], "source extension " + name, 2 * apt.MIB)
        execution.require(value["source_extensions"][name]["bytes"] > 0, "nonempty source extension")
        execution.require(same(value["source_extensions"][name], execution.fingerprint(sources[name])), "native extension source bytes changed: " + name)
    core_blobs = set(execution.PAYLOADS) | {"preboot." + name for name, row in core["preboot"].items() if row["evidence"] is not None}
    execution.require(set(blobs) == core_blobs | set(names.split()), "exact binding blobs; raw private database export forbidden")
    review = execution.validate_contract(core_raw, {k: blobs[k] for k in core_blobs},
                                         {k: sources[k] for k in legacy_names}, now=now)
    execution.require(value["nonce"] == core["nonce"], "binding/core nonce mismatch")
    execution.require(value["program"] == core["inputs"]["program"] and value["bootstrap"] == core["inputs"]["bootstrap"],
                      "historical core must bind the actual assembled program/bootstrap bytes")
    payloads = {name: execution.bound_payload(name, value[name], blobs) for name in names.split()}
    validate_artifact(payloads["bundle_manifest"], payloads["program"], payloads["bootstrap"], {k: sources[k] for k in RUNTIME})
    initialization = execution.decode(blobs["plan"])
    initialized, readback = (execution.decode(payloads[k]) for k in ("native_initialization", "native_readback"))
    declared_contract = isolation.Contract.parse(payloads["native_contract"], value["nonce"], initialization["manifest_sha256"])
    execution.require(str(declared_contract.root) == initialization["objects"]["guest_root"]["path"] and
                      str(declared_contract.input) == initialization["readonly_input"]["path"] and
                      declared_contract.uid == initialization["guest_uid"] and declared_contract.gid == initialization["guest_gid"],
                      "native constructor contract differs from reviewed initialization")
    native_objects(initialized, initialization, blobs["manifest"], value["native_expected"])
    native_objects(readback, initialization, blobs["manifest"], value["native_expected"])
    execution.require(same(initialized, readback), "native independent full readback changed")
    native_capacity(readback["prerequisite_observations"], execution.decode(blobs["capacity"]))
    host_objects(execution.decode(payloads["host_initialization"]), initialization)
    cleanup = execution.decode(payloads["native_cleanup"])
    execution.fields(cleanup, "schema_version scope uuid nonce manifest_sha256 backend_kind errors pending cleaned " + " ".join(NATIVE_FALSE), "native cleanup")
    native_header(cleanup, "i5-preparation-native-cleanup", value["nonce"], initialization["manifest_sha256"])
    execution.require(cleanup["backend_kind"] == initialized["backend_kind"], "native cleanup backend mismatch")
    execution.require(type(cleanup["errors"]) is list and len(cleanup["errors"]) <= 32 and
                      all(type(x) is str and 0 < len(x.encode()) <= 768 for x in cleanup["errors"]), "bounded native cleanup errors")
    execution.require(type(cleanup["pending"]) is dict and type(cleanup["cleaned"]) is list and
                      all(type(x) is str for x in cleanup["cleaned"]) and len(cleanup["cleaned"]) == len(set(cleanup["cleaned"])),
                      "explicit unique native cleanup accounting")
    created = set(GUEST_ROLES) - {"readonly_input"}
    execution.require(set(cleanup["pending"]).isdisjoint(cleanup["cleaned"]) and
                      set(cleanup["pending"]) | set(cleanup["cleaned"]) == created, "native cleanup exact created roles; bound input preserved")
    clean_order = tuple(reversed(GUEST_ROLES[:-1]))
    execution.require(cleanup["cleaned"] == [role for role in clean_order if role in cleanup["cleaned"]],
                      "native cleanup order must follow identity-bound reverse creation")
    for role, row in cleanup["pending"].items():
        execution.fields(row, "state identity", "pending native object")
        expected = initialized["objects"][role]["after"]
        execution.require(type(row["identity"]) is list and len(row["identity"]) == 2 and
                          all(type(n) is int and n > 0 for n in row["identity"]), "strict pending identity integers")
        execution.require(row["state"] == "bound" and same(row["identity"], [expected["dev"], expected["ino"]]),
                          "native pending object identity changed")
    validate_projection(payloads["status_projection"], review["baseline"])
    return dict(schema_version=1, scope="i5-preparation-native-binding-review", uuid=apt.UUID, nonce=value["nonce"],
                consistency_passed=True, authenticity_verified=False, legacy_core_upgraded=False,
                complete_object_observations=13, native_backend_kind=initialized["backend_kind"],
                cleanup_complete=not cleanup["errors"] and not cleanup["pending"],
                cleanup_errors=cleanup["errors"], pending_objects=cleanup["pending"],
                blockers=list(BLOCKERS) + review["blockers"], **FALSE)


assemble = execution.malformed_as_value_error(assemble)
validate_artifact = execution.malformed_as_value_error(validate_artifact)
assemble_lifecycle = execution.malformed_as_value_error(assemble_lifecycle)
validate_lifecycle_artifact = execution.malformed_as_value_error(validate_lifecycle_artifact)
invocation_descriptor = execution.malformed_as_value_error(invocation_descriptor)
validate_delivery = execution.malformed_as_value_error(validate_delivery)
project_status = execution.malformed_as_value_error(project_status)
validate_binding = execution.malformed_as_value_error(validate_binding)
