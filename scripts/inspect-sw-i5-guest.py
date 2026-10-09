#!/usr/bin/env python3
"""Read-only Linux inventory for the I5 preparation VM, not I5 acceptance.

Guest mode runs through the agent with python3 -I -B and writes JSON to stdout
only. The macOS --collect-utm mode saves bounded local preparation evidence.
--details selects a separate scope for package, mount, swap and service facts;
it does not extend the original inventory schema or certify capacity/readiness.
Boot/shutdown may write system state independently of this probe. No credentials,
machine-id contents, host keys, process arguments or user files are collected.
"""

import argparse
import base64
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys


PACKAGES = (
    "python3", "qemu-guest-agent", "docker.io", "docker-ce", "docker-ce-cli",
    "containerd", "containerd.io", "runc", "golang-go", "golang-1.26-go",
    "util-linux", "e2fsprogs",
)
TOOLS = ("go", "docker", "dockerd", "containerd", "runc", "mkfs.ext4", "unshare", "mount")
TOOL_DIRS = ("/usr/local/go/bin", "/usr/local/bin", "/usr/bin", "/usr/sbin", "/bin", "/sbin")
MAX_RESULT_BYTES = 128 * 1024
MAX_TRANSPORT_BYTES = 512 * 1024
DETAILS_RESULT_BYTES = 512 * 1024
DETAILS_TRANSPORT_BYTES = 2 * 1024 * 1024
DETAILS_COMMAND_STDOUT_BYTES = 256 * 1024
DETAILS_PACKAGE_TABLE_STDOUT_BYTES = 512 * 1024
DETAILS_COMMAND_STDERR_BYTES = 8192
DETAILS_SCOPE = "guest-preparation-details"
PACKAGE_FIELDS = (
    "binary:Package", "Version", "Architecture", "Status", "Essential", "Protected",
    "Multi-Arch", "Pre-Depends", "Depends", "Recommends", "Suggests", "Conflicts",
    "Breaks", "Replaces", "Provides", "Installed-Size",
)
DETAIL_TOOLS = ("apt-get", "dpkg", "dpkg-query", "gpgv", "sqv")
SERVICE_UNITS = ("docker.service", "docker.socket", "containerd.service", "containerd.socket")
SERVICE_FIELDS = ("Id", "LoadState", "ActiveState", "SubState", "UnitFileState")
UTM_UUID = "B86E1A47-9A67-4ECF-A51F-2B2F29CDB726"
UTM_NAME = "RadishLink-I5-Debian13-ARM64"


def read(path):
    return Path(path).read_text(encoding="utf-8").strip()


def require_loopback_only():
    interfaces = sorted(p.name for p in Path("/sys/class/net").iterdir())
    if interfaces != ["lo"]:
        raise RuntimeError("loopback-only network required; stop inventory and shut down guest")
    return interfaces


def landlock_abi():
    if platform.machine() not in {"aarch64", "x86_64"}:
        return {"supported_architecture": False}
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(ctypes.c_long(444), ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    if result < 0:
        code = ctypes.get_errno()
        return {"abi": None, "errno": code, "error": errno.errorcode.get(code, "UNKNOWN")}
    return {"abi": result, "meets_build_minimum": result >= 5}


def package_inventory():
    command = ["/usr/bin/dpkg-query", "-W", "-f=${binary:Package}\t${Version}\t${db:Status-Status}\n", *PACKAGES]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}, check=False)
    # Exit 1 is normal for a request including absent packages. Keep stderr and
    # status instead of reporting missing software as installed or suppressing it.
    if result.returncode not in {0, 1}:
        raise RuntimeError("dpkg-query failed: " + result.stderr.strip())
    return {"exit_code": result.returncode, "rows": result.stdout.splitlines(),
            "diagnostic": result.stderr.splitlines()}


