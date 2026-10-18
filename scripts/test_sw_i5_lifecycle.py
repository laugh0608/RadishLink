"""Synthetic lifecycle acceptance. No native Application, VM or real tools."""

import array
import base64
import copy
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import sw_i5_preparation_channels as channels
import sw_i5_preparation_evidence as evidence
import sw_i5_preparation_lifecycle as lifecycle
import sw_i5_preparation_rpc as process_rpc
import sw_i5_preparation_transport as transport
import test_sw_i5_transport as fixtures

NONCE, DIGEST = fixtures.NONCE, fixtures.DIGEST


def result(request, *, forced=False):
    return dict(request, scope="i5-preparation-lifecycle-action-result",
        status={"start": "started", "readiness": "ready", "shutdown": "stopped"}[request["action"]], forced_stop=forced)


def budget(**changes):
    values = dict(total=25, silence=2, init=1, start=1, readiness=1, active=10, watchdog_cleanup=0.5,
                  watchdog_report=0.5, shutdown=1, persist=1, output=0.5, reap=0.5)
    values.update(changes)
    return lifecycle.Budget(**values)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radishlink-lifecycle-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / "output"
        self.output.mkdir()
        self.raw = channels.encode(fixtures.export_fixture(self.output))
        self.parent = self.root / "evidence"
        self.parent.mkdir(mode=0o700)
        self.log = self.root / "actions.jsonl"
        self.children = []
        self.addCleanup(self.reap)

    def reap(self):
        for pid, writer, reader in self.children:
            for fd in (writer, reader):
                try: os.close(fd)
                except OSError: pass
            try:
                code = channels.wait_child(pid, time.monotonic() + 1)
                if code is None:
                    os.kill(pid, signal.SIGTERM)
                    code = channels.wait_child(pid, time.monotonic() + 4)
                    if code is None: os.killpg(pid, signal.SIGKILL); os.waitpid(pid, 0)
            except (ChildProcessError, ProcessLookupError): pass

    def adapter(self, mode="ok"):
        def action(request):
            with self.log.open("a") as file: file.write(json.dumps(request) + "\n")
            if mode == request["action"] + "-fail": raise RuntimeError("synthetic " + request["action"] + " failure")
            if mode == request["action"] + "-hang": time.sleep(10)
            if mode == "start-lost" and request["action"] == "start": os._exit(0)
            if mode == "unexpected" and request["action"] == "start": raise KeyError("synthetic missing callback field")
            if mode == "unicode" and request["action"] in ("start", "shutdown"):
                raise RuntimeError("原始失败" * 3000)
            if mode == "identity" and request["action"] == "readiness": return dict(result(request), nonce="f" * 32)
            return result(request, forced=mode == "forced" and request["action"] == "shutdown")
        return action

    def start(self, mode="ok", *, api=None, limits=None):
        callback = self.adapter(mode)
        values = lifecycle.fork_lifecycle(self.parent, transport.transport_request(NONCE, DIGEST, b"synthetic"),
            rpc=api or fixtures.FakeUTM(self.raw), start=callback, readiness=callback, shutdown=callback,
            budget=limits or budget())
        self.children.append(values)
        return values

    def collect(self, values):
        pid, writer, reader = values
        raw = bytearray()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ready, _, _ = select.select([reader], [], [], 0.02)
            if not ready: continue
            data = os.read(reader, 65536)
            if not data: break
            raw.extend(data)
            self.assertLessEqual(len(raw), 16384)
        code = channels.wait_child(pid, deadline)
        self.assertIsNotNone(code)
        return json.loads(raw), code

    def actions(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_complete_owner_chain_stop_and_v2_durable_reopen(self):
        value, code = self.collect(self.start())
        self.assertEqual(code, 0, value)
        self.assertTrue(value["passed"], value)
        self.assertEqual([v["action"] for v in self.actions()], ["start", "readiness", "shutdown"])
        self.assertEqual(self.actions()[-1]["mode"], "normal")
        self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])
        self.assertEqual(value["receipt"]["schema_version"], 2)
        self.assertFalse(value["receipt"]["i5_ready"])

    def fresh(self, name):
        self.parent = self.root / name
        self.parent.mkdir(mode=0o700)
        if self.log.exists(): self.log.unlink()

    def wait_for(self, predicate, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                if predicate(): return
            except (FileNotFoundError, json.JSONDecodeError): pass
            time.sleep(0.01)
        self.fail("synthetic synchronization deadline")

    def process_api(self, *, lost=False, blocked=False, record=None):
        helper, state, payload = self.root / "rpc-child.py", self.root / "rpc-state.json", self.root / "export.json"
        source = fixtures.RPC_CHILD_SOURCE
        if blocked: source = source.replace('if s["lost"] and action == "execute":',
            'if action == "execute":\n    import time\n    time.sleep(10)\nif s["lost"] and action == "execute":')
        helper.write_text(source)
        state.write_text(json.dumps({"slots": {str(i): base64.b64encode(bytes(1024)).decode() for i in (10, 11)},
            "calls": [], "executes": 0, "polls": 0, "lost": lost}))
        payload.write_bytes(self.raw)
        def launch(argv, **kwargs):
            if record is not None: record.write_text(json.dumps({"transport": os.getpid(), "watchdog": os.getppid()}))
            return subprocess.Popen(argv, **kwargs)
        return process_rpc.ProcessRPC((sys.executable, "-I", "-B", str(helper), str(state), str(payload)), NONCE, DIGEST,
                                      launcher=launch), state

    def test_actual_process_rpc_chain_and_execute_effect_with_lost_return(self):
        for lost in (False, True):
            self.fresh("lost" if lost else "real-chain")
            api, state = self.process_api(lost=lost)
            value, code = self.collect(self.start(api=api))
            self.assertEqual(value["passed"], not lost, value)
            self.assertEqual(code, 2 if lost else 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["executes"], 1)
            self.assertEqual([a[1]["handle"] for a in observed["calls"] if a[0] == "close"], [10, 11])
            self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)
            self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])
            if lost: self.assertIn("RPC response limit", value["lifecycle"]["first_failure"])
            else: self.assertEqual([a[1]["process"] for a in observed["calls"] if a[0] == "result"], [777, 777])

    def test_start_readiness_stop_failure_timeout_identity_and_forced_matrix(self):
        for mode in ("start-fail", "start-hang", "start-lost", "readiness-fail", "readiness-hang", "identity",
                     "shutdown-fail", "shutdown-hang", "forced", "unexpected"):
            with self.subTest(mode=mode):
                self.fresh(mode)
                value, code = self.collect(self.start(mode, limits=budget(start=0.15, readiness=0.15, shutdown=0.15)))
                self.assertEqual(code, 2, value)
                self.assertFalse(value["passed"], value)
                self.assertTrue(value["lifecycle"]["first_failure"])
                actions = self.actions()
                self.assertEqual(sum(a["action"] == "start" for a in actions), 1)
                self.assertEqual(sum(a["action"] == "shutdown" for a in actions), 1)
                self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])
                if mode.startswith("start") or mode == "unexpected":
                    self.assertEqual([a["action"] for a in actions], ["start", "shutdown"])
                if mode.startswith("shutdown"):
                    self.assertTrue(value["receipt"]["accepted"])
                    self.assertTrue(value["lifecycle"]["cleanup_errors"])

    def test_rpc_ack_response_and_limit_failures_remain_failed_after_shutdown(self):
        for mode in ("bad-ack", "bad-readback", "replay", "rpc-lost", "signal", "stderr", "exit"):
            with self.subTest(mode=mode):
                self.fresh(mode)
                with patch.object(channels, "bounded_recovery", side_effect=AssertionError("deferred recovery forked")):
                    value, code = self.collect(self.start(api=fixtures.FakeUTM(self.raw, mode)))
                self.assertEqual(code, 2, value)
                self.assertFalse(value["passed"])
                self.assertEqual(self.actions()[-1]["mode"], "recovery")
                self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)
                self.assertIn("UTM", value["lifecycle"]["first_failure"])
                host = json.loads((self.parent / NONCE / "host-report.bin").read_bytes())
                self.assertEqual(host["watchdog"]["recovery"], {"stopped": False, "passed": False, "i5_ready": False, "deferred": True})

    def test_consumed_nonce_refuses_start_and_preserves_existing_receipt(self):
        first, code = self.collect(self.start())
        self.assertEqual(code, 0)
        old = (self.parent / NONCE / "receipt.json").read_bytes()
        self.log.unlink()
        second, code = self.collect(self.start())
        self.assertEqual(code, 2)
        self.assertEqual(self.actions(), [])
        self.assertIsNone(second["receipt"])
        self.assertEqual((self.parent / NONCE / "receipt.json").read_bytes(), old)
        self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), first["receipt"])

    def test_attempt_fsync_block_and_readback_failure_prevent_start(self):
        for target in ("fsync", "readback"):
            self.fresh("init-" + target)
            if target == "fsync": context = patch.object(os, "fsync", side_effect=lambda fd: time.sleep(10))
            else: context = patch.object(evidence.EvidenceStore, "verify_attempt", side_effect=ValueError("attempt readback mismatch"))
            with context:
                values = self.start(limits=budget(init=0.6))
                value, code = self.collect(values)
            self.assertEqual(code, 2, value)
            self.assertFalse(value["lifecycle"]["start_attempted"])
            self.assertEqual(self.actions(), [])
            self.assertIsNone(value["receipt"])
            self.assertTrue((self.parent / NONCE).exists())
            with self.assertRaises(ValueError): evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST)

    def test_persist_block_is_unconfirmed_no_retry_or_second_shutdown(self):
        with patch.object(evidence.EvidenceStore, "persist", side_effect=lambda *a, **k: time.sleep(10)):
            value, code = self.collect(self.start(limits=budget(persist=0.15)))
        self.assertEqual(code, 2, value)
        self.assertIsNone(value["receipt"])
        self.assertIn("deadline", value["persistence_error"])
        self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)
        with self.assertRaises(ValueError): evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST)

    def test_control_eof_while_rpc_blocked_cancels_and_stops_once(self):
        api, state = self.process_api(blocked=True)
        values = self.start(api=api)
        self.wait_for(lambda: json.loads(state.read_text())["executes"] == 1)
        os.close(values[1])
        value, code = self.collect(values)
        self.assertEqual(code, 2, value)
        self.assertIn("controller liveness EOF", value["lifecycle"]["first_failure"])
        self.assertEqual(self.actions()[-1]["mode"], "recovery")
        self.assertEqual(json.loads(state.read_text())["executes"], 1)

    def test_watchdog_sigkill_after_registration_and_before_transport_fork(self):
        record = self.root / "registered-pids.json"
        api, state = self.process_api(blocked=True, record=record)
        values = self.start(api=api)
        self.wait_for(lambda: json.loads(state.read_text())["executes"] == 1)
        pids = json.loads(record.read_text())
        os.kill(pids["watchdog"], signal.SIGKILL)
        value, code = self.collect(values)
        self.assertEqual(code, 2, value)
        self.assertIn("watchdog exit/signal: -9", value["lifecycle"]["first_failure"])
        self.assertEqual(self.actions()[-1]["mode"], "recovery")
        self.assertEqual(json.loads(state.read_text())["executes"], 1)
        self.fresh("watchdog-before-fork")
        original = channels.fork_watchdog
        def killed(*args, **kwargs):
            values = original(*args, **kwargs)
            os.kill(values[0], signal.SIGKILL)  # No initial lease sent yet: child not forked/admitted.
            return values
        with patch.object(channels, "fork_watchdog", side_effect=killed):
            value, code = self.collect(self.start())
        self.assertEqual(code, 2, value)
        self.assertFalse(value["lifecycle"]["transport_registered"])
        self.assertFalse(value["lifecycle"]["sessions_reaped"])
        self.assertIn("registration/cleanup unconfirmed", repr(value["lifecycle"]["cleanup_errors"]))
        self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)

    def test_stop_complete_freeze_defines_control_loss_cut(self):
        release, entered = self.root / "release", self.root / "entered"
        original = self.adapter()
        def stopped(request):
            if request["action"] == "shutdown":
                entered.write_text("shutdown")
                while not release.exists(): time.sleep(0.01)
            return original(request)
        values = lifecycle.fork_lifecycle(self.parent, transport.transport_request(NONCE, DIGEST, b"synthetic"),
            rpc=fixtures.FakeUTM(self.raw), start=original, readiness=original, shutdown=stopped, budget=budget())
        self.children.append(values)
        self.wait_for(entered.exists)
        os.close(values[1]); release.touch()
        value, code = self.collect(values)
        self.assertEqual(code, 2, value)
        self.assertIn("controller liveness EOF", value["lifecycle"]["first_failure"])
        self.assertFalse(value["receipt"]["passed"])
        self.fresh("after-freeze")
        release.unlink(); entered.unlink()
        persist = evidence.EvidenceStore.persist
        def delayed(store, *args, **kwargs):
            entered.write_text("persist")
            while not release.exists(): time.sleep(0.01)
            return persist(store, *args, **kwargs)
        with patch.object(evidence.EvidenceStore, "persist", delayed):
            values = self.start()
            self.wait_for(entered.exists)
            os.close(values[1]); release.touch()
            value, code = self.collect(values)
        self.assertEqual(code, 0, value)
        self.assertTrue(value["receipt"]["passed"])
        self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)

    def test_long_unicode_failure_is_bounded_durable_and_preserves_first_cause(self):
        value, code = self.collect(self.start("unicode"))
        self.assertEqual(code, 2, value)
        facts = value["lifecycle"]
        self.assertIn("RuntimeError", facts["first_failure"])
        self.assertIn("原始失败", facts["first_failure"])
        self.assertLessEqual(len(channels.encode(facts)), evidence.LIFECYCLE_LIMIT)
        self.assertLessEqual(len(channels.encode(facts["cleanup_errors"])), evidence.CLEANUP_BYTES)
        self.assertIn("[truncated]", facts["first_failure"])
        self.assertLess(len(channels.encode(value)), 16384)
        self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])

    def test_budget_ledger_snapshots_and_v2_tampering_are_strict(self):
        default = lifecycle.Budget()
        self.assertEqual(default.worst_seconds, 897)
        self.assertEqual(len(lifecycle.REAP_SLOTS), 8)
        self.assertEqual(default.caps["active"] - 6, 594)
        self.assertLessEqual(default.worst_seconds, default.total)
        for kwargs in ({"total": 901}, {"active": 601}, {"reap": 3}, {"init": True}, {"silence": 16}, {"total": 20}):
            with self.assertRaises(ValueError): lifecycle.Budget(**kwargs)
        for key in ("total", "caps"):
            limits = budget()
            if key == "total": limits.total = 901
            else: limits.caps["start"] = 61
            with patch.object(os, "fork", side_effect=AssertionError("forked invalid budget")), self.assertRaises(ValueError):
                self.start(limits=limits)
        value, code = self.collect(self.start())
        self.assertEqual(code, 0)
        path = self.parent / NONCE / "receipt.json"
        original = path.read_bytes()
        for change in (lambda v: v.update(schema_version=1), lambda v: v.update(lifecycle=None),
                       lambda v: v["lifecycle"].update(passed=False), lambda v: v["lifecycle"]["shutdown"].update(forced_stop=True),
                       lambda v: v["lifecycle"].update(first_failure=True), lambda v: v["lifecycle"].update(extra=1),
                       lambda v: v["lifecycle"].update(start_attempted=False), lambda v: v["lifecycle"]["start"].update(nonce="f" * 32)):
            edited = copy.deepcopy(value["receipt"]); change(edited); path.write_bytes(channels.encode(edited))
            with self.assertRaises(ValueError): evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST)
        path.write_bytes(original)

    def test_native_request_validation_is_explicit_and_cannot_enter_host_initialization(self):
        request = transport.native_transport_request(fixtures.native_descriptor())
        adapter = self.adapter()
        for candidate, initialization in ((dict(request, schema_version=True), None),
                                           (dict(request, program_base64="eA=="), None), (request, object())):
            with patch.object(os, "fork", side_effect=AssertionError("invalid native request forked")), self.assertRaises(ValueError):
                lifecycle.fork_lifecycle(self.parent, candidate, rpc=lambda *a, **k: None,
                    start=adapter, readiness=adapter, shutdown=adapter, budget=budget(), initialization=initialization)

    def test_controller_sigkill_is_detected_by_independent_owner(self):
        record = self.root / "kill-controller-pids.json"
        api, state = self.process_api(blocked=True, record=record)
        receiver, sender = socket.socketpair()
        controller = os.fork()
        if controller == 0:
            try:
                receiver.close()
                values = self.start(api=api)
                sender.sendmsg([str(values[0]).encode()], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [values[2]]))])
                sender.close()
                os.close(values[2])
                time.sleep(15)
            finally: os._exit(2)
        sender.close()
        owner, report_fd, ended = None, None, False
        try:
            data, ancillary, _, _ = receiver.recvmsg(64, socket.CMSG_SPACE(array.array("i").itemsize))
            owner = int(data)
            for level, kind, payload in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    descriptors = array.array("i"); descriptors.frombytes(payload[:descriptors.itemsize]); report_fd = descriptors[0]
            self.assertIsNotNone(report_fd)
            self.wait_for(lambda: json.loads(state.read_text())["executes"] == 1)
            os.kill(controller, signal.SIGKILL)
            self.assertEqual(os.waitstatus_to_exitcode(os.waitpid(controller, 0)[1]), -9)
            raw = bytearray()
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                ready, _, _ = select.select([report_fd], [], [], 0.02)
                if not ready: continue
                chunk = os.read(report_fd, 65536)
                if not chunk: ended = True; break
                raw.extend(chunk)
            self.assertTrue(ended)
            value = json.loads(raw)
            self.assertFalse(value["passed"], value)
            self.assertIn("controller liveness EOF", value["lifecycle"]["first_failure"])
            self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)
            self.assertEqual(json.loads(state.read_text())["executes"], 1)
            self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])
        finally:
            receiver.close()
            if report_fd is not None: os.close(report_fd)
            try: os.kill(controller, signal.SIGKILL); os.waitpid(controller, 0)
            except (ProcessLookupError, ChildProcessError): pass
            if owner is not None and not ended:
                try: os.kill(owner, signal.SIGTERM)
                except ProcessLookupError: pass
                if record.exists():
                    for pid in json.loads(record.read_text()).values():
                        try: os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError: pass

    def test_pipe_free_descendant_is_killed_and_cannot_turn_host_pass_into_lifecycle_pass(self):
        api = fixtures.FakeUTM(self.raw)
        descendant = self.root / "pipe-free-descendant"
        def leaked(request, timeout, limit):
            if request["action"] == "execute":
                pid = os.fork()
                if pid == 0:
                    channels.close_except(())
                    time.sleep(15)
                    os._exit(0)
                descendant.write_text(str(pid))
            return api(request, timeout, limit)
        try:
            value, code = self.collect(self.start(api=leaked))
            self.assertEqual(code, 2, value)
            self.assertFalse(value["passed"])
            self.assertTrue(value["receipt"]["accepted"])
            self.assertFalse(value["lifecycle"]["sessions_reaped"])
            self.assertIn("transport group remained", value["lifecycle"]["first_failure"])
            self.assertEqual(self.actions()[-1]["mode"], "recovery")
            self.assertFalse(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST)["passed"])
        finally:
            if descendant.exists():
                try: os.kill(int(descendant.read_text()), signal.SIGKILL)
                except ProcessLookupError: pass

    def test_unexpected_owner_error_and_cleanup_error_keep_failure_and_do_not_reenter_caller(self):
        with patch.object(lifecycle._Owner, "host", side_effect=KeyError("unexpected owner field")):
            value, code = self.collect(self.start())
        self.assertEqual(code, 2, value)
        self.assertIn("unexpected owner field", value["lifecycle"]["first_failure"])
        self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)
        self.fresh("unexpected-cleanup")
        original = lifecycle._Owner._finish
        def broken(owner, pid, code, label, kill, deadline):
            if label == "start": raise KeyError("unexpected cleanup field")
            return original(owner, pid, code, label, kill, deadline)
        with patch.object(lifecycle._Owner, "_finish", broken):
            value, code = self.collect(self.start())
        self.assertEqual(code, 2, value)
        self.assertIn("unexpected cleanup field", value["lifecycle"]["first_failure"])
        self.assertTrue(value["lifecycle"]["cleanup_errors"])
        self.assertEqual([a["action"] for a in self.actions()], ["start", "shutdown"])

    def test_rpc_oversized_response_fails_without_second_execute(self):
        api = fixtures.FakeUTM(self.raw)
        def oversized(request, timeout, limit):
            if request["action"] == "result": return b"x" * (limit + 1)
            return api(request, timeout, limit)
        value, code = self.collect(self.start(api=oversized))
        self.assertEqual(code, 2, value)
        self.assertIn("response limit", value["lifecycle"]["first_failure"])
        self.assertEqual(self.actions()[-1]["mode"], "recovery")

    def test_report_consumer_closes_after_freeze_preserves_receipt_without_reexecution(self):
        entered, release = self.root / "persist-entered", self.root / "persist-release"
        persist = evidence.EvidenceStore.persist
        def delayed(store, *args, **kwargs):
            entered.write_text("persist")
            while not release.exists(): time.sleep(0.01)
            return persist(store, *args, **kwargs)
        api, state = self.process_api()
        with patch.object(evidence.EvidenceStore, "persist", delayed):
            values = self.start(api=api)
            self.wait_for(entered.exists)
            os.close(values[2]); release.touch()
            code = channels.wait_child(values[0], time.monotonic() + 5)
        self.assertEqual(code, 2)
        receipt = evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST)
        self.assertTrue(receipt["passed"])
        original = (self.parent / NONCE / "receipt.json").read_bytes()
        self.assertEqual(json.loads(state.read_text())["executes"], 1)
        self.assertEqual(sum(a["action"] == "shutdown" for a in self.actions()), 1)
        self.assertEqual((self.parent / NONCE / "receipt.json").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
