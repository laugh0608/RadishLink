#!/usr/bin/env python3
"""Read-only Linux inventory for the I5 preparation VM, not I5 acceptance.

Run through UTM guest-agent with python3 -I -B; writes JSON to stdout only.
Boot/shutdown may write system state independently of this probe. No credentials,
machine-id contents, host keys, process arguments or user files are collected.
"""

import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import platform
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--validate-result", action="store_true",
                        help="validate guest JSON from stdin locally; does not inspect this host")
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{32}", args.nonce) is None:
        parser.error("nonce must be 32 lowercase hex characters")
    try:
        if args.validate_result:
            validate_result(sys.stdin.buffer.read(MAX_RESULT_BYTES + 1), args.nonce)
            print("I5_GUEST_INVENTORY_VALID: inventory only; I5 remains stopped")
        else:
            print(json.dumps(inventory(args.nonce), sort_keys=True, allow_nan=False))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("I5_GUEST_INVENTORY_FAILED: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