def inventory(nonce):
    if platform.system() != "Linux":
        raise RuntimeError("Linux guest required")
    # Reject before reading other guest facts or invoking dpkg-query.
    interfaces = require_loopback_only()
    release = {}
    for line in read("/etc/os-release").splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"ID", "VERSION_ID", "PRETTY_NAME"}:
            release[key] = value.strip('"')
    devices = []
    for path in sorted(Path("/sys/block").iterdir()):
        devices.append({"name": path.name, "bytes": int(read(path / "size")) * 512,
                        "read_only": read(path / "ro") == "1"})
    root = os.statvfs("/")
    tools = {}
    for name in TOOLS:
        tools[name] = sorted({str(p.resolve()) for directory in TOOL_DIRS
                              if (p := Path(directory) / name).is_file() and os.access(p, os.X_OK)})
    # Do not invoke Go/Docker/toolchain executables, which can have startup
    # writes. Package versions and executable presence are distinct evidence.
    caps = {}
    for line in read("/proc/self/status").splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"CapEff", "CapPrm", "NoNewPrivs", "Seccomp"}:
            caps[key] = value.strip()
    memory = {}
    for line in read("/proc/meminfo").splitlines():
        key, _, value = line.partition(":")
        if key in {"MemTotal", "MemAvailable", "SwapTotal"}:
            memory[key] = value.strip()
    result = {
        "schema_version": 1, "scope": "guest-preparation-inventory", "nonce": nonce,
        "i5_ready": False, "os": release, "kernel": platform.release(),
        "architecture": platform.machine(), "python": platform.python_version(),
        "uid": os.getuid(), "euid": os.geteuid(), "process_security": caps,
        "landlock": landlock_abi(), "memory": memory, "block_devices": devices,
        "root_available_bytes": root.f_bavail * root.f_frsize,
        "network_interfaces": interfaces, "loopback_only": interfaces == ["lo"],
        "ipv4_routes": read("/proc/net/route").splitlines(),
        "ipv6_routes": read("/proc/net/ipv6_route").splitlines(),
        "packages": package_inventory(), "tool_executables": tools,
        "machine_id_nonempty": Path("/etc/machine-id").is_file() and Path("/etc/machine-id").stat().st_size > 0,
        "ssh_public_host_key_count": len(list(Path("/etc/ssh").glob("ssh_host_*_key.pub"))),
        "identity_regeneration_verified": False,
    }
    # Detect changes during collection. This is a snapshot check, not network
    # isolation: removing every VM NIC before boot remains a prerequisite.
    require_loopback_only()
    return result


