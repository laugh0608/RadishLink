"""MemorySyscalls and owned synthetic processes only; no Linux/VM mutation."""

import copy
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels
import sw_i5_preparation_native_lifecycle as lifecycle
import sw_i5_preparation_supervisor as supervision
import test_sw_i5_channels as channel_fixtures
import test_sw_i5_native as native_fixtures

NONCE = native_fixtures.NONCE


def fixture():
    manifest, content = native_fixtures.manifest_fixture()
    digest = hashlib.sha256(manifest).hexdigest()
    contract = native_fixtures.encode(dict(schema_version=1, scope="i5-preparation-isolation", nonce=NONCE, uuid=apt.UUID,
        manifest_sha256=digest, root=native_fixtures.ROOT + "/" + NONCE, input=native_fixtures.INPUT,
        uid=61000, gid=61000, i5_ready=False))
    system = native_fixtures.MemorySyscalls(content)
    expected = {role: dict(dev=system.nodes[path].dev, ino=system.nodes[path].ino, mount_id=mount)
                for role, path, mount in (("root_parent", native_fixtures.ROOT, 21),
                    ("cgroup_root", native_fixtures.GROUP, 22), ("readonly_input", native_fixtures.INPUT, 23))}
    config = lifecycle.NativeGuestConfig(contract, manifest, expected=expected, delivery_sha256="d" * 64)
    return config, system


class NativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radishlink-native-lifecycle-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config, self.system = fixture()
        self.marker = self.root / "worker"
        self.owner_marker = self.root / "owner"
        self.result_dir = self.root / "result"
        self.result_dir.mkdir()
        self.budget = lifecycle.NativeBudget(init=2, active=2, cleanup=0.6, reap=0.6, output=0.6, silence=1)

    def start(self, mode="normal"):
        control_read, control_write = os.pipe()
        output_read, output_write = os.pipe()
        ack_read, ack_write = os.pipe()
        ready_read, ready_write = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.setsid()
            def factory():
                self.owner_marker.write_text(str(os.getpid()))
                if mode == "init-hang": time.sleep(10)
                if mode == "owner-killed": os.kill(os.getpid(), signal.SIGKILL)
                if mode == "partial": self.system.fail_open = native_fixtures.ROOT + "/" + NONCE + "/work"
                if mode == "cleanup-hang":
                    def hook(action, path):
                        if action == "stat" and path.endswith("/ack.slot"): time.sleep(10)
                    self.system.hook = hook
                return self.system
            def work():
                self.marker.write_text(str(os.getpid()))
                if mode in ("worker-hang", "cancel", "kill-after-ready"): time.sleep(10)
                channel_fixtures.result_files(self.result_dir, channel_fixtures.success_summary(NONCE, self.config.digest))
                if mode == "output-blocked":
                    for name in ("worker.stdout", "worker.stderr"):
                        (self.result_dir / name).write_bytes(b"x" * 65536)
                return 0
            adapters = lifecycle.NativeTaskAdapters(work=work, boundary=channel_fixtures.SyntheticBoundary(), guard=Mock(),
                prepare=lambda: None, subreaper=lambda: None,
                exporter=channel_fixtures.SyntheticExport(self.result_dir, digest=self.config.digest))
            try:
                original_owner = lifecycle._owner
                if mode == "report-lost":
                    def drop_report(*args):
                        owner_pid, destination = os.getpid(), args[2]
                        original_write = channels.write_bounded
                        def write(fd, raw, **kwargs):
                            if os.getpid() == owner_pid and fd == destination:
                                os.close(fd)
                                raise BrokenPipeError("synthetic owner report lost")
                            return original_write(fd, raw, **kwargs)
                        with patch.object(channels, "write_bounded", side_effect=write): original_owner(*args)
                    lifecycle._owner = drop_report
                if mode == "registration-hang":
                    original_supervisor = supervision.fork_supervisor
                    def blocked_registration(*args, **kwargs):
                        register = kwargs["register_supervisor"]
                        def blocked(pid):
                            register(pid)
                            time.sleep(10)
                        kwargs["register_supervisor"] = blocked
                        return original_supervisor(*args, **kwargs)
                    supervision.fork_supervisor = blocked_registration
                code = lifecycle.run_native_guest(self.config, control_read, output_write, ack_write,
                    syscalls_factory=factory, task_adapters=adapters, budget=self.budget, ready_fd=ready_write)
            except BaseException as exc:
                self.root.joinpath("error").write_text(type(exc).__name__ + ": " + str(exc))
                code = 3
            os._exit(code)
        for fd in (control_read, output_write, ack_write, ready_write): os.close(fd)
        return pid, control_write, output_read, ack_read, ready_read

    def collect(self, handles, *, cancel=False, kill_owner=False):
        pid, writer, reader, ack, ready = handles
        lease = supervision.Lease(NONCE, self.config.digest, started=0, total=2, silence=1)
        sequence, next_renew, raw, ready_raw, code = 0, 0, bytearray(), bytearray(), None
        acknowledged = True
        killed = False
        until = time.monotonic() + self.budget.total + 2
        try:
            while time.monotonic() < until:
                now = time.monotonic()
                if writer is not None and ready_raw and acknowledged and now >= next_renew:
                    try: os.write(writer, lease.frame(sequence))
                    except BrokenPipeError: os.close(writer); writer = None
                    sequence += 1
                    acknowledged = False
                    next_renew = now + 0.3
                if cancel and self.marker.exists() and writer is not None:
                    os.close(writer); writer = None
                if kill_owner and self.marker.exists() and not killed:
                    os.kill(int(self.owner_marker.read_text()), signal.SIGKILL)
                    killed = True
                fds, _, _ = select.select([reader, ack, ready], [], [], 0.02)
                for fd in fds:
                    data = os.read(fd, 65536)
                    if fd == reader: raw.extend(data)
                    if fd == ready: ready_raw.extend(data)
                    if fd == ack and data: acknowledged = True
                if code is None:
                    done, status = os.waitpid(pid, os.WNOHANG)
                    if done: code = os.waitstatus_to_exitcode(status)
                if code is not None:
                    while True:
                        data = os.read(reader, 65536)
                        if not data: break
                        raw.extend(data)
                    break
            self.assertIsNotNone(code, "invocation parent remained alive")
            self.assertTrue(raw, self.root.joinpath("error").read_text() if self.root.joinpath("error").exists() else "empty native result")
            value = lifecycle.validate_native_export(bytes(raw), NONCE, self.config.digest)
            self.assertEqual(code, 0 if value["passed"] else 2)
            if value["native_lifecycle"]["initialization"] is not None:
                packet = json.loads(ready_raw)
                self.assertEqual(packet["delivery_sha256"], self.config.delivery_sha256)
            return value
        finally:
            for fd in (writer, reader, ack, ready):
                if fd is not None: os.close(fd)
            if code is None:
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)

    def test_complete_actual_native_owner_and_existing_task_supervisor(self):
        value = self.collect(self.start())
        self.assertTrue(value["passed"], (value["native_lifecycle"]["first_failure"], value["task_export"]))
        facts = value["native_lifecycle"]
        self.assertEqual(len(facts["registered"]), 27)
        self.assertEqual(facts["pending"], {})
        self.assertEqual(facts["cleanup"]["errors"], [])
        self.assertTrue(facts["fd_closed"])
        self.assertNotEqual(self.owner_marker.read_text(), self.marker.read_text())
        self.assertFalse(self.system.calls, "parent's MemorySyscalls must never execute native operations")

    def test_cancel_stops_work_and_preserves_unconfirmed_cleanup(self):
        value = self.collect(self.start("cancel"), cancel=True)
        self.assertFalse(value["passed"])
        self.assertIn("control EOF", value["native_lifecycle"]["first_failure"])
        self.assertTrue(value["native_lifecycle"]["owner_reaped"])

    def test_blocked_single_syscall_factory_is_bounded_externally(self):
        started = time.monotonic()
        value = self.collect(self.start("init-hang"))
        self.assertFalse(value["passed"])
        self.assertLess(time.monotonic() - started, self.budget.total)
        self.assertFalse(self.marker.exists())

    def test_killed_owner_is_not_recreated_or_reclaimed_by_path(self):
        value = self.collect(self.start("owner-killed"))
        facts = value["native_lifecycle"]
        self.assertFalse(value["passed"])
        self.assertIsNone(facts["cleanup"])
        self.assertFalse(facts["fd_closed"])
        self.assertEqual(facts["owner_exit"], -signal.SIGKILL)
        self.assertFalse(self.marker.exists())

    def test_native_budget_uses_one_existing_guest_total(self):
        self.assertEqual(lifecycle.NativeBudget().total, 540)
        for kwargs in ({"active": 529}, {"init": True}, {"reap": 3}):
            with self.assertRaises(ValueError): lifecycle.NativeBudget(**kwargs)

    def test_partial_creation_preserves_unbound_object_and_never_runs_task(self):
        value = self.collect(self.start("partial"))
        facts = value["native_lifecycle"]
        self.assertFalse(value["passed"])
        self.assertIsNone(facts["initialization"])
        self.assertEqual(facts["pending"]["work"]["state"], "intent")
        self.assertTrue(facts["cleanup"]["errors"])
        self.assertFalse(self.marker.exists())

    def test_owner_killed_after_ready_retains_nine_objects_and_stops_registered_task(self):
        value = self.collect(self.start("kill-after-ready"), kill_owner=True)
        facts = value["native_lifecycle"]
        self.assertFalse(value["passed"])
        self.assertEqual(len(facts["pending"]), 9)
        self.assertTrue(all(row["state"] == "bound" for row in facts["pending"].values()))
        self.assertIsNone(facts["cleanup"])
        self.assertFalse(facts["task_supervisor_reaped"])
        self.assertFalse(facts["task_worker_reaped"])
        self.assertEqual(facts["processes"]["worker"], int(self.marker.read_text()))
        for role in ("supervisor", "worker"):
            ticket = facts["processes"][role]
            until = time.monotonic() + 0.8
            absent = False
            while time.monotonic() < until:
                try: os.kill(ticket, 0)
                except ProcessLookupError:
                    absent = True
                    break
                time.sleep(0.01)
            self.assertTrue(absent, role + " process remains after exact registered group settlement")
        # Absence is a stop observation; it does not turn either unknown reap
        # fact above into a successful waitpid result.

    def test_blocked_cleanup_syscall_is_killed_without_path_reclamation(self):
        started = time.monotonic()
        value = self.collect(self.start("cleanup-hang"))
        self.assertFalse(value["passed"])
        self.assertLess(time.monotonic() - started, self.budget.total)
        self.assertIn("cleanup deadline", value["native_lifecycle"]["first_failure"])
        self.assertIsNone(value["native_lifecycle"]["cleanup"])
        self.assertEqual(len(value["native_lifecycle"]["pending"]), 9)

    def test_owner_report_loss_does_not_reconstruct_backend(self):
        value = self.collect(self.start("report-lost"))
        facts = value["native_lifecycle"]
        self.assertFalse(value["passed"])
        self.assertIn("result lost", facts["first_failure"])
        self.assertIsNone(facts["cleanup"])
        self.assertFalse(facts["fd_closed"])
        self.assertEqual(facts["pending"], {}, "cleaned registration remains evidence, not a reconstructed cleanup report")

    def test_blocked_registration_is_cancelled_before_supervisor_admission(self):
        value = self.collect(self.start("registration-hang"))
        self.assertFalse(value["passed"])
        self.assertFalse(self.marker.exists())
        self.assertTrue(value["native_lifecycle"]["processes"]["supervisor"])
        self.assertIsNone(value["native_lifecycle"]["cleanup"], "unconfirmed task cannot grant cleanup")

    def test_blocked_final_output_expires_inside_original_output_reserve(self):
        pid, writer, reader, ack, ready = self.start("output-blocked")
        started = time.monotonic()
        code = None
        try:
            readable, _, _ = select.select([ready], [], [], self.budget.init + 0.3)
            self.assertTrue(readable)
            self.assertTrue(os.read(ready, 8192))
            frame = supervision.Lease(NONCE, self.config.digest, started=0, total=2, silence=1).frame(0)
            os.write(writer, frame)
            # Deliberately leave the final output pipe unread. The task export
            # is larger than the OS pipe capacity, so P must bound its write.
            code = channels.wait_child(pid, time.monotonic() + 3)
            self.assertEqual(code, 3)
            self.assertLess(time.monotonic() - started, 3)
            self.assertIn("deadline", self.root.joinpath("error").read_text())
        finally:
            for fd in (writer, reader, ack, ready): os.close(fd)
            if code is None:
                os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)

    def test_envelope_rejects_recursion_flags_and_pending_forgery(self):
        baseline = self.collect(self.start())
        changes = (lambda v: v.update(task_export=v.copy()),
                   lambda v: v["native_lifecycle"].update(physical_verified=True),
                   lambda v: v["native_lifecycle"].update(pending={"guest_root": {}}),
                   lambda v: v["native_lifecycle"].update(owner_exit=True))
        for change in changes:
            value = copy.deepcopy(baseline)
            change(value)
            with self.assertRaises(ValueError): lifecycle.validate_native_export(channels.encode(value), NONCE, self.config.digest)

    def test_recomputed_full_observation_mutations_are_rejected(self):
        baseline = self.collect(self.start())
        mutations = (lambda x: x.update(input_bytes=True),
                     lambda x: x.update(unknown="field"),
                     lambda x: x["cgroup_snapshots"]["worker"].update(procs=[123]),
                     lambda x: x["cgroup_snapshots"]["worker"]["events"].update(populated=1),
                     lambda x: x["cgroup_snapshots"]["worker"]["events"].update(populated=False),
                     lambda x: x["objects"]["work"]["after"].update(dev=True),
                     lambda x: x["objects"]["lease"]["independent_readback"].update(bytes=1024.0),
                     lambda x: x["prerequisite_observations"]["root_parent"].update(capacity_bytes=True))
        for mutate in mutations:
            value = copy.deepcopy(baseline)
            for name in ("initialization", "independent_readback"): mutate(value["native_lifecycle"][name])
            with self.assertRaises(ValueError): lifecycle.validate_native_export(channels.encode(value), NONCE, self.config.digest)

    def test_registration_order_error_projection_and_same_value_types_rejected(self):
        baseline = self.collect(self.start())
        mutations = (lambda x: x["registered"].__setitem__(slice(0, 4), [x["registered"][0], x["registered"][2], x["registered"][1], x["registered"][3]]),
                     lambda x: x["cleanup"].update(errors=["omitted error"]),
                     lambda x: x["cleanup"]["cleaned"].reverse(),
                     lambda x: x["processes"].update(owner=True))
        for mutate in mutations:
            value = copy.deepcopy(baseline)
            mutate(value["native_lifecycle"])
            with self.assertRaises(ValueError): lifecycle.validate_native_export(channels.encode(value), NONCE, self.config.digest)

    def test_supervisor_registration_failure_reaps_direct_child_and_never_admits_worker(self):
        recorded = []
        def rejected(pid):
            recorded.append(pid)
            raise ValueError("synthetic registration rejected")
        with self.assertRaisesRegex(ValueError, "registration rejected"):
            supervision.fork_supervisor(lambda: self.marker.write_text("forbidden"), channel_fixtures.SyntheticBoundary(),
                Mock(), NONCE, self.config.digest, total=1, silence=0.5, subreaper=lambda: None,
                register_supervisor=rejected, cleanup_seconds=0.3, absolute_deadline=time.monotonic() + 0.4)
        self.assertEqual(len(recorded), 1)
        with self.assertRaises(ChildProcessError): os.waitpid(recorded[0], os.WNOHANG)
        self.assertFalse(self.marker.exists())


if __name__ == "__main__": unittest.main()
