"""Preparation-only Linux boundaries. No CLI, mount discovery or live enablement.

The caller must own a private namespace, fresh delegated cgroups and reviewed
mountpoints. Kernel mutations below are exercised through injected APIs in the
offline suite; public guest/UTM/I5 entry points remain stopped.
"""

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import re
import resource
import stat

from sw_i5_apt import MIB, UUID, decode, digest, fields, require
from sw_i5_resources import below, covering, parse_mounts

STORAGE = {"input": 256 * MIB, "work": 128 * MIB, "result": 8 * MIB}
NATIVE_ROOT_BYTES, NATIVE_ROOT_INODES = MIB, 1024
NATIVE_CGROUP2, NATIVE_TMPFS = 0x63677270, 0x01021994
NATIVE_INPUT_FS = {"iso9660": 0x9660, "squashfs": 0x73717368}
NATIVE_CREATE_ORDER = ("guest_root", "work", "result", "cgroup_parent", "cgroup_supervisor", "cgroup_worker", "control", "lease", "ack")
NATIVE_CLEAN_ORDER = tuple(reversed(NATIVE_CREATE_ORDER))
NATIVE_FALSE_FLAGS = ("authorized", "install_authorized", "physical_verified", "i5_ready")
LIMITS = {
    "parent": {"memory.max": str(512 * MIB), "memory.swap.max": "0", "pids.max": "48", "memory.oom.group": "0", "cpu.max": "200000 100000"},
    "supervisor": {"memory.max": str(64 * MIB), "memory.swap.max": "0", "pids.max": "8", "memory.oom.group": "1", "cpu.max": "25000 100000"},
    "worker": {"memory.max": str(384 * MIB), "memory.swap.max": "0", "pids.max": "32", "memory.oom.group": "1", "cpu.max": "100000 100000"},
}
READ_FILES = {"cgroup.type", "cgroup.procs", "cgroup.subtree_control", "cgroup.events",
              "memory.events", "pids.events", *LIMITS["worker"]}


def seccomp_program(machine):
    # Linux v6.12 UAPI syscall tables, not host libc syscall numbers. Blocking
    # socket creation/IPC endpoints also covers filesystem Unix sockets, which
    # a read-only mount or network namespace alone would not isolate.
    tables = {
        "x86_64": (0xC000003E, 56, (41, 42, 44, 46, 53, 101, 272, 308, 310, 311, 321, 323)),
        "aarch64": (0xC00000B7, 220, (198, 199, 203, 206, 211, 117, 97, 268, 270, 271, 280, 282)),
    }
    require(machine in tables, "unsupported seccomp architecture")
    arch, clone, denied = tables[machine]
    # sock_filter: code, jt, jf, k. Kill foreign ABI/x32; EPERM for denied calls.
    program = [(0x20, 0, 0, 4), (0x15, 1, 0, arch), (0x06, 0, 0, 0x80000000),
               (0x20, 0, 0, 0), (0x45, 0, 1, 0x40000000), (0x06, 0, 0, 0x80000000)]
    for number in (*denied, 425, 426, 427, 435):  # io_uring, clone3
        program += [(0x15, 0, 1, number), (0x06, 0, 0, 0x00050001)]
    program += [(0x15, 0, 3, clone), (0x20, 0, 0, 16), (0x45, 0, 1, 0x7E020000),
                (0x06, 0, 0, 0x00050001), (0x06, 0, 0, 0x7FFF0000)]
    return program


@dataclass(frozen=True)
class Contract:
    nonce: str
    manifest_sha256: str
    root: Path
    input: Path
    uid: int
    gid: int

    @classmethod
    def parse(cls, raw, nonce, manifest_sha256):
        value = decode(raw, 8192)
        fields(value, "schema_version scope nonce uuid manifest_sha256 root input uid gid i5_ready")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["scope"] == "i5-preparation-isolation" and value["uuid"] == UUID and
                type(nonce) is str and re.fullmatch(r"[0-9a-f]{32}", nonce) and value["nonce"] == nonce and
                digest(manifest_sha256) and value["manifest_sha256"] == manifest_sha256 and value["i5_ready"] is False,
                "isolation contract binding")
        paths = []
        for name in ("root", "input"):
            text = value[name]
            require(type(text) is str and re.fullmatch(r"/[A-Za-z0-9_./-]+", text), "invalid isolation path")
            path = Path(text)
            require(str(path) == text and ".." not in path.parts and path != Path("/"), "noncanonical isolation path")
            paths.append(path)
        require(paths[0] == Path("/run/radishlink-i5-preparation") / nonce and
                not below(paths[1], paths[0]) and not below(paths[0], paths[1]), "fixed disjoint preparation paths required")
        require(all(type(value[k]) is int and 1000 <= value[k] < 65534 for k in ("uid", "gid")),
                "reviewed unprivileged identity required")
        return cls(nonce, manifest_sha256, *paths, value["uid"], value["gid"])

    @property
    def work(self):
        return self.root / "work"

    @property
    def result(self):
        return self.root / "result"

    @property
    def cgroup(self):
        return Path("/sys/fs/cgroup/radishlink-i5-preparation") / self.nonce


