"""Internal Linux guest initializer; no CLI, launcher or execution authorization.

The default backend uses real descriptor-relative Linux operations. Offline
checks inject an in-memory syscall model and never treat a directory as cgroupfs.
The same process must retain this owner through task completion and cleanup.
Deadlines between syscalls do not bound a blocked syscall: an external process
supervisor with an independent cleanup/kill/reap budget remains required.
"""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import stat
import time

import sw_i5_apt as apt
import sw_i5_preparation_isolation as isolation
import sw_i5_resources as resources

ROOT_BYTES, ROOT_INODES = isolation.NATIVE_ROOT_BYTES, isolation.NATIVE_ROOT_INODES
CGROUP2, TMPFS = isolation.NATIVE_CGROUP2, isolation.NATIVE_TMPFS
INPUT_FS = isolation.NATIVE_INPUT_FS
CREATE_ORDER, CLEAN_ORDER = isolation.NATIVE_CREATE_ORDER, isolation.NATIVE_CLEAN_ORDER
FALSE_FLAGS = isolation.NATIVE_FALSE_FLAGS
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def ident(info):
    return [info.st_dev, info.st_ino]


class LinuxNativeSyscalls:
    """Narrow injected syscall surface. Construction itself never mutates Linux."""
    backend_kind = "kernel"

    def platform(self): return os.uname().sysname
    def euid(self): return os.geteuid()
    def clock(self): return time.monotonic()
    def open(self, path, flags, mode=0o600, *, dir_fd=None): return os.open(path, flags, mode, dir_fd=dir_fd)
    def close(self, fd): os.close(fd)
    def fstat(self, fd): return os.fstat(fd)
    def stat(self, name, *, dir_fd): return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    def listdir(self, fd): return os.listdir(fd)
    def read(self, fd, size): return os.read(fd, size)
    def write(self, fd, raw): return os.write(fd, raw)
    def mkdir(self, name, mode, *, dir_fd): os.mkdir(name, mode, dir_fd=dir_fd)
    def unlink(self, name, *, dir_fd): os.unlink(name, dir_fd=dir_fd)
    def rmdir(self, name, *, dir_fd): os.rmdir(name, dir_fd=dir_fd)
    def statvfs(self, fd): return os.fstatvfs(fd)

    def fstype(self, fd):
        buffer = ctypes.create_string_buffer(256)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.fstatfs(fd, ctypes.byref(buffer)) != 0:
            raise OSError(ctypes.get_errno(), "native initialization fstatfs")
        return ctypes.c_long.from_buffer(buffer).value

    def kernel_read(self, path, maximum):
        with Path(path).open("rb") as stream:
            raw = stream.read(maximum + 1)
        apt.require(len(raw) <= maximum, "native kernel observation limit")
        return raw.decode("ascii")

    def mounts(self):
        return self.kernel_read("/proc/self/mountinfo", 256 * 1024)

    def uid_idle(self, uid):
        # A disappearing process is harmless. Permission errors and malformed
        # status remain failures; exclusive identity is rechecked at admission.
        entries = [entry for entry in Path("/proc").iterdir() if entry.name.isdigit()]
        apt.require(len(entries) <= 8192, "native process inventory limit")
        for entry in entries:
            try:
                text = self.kernel_read(entry / "status", 8192)
            except FileNotFoundError:
                continue
            rows = [line.split()[1:] for line in text.splitlines() if line.startswith("Uid:")]
            apt.require(len(rows) == 1 and len(rows[0]) == 4 and all(n.isdigit() for n in rows[0]),
                        "native process UID observation invalid")
            apt.require(uid not in [int(n) for n in rows[0]], "native target UID already in use")