def details_command(argv, *, operation, allowed=(0,)):
    # Output acceptance limits, not a claim of subprocess memory isolation.
    if operation not in {"package-table", "tool-ownership", "service-state"}:
        raise ValueError("unknown details operation")
    result = subprocess.run(argv, capture_output=True, timeout=8, check=False,
                            env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                                 "SYSTEMD_PAGER": "", "SYSTEMD_COLORS": "0"})
    stdout_bytes, stderr_bytes = len(result.stdout), len(result.stderr)
    stdout_limit = DETAILS_PACKAGE_TABLE_STDOUT_BYTES if operation == "package-table" else DETAILS_COMMAND_STDOUT_BYTES
    exceeded = [name for name, size, limit in (
        ("stdout", stdout_bytes, stdout_limit),
        ("stderr", stderr_bytes, DETAILS_COMMAND_STDERR_BYTES),
    ) if size > limit]
    if exceeded:
        # Report counts before decoding, without echoing oversized contents or
        # dynamic command arguments. A failed command remains a failed command.
        raise RuntimeError(Path(argv[0]).name + " output exceeds details limit; " +
                           f"operation={operation}; exceeded={','.join(exceeded)}; " +
                           f"stdout_bytes={stdout_bytes}; stdout_limit={stdout_limit}; " +
                           f"stderr_bytes={stderr_bytes}; stderr_limit={DETAILS_COMMAND_STDERR_BYTES}; " +
                           f"exit_code={result.returncode}")
    if result.returncode not in allowed or result.stderr:
        raise RuntimeError(Path(argv[0]).name + " failed: exit=" + str(result.returncode) +
                           "; " + result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8"), result.returncode


def read_details(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise RuntimeError(str(path) + " exceeds details read limit")
    return raw.decode("utf-8")


def package_details():
    output, _ = details_command(["/usr/bin/dpkg-query", "--no-pager", "-W",
                                "-f=" + "\\t".join("${" + f + "}" for f in PACKAGE_FIELDS) + "\\n"],
                               operation="package-table")
    rows = [line.split("\t") for line in output.splitlines()]
    result = {"fields": list(PACKAGE_FIELDS), "rows": rows}
    validate_packages(result)
    return result


def validate_packages(value):
    if not isinstance(value, dict) or set(value) != {"fields", "rows"} or \
            value["fields"] != list(PACKAGE_FIELDS) or not isinstance(value["rows"], list) or not value["rows"]:
        raise ValueError("invalid complete package table")
    identities = set()
    for row in value["rows"]:
        if not isinstance(row, list) or len(row) != len(PACKAGE_FIELDS) or \
                any(not isinstance(v, str) or any(ord(c) < 32 for c in v) for v in row):
            raise ValueError("invalid package row")
        identity = (row[0], row[2])
        if not row[0] or not row[3] or identity in identities:
            raise ValueError("empty or duplicate package identity/status")
        identities.add(identity)


def mount_details(text):
    mounts = []
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        left, right = before.split(), after.split()
        if not separator or len(left) < 6 or len(right) != 3:
            raise ValueError("invalid mountinfo record")
        if not left[0].isdigit() or not left[1].isdigit() or not re.fullmatch(r"[0-9]+:[0-9]+", left[2]):
            raise ValueError("invalid mountinfo identifiers")
        # Omit arbitrary super options and sources (e.g. network credentials).
        # Keep only capacity flags and local device sources. Escaped paths stay
        # escaped exactly as in proc; consumers must not unescape as shell code.
        source = right[1] if re.fullmatch(r"/dev/[A-Za-z0-9_./-]+", right[1]) else None
        if any(not re.fullmatch(r"(?:shared|master|propagate_from):[0-9]+|unbindable", f) for f in left[6:]):
            raise ValueError("unknown mount propagation field")
        flags = [sorted({f for f in options.split(",") if capacity_flag(f)}) for options in (left[5], right[2])]
        mounts.append({"id": int(left[0]), "parent": int(left[1]), "device": left[2],
                       "root": left[3], "target": left[4], "filesystem": right[0],
                       "device_source": source, "mount_flags": flags[0], "super_flags": flags[1],
                       "propagation": left[6:]})
    if not mounts or len({m["id"] for m in mounts}) != len(mounts):
        raise ValueError("empty or duplicate mountinfo")
    return mounts


def swap_details(text):
    lines = text.splitlines()
    if not lines or lines[0].split() != ["Filename", "Type", "Size", "Used", "Priority"]:
        raise ValueError("invalid swaps header")
    rows = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 5 or not fields[0].startswith("/") or fields[1] not in {"file", "partition"}:
            raise ValueError("invalid swaps row")
        size, used, priority = map(int, fields[2:])
        if size < 0 or used < 0 or used > size:
            raise ValueError("invalid swap capacity")
        rows.append({"path": fields[0], "type": fields[1], "size_kib": size,
                     "used_kib": used, "priority": priority})
    return rows


def service_details():
    text, code = details_command(["/usr/bin/systemctl", "show", "--all", "--no-pager",
                                  "--property=" + ",".join(SERVICE_FIELDS), *SERVICE_UNITS],
                                 operation="service-state", allowed=(0, 1))
    units = {}
    for block in text.strip().split("\n\n"):
        fields = {}
        for line in block.splitlines():
            key, sep, value = line.partition("=")
            if not sep or key not in SERVICE_FIELDS or key in fields:
                raise ValueError("invalid service property")
            fields[key] = value
        if set(fields) != set(SERVICE_FIELDS) or fields["Id"] in units:
            raise ValueError("incomplete or duplicate service record")
        units[fields["Id"]] = fields
    if set(units) != set(SERVICE_UNITS) or (code == 1 and not any(
            row["LoadState"] == "not-found" for row in units.values())):
        raise ValueError("incomplete or failed service query")
    return {"exit_code": code, "units": units,
            "policy_rc_d_present": os.path.lexists("/usr/sbin/policy-rc.d")}


def preparation_details(nonce):
    base = inventory(nonce)  # Reuse platform/network guard and original facts.
    packages = package_details()
    tools = {name: sorted({str(p.resolve()) for directory in TOOL_DIRS
                    if (p := Path(directory) / name).is_file() and os.access(p, os.X_OK)})
             for name in DETAIL_TOOLS}
    # Preserve dpkg ownership text, including diversions; do not guess a version
    # for an unmanaged binary or invoke the verifier/toolchain itself.
    paths = sorted({p for found in tools.values() for p in found})
    ownership = ""
    if paths:
        ownership, _ = details_command(["/usr/bin/dpkg-query", "--no-pager", "-S", *paths],
                                       operation="tool-ownership")
    mounts = mount_details(read_details("/proc/self/mountinfo"))
    swaps = swap_details(read_details("/proc/swaps"))
    filesystems = {}
    for path in ("/", "/var", "/tmp", "/run"):
        stat, space = os.stat(path), os.statvfs(path)
        filesystems[path] = {"device": f"{os.major(stat.st_dev)}:{os.minor(stat.st_dev)}",
                             "available_bytes": space.f_bavail * space.f_frsize}
    result = {"schema_version": 1, "scope": DETAILS_SCOPE, "nonce": nonce, "i5_ready": False,
              "base_inventory": base, "packages": packages, "tools": tools,
              "tool_ownership": ownership.splitlines(), "mounts": mounts, "swaps": swaps,
              "filesystems": filesystems, "services": service_details()}
    require_loopback_only()
    return result


def validate_details(raw, nonce):
    if len(raw) > DETAILS_RESULT_BYTES:
        raise ValueError("details exceeds 512 KiB")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    except RecursionError as exc:
        raise ValueError("details JSON nesting too deep") from exc
    fields = {"schema_version", "scope", "nonce", "i5_ready", "base_inventory", "packages", "tools",
              "tool_ownership", "mounts", "swaps", "filesystems", "services"}
    if not isinstance(result, dict) or set(result) != fields or type(result["schema_version"]) is not int or \
            result["schema_version"] != 1 or result["scope"] != DETAILS_SCOPE or \
            result["nonce"] != nonce or result["i5_ready"] is not False:
        raise ValueError("details scope/schema/fields/nonce mismatch")
    validate_result(json.dumps(result["base_inventory"]).encode(), nonce)
    validate_packages(result["packages"])
    for field in ("tools", "filesystems", "services"):
        if not isinstance(result[field], dict):
            raise ValueError("invalid details " + field)
    for field in ("tool_ownership", "mounts", "swaps"):
        if not isinstance(result[field], list):
            raise ValueError("invalid details " + field)
    if set(result["tools"]) != set(DETAIL_TOOLS) or set(result["filesystems"]) != {"/", "/var", "/tmp", "/run"}:
        raise ValueError("incomplete tools/filesystems")
    if not result["mounts"] or set(result["services"]) != {"exit_code", "units", "policy_rc_d_present"} or \
            not isinstance(result["services"]["units"], dict) or \
            set(result["services"]["units"]) != set(SERVICE_UNITS):
        raise ValueError("incomplete mounts/services")
    for paths in result["tools"].values():
        if not isinstance(paths, list) or any(not plain_text(p) or not p.startswith("/") for p in paths):
            raise ValueError("invalid tool paths")
    if any(not plain_text(line) for line in result["tool_ownership"]):
        raise ValueError("invalid tool ownership")
    for value in result["filesystems"].values():
        typed_record(value, {"device": str, "available_bytes": int}, "filesystem")
        if not re.fullmatch(r"[0-9]+:[0-9]+", value["device"]) or value["available_bytes"] < 0:
            raise ValueError("invalid filesystem device/capacity")
    mount_ids = set()
    for value in result["mounts"]:
        typed_record(value, {"id": int, "parent": int, "device": str, "root": str,
                             "target": str, "filesystem": str, "device_source": (str, type(None)),
                             "mount_flags": list, "super_flags": list, "propagation": list}, "mount")
        if value["id"] <= 0 or value["parent"] < 0 or value["id"] in mount_ids or \
                not re.fullmatch(r"[0-9]+:[0-9]+", value["device"]) or \
                not value["root"].startswith("/") or not value["target"].startswith("/") or \
                (value["device_source"] is not None and not re.fullmatch(r"/dev/[A-Za-z0-9_./-]+", value["device_source"])):
            raise ValueError("invalid mount identifiers/paths")
        if any(not capacity_flag(f) for f in value["mount_flags"] + value["super_flags"]):
            raise ValueError("invalid capacity flags")
        if any(not plain_text(f) or not re.fullmatch(r"(?:shared|master|propagate_from):[0-9]+|unbindable", f)
               for f in value["propagation"]):
            raise ValueError("invalid mount propagation")
        mount_ids.add(value["id"])
    for value in result["swaps"]:
        typed_record(value, {"path": str, "type": str, "size_kib": int, "used_kib": int, "priority": int}, "swap")
        if not value["path"].startswith("/") or value["type"] not in {"file", "partition"} or \
                value["size_kib"] < 0 or not 0 <= value["used_kib"] <= value["size_kib"]:
            raise ValueError("invalid swap capacity/path")
    services = result["services"]
    if type(services["exit_code"]) is not int or services["exit_code"] not in {0, 1} or \
            type(services["policy_rc_d_present"]) is not bool:
        raise ValueError("invalid service query status")
    for name, value in services["units"].items():
        typed_record(value, {f: str for f in SERVICE_FIELDS}, "service")
        if value["Id"] != name or any(not value[f] for f in ("LoadState", "ActiveState", "SubState")):
            raise ValueError("invalid service identity/state")
    if services["exit_code"] == 1 and not any(v["LoadState"] == "not-found" for v in services["units"].values()):
        raise ValueError("unexplained service query failure")
    return result


def plain_text(value):
    return isinstance(value, str) and not any(ord(c) < 32 or ord(c) == 127 for c in value)


def capacity_flag(value):
    return plain_text(value) and (value in {"ro", "rw", "noswap"} or
                                 re.fullmatch(r"(?:size|nr_inodes)=[0-9]+[kKmMgG%]?", value) is not None)


def typed_record(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("invalid " + label + " fields")
    for name, kinds in fields.items():
        if type(value[name]) not in (kinds if isinstance(kinds, tuple) else (kinds,)) or \
                (isinstance(value[name], str) and not plain_text(value[name])):
            raise ValueError("invalid " + label + " " + name)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("non-finite JSON number")


def validate_result(raw, nonce):
    """Check return framing only; never certify VM identity or I5 readiness."""
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError("inventory exceeds 128 KiB")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                            parse_constant=reject_constant)
    except RecursionError as exc:
        raise ValueError("inventory JSON nesting too deep") from exc
    if not isinstance(result, dict):
        raise ValueError("inventory must be a JSON object")
    if type(result.get("schema_version")) is not int or result["schema_version"] != 1:
        raise ValueError("unsupported inventory schema")
    if result.get("scope") != "guest-preparation-inventory" or result.get("nonce") != nonce:
        raise ValueError("inventory scope or nonce mismatch")
    if result.get("i5_ready") is not False or result.get("identity_regeneration_verified") is not False:
        raise ValueError("inventory cannot certify readiness or regenerated identity")
    if result.get("network_interfaces") != ["lo"] or result.get("loopback_only") is not True:
        raise ValueError("loopback-only inventory required")
    # Require all collection fields, not just a partial success envelope. Facts
    # and tool versions are still reviewed against the environment operation pack.
    groups = {
        dict: ("os", "process_security", "landlock", "memory", "packages", "tool_executables"),
        list: ("block_devices", "ipv4_routes", "ipv6_routes"),
        str: ("kernel", "architecture", "python"),
        int: ("uid", "euid", "root_available_bytes", "ssh_public_host_key_count"),
        bool: ("machine_id_nonempty",),
    }
    for kind, fields in groups.items():
        for field in fields:
            if type(result.get(field)) is not kind:
                raise ValueError("missing or invalid inventory field: " + field)
            if kind is int and result[field] < 0:
                raise ValueError("negative inventory field: " + field)
    return result


def check_utm_config():
    if platform.system() != "Darwin":
        raise RuntimeError("UTM collection requires macOS")
    path = Path.home() / "VirtualMachines" / (UTM_NAME + ".utm") / "config.plist"
    config = plistlib.loads(path.read_bytes())
    if config.get("Information", {}).get("UUID") != UTM_UUID or \
            config.get("Information", {}).get("Name") != UTM_NAME:
        raise RuntimeError("UTM config target mismatch")
    sharing = config.get("Sharing", {})
    if config.get("Network") != [] or sharing.get("ClipboardSharing") is not False or \
            sharing.get("DirectoryShareMode") != "None":
        raise RuntimeError("UTM config isolation required")


def probe_program(case_name):
    if case_name in {"inventory", "details"}:
        return Path(__file__).read_bytes()
    if case_name not in {"success", "failure"}:
        raise ValueError("unknown UTM case")
    # Delayed synthetic output tests both streams and real exit propagation.
    # No shell, network, files, toolchain or identity access in either probe.
    return ("import sys, time\n"
            "time.sleep(1)\n"
            f"print('I5_UTM_{case_name.upper()}:' + sys.argv[2])\n"
            f"print('I5_UTM_{case_name.upper()}_STDERR:' + sys.argv[2], file=sys.stderr)\n"
            f"raise SystemExit({17 if case_name == 'failure' else 0})\n").encode()


def parse_execution(raw, nonce, case_name):
    result_limit, transport_limit = return_limits(case_name)
    if len(raw) > transport_limit:
        raise ValueError("oversized UTM transport result")
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                            parse_constant=reject_constant)
    except RecursionError as exc:
        raise ValueError("UTM result JSON nesting too deep") from exc
    if not isinstance(result, dict) or type(result.get("schema_version")) is not int or \
            result["schema_version"] != 1 or result.get("scope") != "utm-guest-execution":
        raise ValueError("invalid UTM transport envelope")
    if result.get("uuid") != UTM_UUID or result.get("nonce") != nonce or result.get("case_name") != case_name:
        raise ValueError("UTM transport binding mismatch")
    if result.get("exited") is not True:
        raise ValueError("guest exit unconfirmed")
    for field, maximum in (("exit_code", 255), ("signal_code", 255), ("polls", 10000)):
        value = result.get(field)
        if type(value) is not int or value < (1 if field == "polls" else 0) or value > maximum:
            raise ValueError("missing or invalid UTM " + field)
    streams = []
    for field in ("stdout_base64", "stderr_base64"):
        value = result.get(field)
        if not isinstance(value, str):
            raise ValueError("missing UTM stream: " + field)
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) > result_limit or base64.b64encode(decoded).decode() != value:
            raise ValueError("oversized or noncanonical UTM stream: " + field)
        streams.append(decoded)
    return result, streams[0], streams[1]