def counters(text):
    result = {}
    for row in text.splitlines():
        parts = row.split()
        require(len(parts) == 2 and parts[0] not in result and parts[1].isdigit(), "invalid kernel counters")
        result[parts[0]] = int(parts[1])
    return result


def verify_cgroup(snapshot, role):
    fields(snapshot, "path identity type procs subtree children limits events memory_events pids_events")
    require(role in LIMITS and snapshot["type"] == "domain" and snapshot["limits"] == LIMITS[role],
            "cgroup hard limits mismatch")
    identity = snapshot["identity"]
    require(type(identity) is tuple and len(identity) == 2 and all(type(n) is int and n > 0 for n in identity),
            "cgroup inode binding required")
    require(snapshot["subtree"] == ("cpu memory pids" if role == "parent" else ""), "unexpected cgroup delegation")
    require(snapshot["children"] == (["supervisor", "worker"] if role == "parent" else []), "unexpected cgroup descendants")
    require(type(snapshot["procs"]) is list and all(type(n) is int and n > 0 for n in snapshot["procs"]), "invalid cgroup PIDs")
    if role == "parent":
        require(not snapshot["procs"], "parent cgroup must have no processes")
    require(snapshot["events"].get("populated") in {0, 1} and snapshot["events"].get("frozen") == 0,
            "cgroup population/frozen state unknown")
    for key in ("max", "oom", "oom_kill", "oom_group_kill"):
        require(snapshot["memory_events"].get(key) == 0, "memory limit/OOM event: " + key)
    require(snapshot["pids_events"].get("max") == 0, "PID limit event")


class CgroupV2:
    """Pinned, nondelegated cgroup directory; no pathname-based PID killing.

    Construction rejects ordinary filesystems. Tests substitute this interface
    with a fake rather than pretending a temporary directory is cgroupfs.
    """
    def __init__(self, path):
        self.path = Path(path)
        require(os.uname().sysname == "Linux" and self.path.resolve(strict=True) == self.path and
                re.fullmatch(r"/sys/fs/cgroup/radishlink-i5-preparation/[0-9a-f]{32}(?:/(?:worker|supervisor))?",
                             str(self.path)), "exact Linux preparation cgroup required")
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            # The f_type field is the first native long in Linux struct statfs;
            # reserve more than the ABI struct size without guessing its tail.
            buffer = ctypes.create_string_buffer(256)
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.fstatfs(self.fd, ctypes.byref(buffer)) != 0:
                raise OSError(ctypes.get_errno(), "cgroup fstatfs")
            require(ctypes.c_long.from_buffer(buffer).value == 0x63677270, "cgroup2 filesystem required")
            info = os.fstat(self.fd)
            self.identity = (info.st_dev, info.st_ino)
            self.check_identity()
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def check_identity(self):
        current = self.path.lstat()
        info = os.fstat(self.fd)
        require(stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == self.identity and
                (info.st_dev, info.st_ino) == self.identity and info.st_uid == 0 and info.st_mode & 0o022 == 0,
                "cgroup replaced or delegated to worker")

    def read(self, name):
        require(name in READ_FILES, "unknown cgroup read")
        self.check_identity()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            data = os.read(fd, 8193)
            require(len(data) <= 8192, "cgroup read limit")
            return data.decode("ascii").strip()
        finally:
            os.close(fd)

    def write(self, name, text):
        require(name in {*LIMITS["worker"], "cgroup.kill", "cgroup.procs"} and
                type(text) is str and (re.fullmatch(r"[0-9]+ [0-9]+", text) if name == "cpu.max" else text.isdigit()),
                "unknown cgroup mutation")
        self.check_identity()
        fd = os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            raw = (text + "\n").encode("ascii")
            require(os.write(fd, raw) == len(raw), "short cgroup write")
        finally:
            os.close(fd)

    def configure(self, role):
        require(role in LIMITS and not self.read("cgroup.procs") and self.read("cgroup.type") == "domain",
                "fresh empty domain required before limits")
        for name, value in LIMITS[role].items():
            self.write(name, value)
        verify_cgroup(self.snapshot(), role)

    def attach(self, pid):
        require(type(pid) is int and pid > 1 and not self.read("cgroup.procs"), "exclusive blocked child required")
        self.write("cgroup.procs", str(pid))
        require(self.read("cgroup.procs") == str(pid), "child cgroup admission failed")

    def kill(self):
        # cgroup.kill covers fork races and descendants that called setsid.
        self.write("cgroup.kill", "1")

    def populated(self):
        events = counters(self.read("cgroup.events"))
        require(events.get("populated") in {0, 1}, "unknown cgroup population")
        return events["populated"] == 1

    def snapshot(self):
        procs = self.read("cgroup.procs").split()
        require(all(p.isdigit() for p in procs), "invalid cgroup process list")
        entries = os.listdir(self.fd)
        require(len(entries) <= 256, "cgroup entry count limit")
        children = sorted(name for name in entries if stat.S_ISDIR(os.stat(name, dir_fd=self.fd, follow_symlinks=False).st_mode))
        return {"path": str(self.path), "identity": self.identity, "type": self.read("cgroup.type"), "procs": [int(p) for p in procs],
                "children": children,
                "subtree": " ".join(sorted(self.read("cgroup.subtree_control").split())),
                "limits": {name: self.read(name) for name in LIMITS["worker"]},
                "events": counters(self.read("cgroup.events")), "memory_events": counters(self.read("memory.events")),
                "pids_events": counters(self.read("pids.events"))}


