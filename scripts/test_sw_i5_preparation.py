"""Offline isolation/recovery tests. No Linux mutations, real APT or UTM."""

import copy
import json
import os
from pathlib import Path
import select
import signal
import stat
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import sw_i5_preparation_isolation as isolation
import sw_i5_preparation_supervisor as supervision
import sw_i5_utm_control as control

NONCE, DIGEST = "a" * 32, "b" * 64


def contract():
    value = {"schema_version": 1, "scope": "i5-preparation-isolation", "nonce": NONCE,
             "uuid": isolation.UUID, "manifest_sha256": DIGEST, "root": "/run/radishlink-i5-preparation/" + NONCE,
             "input": "/opt/i5/input", "uid": 61000, "gid": 61000, "i5_ready": False}
    return isolation.Contract.parse(json.dumps(value).encode(), NONCE, DIGEST)


def fixture():
    config = contract()
    raw = "1 0 8:0 / / ro - ext4 /dev/vda ro\n"
    raw += f"2 1 11:0 / {config.input} ro - iso9660 /dev/sr0 ro\n"
    raw += f"3 1 0:40 / {config.work} rw,nosuid,nodev,noexec - tmpfs tmpfs rw,size=131072k,nr_inodes=32768,noswap\n"
    raw += f"4 1 0:41 / {config.result} rw,nosuid,nodev,noexec - tmpfs tmpfs rw,size=8192k,nr_inodes=4096,noswap\n"
    spaces = {name: {"bytes": cap, "inodes": 32768 if name == "work" else 4096,
                     "device": {"input": "11:0", "work": "0:40", "result": "0:41"}[name], "inode": i + 10}
              for i, (name, cap) in enumerate(isolation.STORAGE.items())}
    identity = {"uid": config.uid, "gid": config.gid, "groups": [], "capabilities": [0] * 5,
                "no_new_privs": 1, "namespace": 100, "supervisor_namespace": 99,
                "net_namespace": 102, "supervisor_net_namespace": 101, "ipc_namespace": 104, "supervisor_ipc_namespace": 103,
                "interfaces": ["lo"], "inherited_fds": [0, 1, 2], "seccomp": 2, "exclusive_uid": True, "admission_fd": None}
    groups = {role: {"path": str(config.cgroup if role == "parent" else config.cgroup / role),
                    "identity": (27, index + 100), "type": "domain",
                    "procs": [os.getpid()] if role == "supervisor" else [],
                    "children": ["supervisor", "worker"] if role == "parent" else [],
                    "subtree": "cpu memory pids" if role == "parent" else "", "limits": dict(limits),
                    "events": {"populated": 1 if role != "worker" else 0, "frozen": 0},
                    "memory_events": {"low": 0, "high": 0, "max": 0, "oom": 0, "oom_kill": 0, "oom_group_kill": 0},
                    "pids_events": {"max": 0}}
              for index, (role, limits) in enumerate(isolation.LIMITS.items())}
    return config, [raw, spaces, identity, groups]