class NativeGuestInitialization:
    """Nine fresh guest objects plus one bound immutable input tree.

    `expected` binds independently observed preexisting directory and mount
    identities. It is a prerequisite declaration, never a capacity proof.
    readonly_input.sha256 in this NEW scope identifies manifest bytes; it is
    deliberately not the old review plan's media-image digest field.
    """
    def __init__(self, contract_raw, manifest_raw, *, expected, syscalls=None):
        apt.require(type(contract_raw) is bytes and type(manifest_raw) is bytes, "native immutable input bytes required")
        declaration = apt.decode(contract_raw, 8192)
        nonce, digest = declaration.get("nonce"), declaration.get("manifest_sha256")
        self.contract = isolation.Contract.parse(contract_raw, nonce, digest)
        apt.require(hashlib.sha256(manifest_raw).hexdigest() == digest, "native manifest bytes binding")
        self.manifest = apt.validate_manifest(manifest_raw, nonce)
        apt.fields(expected, "root_parent cgroup_root readonly_input")
        for row in expected.values():
            apt.fields(row, "dev ino mount_id")
            apt.require(all(type(n) is int and n > 0 for n in row.values()), "native expected identity requires positive integers")
        self.expected = {key: dict(row) for key, row in expected.items()}
        self.system = LinuxNativeSyscalls() if syscalls is None else syscalls
        apt.require(self.system.platform() == "Linux" and self.system.euid() == 0, "native Linux root initializer required")
        self.backend_kind = "kernel" if syscalls is None and type(self.system) is LinuxNativeSyscalls else "injected-offline"
        self.entries, self.pinned, self.parents, self.pseudo = {}, {}, {}, {}
        self.observations, self.started, self.closed = {}, False, False
        self.groups, self.prerequisite_observations = {}, {}
        contract = self.contract
        self.paths = {"guest_root": contract.root, "work": contract.work, "result": contract.result,
            "control": contract.root / "control", "lease": contract.root / "control/lease.slot", "ack": contract.root / "control/ack.slot",
            "cgroup_parent": contract.cgroup, "cgroup_supervisor": contract.cgroup / "supervisor",
            "cgroup_worker": contract.cgroup / "worker", "readonly_input": contract.input}
        self.files = dict(self.manifest["files"])
        for source in apt.SOURCES.values():
            _, index, _ = apt.source_paths(source)
            item = self.files[index]
            self.files[str(Path(index).parent / "by-hash/SHA256" / item["sha256"])] = dict(item)
        self.input_bytes = sum(row["bytes"] for row in self.files.values())
        self.files_digest = hashlib.sha256(json.dumps(self.files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def tick(self, deadline):
        apt.require(not self.closed and type(deadline) in (int, float) and not isinstance(deadline, bool) and
                    0 < deadline < float("inf") and self.system.clock() < deadline, "native initialization deadline")

    def directory(self, path, deadline):
        self.tick(deadline)
        fd = self.system.open("/", DIR_FLAGS)
        try:
            for name in Path(path).parts[1:]:
                self.tick(deadline)
                child = self.system.open(name, DIR_FLAGS, dir_fd=fd)
                self.system.close(fd)
                fd = child
            return fd
        except BaseException:
            self.system.close(fd)
            raise

    def names(self, fd, maximum=256):
        entries = self.system.listdir(fd)
        apt.require(type(entries) is list and len(entries) <= maximum and len(entries) == len(set(entries)) and
                    all(type(n) is str and n not in ("", ".", "..") and "/" not in n for n in entries),
                    "native directory entry limit/type")
        return entries

    def safe_info(self, info, *, regular=False, mode=0o700):
        apt.require((stat.S_ISREG(info.st_mode) if regular else stat.S_ISDIR(info.st_mode)) and info.st_uid == 0 and
                    info.st_gid == 0 and stat.S_IMODE(info.st_mode) == mode and
                    (not regular or info.st_nlink == 1), "native object type/ownership/mode/link mismatch")

    def parent(self, role):
        if role == "guest_root": return self.parents["root_parent"]
        if role == "cgroup_parent": return self.parents["cgroup_root"]
        if role in ("cgroup_supervisor", "cgroup_worker"): return self.pinned["cgroup_parent"]
        if role in ("lease", "ack"): return self.pinned["control"]
        return self.pinned["guest_root"]

    def check_pin(self, role, fd):
        info = self.system.fstat(fd)
        expected = self.entries[role]["identity"]
        apt.require(ident(info) == expected == ident(self.system.fstat(self.pinned[role])), "native pinned identity changed: " + role)
        return info

    def check_ancestors(self, deadline):
        raw = self.system.mounts()
        apt.require(type(raw) is str and len(raw.encode()) <= 256 * 1024, "native mount inventory limit")
        mounts = resources.parse_mounts(raw)
        for role, path in (("root_parent", self.contract.root.parent), ("cgroup_root", self.contract.cgroup.parent)):
            if role not in self.parents: continue
            fd = self.directory(path, deadline)
            try:
                expected = self.expected[role]
                apt.require(ident(self.system.fstat(fd)) == [expected["dev"], expected["ino"]] ==
                            ident(self.system.fstat(self.parents[role])), "native fixed ancestor identity changed")
                self.safe_info(self.system.fstat(fd))
                self.mount(role, fd, mounts, raw)
            finally: self.system.close(fd)

    def open_role(self, role, deadline):
        self.check_ancestors(deadline)
        path = self.paths[role]
        parent = self.directory(path.parent, deadline)
        try:
            if role != "readonly_input":
                apt.require(ident(self.system.fstat(parent)) == ident(self.system.fstat(self.parent(role))),
                            "native parent identity changed: " + role)
            fd = self.system.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                                  (0 if role in ("lease", "ack") else os.O_DIRECTORY), dir_fd=parent)
            try:
                if role != "readonly_input": self.check_pin(role, fd)
                return fd
            except BaseException:
                self.system.close(fd)
                raise
        finally:
            self.system.close(parent)

    def pseudo_read(self, role, fd, name, deadline):
        self.tick(deadline)
        stream = self.system.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            info = self.system.fstat(stream)
            apt.require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_mode & 0o022 == 0,
                        "unsafe native cgroup pseudo-file")
            key = (role, name)
            if key in self.pseudo: apt.require(ident(info) == self.pseudo[key], "native cgroup pseudo-file identity changed")
            else: self.pseudo[key] = ident(info)
            raw = self.system.read(stream, 8193)
            apt.require(len(raw) <= 8192, "native cgroup read limit")
            return raw.decode("ascii").strip()
        finally: self.system.close(stream)

    def pseudo_write(self, role, fd, name, value, deadline):
        self.pseudo_read(role, fd, name, deadline)
        self.tick(deadline)
        stream = self.system.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            apt.require(ident(self.system.fstat(stream)) == self.pseudo[(role, name)], "native cgroup write identity changed")
            raw = (value + "\n").encode("ascii")
            apt.require(self.system.write(stream, raw) == len(raw), "short native cgroup write")
        finally: self.system.close(stream)

    def mount(self, role, fd, mounts, raw):
        path = self.contract.root.parent if role == "root_parent" else self.contract.cgroup.parent if role == "cgroup_root" else self.contract.input
        info = self.system.fstat(fd)
        expected = self.expected[role]
        apt.require(ident(info) == [expected["dev"], expected["ino"]], "native prerequisite identity changed: " + role)
        mount = resources.covering(mounts, path)
        apt.require(mount.ident == expected["mount_id"] and mount.device == f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}",
                    "native prerequisite mount identity changed: " + role)
        line = [line for line in raw.splitlines() if line.split()[0] == str(mount.ident)]
        apt.require(len(line) == 1 and line[0].split().index("-") == 6, "native private mount required")
        apt.require(not any(m.path != mount.path and resources.below(m.path, path) for m in mounts), "native nested prerequisite mount")
        if role == "cgroup_root":
            apt.require(mount.kind == "cgroup2" and "rw" in mount.options and "rw" in mount.super_options and
                        self.system.fstype(fd) == CGROUP2, "native cgroup2 filesystem required")
        else:
            apt.require(mount.path == path and mount.root == "/" and sum(m.device == mount.device for m in mounts) == 1,
                        "native independent prerequisite domain required")
            space = self.system.statvfs(fd)
            if role == "root_parent":
                apt.require(mount.kind == "tmpfs" and self.system.fstype(fd) == TMPFS and
                            {"rw", "nosuid", "nodev", "noexec"} <= mount.options and {"rw", "noswap"} <= mount.super_options and
                            "ro" not in mount.options and "ro" not in mount.super_options and
                            0 < space.f_blocks * space.f_frsize <= ROOT_BYTES and 0 < space.f_files <= ROOT_INODES,
                            "native root parent bounded noswap tmpfs required")
            else:
                apt.require(mount.kind in INPUT_FS and self.system.fstype(fd) == INPUT_FS[mount.kind] and
                            "ro" in mount.options and "ro" in mount.super_options and "rw" not in mount.options and
                            "rw" not in mount.super_options and 0 < space.f_blocks * space.f_frsize <= isolation.STORAGE["input"],
                            "native readonly immutable input required")
        self.prerequisite_observations[role] = dict(dev=info.st_dev, ino=info.st_ino, mount_id=mount.ident,
            path=str(path), device=mount.device, filesystem=mount.kind, filesystem_magic=self.system.fstype(fd),
            mount_options=sorted(mount.options), super_options=sorted(mount.super_options),
            capacity_bytes=None if role == "cgroup_root" else space.f_blocks * space.f_frsize,
            inodes=None if role == "cgroup_root" else space.f_files)
        return mount

    def prerequisites(self, deadline):
        self.tick(deadline)
        self.system.uid_idle(self.contract.uid)
        self.tick(deadline)
        raw = self.system.mounts()
        apt.require(type(raw) is str and len(raw.encode()) <= 256 * 1024, "native mount inventory limit")
        mounts = resources.parse_mounts(raw)
        observed = {}
        for role, path in (("root_parent", self.contract.root.parent), ("cgroup_root", self.contract.cgroup.parent),
                           ("readonly_input", self.contract.input)):
            fd = self.directory(path, deadline)
            try:
                self.safe_info(self.system.fstat(fd), mode=0o555 if role == "readonly_input" else 0o700)
                observed[role] = self.mount(role, fd, mounts, raw)
                if role in self.parents:
                    apt.require(ident(self.system.fstat(fd)) == ident(self.system.fstat(self.parents[role])),
                                "native prerequisite pinned identity changed")
                else:
                    self.parents[role] = fd
                    fd = None
            finally:
                if fd is not None: self.system.close(fd)
        apt.require(len({row.device for row in observed.values()}) == 3, "native prerequisite device aliases")
        fd = self.parents["cgroup_root"]
        apt.require(self.pseudo_read("delegate", fd, "cgroup.type", deadline) == "domain" and
                    not self.pseudo_read("delegate", fd, "cgroup.procs", deadline) and
                    set(self.pseudo_read("delegate", fd, "cgroup.controllers", deadline).split()) >= {"cpu", "memory", "pids"} and
                    set(self.pseudo_read("delegate", fd, "cgroup.subtree_control", deadline).split()) == {"cpu", "memory", "pids"},
                    "native preconfigured cgroup delegation required")

    def input_readback(self, deadline, observer):
        fd = self.directory(self.contract.input, deadline)
        try:
            info = self.system.fstat(fd)
            self.safe_info(info, mode=0o555)
            apt.require(ident(info) == ident(self.system.fstat(self.parents["readonly_input"])), "native readonly input identity changed")
            directories = {str(parent) for name in self.files for parent in Path(name).parents if str(parent) != "."}
            def walk(parent, prefix=""):
                for name in self.names(parent, 128):
                    self.tick(deadline)
                    relative = prefix + name
                    entry = self.system.stat(name, dir_fd=parent)
                    is_dir = relative in directories
                    apt.require(is_dir or relative in self.files, "unexpected native input entry")
                    self.safe_info(entry, regular=not is_dir, mode=0o555 if is_dir else 0o444)
                    stream = self.system.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                                              (os.O_DIRECTORY if is_dir else 0), dir_fd=parent)
                    try:
                        apt.require(ident(self.system.fstat(stream)) == ident(entry) and entry.st_dev == info.st_dev,
                                    "native input entry replaced/device alias")
                        if is_dir:
                            walk(stream, relative + "/")
                        else:
                            row, digest, size = self.files[relative], hashlib.sha256(), 0
                            apt.require(entry.st_size == row["bytes"], "native input file length mismatch")
                            while True:
                                self.tick(deadline)
                                chunk = self.system.read(stream, min(65536, row["bytes"] - size + 1))
                                if not chunk: break
                                size += len(chunk)
                                apt.require(size <= row["bytes"], "native input byte limit")
                                digest.update(chunk)
                            apt.require(size == row["bytes"] and digest.hexdigest() == row["sha256"], "native input digest mismatch")
                            apt.require(ident(self.system.stat(name, dir_fd=parent)) == ident(entry), "native input file replaced after read")
                            seen.add(relative)
                    finally: self.system.close(stream)
            seen = set()
            walk(fd)
            apt.require(seen == set(self.files), "native input file set mismatch")
            return self.observation("readonly_input", info, observer)
        finally: self.system.close(fd)

    def observation(self, role, info, observer):
        slot = role in ("lease", "ack")
        kind = "regular" if slot else "readonly-tree" if role == "readonly_input" else "directory"
        return dict(observer=observer, realm="guest", role=role, path=str(self.paths[role]), nonce=self.contract.nonce,
            manifest_sha256=self.contract.manifest_sha256, dev=info.st_dev, ino=info.st_ino, uid=info.st_uid, gid=info.st_gid,
            mode=stat.S_IMODE(info.st_mode), kind=kind, nlink=info.st_nlink, bytes=1024 if slot else self.input_bytes if role == "readonly_input" else 0,
            sha256=hashlib.sha256(bytes(1024)).hexdigest() if slot else self.contract.manifest_sha256 if role == "readonly_input" else None,
            symlink=False, limits=dict(isolation.LIMITS[role.removeprefix("cgroup_")]) if role.startswith("cgroup_") else None)

    def event(self, role, state, register, identity=None):
        register(dict(role=role, state=state, identity=identity, bytes=1024 if role in ("lease", "ack") else 0, sequence=None))

    def create(self, role, deadline, register):
        self.tick(deadline)
        self.check_ancestors(deadline)
        parent_check = self.directory(self.paths[role].parent, deadline)
        try:
            apt.require(ident(self.system.fstat(parent_check)) == ident(self.system.fstat(self.parent(role))),
                        "native creation parent changed")
        finally: self.system.close(parent_check)
        self.entries[role] = dict(state="intent", identity=None)
        self.event(role, "intent", register)
        self.tick(deadline)
        parent, name = self.parent(role), self.paths[role].name
        slot = role in ("lease", "ack")
        if slot:
            fd = self.system.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        else:
            self.system.mkdir(name, 0o700, dir_fd=parent)
            fd = self.system.open(name, DIR_FLAGS, dir_fd=parent)
        self.pinned[role] = fd
        info = self.system.fstat(fd)
        self.safe_info(info, regular=slot, mode=0o600 if slot else 0o700)
        self.entries[role] = dict(state="bound", identity=ident(info))
        self.event(role, "bound", register, ident(info))
        self.tick(deadline)
        if slot:
            apt.require(self.system.write(fd, bytes(1024)) == 1024, "short native control slot write")
        elif role.startswith("cgroup_"):
            apt.require(self.system.fstype(fd) == CGROUP2 and self.pseudo_read(role, fd, "cgroup.type", deadline) == "domain" and
                        not self.pseudo_read(role, fd, "cgroup.procs", deadline) and
                        not self.pseudo_read(role, fd, "cgroup.subtree_control", deadline), "native fresh empty cgroup domain required")
            for key, value in isolation.LIMITS[role.removeprefix("cgroup_")].items():
                self.pseudo_write(role, fd, key, value, deadline)
            if role == "cgroup_parent":
                apt.require(set(self.pseudo_read(role, fd, "cgroup.controllers", deadline).split()) >= {"cpu", "memory", "pids"},
                            "native child cgroup controllers missing")
                self.pseudo_write(role, fd, "cgroup.subtree_control", "+cpu +memory +pids", deadline)
        self.observations[role] = dict(before=None, after=self.observation(role, info, "creator"), independent_readback=None)

    def group_readback(self, role, fd, deadline, *, cleanup=False, removing=False):
        apt.require(self.system.fstype(fd) == CGROUP2, "native cgroup2 readback required")
        children = []
        for name in self.names(fd):
            if stat.S_ISDIR(self.system.stat(name, dir_fd=fd).st_mode): children.append(name)
        snapshot = dict(path=str(self.paths[role]), identity=tuple(ident(self.system.fstat(fd))),
            type=self.pseudo_read(role, fd, "cgroup.type", deadline), procs=[int(n) for n in self.pseudo_read(role, fd, "cgroup.procs", deadline).split()],
            subtree=" ".join(sorted(self.pseudo_read(role, fd, "cgroup.subtree_control", deadline).split())), children=sorted(children),
            limits={name: self.pseudo_read(role, fd, name, deadline) for name in isolation.LIMITS["worker"]},
            events=isolation.counters(self.pseudo_read(role, fd, "cgroup.events", deadline)),
            memory_events=isolation.counters(self.pseudo_read(role, fd, "memory.events", deadline)),
            pids_events=isolation.counters(self.pseudo_read(role, fd, "pids.events", deadline)))
        apt.require(not snapshot["procs"] and snapshot["events"].get("populated") == 0 and
                    (not removing or not children), "native cgroup not reaped/empty")
        if not cleanup: isolation.verify_cgroup(snapshot, role.removeprefix("cgroup_"))
        return snapshot

    def result(self):
        return dict(schema_version=1, scope="i5-preparation-native-initialization", uuid=apt.UUID,
            nonce=self.contract.nonce, manifest_sha256=self.contract.manifest_sha256, backend_kind=self.backend_kind,
            cgroup_snapshots=json.loads(json.dumps(self.groups)),
            prerequisite_observations=json.loads(json.dumps(self.prerequisite_observations)), objects=json.loads(json.dumps(self.observations)), input_bytes=self.input_bytes, input_files_sha256=self.files_digest,
            **{flag: False for flag in FALSE_FLAGS})

    def initialize(self, *, deadline, register):
        apt.require(not self.started, "native initialization is single use")
        self.started = True
        self.prerequisites(deadline)
        observed = self.input_readback(deadline, "preexisting-observer")
        self.observations["readonly_input"] = dict(before=observed, after=dict(observed, observer="creator"), independent_readback=None)
        for role in CREATE_ORDER: self.create(role, deadline, register)
        for role in CREATE_ORDER:
            self.observations[role]["after"] = self.observation(role, self.system.fstat(self.pinned[role]), "creator")
        return self.readback(deadline=deadline)

    def readback(self, *, deadline):
        apt.require(self.started and set(self.observations) == {*CREATE_ORDER, "readonly_input"}, "native complete initialization required")
        self.prerequisites(deadline)
        self.observations["readonly_input"]["independent_readback"] = self.input_readback(deadline, "independent-reader")
        for role in CREATE_ORDER:
            fd = self.open_role(role, deadline)
            try:
                info = self.check_pin(role, fd)
                self.safe_info(info, regular=role in ("lease", "ack"), mode=0o600 if role in ("lease", "ack") else 0o700)
                if role in ("lease", "ack"):
                    apt.require(info.st_size == 1024 and self.system.read(fd, 1025) == bytes(1024), "native control slot initial readback")
                elif role.startswith("cgroup_"):
                    self.groups[role.removeprefix("cgroup_")] = self.group_readback(role, fd, deadline)
                else:
                    expected = {"work", "result", "control"} if role == "guest_root" else {"lease.slot", "ack.slot"} if role == "control" else set()
                    apt.require(set(self.names(fd)) == expected, "native initialization unexpected directory entries")
                snapshot = self.observation(role, info, "independent-reader")
                before = {k: v for k, v in self.observations[role]["after"].items() if k != "observer"}
                apt.require({k: v for k, v in snapshot.items() if k != "observer"} == before, "native independent observation changed")
                self.observations[role]["independent_readback"] = snapshot
            finally: self.system.close(fd)
        return self.result()

    def cleanup(self, *, deadline, register):
        """Own independent deadline; task cancellation must not suppress cleanup."""
        errors, cleaned = [], []
        # No control object may be removed while any owned cgroup could still
        # contain a process. This barrier applies even after partial creation.
        try:
            if self.entries: self.check_ancestors(deadline)
            for role in CREATE_ORDER:
                if not role.startswith("cgroup_") or role not in self.entries: continue
                apt.require(self.entries[role]["state"] == "bound", "native cgroup identity unconfirmed; preserve all")
                fd = self.open_role(role, deadline)
                try:
                    snapshot = self.group_readback(role, fd, deadline, cleanup=True)
                    allowed = {self.paths[child].name for child in ("cgroup_supervisor", "cgroup_worker")
                               if child in self.entries} if role == "cgroup_parent" else set()
                    apt.require(set(snapshot["children"]) == allowed, "native cgroup unknown/missing descendants; preserve all")
                finally: self.system.close(fd)
        except Exception as exc:
            errors.append(("cleanup precondition: " + type(exc).__name__ + ": " + str(exc)).encode("utf-8")[:400].decode("utf-8", "ignore"))
            return self.cleanup_result(errors, cleaned)
        for role in CLEAN_ORDER:
            if role not in self.entries: continue
            try:
                self.tick(deadline)
                row = self.entries[role]
                apt.require(row["state"] == "bound", "native creation identity unconfirmed; preserve")
                fd = self.open_role(role, deadline)
                try:
                    info = self.check_pin(role, fd)
                    slot = role in ("lease", "ack")
                    self.safe_info(info, regular=slot, mode=0o600 if slot else 0o700)
                    if slot: apt.require(info.st_size == 1024, "native cleanup slot length changed")
                    elif role.startswith("cgroup_"): self.group_readback(role, fd, deadline, cleanup=True, removing=True)
                    else: apt.require(not self.names(fd), "native cleanup unknown entry; preserve")
                    self.tick(deadline)
                    current = self.system.stat(self.paths[role].name, dir_fd=self.parent(role))
                    apt.require(ident(current) == row["identity"], "native cleanup final identity changed")
                    if slot: self.system.unlink(self.paths[role].name, dir_fd=self.parent(role))
                    else: self.system.rmdir(self.paths[role].name, dir_fd=self.parent(role))
                finally: self.system.close(fd)
                self.system.close(self.pinned.pop(role))
                self.entries.pop(role)
                cleaned.append(role)
                self.event(role, "cleaned", register, row["identity"])
            except Exception as exc:
                text = role + ": " + type(exc).__name__ + ": " + str(exc)
                errors.append(text.encode("utf-8")[:400].decode("utf-8", "ignore"))
        return self.cleanup_result(errors, cleaned)

    def cleanup_result(self, errors, cleaned):
        return dict(schema_version=1, scope="i5-preparation-native-cleanup", uuid=apt.UUID, nonce=self.contract.nonce,
            manifest_sha256=self.contract.manifest_sha256, backend_kind=self.backend_kind, errors=errors, cleaned=cleaned,
            pending={role: dict(row) for role, row in self.entries.items()}, **{flag: False for flag in FALSE_FLAGS})

    def close(self):
        errors = []
        for mapping in (self.pinned, self.parents):
            for fd in list(mapping.values()):
                try: self.system.close(fd)
                except OSError as exc: errors.append(str(exc))
            mapping.clear()
        self.closed = True
        apt.require(not errors, "native descriptor close errors: " + "; ".join(errors))