def verify_worker_mounts(contract, raw, spaces, identity):
    """Validate effective mount flags/superblocks, never free-space sampling alone."""
    require(len(raw.encode()) <= 256 * 1024, "mount inventory limit")
    mounts = parse_mounts(raw)
    # Shared/slave propagation and stacked mounts could invalidate ro coverage.
    require(all(line.split().index("-") == 6 for line in raw.splitlines()), "private mount propagation required")
    require(len({m.path for m in mounts}) == len(mounts), "stacked mount rejected")
    allowed = {contract.work, contract.result}
    domains = {}
    for role, path in (("input", contract.input), ("work", contract.work), ("result", contract.result)):
        mount = covering(mounts, path)
        require(mount.path == path and mount.root == "/", "independent preparation domain required")
        flags = {"ro"} if role == "input" else {"rw", "nosuid", "nodev", "noexec"}
        require(flags <= mount.options and not ({"ro", "rw"} - flags) & mount.options, "preparation mount flags")
        if role == "input":
            require(mount.kind in {"iso9660", "squashfs"} and "ro" in mount.super_options,
                    "immutable input filesystem required")
        else:
            require(mount.kind == "tmpfs" and "noswap" in mount.super_options, "noswap tmpfs required")
            require("rw" in mount.super_options, "writable tmpfs superblock required")
        info = spaces[role]
        require(type(info) is dict and set(info) == {"bytes", "inodes", "device", "inode"} and
                type(info["bytes"]) is int and 0 < info["bytes"] <= STORAGE[role] and
                type(info["inodes"]) is int and 0 < info["inodes"] <= (32768 if role == "work" else 4096) and
                info["device"] == mount.device and type(info["inode"]) is int and info["inode"] > 0,
                "filesystem hard capacity/inode binding")
        require(sum(m.device == mount.device for m in mounts) == 1, "preparation domain alias")
        require(not any(m.path != path and below(m.path, path) for m in mounts), "nested preparation domain")
        domains[role] = (mount.ident, mount.device, info["inode"], info["bytes"], info["inodes"])
    require(all("ro" in m.options and "rw" not in m.options for m in mounts if m.path not in allowed),
            "writable path outside work/result")
    require(len({value[1] for value in domains.values()}) == 3, "independent domain devices required")
    fields(identity, "uid gid groups capabilities no_new_privs namespace supervisor_namespace net_namespace supervisor_net_namespace "
           "ipc_namespace supervisor_ipc_namespace interfaces inherited_fds seccomp exclusive_uid admission_fd")
    admission_fd = identity["admission_fd"]
    require(admission_fd is None or (type(admission_fd) is int and admission_fd >= 3), "invalid admission descriptor")
    expected_fds = [0, 1, 2] + ([] if admission_fd is None else [admission_fd])
    for name, supervisor in (("namespace", "supervisor_namespace"), ("net_namespace", "supervisor_net_namespace"),
                             ("ipc_namespace", "supervisor_ipc_namespace")):
        require(type(identity[name]) is int and type(identity[supervisor]) is int and
                identity[name] > 0 and identity[supervisor] > 0 and identity[name] != identity[supervisor], "private namespace identity")
    require(identity["uid"] == contract.uid and identity["gid"] == contract.gid and identity["groups"] == [] and
            identity["capabilities"] == [0, 0, 0, 0, 0] and identity["no_new_privs"] == 1 and
            identity["namespace"] != identity["supervisor_namespace"] and identity["interfaces"] == ["lo"] and
            identity["inherited_fds"] == expected_fds and identity["seccomp"] == 2 and identity["exclusive_uid"] is True,
            "worker privilege/namespace/FD boundary")
    return domains


