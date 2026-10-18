"""Offline injected syscall tests; no Linux mutation, VM, tool or process launch."""

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sw_i5_apt as apt
import sw_i5_preparation_isolation as isolation
import sw_i5_preparation_native as native

NONCE = "a" * 32
INPUT = "/media/i5-input"
ROOT = "/run/radishlink-i5-preparation"
GROUP = "/sys/fs/cgroup/radishlink-i5-preparation"


def encode(value): return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
def blob(raw): return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def manifest_fixture():
    files, content = {}, {}
    for source in apt.SOURCES.values():
        for path in apt.source_paths(source):
            raw = ("synthetic-only " + path).encode()
            files[path], content[path] = blob(raw), raw
        _, index, _ = apt.source_paths(source)
        content[str(Path(index).parent / "by-hash/SHA256" / files[index]["sha256"])] = content[index]
    baseline = dict(status=blob(b"synthetic status"), extended_states=None, crypto_policy=None,
        architecture="arm64", foreign_architectures=[], tools={name: dict(package=owner, version="1.0", sha256="b" * 64)
        for name, owner in apt.TOOLS.items()})
    value = dict(schema_version=1, scope="i5-preparation-apt-input", nonce=NONCE, uuid=apt.UUID,
        files=files, baseline=baseline, install_authorized=False, i5_ready=False)
    return encode(value), content