def verify_case(result, stdout, stderr, nonce, case_name):
    if result["signal_code"] != 0:
        raise ValueError("guest terminated by signal " + str(result["signal_code"]))
    expected_exit = 17 if case_name == "failure" else 0
    if result["exit_code"] != expected_exit:
        raise ValueError(f"guest exit {result['exit_code']}; expected {expected_exit}")
    if case_name in {"inventory", "details"}:
        (validate_details if case_name == "details" else validate_result)(stdout, nonce)
        if stderr:
            raise ValueError("unexpected inventory stderr; inspect preserved evidence")
    elif stdout != f"I5_UTM_{case_name.upper()}:{nonce}\n".encode() or \
            stderr != f"I5_UTM_{case_name.upper()}_STDERR:{nonce}\n".encode():
        raise ValueError("synthetic output mismatch; inspect preserved evidence")


def collect_utm(nonce, case_name):
    """No VM lifecycle control; caller must shut down after success or failure."""
    if re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise ValueError("invalid nonce")
    _, transport_limit = return_limits(case_name)
    check_utm_config()
    source = Path(__file__).resolve()
    adapter = source.with_name("sw_i5_utm_result.js")
    program = probe_program(case_name)
    request = {"schema_version": 1, "uuid": UTM_UUID, "nonce": nonce,
               "case_name": case_name, "program_base64": base64.b64encode(program).decode()}
    root = source.parents[1] / ".tmp" / ("i5-guest-return-" + nonce)
    # Reject redirected paths and prior attempts instead of overwriting evidence.
    if root.resolve() != root:
        raise ValueError("canonical local evidence path required")
    evidence = root / case_name
    evidence.mkdir(parents=True, exist_ok=False)
    metadata = {"schema_version": 1, "uuid": UTM_UUID, "nonce": nonce, "case_name": case_name,
                "program_sha256": hashlib.sha256(program).hexdigest(),
                "adapter_sha256": hashlib.sha256(adapter.read_bytes()).hexdigest()}
    (evidence / "input.json").write_text(json.dumps(metadata, indent=2) + "\n")
    argv = ["/usr/bin/osascript", "-l", "JavaScript", str(adapter), "--collect"]
    try:
        try:
            completed = subprocess.run(argv, input=json.dumps(request).encode(), capture_output=True,
                                       timeout=60, check=False)
            output, diagnostic, code = completed.stdout, completed.stderr, completed.returncode
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            output, diagnostic, code = exc.stdout or b"", exc.stderr or b"", None
            timed_out = True
        # The adapter bounds each guest stream before serialization. Also cap
        # retained transport diagnostics; truncation is failure, never success.
        (evidence / "transport.stdout").write_bytes(output[:transport_limit])
        (evidence / "transport.stderr").write_bytes(diagnostic[:transport_limit])
        (evidence / "transport.json").write_text(json.dumps({"exit_code": code, "timeout": timed_out,
            "stdout_bytes": len(output), "stderr_bytes": len(diagnostic)}) + "\n")
        if timed_out:
            raise RuntimeError("UTM result timeout; guest completion unknown; shut down VM")
        if code != 0:
            raise RuntimeError(f"UTM adapter exit {code}; inspect {evidence / 'transport.stderr'}; shut down VM")
        if diagnostic:
            raise RuntimeError("unexpected UTM adapter stderr; inspect evidence; shut down VM")
        result, stdout, stderr = parse_execution(output, nonce, case_name)
        (evidence / "guest.stdout").write_bytes(stdout)
        (evidence / "guest.stderr").write_bytes(stderr)
        (evidence / "execution.json").write_text(json.dumps(result, indent=2) + "\n")
        check_utm_config()
        verify_case(result, stdout, stderr, nonce, case_name)
        return result
    except (OSError, ValueError, RuntimeError) as exc:
        try:
            (evidence / "failure.txt").write_text(str(exc) + "\n")
        except OSError as diagnostic_error:
            raise RuntimeError(f"{exc}; failure evidence write failed: {diagnostic_error}") from exc
        raise