class IsolationTests(unittest.TestCase):
    def test_contract_is_separate_strict_and_bound(self):
        valid = contract()
        self.assertEqual(valid.work, valid.root / "work")
        record = {"schema_version": 1, "scope": "i5-preparation-isolation", "nonce": NONCE,
                  "uuid": isolation.UUID, "manifest_sha256": DIGEST, "root": str(valid.root),
                  "input": str(valid.input), "uid": valid.uid, "gid": valid.gid, "i5_ready": False}
        for key, value in (("schema_version", True), ("scope", "i5-preparation-apt-input"), ("nonce", "c" * 32),
                           ("uuid", "other"), ("root", "/"), ("root", str(valid.root) + "/../escape"),
                           ("input", str(valid.work)), ("uid", 0), ("i5_ready", True), ("extra", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                isolation.Contract.parse(json.dumps(dict(record, **{key: value})).encode(), NONCE, DIGEST)
        raw = json.dumps(record).encode()
        with self.assertRaises(ValueError):
            isolation.Contract.parse(raw[:-1] + b',"uid":61000}', NONCE, DIGEST)

    def test_guard_good_state_and_sticky_identity_replacement(self):
        config, data = fixture()
        guard = isolation.IsolationGuard(config, lambda: data)
        initial = guard.check()
        self.assertEqual(initial, guard.check())
        data[1]["work"]["inode"] += 1
        with self.assertRaisesRegex(ValueError, "identity changed"):
            guard.check()
        data[1]["work"]["inode"] -= 1
        with self.assertRaisesRegex(ValueError, "identity changed"):
            guard.check()

    def test_mount_hard_boundaries_fail_closed(self):
        config, original = fixture()
        changes = [lambda d: d.__setitem__(0, d[0].replace(" / ro -", " / rw -")),
                   lambda d: d.__setitem__(0, d[0].replace(",noswap", "")),
                   lambda d: d.__setitem__(0, d[0].replace("noexec", "exec")),
                   lambda d: d.__setitem__(0, d[0].replace(" - tmpfs", " shared:1 - tmpfs", 1)),
                   lambda d: d.__setitem__(0, d[0] + f"5 1 0:40 / /escape rw - tmpfs tmpfs rw,noswap\n"),
                   lambda d: d.__setitem__(0, d[0] + f"5 3 0:42 / {config.work}/nested rw - tmpfs tmpfs rw,noswap\n"),
                   lambda d: d[1]["work"].__setitem__("bytes", 129 * isolation.MIB),
                   lambda d: d[1]["result"].__setitem__("inodes", 4097),
                   lambda d: d[1]["input"].__setitem__("device", "8:0"),
                   lambda d: d[2].__setitem__("capabilities", [1] + [0] * 4),
                   lambda d: d[2].__setitem__("groups", [1000]),
                   lambda d: d[2].__setitem__("seccomp", 0),
                   lambda d: d[2].__setitem__("exclusive_uid", False),
                   lambda d: d[2].__setitem__("inherited_fds", [0, 1, 2, 7]),
                   lambda d: d[2].__setitem__("namespace", 99)]
        for index, mutate in enumerate(changes):
            data = copy.deepcopy(original)
            mutate(data)
            with self.subTest(index=index), self.assertRaises(ValueError):
                isolation.IsolationGuard(config, lambda: data).check()

    def test_cgroup_limits_events_membership_and_hierarchy(self):
        config, original = fixture()
        changes = [lambda g: g["worker"]["limits"].__setitem__("memory.max", "max"),
                   lambda g: g["worker"]["limits"].__setitem__("memory.swap.max", "1"),
                   lambda g: g["parent"]["limits"].__setitem__("pids.max", "49"),
                   lambda g: g["worker"]["memory_events"].__setitem__("oom_kill", 1),
                   lambda g: g["worker"]["pids_events"].__setitem__("max", 1),
                   lambda g: g["worker"].__setitem__("type", "threaded"),
                   lambda g: g["worker"].__setitem__("subtree", "memory pids"),
                   lambda g: g["parent"].__setitem__("children", ["other", "supervisor", "worker"]),
                   lambda g: g["worker"].__setitem__("path", "/sys/fs/cgroup/another/worker"),
                   lambda g: g["supervisor"].__setitem__("identity", g["worker"]["identity"]),
                   lambda g: g["supervisor"].__setitem__("procs", [123456]),
                   lambda g: g["parent"].__setitem__("procs", [123456])]
        for index, mutate in enumerate(changes):
            data = copy.deepcopy(original)
            mutate(data[3])
            with self.subTest(index=index), self.assertRaises(ValueError):
                isolation.IsolationGuard(config, lambda: data).check()

    def test_namespace_order_and_each_mutation_failure_stops(self):
        expected = ["mountpoints", "private", "readonly", "tmpfs", "tmpfs", "drop_identity", "stdio", "restrict_syscalls"]
        for fail_at in range(len(expected) + 1):
            calls, valid = [], []
            class Kernel:
                def __getattr__(self, name):
                    def call(*args):
                        calls.append((name, args))
                        if len(calls) - 1 == fail_at:
                            raise OSError("synthetic kernel rejection")
                    return call
            if fail_at < len(expected):
                with self.assertRaisesRegex(OSError, "synthetic"):
                    isolation.confine_worker(contract(), Kernel(), lambda: valid.append(True))
                self.assertFalse(valid)
                self.assertEqual(len(calls), fail_at + 1)
            else:
                isolation.confine_worker(contract(), Kernel(), lambda: valid.append(True))
                self.assertEqual([name for name, _ in calls], expected)
                self.assertEqual(calls[3][1][1:3], (128 * isolation.MIB, 32768))
                self.assertEqual(calls[4][1][1:3], (8 * isolation.MIB, 4096))
                self.assertEqual(valid, [True])

    def test_cgroup_configure_readback_and_single_kill_write(self):
        _, data = fixture()
        group = isolation.CgroupV2.__new__(isolation.CgroupV2)
        group.read = Mock(side_effect=lambda name: "" if name == "cgroup.procs" else "domain")
        group.write = Mock()
        group.snapshot = Mock(return_value=data[3]["worker"])
        group.configure("worker")
        self.assertEqual(group.write.call_args_list[0].args, ("memory.max", str(384 * isolation.MIB)))
        group.kill()
        self.assertEqual(group.write.call_args_list[-1].args, ("cgroup.kill", "1"))
        group.snapshot.return_value["limits"]["memory.max"] = "max"
        with self.assertRaises(ValueError):
            group.configure("worker")
        group.read = Mock(return_value="12")
        group.write.reset_mock()
        with self.assertRaises(ValueError):
            group.configure("worker")
        group.write.assert_not_called()

    def test_seccomp_filter_control_flow(self):
        # Interpret the emitted classic BPF independently. This verifies branch
        # offsets/ABI matching, not kernel enforcement or actual APT behavior.
        def execute(program, arch, nr, flags=0):
            pc, accumulator = 0, 0
            memory = {0: nr, 4: arch, 16: flags}
            while pc < len(program):
                code, jt, jf, value = program[pc]
                pc += 1
                if code == 0x20:
                    accumulator = memory[value]
                elif code == 0x15:
                    pc += jt if accumulator == value else jf
                elif code == 0x45:
                    pc += jt if accumulator & value else jf
                elif code == 0x06:
                    return value
                else:
                    self.fail("unsupported BPF instruction")
            self.fail("filter fell through")
        for arch_name, arch, clone, socket, ordinary in (("x86_64", 0xC000003E, 56, 41, 1),
                                                       ("aarch64", 0xC00000B7, 220, 198, 64)):
            program = isolation.seccomp_program(arch_name)
            self.assertEqual(execute(program, arch, ordinary), 0x7FFF0000)
            self.assertEqual(execute(program, arch, clone, 17), 0x7FFF0000)
            for flags in (0x10000000, 0x40000000, 0x00020000, 0x02000000):
                self.assertEqual(execute(program, arch, clone, flags), 0x00050001)
            for nr in (socket, 425, 426, 427, 435):
                self.assertEqual(execute(program, arch, nr), 0x00050001)
            self.assertEqual(execute(program, 0, ordinary), 0x80000000)
            self.assertEqual(execute(program, arch, socket | 0x40000000), 0x80000000)

    def test_kernel_probe_reads_bound_process_not_declared_success_flags(self):
        config, sample = fixture()
        status = {"Uid": "61000 61000 61000 61000", "Gid": "61000 61000 61000 61000", "Groups": "",
                  "CapInh": "0", "CapPrm": "0", "CapEff": "0", "CapBnd": "0", "CapAmb": "0", "NoNewPrivs": "1", "Seccomp": "2"}
        probe = isolation.LinuxPreparationProbe.__new__(isolation.LinuxPreparationProbe)
        probe.contract, probe.pid, probe.admission_fd = config, 1234, 7
        probe.group_snapshot = Mock(return_value=sample[3])
        def text(path, limit=8192):
            name = str(path)
            if name.endswith("/mountinfo"): return sample[0]
            if name.endswith("/cgroup"): return "0::" + str(config.cgroup).removeprefix("/sys/fs/cgroup") + "/worker\n"
            if name.endswith("/fdinfo/7"): return "flags:\t02000000\n"
            if name.endswith("/net/dev"): return "header\nheader\n lo: 0 0 0 0\n"
            self.fail("unexpected kernel read " + name)
        def info(path):
            name = str(path)
            if "/ns/" in name:
                offset = {"mnt": 100, "net": 102, "ipc": 104}[path.name]
                return SimpleNamespace(st_ino=offset - (1 if "/self/" in name else 0))
            if name.endswith("/fd/7"): return SimpleNamespace(st_mode=stat.S_IFIFO)
            if "/fd/" in name: return SimpleNamespace(st_mode=stat.S_IFREG, st_dev=os.makedev(0, 41))
            role = path.name
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_ino=sample[1][role]["inode"],
                                   st_dev=os.makedev(*(int(v) for v in sample[1][role]["device"].split(":"))))
        def entries(path):
            return [Path(str(n)) for n in ([1234] if str(path) == "/proc" else [0, 1, 2, 7])]
        def space(path):
            value = sample[1][path.name]
            return SimpleNamespace(f_blocks=value["bytes"] // 4096, f_frsize=4096, f_files=value["inodes"])
        def link(path):
            return {"0": "/dev/null", "1": str(config.result / "worker.stdout"), "2": str(config.result / "worker.stderr")}[path.name]
        with patch.object(isolation, "kernel_text", side_effect=text), patch.object(isolation, "process_status", return_value=status), \
                patch.object(Path, "stat", info), patch.object(Path, "iterdir", entries), \
                patch.object(os, "statvfs", side_effect=space), patch.object(os, "readlink", side_effect=link):
            data = probe()
            self.assertEqual(data[2]["admission_fd"], 7)
            isolation.verify_worker_mounts(config, *data[:3])
            status["Uid"] = "61000 61000 0 61000"
            with self.assertRaisesRegex(ValueError, "saved/filesystem"):
                probe()

    def test_cgroup_short_write_and_identity_failure_are_not_retried(self):
        group = isolation.CgroupV2.__new__(isolation.CgroupV2)
        group.fd = 91
        group.check_identity = Mock()
        with patch.object(os, "open", return_value=92) as opened, patch.object(os, "write", return_value=0) as written, \
                patch.object(os, "close") as closed:
            with self.assertRaisesRegex(ValueError, "short"):
                group.kill()
            self.assertEqual(written.call_count, 1)
            self.assertEqual(opened.call_args.kwargs["dir_fd"], 91)
            closed.assert_called_once_with(92)
            group.check_identity.side_effect = ValueError("cgroup replaced")
            opened.reset_mock()
            with self.assertRaisesRegex(ValueError, "replaced"):
                group.kill()
            opened.assert_not_called()


class LeaseTests(unittest.TestCase):
    def lease(self):
        return supervision.Lease(NONCE, DIGEST, started=0, total=5, silence=1)

    def test_binding_sequence_partial_frames_and_absolute_deadline(self):
        lease = self.lease()
        frame = lease.frame(0)
        lease.feed(frame[:60], 0.1)
        with self.assertRaisesRegex(ValueError, "initial"):
            lease.check(0.1)
        lease.feed(frame[60:], 0.2)
        lease.check(0.2)
        for seq in range(1, 6):
            lease.feed(lease.frame(seq), seq * 0.8)
        with self.assertRaisesRegex(ValueError, "absolute"):
            lease.feed(lease.frame(6), 5)

    def test_lease_rejection_matrix(self):
        for mode in ("replay", "nonce", "manifest", "duplicate", "cancel", "extra", "oversized", "burst", "late"):
            lease = self.lease()
            lease.feed(lease.frame(0), 0)
            raw, now = lease.frame(1), 0.1
            if mode == "replay": raw = lease.frame(0)
            if mode == "nonce": raw = raw.replace(NONCE.encode(), b"c" * 32)
            if mode == "manifest": raw = raw.replace(DIGEST.encode(), b"d" * 64)
            if mode == "duplicate": raw = raw[:-2] + b',"sequence":1}\n'
            if mode == "cancel": raw = lease.frame(1, "cancel")
            if mode == "extra": raw = raw[:-2] + b',"extra":true}\n'
            if mode == "oversized": raw = b"x" * 513
            if mode == "burst": raw += raw
            if mode == "late": now = 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                lease.feed(raw, now)

    def test_host_and_guest_lease_cannot_be_interchanged(self):
        guest = self.lease()
        host = supervision.Lease(NONCE, DIGEST, started=0, total=620, silence=15, side="host")
        with self.assertRaisesRegex(ValueError, "invalid lease"):
            host.feed(guest.frame(0), 0)
        with self.assertRaisesRegex(ValueError, "invalid lease"):
            guest.feed(host.frame(0), 0)
        with self.assertRaises(ValueError):
            supervision.Lease(NONCE, DIGEST, started=0, total=620, side="guest")


class SimWorker:
    def __init__(self, mode, events):
        self.mode, self.events, self.killed = mode, events, False
        self.admission_fd = 7

    def spawn(self):
        self.events.append("spawn")
        return 1234

    def release(self):
        self.events.append("release")

    def admit_setup(self):
        self.events.append("setup")

    def ready(self):
        return self.mode != "setup-hang"

    def poll(self):
        if self.mode in {"hang", "kill-failed", "setup-hang"} and not self.killed:
            return None
        return 17 if self.mode == "worker-failed" else 0

    def cancel_admission(self):
        self.events.append("close-admission")


class SimBoundary:
    def __init__(self, worker, events):
        self.worker, self.events, self.attached = worker, events, False

    def attach(self, pid):
        self.events.append(("attach", pid))
        self.attached = True
        if self.worker.mode == "attach-failed":
            raise OSError("synthetic attach readback failed")

    def populated(self):
        if not self.attached:
            return False
        if self.worker.mode == "descendants" and not self.worker.killed:
            return True
        return self.worker.poll() is None

    def kill(self):
        self.events.append("cgroup.kill")
        if self.worker.mode == "kill-failed":
            raise OSError("synthetic kill failure")
        self.worker.killed = True


class SupervisorTests(unittest.TestCase):
    def scenario(self, mode):
        events, clock = [], [0.0]
        worker = SimWorker(mode, events)
        boundary = SimBoundary(worker, events)
        guard = Mock()
        if mode == "guard-failed":
            guard.before_admission.side_effect = ValueError("synthetic baseline failure")
        if mode == "guard-changed":
            guard.check.side_effect = [ValueError("synthetic identity changed"), ValueError("sticky")]
        read_fd, write_fd = os.pipe()
        lease = supervision.Lease(NONCE, DIGEST, started=0, total=1, silence=0.2)
        if mode != "missing-initial":
            lease.feed(lease.frame(0), 0)
        if mode == "eof":
            os.close(write_fd)
            write_fd = None
        try:
            result = supervision.supervise(worker, boundary, guard, read_fd, lease, clock=lambda: clock[0],
                        pause=lambda seconds: clock.__setitem__(0, clock[0] + seconds), cleanup_seconds=0.1)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
        return result, events, clock[0]

    def test_admission_order_and_success(self):
        result, events, _ = self.scenario("ok")
        self.assertTrue(result["passed"], result)
        self.assertEqual(events[:4], ["spawn", ("attach", 1234), "setup", "release"])
        self.assertIn("cgroup.kill", events)
        self.assertFalse(result["i5_ready"])

    def test_failure_cleanup_matrix(self):
        for mode in ("hang", "setup-hang", "worker-failed", "descendants", "attach-failed", "guard-changed", "kill-failed"):
            with self.subTest(mode=mode):
                result, events, elapsed = self.scenario(mode)
                self.assertFalse(result["passed"])
                self.assertTrue(result["failure"] or result["cleanup_errors"])
                self.assertIn("cgroup.kill", events)
                self.assertLess(elapsed, 0.5)
                if mode in {"attach-failed", "guard-changed"}:
                    self.assertNotIn("release", events)
                if mode == "kill-failed":
                    self.assertIn("lease expired", result["failure"])
                    self.assertEqual(len(result["cleanup_errors"]), 2)

    def test_initial_rejection_never_starts_or_kills(self):
        for mode in ("guard-failed", "missing-initial", "eof"):
            result, events, _ = self.scenario(mode)
            self.assertFalse(result["passed"])
            self.assertEqual(events, [])

    def test_real_independent_process_handles_blocked_worker_and_pipe_loss(self):
        # Only this synthetic boundary uses an exact owned PID. Production
        # CgroupV2.kill uses the bound kernel cgroup and never this fake.
        class RealSyntheticBoundary:
            pid = None
            killed = False
            def attach(self, pid): self.pid = pid
            def populated(self): return self.pid is not None and not self.killed
            def kill(self):
                if self.pid:
                    try:
                        os.kill(self.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.killed = True
        for mode in ("silent", "closed", "result-lost", "setup-error", "worker-killed"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="radishlink-supervisor-") as directory:
                marker = Path(directory) / "worker"
                def work():
                    marker.write_text(str(os.getpid()))
                    if mode == "worker-killed":
                        os.kill(os.getpid(), signal.SIGKILL)
                    time.sleep(2)
                    return 0
                def prepare():
                    if mode == "setup-error":
                        raise OSError("synthetic namespace setup rejected")
                pid, writer, reader = supervision.fork_supervisor(work, RealSyntheticBoundary(), Mock(), NONCE, DIGEST,
                                    total=1, silence=0.2, subreaper=lambda: None, prepare=prepare)
                try:
                    frame = supervision.Lease(NONCE, DIGEST, started=0, total=1, silence=0.2).frame(0)
                    os.write(writer, frame)
                    if mode != "setup-error":
                        until = time.monotonic() + 0.5
                        while not marker.exists() and time.monotonic() < until:
                            time.sleep(0.005)
                        self.assertTrue(marker.exists(), "worker not admitted")
                    if mode == "closed":
                        os.close(writer)
                        writer = None
                    if mode == "result-lost":
                        os.close(reader)
                        reader = None
                    if reader is not None:
                        ready, _, _ = select.select([reader], [], [], 2)
                        self.assertTrue(ready)
                        result = json.loads(os.read(reader, supervision.MAX_REPORT + 1))
                        self.assertFalse(result["passed"])
                        self.assertTrue(result["population_empty"])
                        self.assertTrue(result["reaped"])
                        expected = {"closed": "closed", "setup-error": "synthetic namespace", "worker-killed": "-9"}.get(mode, "expired")
                        self.assertIn(expected, result["failure"])
                    self.assertEqual(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]), 2)
                    if mode == "setup-error":
                        self.assertFalse(marker.exists(), "tools ran after setup failed")
                    else:
                        with self.assertRaises(ProcessLookupError):
                            os.kill(int(marker.read_text()), 0)
                finally:
                    if writer is not None: os.close(writer)
                    if reader is not None: os.close(reader)
                    try:
                        os.waitpid(pid, 0)
                    except ChildProcessError:
                        pass

    def test_host_watchdog_overflow_lost_result_and_recovery_failure(self):
        for mode in ("valid", "empty", "invalid", "overflow", "silent", "closed-lease", "recovery-failed", "cancel"):
            with self.subTest(mode=mode):
                lease_read, lease_write = os.pipe()
                result_read, result_write = os.pipe()
                lease = supervision.Lease(NONCE, DIGEST, started=time.monotonic(), total=0.2, silence=0.05, side="host")
                lease.feed(lease.frame(0), time.monotonic())
                recover = Mock(return_value={"stopped": True, "passed": False})
                validate = Mock(side_effect=ValueError("wrong result binding") if mode == "invalid" else None)
                if mode == "cancel": validate.side_effect = lambda _: os.kill(os.getpid(), signal.SIGTERM)
                if mode == "recovery-failed": recover.side_effect = OSError("synthetic recovery lost")
                try:
                    if mode in {"valid", "invalid", "cancel"}: os.write(result_write, b"synthetic result")
                    if mode == "overflow": os.write(result_write, b"x" * 65)
                    if mode != "silent":
                        os.close(result_write)
                        result_write = None
                    if mode == "closed-lease":
                        os.close(lease_write)
                        lease_write = None
                    result = supervision.watch_transport(lease_read, result_read, lease, validate=validate,
                                                         recover=recover, transport_limit=64)
                    self.assertEqual(result["transport_complete"], mode == "valid")
                    self.assertFalse(result["i5_ready"])
                    self.assertEqual(recover.call_count, 0 if mode == "valid" else 1)
                    if mode == "recovery-failed":
                        self.assertIn("without result", result["failure"])
                        self.assertFalse(result["recovery"]["stopped"])
                finally:
                    for fd in (lease_read, lease_write, result_read, result_write):
                        if fd is not None: os.close(fd)


class RecoveryTests(unittest.TestCase):
    def test_v2_operation_binds_all_isolation_sources_and_keeps_v1_separate(self):
        observed = {"base_revision": "a" * 40, "hashes": {name: "a" * 64 for name in control.ISOLATION_SOURCES},
                    "config_sha256": "b" * 64, "utmctl_sha256": "c" * 64, "manifest_sha256": "d" * 64,
                    "isolation_sha256": "f" * 64,
                    "media": {"path": "/synthetic/input.iso", "bytes": 1234, "sha256": "e" * 64, "read_only": True}}
        record = dict(observed, schema_version=2, scope="i5-preparation-apt-operation", nonce=NONCE,
                      uuid=isolation.UUID, authorized=True, guest_seconds=540, host_seconds=620, total_seconds=900,
                      lease_seconds=15, cleanup_seconds=20)
        control.validate_apt_operation(record, NONCE, observed)
        for key, value in (("isolation_sha256", "a" * 64), ("cleanup_seconds", 30), ("lease_seconds", True),
                           ("schema_version", 1), ("hashes", {name: "a" * 64 for name in control.APT_SOURCES})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                control.validate_apt_operation(dict(record, **{key: value}), NONCE, observed)

    def scenario(self, mode):
        clock, calls, state = [0.0], [], ["started"]
        ticket = {"schema_version": 1, "scope": "i5-preparation-recovery", "nonce": NONCE,
                  "uuid": isolation.UUID, "config_sha256": "c" * 64, "media_sha256": "d" * 64,
                  "start_attempted": mode != "not-started", "status_before": "stopped"}
        def observe(timeout):
            self.assertLessEqual(timeout, 5)
            if mode == "observe-late": clock[0] += 121
            result = {key: ticket[key] for key in ("nonce", "uuid", "config_sha256", "media_sha256")}
            result["status"] = "stopped" if mode == "already-stopped" else state[0]
            if mode == "identity-changed": result["media_sha256"] = "e" * 64
            if mode == "state-unknown": result["status"] = "paused"
            return result
        def command(argv, timeout, limit):
            calls.append(argv)
            self.assertEqual(argv[:3], [str(control.UTMCTL), "stop", isolation.UUID])
            self.assertLessEqual(timeout, 10)
            self.assertEqual(limit, 65536)
            if mode == "graceful" or (argv[-1] == "--force" and mode != "force-failed"):
                state[0] = "stopped"
            return {"exit_code": 1 if mode == "force-failed" else 0, "stdout": b"", "stderr": b"",
                    "failure": "deadline" if mode == "command-timeout" else None, "cleanup_errors": []}
        result = control.recover_preparation(ticket, observe=observe, command=command, clock=lambda: clock[0],
                                            pause=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        return result, calls, clock[0]

    def test_no_authority_or_wrong_identity_never_stops_vm(self):
        for mode in ("not-started", "identity-changed", "state-unknown", "observe-late", "already-stopped"):
            result, calls, _ = self.scenario(mode)
            self.assertEqual(calls, [])
            self.assertFalse(result["passed"])

    def test_graceful_force_timeout_and_failed_recovery_keep_failure(self):
        for mode in ("graceful", "force", "command-timeout", "force-failed"):
            with self.subTest(mode=mode):
                result, calls, elapsed = self.scenario(mode)
                self.assertFalse(result["passed"])
                self.assertFalse(result["i5_ready"])
                self.assertEqual(result["failure"], "preparation contact lost")
                self.assertEqual(sum(call[-1] == "--request" for call in calls), 1)
                self.assertEqual(sum(call[-1] == "--force" for call in calls), 0 if mode == "graceful" else 1)
                self.assertLessEqual(elapsed, 120)
                self.assertEqual(result["stopped"], mode != "force-failed")
                if mode in {"command-timeout", "force-failed"}:
                    self.assertTrue(result["cleanup_errors"])


if __name__ == "__main__":
    unittest.main()
