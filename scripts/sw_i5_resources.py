"""I5 Linux capacity probes, before any Go bootstrap. Standard library only.

This verifies local block domains, not VM backing storage or daemon isolation.
The public I5 entry points remain closed pending environment acceptance.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from dataclasses import dataclass


MIB = 1024 * 1024
CAPS = {"build": 256 * MIB, "daemon": 160 * MIB,
        "evidence": 240 * MIB, "diagnostic": 64 * MIB}
HOST_FREE = 1024 * MIB


class ResourceError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ResourceError(message)


def absolute_path(value: str) -> Path:
    require(isinstance(value, str) and value.startswith("/"), "absolute path required")
    path = Path(value)
    require(str(path) == value and ".." not in path.parts and path != Path("/"),
            "noncanonical or root path")
    return path


def below(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate configuration key: " + key)
        result[key] = value
    return result


@dataclass(frozen=True)
class Config:
    root: Path
    host_path: Path
    devices: dict[str, str]

    @classmethod
    def decode(cls, raw: str) -> Config:
        obj = json.loads(raw, object_pairs_hook=unique_object)
        require(isinstance(obj, dict) and set(obj) == {
            "schema_version", "root", "host_path", "devices"}, "configuration fields")
        require(type(obj["schema_version"]) is int and obj["schema_version"] == 1,
                "unsupported configuration version")
        root, host = absolute_path(obj["root"]), absolute_path(obj["host_path"])
        require(not below(host, root), "host free-space path must be outside capacity domains")
        devices = obj["devices"]
        require(isinstance(devices, dict) and set(devices) == set(CAPS), "four domains required")
        require(all(isinstance(v, str) and re.fullmatch(r"[0-9]+:[0-9]+", v)
                    for v in devices.values()), "expected major:minor required")
        require(len(set(devices.values())) == 4, "devices must be distinct")
        return cls(root, host, devices)


@dataclass(frozen=True)
class Mount:
    ident: int
    device: str
    root: str
    path: Path
    options: frozenset[str]
    kind: str
    source: str
    super_options: frozenset[str]


def mount_path(raw: str) -> str:
    # mountinfo uses octal escapes; reject unsupported ones instead of guessing.
    for escaped, value in ((r"\040", " "), (r"\011", "\t"),
                           (r"\012", "\n"), (r"\134", "\\")):
        raw = raw.replace(escaped, value)
    require("\\" not in raw and not any(c in raw for c in "\n\t"), "unsupported mount path")
    return raw


def parse_mounts(raw: str) -> tuple[Mount, ...]:
    mounts = []
    seen = set()
    for line in raw.splitlines():
        fields = line.split()
        require(fields.count("-") == 1, "invalid mountinfo separator")
        split = fields.index("-")
        require(split >= 6 and len(fields) == split + 4, "invalid mountinfo fields")
        require(fields[0].isdigit() and fields[1].isdigit()
                and re.fullmatch(r"[0-9]+:[0-9]+", fields[2]) is not None,
                "invalid mountinfo identity")
        ident = int(fields[0])
        path = Path(mount_path(fields[4]))
        require(ident > 0 and ident not in seen and path.is_absolute(), "duplicate mount identity")
        seen.add(ident)
        mounts.append(Mount(ident, fields[2], mount_path(fields[3]), path,
                            frozenset(fields[5].split(",")), fields[split + 1],
                            mount_path(fields[split + 2]),
                            frozenset(fields[split + 3].split(","))))
    require(bool(mounts), "empty mountinfo")
    return tuple(mounts)


def covering(mounts: tuple[Mount, ...], path: Path) -> Mount:
    candidates = [m for m in mounts if below(path, m.path)]
    require(bool(candidates), "path without mount: " + str(path))
    longest = max(len(m.path.parts) for m in candidates)
    selected = [m for m in candidates if len(m.path.parts) == longest]
    require(len(selected) == 1, "overmounted/ambiguous path: " + str(path))
    return selected[0]


class LinuxProbe:
    """Read live kernel data; never shell out or create a directory."""

    def mounts(self) -> tuple[Mount, ...]:
        require(os.uname().sysname == "Linux", "Linux kernel required")
        return parse_mounts(Path("/proc/self/mountinfo").read_text())

    def directory(self, path: Path):
        require(path.resolve(strict=True) == path, "symlink in path: " + str(path))
        info = path.stat()
        require(stat.S_ISDIR(info.st_mode), "directory required: " + str(path))
        return info

    def space(self, path: Path):
        return os.statvfs(path)

    def device(self, mount: Mount) -> tuple[str, int]:
        source = Path(mount.source)
        info = source.stat()
        require(stat.S_ISBLK(info.st_mode), "mount source is not a block device")
        require(f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}" == mount.device,
                "mount source device differs from mountinfo")
        sys = Path("/sys/dev/block") / mount.device
        resolved = sys.resolve(strict=True)
        # Initial backend deliberately excludes loop/dm/md and partitions: their
        # backing allocations need another verified accounting layer.
        require(re.fullmatch(r"(?:vd[a-z]+|sd[a-z]+|nvme[0-9]+n[0-9]+)", resolved.name)
                is not None and not (sys / "partition").exists(),
                "unsupported block backend (requires an independent whole disk)")
        sectors = (sys / "size").read_text().strip()
        require(sectors.isdigit() and int(sectors) > 0, "invalid block capacity")
        return str(resolved), int(sectors) * 512


def check_space(probe, path: Path, minimum: int, capacity: int | None = None):
    space = probe.space(path)
    require(space.f_frsize > 0 and 0 <= space.f_bavail <= space.f_bfree <= space.f_blocks
            and 0 < space.f_favail <= space.f_ffree <= space.f_files,
            "invalid space/inode inventory: " + str(path))
    require(space.f_bavail * space.f_frsize >= minimum,
            "insufficient available bytes: " + str(path))
    if capacity is not None:
        require(0 < space.f_blocks * space.f_frsize <= capacity,
                "filesystem exceeds device capacity: " + str(path))
    return space


def inspect_domains(config: Config, probe=None, *, build_scope=False) -> dict:
    probe = probe or LinuxProbe()
    mounts = probe.mounts()
    root_info = probe.directory(config.root)
    host_info = probe.directory(config.host_path)
    host_mount = covering(mounts, config.host_path)
    require(host_mount.kind == "ext4" and root_info.st_dev == host_info.st_dev,
            "host path must share the ext4 filesystem containing the batch root")
    require(host_mount.device not in config.devices.values(), "host path is a domain alias")
    require(f"{os.major(host_info.st_dev)}:{os.minor(host_info.st_dev)}" == host_mount.device,
            "host path device mismatch")
    host = check_space(probe, config.host_path, HOST_FREE)
    records = {}
    for name, cap in CAPS.items():
        path = config.root / name
        info = probe.directory(path)
        mount = covering(mounts, path)
        require(mount.path == path and mount.root == "/" and mount.kind == "ext4",
                "independent full ext4 mount required: " + name)
        require(mount.device == config.devices[name]
                and f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" == mount.device,
                "domain device mismatch: " + name)
        access = "ro" if build_scope and name != "build" else "rw"
        require({access, "nosuid", "nodev"} <= mount.options
                and ({"rw", "ro"} & mount.options) == {access}
                and "rw" in mount.super_options, "domain mount options: " + name)
        require(sum(m.device == mount.device for m in mounts) == 1,
                "domain device alias: " + name)
        require(not any(m.path != path and below(m.path, path) for m in mounts),
                "nested domain mount: " + name)
        require(info.st_uid == os.geteuid() and info.st_mode & 0o777 == 0o700,
                "domain must be owned by caller with mode 0700: " + name)
        device_path, size = probe.device(mount)
        require(0 < size <= cap, "block domain exceeds cap: " + name)
        space = check_space(probe, path, 1, size)
        records[name] = {"mount_id": mount.ident, "device": mount.device,
                         "sysfs": device_path, "capacity": size, "fsid": space.f_fsid,
                         "root_inode": info.st_ino,
                         "available": space.f_bavail * space.f_frsize,
                         "available_inodes": space.f_favail}
    require(all(m.path == config.root or m.path in [config.root / n for n in CAPS]
                for m in mounts if below(m.path, config.root)), "unexpected batch mount")
    if build_scope:
        # Landlock does not mediate chmod/chown/utime etc. All other mounts must
        # already be read-only in the separately prepared build namespace.
        require(all("ro" in m.options and "rw" not in m.options
                    for m in mounts if m.path != config.root / "build"),
                "build namespace has another writable mount")
    require(mounts == probe.mounts(), "mount inventory changed during probe")
    return {"schema_version": 1, "scope": "local-block-domains-only",
            "host": {"mount_id": host_mount.ident, "device": host_mount.device,
                     "fsid": host.f_fsid, "available": host.f_bavail * host.f_frsize},
            "domains": records, "i5_ready": False}


def identity(snapshot: dict) -> dict:
    # Available bytes/inodes may change. Identity and upper bounds may not.
    return {"host": {k: v for k, v in snapshot["host"].items() if k != "available"},
            "domains": {n: {k: v for k, v in r.items()
                             if k not in {"available", "available_inodes"}}
                        for n, r in snapshot["domains"].items()}}


class DomainGuard:
    """A probe failure remains fatal for the whole stage; no implicit retry."""

    def __init__(self, config: Config, probe=None, *, build_scope=False):
        self.config, self.probe, self.build_scope = config, probe, build_scope
        self.initial = None
        self.failure = None

    def check(self) -> dict:
        if self.failure is not None:
            raise self.failure
        try:
            snapshot = inspect_domains(self.config, self.probe, build_scope=self.build_scope)
            current = identity(snapshot)
            if self.initial is None:
                self.initial = current
            require(current == self.initial, "capacity domain identity changed")
            return snapshot
        except (OSError, ValueError, ResourceError) as exc:
            self.failure = ResourceError("capacity probe stopped: " + str(exc))
            raise self.failure from exc