def return_limits(case_name):
    if case_name == "details":
        return DETAILS_RESULT_BYTES, DETAILS_TRANSPORT_BYTES
    if case_name in {"inventory", "success", "failure"}:
        return MAX_RESULT_BYTES, MAX_TRANSPORT_BYTES
    raise ValueError("unknown UTM case")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nonce", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-result", action="store_true",
                      help="validate guest JSON from stdin locally; does not inspect this host")
    mode.add_argument("--details", action="store_true", help="collect separate preparation details in Linux guest")
    mode.add_argument("--validate-details", action="store_true", help="validate preparation details from stdin locally")
    mode.add_argument("--collect-utm", choices=("success", "failure", "inventory", "details"),
                      help="authorized macOS collection from the already-running isolated VM; never starts/stops it")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{32}", args.nonce) is None:
        parser.error("nonce must be 32 lowercase hex characters")
    try:
        if args.collect_utm:
            result = collect_utm(args.nonce, args.collect_utm)
            print(json.dumps(result, sort_keys=True))
            return result["exit_code"]
        elif args.validate_result:
            validate_result(sys.stdin.buffer.read(MAX_RESULT_BYTES + 1), args.nonce)
            print("I5_GUEST_INVENTORY_VALID: inventory only; I5 remains stopped")
        elif args.validate_details:
            validate_details(sys.stdin.buffer.read(DETAILS_RESULT_BYTES + 1), args.nonce)
            print("I5_GUEST_DETAILS_VALID: preparation facts only; I5 remains stopped")
        elif args.details:
            raw = json.dumps(preparation_details(args.nonce), sort_keys=True, allow_nan=False).encode()
            validate_details(raw + b"\n", args.nonce)
            print(raw.decode())
        else:
            print(json.dumps(inventory(args.nonce), sort_keys=True, allow_nan=False))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("I5_GUEST_INVENTORY_FAILED: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