class MemorySyscalls:
    """Kernel behavior model with inode objects, pinned FD offsets and faults.

    Auto-generated cgroup pseudo-files exist only in this model. No temporary
    filesystem is labelled cgroupfs and no native syscall is delegated to os.
    """
    backend_kind = "injected-offline"

    def __init__(self, content):
        self.nodes, self.fds, self.next_inode, self.next_fd = {}, {}, 10, 10
        self.now, self.calls, self.uid_busy, self.platform_name, self.root_uid = 1.0, [], False, "Linux", 0
        self.fail_open, self.short_write, self.override_read, self.hook = None, None, {}, None
        self.magic, self.capacity = {}, {}
        self.add_dir("/")
        for path in (ROOT, GROUP, INPUT): self.add_parents(path)
        self.set_device(ROOT, 11)
        self.set_device(GROUP, 12)
        self.set_device(INPUT, 13)
        self.nodes[INPUT].mode = stat.S_IFDIR | 0o555
        self.magic.update({11: native.TMPFS, 12: native.CGROUP2, 13: native.INPUT_FS["iso9660"]})
        self.capacity.update({11: (native.ROOT_BYTES, native.ROOT_INODES), 13: (4 * apt.MIB, 4096)})
        self.group_files(GROUP, delegated=True)
        for relative, raw in content.items():
            path = INPUT + "/" + relative
            self.add_parents(str(Path(path).parent), mode=0o555, device=13)
            self.add_file(path, raw, mode=0o444, device=13)
        self.mount_rows = [
            "1 0 0:1 / / rw - ext4 /dev/synthetic rw",
            f"21 1 0:11 / {ROOT} rw,nosuid,nodev,noexec - tmpfs tmpfs rw,noswap,size=1048576,nr_inodes=1024",
            "22 1 0:12 / /sys/fs/cgroup rw - cgroup2 cgroup rw",
            f"23 1 0:13 / {INPUT} ro - iso9660 /dev/synthetic-input ro"]

    def add_dir(self, path, *, mode=0o700, device=1):
        self.next_inode += 1
        node = SimpleNamespace(path=path, ino=self.next_inode, dev=device, mode=stat.S_IFDIR | mode,
                               uid=0, gid=0, nlink=None, raw=b"", pseudo=False)
        self.nodes[path] = node
        return node

    def add_parents(self, path, *, mode=0o700, device=1):
        current = ""
        for name in Path(path).parts[1:]:
            current += "/" + name
            if current not in self.nodes: self.add_dir(current, mode=mode, device=device)

    def add_file(self, path, raw=b"", *, mode=0o644, device=None, pseudo=False):
        self.next_inode += 1
        node = SimpleNamespace(path=path, ino=self.next_inode, dev=self.nodes[str(Path(path).parent)].dev if device is None else device,
                               mode=stat.S_IFREG | mode, uid=0, gid=0, nlink=1, raw=raw, pseudo=pseudo)
        self.nodes[path] = node
        return node

    def set_device(self, path, device): self.nodes[path].dev = device
    def platform(self): return self.platform_name
    def euid(self): return self.root_uid
    def clock(self): return self.now
    def mounts(self): return "\n".join(self.mount_rows) + "\n"
    def uid_idle(self, uid):
        if self.uid_busy: raise ValueError("native target UID already in use")
    def absolute(self, path, dir_fd):
        return path if path.startswith("/") else self.fds[dir_fd][0].path.rstrip("/") + "/" + path

    def open(self, path, flags, mode=0o600, *, dir_fd=None):
        path = self.absolute(str(path), dir_fd)
        self.calls.append(("open", path, flags))
        if self.hook: self.hook("open", path)
        if self.fail_open == path: raise PermissionError("injected open failure")
        node = self.nodes.get(path)
        if flags & os.O_CREAT:
            if node is not None and flags & os.O_EXCL: raise FileExistsError(path)
            if node is None: node = self.add_file(path, mode=mode)
        if node is None: raise FileNotFoundError(path)
        if stat.S_ISLNK(node.mode) and flags & os.O_NOFOLLOW: raise OSError("injected symlink rejected")
        if flags & os.O_DIRECTORY and not stat.S_ISDIR(node.mode): raise NotADirectoryError(path)
        self.next_fd += 1
        self.fds[self.next_fd] = [node, 0, flags]
        return self.next_fd

    def close(self, fd):
        self.calls.append(("close", fd))
        if fd not in self.fds: raise OSError("model invalid FD")
        del self.fds[fd]

    def info(self, node):
        nlink = node.nlink
        if nlink is None: nlink = 2 + sum(stat.S_ISDIR(other.mode) and str(Path(path).parent) == node.path for path, other in self.nodes.items() if path != "/")
        return SimpleNamespace(st_dev=node.dev, st_ino=node.ino, st_mode=node.mode, st_uid=node.uid, st_gid=node.gid,
                               st_nlink=nlink, st_size=len(node.raw))
    def fstat(self, fd): return self.info(self.fds[fd][0])
    def stat(self, name, *, dir_fd):
        path = self.absolute(name, dir_fd)
        if self.hook: self.hook("stat", path)
        if path not in self.nodes: raise FileNotFoundError(path)
        return self.info(self.nodes[path])
    def listdir(self, fd):
        path = self.fds[fd][0].path
        return [Path(p).name for p in self.nodes if p != path and str(Path(p).parent) == path]
    def read(self, fd, size):
        node, offset, flags = self.fds[fd]
        if flags & os.O_ACCMODE == os.O_WRONLY: raise OSError("read on write-only FD")
        raw = self.override_read.get(node.path, node.raw)
        result = raw[offset:offset + size]
        self.fds[fd][1] += len(result)
        return result
    def write(self, fd, raw):
        node, offset, flags = self.fds[fd]
        self.calls.append(("write", node.path, raw))
        if flags & os.O_ACCMODE == os.O_RDONLY: raise OSError("write on readonly FD")
        size = len(raw) - 1 if self.short_write == node.path else len(raw)
        if node.pseudo:
            if Path(node.path).name == "cgroup.subtree_control":
                node.raw = b"cpu memory pids\n"
            else: node.raw = raw[:size]
        else: node.raw = node.raw[:offset] + raw[:size] + node.raw[offset + size:]
        self.fds[fd][1] += size
        return size

    def group_files(self, path, *, delegated=False):
        values = {"cgroup.type": "domain", "cgroup.procs": "", "cgroup.controllers": "cpu memory pids",
                  "cgroup.subtree_control": "cpu memory pids" if delegated else "", "cgroup.events": "populated 0\nfrozen 0",
                  "memory.events": "max 0\noom 0\noom_kill 0\noom_group_kill 0", "pids.events": "max 0"}
        values.update({name: "max" for name in isolation.LIMITS["worker"]})
        for name, value in values.items(): self.add_file(path + "/" + name, (value + "\n").encode(), device=12, pseudo=True)

    def mkdir(self, name, mode, *, dir_fd):
        path = self.absolute(name, dir_fd)
        self.calls.append(("mkdir", path))
        if path in self.nodes: raise FileExistsError(path)
        device = self.fds[dir_fd][0].dev
        self.add_dir(path, mode=mode, device=device)
        if device == 12: self.group_files(path)
    def unlink(self, name, *, dir_fd):
        path = self.absolute(name, dir_fd)
        self.calls.append(("unlink", path))
        if self.nodes[path].pseudo: raise AssertionError("must never unlink cgroup pseudo-file")
        del self.nodes[path]
    def rmdir(self, name, *, dir_fd):
        path = self.absolute(name, dir_fd)
        self.calls.append(("rmdir", path))
        children = [p for p in self.nodes if p != path and str(Path(p).parent) == path]
        if any(not self.nodes[p].pseudo for p in children): raise OSError("model directory not empty")
        for child in children: del self.nodes[child]
        del self.nodes[path]
    def fstype(self, fd): return self.magic.get(self.fds[fd][0].dev, 0xEF53)
    def statvfs(self, fd):
        size, inodes = self.capacity[self.fds[fd][0].dev]
        return SimpleNamespace(f_blocks=size // 4096, f_frsize=4096, f_files=inodes)


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.content = manifest_fixture()
        self.digest = hashlib.sha256(self.manifest).hexdigest()
        self.contract = encode(dict(schema_version=1, scope="i5-preparation-isolation", nonce=NONCE, uuid=apt.UUID,
            manifest_sha256=self.digest, root=ROOT + "/" + NONCE, input=INPUT, uid=61000, gid=61000, i5_ready=False))
        self.system = MemorySyscalls(self.content)
        self.expected = {role: dict(dev=self.system.nodes[path].dev, ino=self.system.nodes[path].ino, mount_id=mount)
            for role, path, mount in (("root_parent", ROOT, 21), ("cgroup_root", GROUP, 22), ("readonly_input", INPUT, 23))}
        self.events = []
        self.owner = None

    def make(self):
        self.owner = native.NativeGuestInitialization(self.contract, self.manifest, expected=self.expected, syscalls=self.system)
        self.addCleanup(self.owner.close)
        return self.owner
    def run_init(self): return self.make().initialize(deadline=50.0, register=self.events.append)
    def reject(self, match):
        with self.assertRaisesRegex((ValueError, OSError), match): self.run_init()

    def test_complete_nine_created_ten_readback_and_same_owner_cleanup(self):
        result = self.run_init()
        self.assertEqual(result["backend_kind"], "injected-offline")
        self.assertEqual(set(result["objects"]), {*native.CREATE_ORDER, "readonly_input"})
        self.assertEqual(result["input_bytes"], sum(len(raw) for raw in self.content.values()))
        self.assertEqual(result["objects"]["readonly_input"]["before"]["sha256"], self.digest)
        self.assertTrue(all(result[name] is False for name in native.FALSE_FLAGS))
        for role, row in result["objects"].items():
            self.assertEqual(row["after"]["dev"], row["independent_readback"]["dev"])
            self.assertEqual(row["after"]["ino"], row["independent_readback"]["ino"])
            self.assertEqual(row["independent_readback"]["observer"], "independent-reader")
        cleaned = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(cleaned["errors"], [])
        self.assertEqual(cleaned["cleaned"], list(native.CLEAN_ORDER))
        self.assertEqual(cleaned["pending"], {})
        self.assertIn(INPUT, self.system.nodes)
        self.assertNotIn(ROOT + "/" + NONCE, self.system.nodes)
        self.assertNotIn(GROUP + "/" + NONCE, self.system.nodes)
        self.owner.close()
        self.assertEqual(self.system.fds, {})

    def test_cgroup_pseudo_files_never_created_or_unlinked(self):
        self.run_init()
        self.owner.cleanup(deadline=60.0, register=self.events.append)
        for call in self.system.calls:
            if call[0] == "open" and call[1].startswith(GROUP): self.assertFalse(call[2] & (os.O_CREAT | os.O_TRUNC))
            if call[0] == "unlink": self.assertFalse(call[1].startswith(GROUP))
        writes = [call for call in self.system.calls if call[0] == "write"]
        self.assertFalse(any(call[1].startswith(GROUP + "/cgroup.") for call in writes))
        self.assertIn(("write", GROUP + "/" + NONCE + "/cgroup.subtree_control", b"+cpu +memory +pids\n"), writes)

    def test_native_constructor_rejects_real_macos_before_filesystem_access(self):
        with patch.object(native.os, "uname", return_value=SimpleNamespace(sysname="Darwin")), patch.object(native.os, "open", side_effect=AssertionError("no FS")):
            with self.assertRaisesRegex(ValueError, "Linux root"):
                native.NativeGuestInitialization(self.contract, self.manifest, expected=self.expected)

    def test_platform_uid_expected_and_manifest_binding_strict(self):
        for change in ("platform", "root_uid", "uid_busy", "bool_expected", "unknown_expected", "digest"):
            self.setUp()
            if change == "platform": self.system.platform_name = "Darwin"
            elif change == "root_uid": self.system.root_uid = 1000
            elif change == "uid_busy": self.system.uid_busy = True
            elif change == "bool_expected": self.expected["root_parent"]["ino"] = True
            elif change == "unknown_expected": self.expected["extra"] = dict(self.expected["root_parent"])
            else: self.manifest += b" "
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_init()
            self.assertFalse(any(call[0] == "mkdir" for call in self.system.calls))

    def test_prerequisite_identity_mounts_and_physical_bounds(self):
        for change in ("identity", "mount", "tmpfs_magic", "noswap", "large", "inodes", "input_rw", "input_magic", "propagation", "alias", "delegate", "controller", "procs"):
            self.setUp()
            if change == "identity": self.expected["root_parent"]["ino"] += 1
            elif change == "mount": self.expected["root_parent"]["mount_id"] += 1
            elif change == "tmpfs_magic": self.system.magic[11] = 0xEF53
            elif change == "noswap": self.system.mount_rows[1] = self.system.mount_rows[1].replace(",noswap", "")
            elif change == "large": self.system.capacity[11] = (2 * apt.MIB, 1024)
            elif change == "inodes": self.system.capacity[11] = (apt.MIB, 1025)
            elif change == "input_rw": self.system.mount_rows[3] = self.system.mount_rows[3].replace(" ro", " rw")
            elif change == "input_magic": self.system.magic[13] = native.TMPFS
            elif change == "propagation": self.system.mount_rows[1] = self.system.mount_rows[1].replace(" - ", " shared:1 - ")
            elif change == "alias": self.system.mount_rows.append(f"24 1 0:13 / /media/alias ro - iso9660 /dev/synthetic-input ro")
            elif change == "delegate": self.system.nodes[GROUP + "/cgroup.subtree_control"].raw = b""
            elif change == "controller": self.system.nodes[GROUP + "/cgroup.controllers"].raw = b"memory pids\n"
            else: self.system.nodes[GROUP + "/cgroup.procs"].raw = b"42\n"
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_init()
            self.assertFalse(any(call[0] == "mkdir" for call in self.system.calls))

    def test_input_full_tree_modes_hashes_symlink_extra_and_missing(self):
        for change in ("hash", "missing", "extra", "symlink", "mode", "hardlink", "size"):
            self.setUp()
            target = INPUT + "/" + next(iter(self.content))
            if change == "hash": self.system.nodes[target].raw = b"x" * len(self.system.nodes[target].raw)
            elif change == "missing": del self.system.nodes[target]
            elif change == "extra": self.system.add_file(INPUT + "/extra", b"x", mode=0o444, device=13)
            elif change == "symlink": self.system.nodes[target].mode = stat.S_IFLNK | 0o777
            elif change == "mode": self.system.nodes[target].mode = stat.S_IFREG | 0o644
            elif change == "hardlink": self.system.nodes[target].nlink = 2
            else: self.system.nodes[target].raw += b"x"
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_init()
            self.assertFalse(any(call[0] == "mkdir" for call in self.system.calls))

    def test_existing_object_not_overwritten_or_cleaned(self):
        existing = ROOT + "/" + NONCE
        self.system.add_dir(existing, device=11)
        inode = self.system.nodes[existing].ino
        self.reject("File exists|" + NONCE)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertIn("guest_root", result["pending"])
        self.assertEqual(self.system.nodes[existing].ino, inode)
        with self.assertRaisesRegex(ValueError, "single use"): self.owner.initialize(deadline=50.0, register=self.events.append)

    def test_create_succeeded_open_failed_preserves_unbound_residue(self):
        self.system.fail_open = ROOT + "/" + NONCE
        self.reject("open failure")
        self.system.fail_open = None
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(result["pending"]["guest_root"], dict(state="intent", identity=None))
        self.assertIn(ROOT + "/" + NONCE, self.system.nodes)

    def test_missing_pseudo_file_is_failure_without_creating_replacement(self):
        original = self.system.group_files
        def files(path, **kwargs):
            original(path, **kwargs)
            if path.endswith(NONCE): del self.system.nodes[path + "/memory.max"]
        self.system.group_files = files
        self.reject("memory.max")
        self.assertNotIn(GROUP + "/" + NONCE + "/memory.max", self.system.nodes)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertIn("cgroup_parent", result["pending"])
        self.assertTrue(result["errors"])

    def test_short_cgroup_write_and_independent_limit_mismatch_fail(self):
        for change in ("short", "readback"):
            self.setUp()
            target = GROUP + "/" + NONCE + "/memory.max"
            if change == "short": self.system.short_write = target
            else: self.system.override_read[target] = b"1\n"
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "short|hard limits"):
                self.run_init()

    def test_control_slots_exact_zero_size_mode_link_and_identity(self):
        for change in ("short", "nonzero", "mode", "link", "identity"):
            self.setUp()
            target = ROOT + "/" + NONCE + "/control/lease.slot"
            if change == "short": self.system.short_write = target
            else:
                calls = [0]
                def hook(action, path):
                    if action == "open" and path == target:
                        calls[0] += 1
                        if calls[0] == 2:
                            node = self.system.nodes[target]
                            if change == "nonzero": node.raw = b"x" + bytes(1023)
                            elif change == "mode": node.mode = stat.S_IFREG | 0o644
                            elif change == "link": node.nlink = 2
                            else: self.system.add_file(target, bytes(1024), mode=0o600, device=11)
                self.system.hook = hook
            with self.subTest(change=change), self.assertRaises(ValueError): self.run_init()

    def test_independent_readback_reopens_pinned_objects(self):
        self.run_init()
        target = ROOT + "/" + NONCE + "/work"
        self.system.add_dir(target, device=11)
        with self.assertRaisesRegex(ValueError, "pinned identity"): self.owner.readback(deadline=50.0)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertIn("work", result["pending"])
        self.assertIn(target, self.system.nodes)

    def test_cgroup_reap_population_and_unknown_children_preserved(self):
        for change in ("procs", "populated", "child"):
            self.setUp()
            self.run_init()
            group = GROUP + "/" + NONCE + "/worker"
            if change == "procs": self.system.nodes[group + "/cgroup.procs"].raw = b"42\n"
            elif change == "populated": self.system.nodes[group + "/cgroup.events"].raw = b"populated 1\nfrozen 0\n"
            else: self.system.add_dir(group + "/unknown", device=12)
            result = self.owner.cleanup(deadline=60.0, register=self.events.append)
            with self.subTest(change=change):
                self.assertIn("cgroup_worker", result["pending"])
                self.assertIn(group, self.system.nodes)

    def test_cleanup_unknown_entry_and_changed_ancestor_preserved(self):
        for change in ("entry", "ancestor"):
            self.setUp()
            self.run_init()
            target = ROOT + "/" + NONCE + "/work"
            if change == "entry": self.system.add_file(target + "/unknown", b"x", device=11)
            else: self.system.add_dir(ROOT, device=11)
            result = self.owner.cleanup(deadline=60.0, register=self.events.append)
            with self.subTest(change=change):
                self.assertTrue(result["errors"])
                self.assertIn("guest_root", result["pending"])
                self.assertIn(target, self.system.nodes)

    def test_deadline_strict_and_cleanup_independent_after_work_deadline(self):
        for deadline in (True, False, float("inf"), float("nan"), "50", 0, -1, 1.0):
            self.setUp()
            owner = self.make()
            with self.subTest(deadline=deadline), self.assertRaisesRegex(ValueError, "deadline"):
                owner.initialize(deadline=deadline, register=self.events.append)
            self.assertFalse(any(call[0] == "mkdir" for call in self.system.calls))
        self.setUp()
        self.run_init()
        self.system.now = 51
        with self.assertRaisesRegex(ValueError, "deadline"): self.owner.readback(deadline=50.0)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(result["pending"], {})
        self.assertEqual(result["errors"], [])

    def test_cleanup_deadline_does_not_claim_absence_or_erase_primary_failure(self):
        self.run_init()
        result = self.owner.cleanup(deadline=1.0, register=self.events.append)
        self.assertEqual(set(result["pending"]), set(native.CREATE_ORDER))
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["cleaned"], [])

    def test_cleanup_idempotent_and_initialization_still_single_use(self):
        self.run_init()
        self.owner.cleanup(deadline=60.0, register=self.events.append)
        calls = len(self.system.calls)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(result["pending"], {})
        self.assertEqual(result["cleaned"], [])
        self.assertEqual(len(self.system.calls), calls)
        with self.assertRaisesRegex(ValueError, "single use"): self.owner.initialize(deadline=60.0, register=self.events.append)

    def test_legacy_synthetic_entry_actually_rejects_native_owner(self):
        import sw_i5_preparation_initialization as old
        import test_sw_i5_preparation_plan as plans
        ledger, source = plans.capacity(), b"synthetic JXA bytes; never executed"
        value = plans.initialization(ledger)
        value["jxa_source"] = blob(source)
        with self.assertRaisesRegex(ValueError, "explicit mapped synthetic guest backend"):
            old.SyntheticInitialization(encode(value), encode(ledger), source, guest_backend=self.make())

    def test_fake_cannot_self_attest_as_kernel(self):
        self.system.backend_kind = "kernel"
        result = self.run_init()
        self.assertEqual(result["backend_kind"], "injected-offline")
        self.assertEqual(self.owner.cleanup(deadline=60.0, register=self.events.append)["backend_kind"], "injected-offline")

    def test_actual_snapshots_and_prerequisite_observations_are_retained(self):
        result = self.run_init()
        self.assertEqual(set(result["cgroup_snapshots"]), set(isolation.LIMITS))
        for role, snapshot in result["cgroup_snapshots"].items():
            row = result["objects"]["cgroup_" + role]["independent_readback"]
            self.assertEqual(snapshot["identity"], [row["dev"], row["ino"]])
            self.assertEqual(snapshot["procs"], [])
            self.assertEqual(snapshot["events"]["populated"], 0)
            self.assertEqual(snapshot["limits"], isolation.LIMITS[role])
        for role, observation in result["prerequisite_observations"].items():
            self.assertEqual({key: observation[key] for key in ("dev", "ino", "mount_id")}, self.expected[role])
        self.assertEqual(result["prerequisite_observations"]["root_parent"]["capacity_bytes"], native.ROOT_BYTES)
        self.assertIsNone(result["prerequisite_observations"]["cgroup_root"]["capacity_bytes"])

    def test_active_worker_prevents_every_cleanup_mutation(self):
        self.run_init()
        self.system.nodes[GROUP + "/" + NONCE + "/worker/cgroup.procs"].raw = b"42\n"
        before = len(self.system.calls)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(set(result["pending"]), set(native.CREATE_ORDER))
        self.assertTrue(result["errors"])
        self.assertFalse(any(call[0] in ("unlink", "rmdir") for call in self.system.calls[before:]))

    def test_work_cancellation_after_bound_uses_independent_cleanup(self):
        owner = self.make()
        def register(event):
            self.events.append(event)
            if event["role"] == "work" and event["state"] == "bound": raise KeyboardInterrupt("synthetic cancellation")
        with self.assertRaisesRegex(KeyboardInterrupt, "synthetic cancellation"):
            owner.initialize(deadline=50.0, register=register)
        result = owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["pending"], {})
        self.assertEqual(result["cleaned"], ["work", "guest_root"])

    def test_deadline_expires_during_initialization_and_cleanup_can_finish(self):
        owner = self.make()
        def register(event):
            self.events.append(event)
            if event["role"] == "work" and event["state"] == "bound": self.system.now = 51.0
        with self.assertRaisesRegex(ValueError, "deadline"):
            owner.initialize(deadline=50.0, register=register)
        result = owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(result["pending"], {})
        self.assertEqual(result["errors"], [])

    def test_no_created_objects_cleanup_has_no_false_failure(self):
        self.system.uid_busy = True
        self.reject("already in use")
        result = self.owner.cleanup(deadline=0.0, register=self.events.append)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["pending"], {})

    def test_cgroup_identity_changed_preserves_all_objects(self):
        self.run_init()
        group = GROUP + "/" + NONCE + "/worker"
        self.system.add_dir(group, device=12)
        before = len(self.system.calls)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(set(result["pending"]), set(native.CREATE_ORDER))
        self.assertFalse(any(call[0] in ("unlink", "rmdir") for call in self.system.calls[before:]))

    def test_parent_mount_rebinding_preserves_all_objects(self):
        self.run_init()
        self.system.mount_rows[1] = self.system.mount_rows[1].replace("21 1", "31 1")
        before = len(self.system.calls)
        result = self.owner.cleanup(deadline=60.0, register=self.events.append)
        self.assertEqual(set(result["pending"]), set(native.CREATE_ORDER))
        self.assertFalse(any(call[0] in ("unlink", "rmdir") for call in self.system.calls[before:]))


if __name__ == "__main__": unittest.main()