def kernel_text(path, limit=8192):
    # procfs paths below are fixed or contain a supervisor-owned child PID.
    # Unlike disk inputs, /proc/<pid>/root and /ns are intentional kernel links.
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "kernel observation limit")
    return raw.decode("ascii")


def process_status(pid):
    result = {}
    for line in kernel_text(f"/proc/{pid}/status").splitlines():
        key, separator, value = line.partition(":")
        require(separator and key not in result, "invalid process status")
        result[key] = value.strip()
    return result


class LinuxPreparationProbe:
    """Effective kernel observations for the owned, blocked/active worker.

    Construct only after the cgroups were separately prepared and configured.
    No directory creation, mount, account change or process launch happens here.
    """
    def __init__(self, contract):
        self.contract, self.pid, self.admission_fd = contract, None, None
        self.groups = {}
        try:
            for role in LIMITS:
                path = contract.cgroup if role == "parent" else contract.cgroup / role
                self.groups[role] = CgroupV2(path)
        except BaseException:
            self.close()
            raise

    def close(self):
        for group in self.groups.values():
            group.close()
        self.groups.clear()

    def bind_worker(self, pid, admission_fd):
        require(self.pid is None and type(pid) is int and pid > 1 and type(admission_fd) is int and admission_fd >= 3,
                "one owned blocked worker required")
        self.pid, self.admission_fd = pid, admission_fd

    def group_snapshot(self):
        return {role: group.snapshot() for role, group in self.groups.items()}

    def __call__(self):
        groups = self.group_snapshot()
        if self.pid is None:
            return "", {}, {}, groups
        process = Path("/proc") / str(self.pid)
        config = self.contract
        require(kernel_text(process / "cgroup").strip() == "0::" + str(config.cgroup).removeprefix("/sys/fs/cgroup") + "/worker",
                "worker escaped bound cgroup")
        raw = kernel_text(process / "mountinfo", 256 * 1024)
        spaces = {}
        for role, path in (("input", config.input), ("work", config.work), ("result", config.result)):
            target = process / "root" / str(path).lstrip("/")
            info, space = target.stat(), os.statvfs(target)
            require(stat.S_ISDIR(info.st_mode), "worker domain is not a directory")
            spaces[role] = {"bytes": space.f_blocks * space.f_frsize, "inodes": space.f_files,
                            "device": f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}", "inode": info.st_ino}
        status = process_status(self.pid)
        uids, gids = [int(v) for v in status["Uid"].split()], [int(v) for v in status["Gid"].split()]
        require(uids == [config.uid] * 4 and gids == [config.gid] * 4, "saved/filesystem identity mismatch")
        fds = sorted(int(p.name) for p in (process / "fd").iterdir())
        admission = self.admission_fd if self.admission_fd in fds else None
        if admission is not None:
            path = process / "fd" / str(admission)
            require(stat.S_ISFIFO(path.stat().st_mode), "admission must be a read-only pipe")
            flags = [line.split()[1] for line in kernel_text(process / "fdinfo" / str(admission)).splitlines()
                     if line.startswith("flags:")]
            require(len(flags) == 1 and int(flags[0], 8) & os.O_ACCMODE == os.O_RDONLY, "writable admission channel")
        require(os.readlink(process / "fd/0") == "/dev/null" and
                os.readlink(process / "fd/1") == str(config.result / "worker.stdout") and
                os.readlink(process / "fd/2") == str(config.result / "worker.stderr"), "unbounded worker stdio")
        for fd in (1, 2):
            info = (process / "fd" / str(fd)).stat()
            require(stat.S_ISREG(info.st_mode) and f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" == spaces["result"]["device"],
                    "worker output outside bounded result filesystem")
        entries = [p for p in Path("/proc").iterdir() if p.name.isdigit()]
        require(len(entries) <= 8192, "process inventory limit")
        for entry in entries:
            try:
                other = process_status(int(entry.name))
                if config.uid in [int(v) for v in other["Uid"].split()]:
                    require(kernel_text(entry / "cgroup").strip() == "0::" +
                            str(config.cgroup).removeprefix("/sys/fs/cgroup") + "/worker", "UID used outside worker cgroup")
            except FileNotFoundError:
                continue  # Only a process that vanished during enumeration.
        identity = {"uid": uids[0], "gid": gids[0], "groups": [int(v) for v in status["Groups"].split()],
                    "capabilities": [int(status[k], 16) for k in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")],
                    "no_new_privs": int(status["NoNewPrivs"]), "seccomp": int(status["Seccomp"]), "exclusive_uid": True,
                    "inherited_fds": fds, "admission_fd": admission,
                    "interfaces": sorted(line.split(":")[0].strip() for line in kernel_text(process / "net/dev").splitlines()[2:])}
        for name, ns in (("namespace", "mnt"), ("net_namespace", "net"), ("ipc_namespace", "ipc")):
            identity[name] = (process / "ns" / ns).stat().st_ino
            identity["supervisor_" + name] = (Path("/proc/self/ns") / ns).stat().st_ino
        return raw, spaces, identity, groups


class IsolationGuard:
    """Stable mount/cgroup identity and sticky failures for one preparation."""
    def __init__(self, contract, probe):
        self.contract, self.probe = contract, probe
        self.initial, self.failure = None, None
        self.group_identity = None

    def admit_supervisor(self):
        group = CgroupV2(self.contract.cgroup / "supervisor")
        try:
            verify_cgroup(group.snapshot(), "supervisor")
            group.attach(os.getpid())
        finally:
            group.close()

    def bind_worker(self, pid, admission_fd):
        self.probe.bind_worker(pid, admission_fd)

    def check_cgroups(self):
        if self.failure:
            raise ValueError(self.failure)
        try:
            groups = self.probe.group_snapshot() if hasattr(self.probe, "group_snapshot") else self.probe()[3]
            require(set(groups) == set(LIMITS), "complete cgroup hierarchy required")
            for role, snapshot in groups.items():
                verify_cgroup(snapshot, role)
                expected = self.contract.cgroup if role == "parent" else self.contract.cgroup / role
                require(snapshot["path"] == str(expected), "cgroup hierarchy path mismatch")
            current = {role: s["identity"] for role, s in groups.items()}
            require(len(set(current.values())) == 3, "supervisor must be outside worker cgroup")
            require(groups["supervisor"]["procs"] == [os.getpid()], "supervisor cgroup membership required")
            if self.group_identity is None:
                self.group_identity = current
            require(current == self.group_identity, "cgroup identity changed")
            return groups
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self.failure = "preparation isolation stopped: " + str(exc)
            raise ValueError(self.failure) from exc

    def before_admission(self):
        groups = self.check_cgroups()
        if groups["worker"]["procs"] or groups["worker"]["events"]["populated"] != 0:
            self.failure = "worker cgroup already in use"
            raise ValueError(self.failure)

    def check(self):
        if self.failure:
            raise ValueError(self.failure)
        try:
            raw, spaces, identity, groups = self.probe()
            domains = verify_worker_mounts(self.contract, raw, spaces, identity)
            groups = self.check_cgroups()
            stable = domains, {role: s["identity"] for role, s in groups.items()}
            if self.initial is None:
                self.initial = stable
            require(stable == self.initial, "preparation boundary identity changed")
            return stable
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self.failure = "preparation isolation stopped: " + str(exc)
            raise ValueError(self.failure) from exc


class LinuxNamespace:
    """Fixed syscalls for the already-forked, privileged setup child only."""
    def __init__(self):
        require(os.uname().sysname == "Linux" and os.uname().machine in {"aarch64", "x86_64"},
                "supported Linux namespace ABI required")
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.syscall.restype = ctypes.c_long

    def checked(self, result, label):
        if result < 0:
            raise OSError(ctypes.get_errno(), label)

    def mountpoints(self, contract):
        require(os.geteuid() == 0, "privileged setup child required")
        for path in (contract.root, contract.work, contract.result):
            require(path.resolve(strict=True) == path, "canonical prepared mountpoint required")
            info = path.stat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o022 == 0,
                    "root-owned prepared mountpoint required")
            if path != contract.root:
                require(not any(path.iterdir()), "fresh empty mountpoint required")

    def private(self):
        # NEWNS | NEWNET | NEWIPC. No user namespace or host network fallback.
        self.checked(self.libc.unshare(0x00020000 | 0x40000000 | 0x08000000), "unshare preparation")
        self.checked(self.libc.mount(None, b"/", None, ctypes.c_ulong((1 << 18) | (1 << 14)), None), "private mounts")

    def tmpfs(self, path, cap, inodes, uid, gid):
        options = f"size={cap},nr_inodes={inodes},noswap,mode=0700,uid={uid},gid={gid}".encode()
        self.checked(self.libc.mount(b"tmpfs", os.fsencode(path), b"tmpfs", ctypes.c_ulong(2 | 4 | 8), options), "bounded tmpfs")

    def readonly(self, path, recursive=True):
        class MountAttr(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("attr_set", "attr_clr", "propagation", "userns_fd")]
        attrs = MountAttr(1, 0, 0, 0)  # MOUNT_ATTR_RDONLY
        self.checked(self.libc.syscall(ctypes.c_long(442), ctypes.c_int(-100), ctypes.c_char_p(os.fsencode(path)),
                     ctypes.c_uint(0x8000 if recursive else 0), ctypes.byref(attrs), ctypes.c_size_t(ctypes.sizeof(attrs))),
                     "recursive read-only mount_setattr")

    def drop_identity(self, uid, gid):
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (128 * MIB, 128 * MIB))
        self.checked(self.libc.prctl(38, 1, 0, 0, 0), "no_new_privs")
        # Empty bounding/ambient sets before dropping uid. Unknown capability
        # range is not guessed: read the running kernel's bounded integer.
        last = int(Path("/proc/sys/kernel/cap_last_cap").read_text())
        require(0 <= last < 64, "unsupported capability range")
        for cap in range(last + 1):
            self.checked(self.libc.prctl(24, cap, 0, 0, 0), "capability bounding set")
        self.checked(self.libc.prctl(47, 4, 0, 0, 0), "ambient capabilities")
        os.setgroups([])
        os.setresgid(gid, gid, gid)
        os.setresuid(uid, uid, uid)
        class Header(ctypes.Structure):
            _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
        class Data(ctypes.Structure):
            _fields_ = [(key, ctypes.c_uint32) for key in ("effective", "permitted", "inheritable")]
        header, data = Header(0x20080522, 0), (Data * 2)()
        self.checked(self.libc.capset(ctypes.byref(header), ctypes.byref(data)), "clear capability sets")

    def restrict_syscalls(self):
        class Filter(ctypes.Structure):
            _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]
        class Program(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ushort), ("filter", ctypes.POINTER(Filter))]
        instructions = seccomp_program(os.uname().machine)
        filters = (Filter * len(instructions))(*(Filter(*row) for row in instructions))
        program = Program(len(filters), filters)
        self.checked(self.libc.prctl(22, 2, ctypes.byref(program), 0, 0), "seccomp preparation filter")

    def stdio(self, result):
        # Tool-wrapper output also consumes the 8 MiB result filesystem, never
        # an unbounded guest-agent or host capture buffer. Export is separate.
        targets = [(0, Path("/dev/null"), os.O_RDONLY),
                   (1, result / "worker.stdout", os.O_WRONLY | os.O_CREAT | os.O_EXCL),
                   (2, result / "worker.stderr", os.O_WRONLY | os.O_CREAT | os.O_EXCL)]
        for destination, path, flags in targets:
            fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            try:
                os.dup2(fd, destination)
            finally:
                if fd != destination:
                    os.close(fd)


def confine_worker(contract, kernel, validate):
    """Fail closed at every syscall; validate effective state before tools.

    Mountpoints must already exist on reviewed input/system media. Work/result
    are fresh mounts in this namespace; evidence export/recovery must precede
    its destruction. This function does not create host/guest system paths.
    """
    kernel.mountpoints(contract)
    kernel.private()
    kernel.readonly(Path("/"))
    kernel.tmpfs(contract.work, STORAGE["work"], 32768, contract.uid, contract.gid)
    kernel.tmpfs(contract.result, STORAGE["result"], 4096, contract.uid, contract.gid)
    kernel.drop_identity(contract.uid, contract.gid)
    kernel.stdio(contract.result)
    kernel.restrict_syscalls()
    validate()
