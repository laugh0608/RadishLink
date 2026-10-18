"""Delivery-to-host offline chain with real owned P/N/S/W processes.

Only MemorySyscalls models Linux. The injected RPC server models fixed mailbox
slots by forwarding control/ACK pipes; this does not test UTM files, a library
loader, real mounts, cgroups, APT, signatures, or macOS write containment. ZIP
sources are hashed and statically validated, never imported from the ZIP.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import sw_i5_apt as apt
import sw_i5_preparation_bundle as bundle
import sw_i5_preparation_channels as channels
import sw_i5_preparation_evidence as evidence
import sw_i5_preparation_execution as execution
import sw_i5_preparation_lifecycle as host
import sw_i5_preparation_native_lifecycle as native
import sw_i5_preparation_rpc as process_rpc
import sw_i5_preparation_transport as transport
import test_sw_i5_bundle as delivery_fixtures
import test_sw_i5_channels as task_fixtures
import test_sw_i5_native as native_fixtures


def delivery_fixture():
    fixture = delivery_fixtures.DeliveryFixture()
    content = {}
    for name, source in apt.SOURCES.items():
        release, index, key = apt.source_paths(source)
        content.update({release: ("synthetic-signed-" + name).encode(),
                        index: ("synthetic-compressed-" + name).encode(),
                        key: ("synthetic-key-" + name).encode()})
        content[str(Path(index).parent / "by-hash/SHA256" / hashlib.sha256(content[index]).hexdigest())] = content[index]
    input_path = fixture.plan_value["readonly_input"]["path"]
    with patch.object(native_fixtures, "INPUT", input_path):
        system = native_fixtures.MemorySyscalls(content)
    expected = {role: {"dev": system.nodes[path].dev, "ino": system.nodes[path].ino, "mount_id": mount}
                for role, path, mount in (("root_parent", native_fixtures.ROOT, 21),
                    ("cgroup_root", native_fixtures.GROUP, 22), ("readonly_input", input_path, 23))}
    # Keep the independently fabricated coverage devices disjoint from the
    # model's fixed 11/12/13 devices and 21/22/23 mount tickets.
    for row in fixture.coverage["surfaces"].values():
        for domain in row["physical_domains"].values():
            domain["dev"] += 1000
            if domain["mount_id"] is not None: domain["mount_id"] += 1000
    for surface, component, role in (("guest_system_tmpfs", "initialization_root", "root_parent"),
                                     ("readonly_input", "apt_media", "readonly_input")):
        row = fixture.coverage["surfaces"][surface]
        domain = row["physical_domains"][row["components"][component]["physical_domain"]]
        domain.update(expected[role])
    fixture.native_expected = expected
    fixture.value["native_expected"] = expected
    input_row = fixture.coverage["surfaces"]["readonly_input"]
    library = input_row["physical_domains"][input_row["components"]["library_media"]["physical_domain"]]
    fixture.value["library_expected"] = {key: library[key] for key in ("dev", "ino", "mount_id")}
    fixture.files["expected.json"] = execution.encode(expected)
    fixture.rebind_coverage()
    fixture.rebind()
    review = fixture.review()
    config = native.NativeGuestConfig(fixture.files["isolation.json"], fixture.files["apt-manifest.json"],
        expected=execution.decode(fixture.files["expected.json"]), delivery_sha256=fixture.descriptor["delivery_sha256"])
    return fixture, review, config, system


def exchange(path, request, timeout=2, limit=transport.RPC_LIMIT):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(channels.encode(request))
        connection.shutdown(socket.SHUT_WR)
        raw = bytearray()
        while True:
            data = connection.recv(min(65536, limit - len(raw) + 1))
            if not data: break
            raw.extend(data)
            apt.require(len(raw) <= limit, "offline RPC response limit")
    if raw:
        value = apt.decode(bytes(raw), limit)
        if type(value) is dict and set(value) == {"error"}: raise ValueError(value["error"])
    return bytes(raw)


class OfflineGuestRPC:
    """Explicit injectable RPC. A separate test-owned server reaps guest P."""
    def __init__(self, path, nonce, digest):
        self.path, self.nonce, self.digest = path, nonce, digest

    def __call__(self, request, timeout, limit):
        process_rpc.validate_request(request, self.nonce, self.digest)
        return exchange(self.path, request, timeout, limit)

    def action(self, request):
        return apt.decode(exchange(self.path, {"admin": "action", "request": request}), 65536)


class GuestServer:
    def __init__(self, root, config, system, mode):
        self.root, self.config, self.system, self.mode = root, config, system, mode
        self.pid, self.code, self.control = None, None, None
        self.fds, self.buffers = {}, {"output": bytearray(), "ack": bytearray(), "ready": bytearray()}
        self.slots = {10: bytes(1024), 11: bytes(1024)}
        self.calls, self.actions, self.executes = [], [], 0

    def pump(self):
        if self.fds:
            readable, _, _ = select.select(list(self.fds), [], [], 0)
            for fd in readable:
                data = os.read(fd, 65536)
                role = self.fds[fd]
                if not data:
                    os.close(fd)
                    del self.fds[fd]
                else:
                    self.buffers[role].extend(data)
                    apt.require(len(self.buffers[role]) <= channels.EXPORT_LIMIT, "offline guest pipe limit")
                    if role == "ack":
                        while b"\n" in self.buffers[role]:
                            frame, _, remaining = self.buffers[role].partition(b"\n")
                            self.buffers[role] = bytearray(remaining)
                            self.slots[11] = transport.pack_slot(bytes(frame) + b"\n")
        if self.pid is not None and self.code is None:
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done: self.code = os.waitstatus_to_exitcode(status)

    def launch(self):
        apt.require(self.executes == 0, "second guest invocation forbidden")
        self.executes += 1
        control_read, control_write = os.pipe()
        output_read, output_write = os.pipe()
        ack_read, ack_write = os.pipe()
        ready_read, ready_write = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.setsid()  # Models a guest domain, outside the host transport group.
            def factory():
                self.root.joinpath("native-owner").write_text(str(os.getpid()))
                return self.system
            def work():
                self.root.joinpath("native-worker").write_text(str(os.getpid()))
                if self.mode == "cancel":
                    while True: select.select([], [], [], 0.02)
                result = self.root / "task-result"
                task_fixtures.result_files(result, task_fixtures.success_summary(self.config.nonce, self.config.digest))
                return 0
            adapters = native.NativeTaskAdapters(work=work, boundary=task_fixtures.SyntheticBoundary(), guard=Mock(),
                prepare=lambda: None, subreaper=lambda: None,
                exporter=task_fixtures.SyntheticExport(self.root / "task-result", digest=self.config.digest))
            try:
                code = native.run_native_guest(self.config, control_read, output_write, ack_write,
                    syscalls_factory=factory, task_adapters=adapters,
                    budget=native.NativeBudget(init=2, active=8, cleanup=1, reap=1, output=1, silence=3), ready_fd=ready_write)
            except BaseException as exc:
                self.root.joinpath("guest-error").write_text((type(exc).__name__ + ": " + str(exc))[:4096])
                code = 3
            os._exit(code)
        self.pid, self.control = pid, control_write
        for fd in (control_read, output_write, ack_write, ready_write): os.close(fd)
        self.fds = {output_read: "output", ack_read: "ack", ready_read: "ready"}
        for fd in self.fds: os.set_blocking(fd, False)

    def stop_guest(self, timeout=1.5):
        if self.control is not None: os.close(self.control); self.control = None
        until = time.monotonic() + timeout
        while (self.code is None or self.fds) and self.pid is not None and time.monotonic() < until:
            self.pump()
            select.select([], [], [], 0.005)
        apt.require(self.pid is None or self.code is not None, "offline guest direct-child reap unconfirmed")

    def snapshot(self):
        self.pump()
        return dict(pid=self.pid, code=self.code, executes=self.executes, calls=self.calls, actions=self.actions,
            output=base64.b64encode(self.buffers["output"]).decode(),
            guest_error=self.root.joinpath("guest-error").read_text() if self.root.joinpath("guest-error").exists() else None)

    def dispatch(self, request):
        self.pump()
        if "admin" in request:
            if request["admin"] in ("stop", "snapshot"):
                if request["admin"] == "stop": self.stop_guest()
                return self.snapshot()
            action = request["request"]
            self.actions.append(action["action"])
            if action["action"] == "shutdown": self.stop_guest()
            return dict(action, scope="i5-preparation-lifecycle-action-result", forced_stop=False,
                status={"start": "started", "readiness": "ready", "shutdown": "stopped"}[action["action"]])
        process_rpc.validate_request(request, self.config.nonce, self.config.digest)
        action, args = request["action"], request["args"]
        self.calls.append(action)
        if action == "identify": value = {"uuid": apt.UUID, "status": "started"}
        elif action == "execute-native":
            apt.require(args["descriptor"]["delivery_sha256"] == self.config.delivery_sha256, "RPC exact delivery identity")
            self.launch()
            if self.mode == "lost":
                until = time.monotonic() + 0.8
                while not self.buffers["ready"] and self.code is None and time.monotonic() < until:
                    self.pump(); select.select([], [], [], 0.005)
                apt.require(self.buffers["ready"], "lost-response guest never initialized")
                self.stop_guest(timeout=0.8)
                return None  # Effect happened; the RPC response is deliberately lost.
            value = 777
        elif action == "native-ready":
            apt.require(args["process"] == 777, "offline guest process ticket")
            apt.require(self.code is None or self.buffers["ready"], "guest exited before initialization ready")
            value = apt.decode(bytes(self.buffers["ready"]), 2048) if self.buffers["ready"] else None
        elif action == "open":
            apt.require(self.buffers["ready"], "mailbox opened before native initialization")
            value = 10 if args["role"] == "lease" else 11
        elif action == "read": value = base64.b64encode(self.slots[args["handle"]]).decode()
        elif action == "write":
            apt.require(args["handle"] == 10 and self.control is not None, "offline lease slot is not writable")
            self.slots[10] = base64.b64decode(args["data"], validate=True)
            frame = transport.unpack_slot(self.slots[10])
            apt.require(frame is not None, "offline mailbox invalid frame")
            channels.write_frame(self.control, frame)
            value = None
        elif action == "result":
            apt.require(args["process"] == 777, "offline guest result ticket")
            value = {"exited": False} if self.code is None or self.fds else dict(exited=True, exit_code=self.code,
                signal_code=0, stdout_base64=base64.b64encode(self.buffers["output"]).decode(), stderr_base64="")
        elif action == "close": value = None
        else: raise ValueError("offline RPC unknown action")
        response = dict(request, scope="i5-preparation-utm-rpc-result", value=value)
        response.pop("args")
        return response

    def serve(self, listener):
        try:
            while True:
                self.pump()
                readable, _, _ = select.select([listener], [], [], 0.01)
                if not readable: continue
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(2)
                    try:
                        raw = bytearray()
                        while True:
                            data = connection.recv(65536)
                            if not data: break
                            raw.extend(data)
                            apt.require(len(raw) <= process_rpc.REQUEST_LIMIT, "offline RPC request limit")
                        request = apt.decode(bytes(raw), process_rpc.REQUEST_LIMIT)
                        value = self.dispatch(request)
                        if value is not None: connection.sendall(channels.encode(value))
                        if request.get("admin") == "stop": break
                    except BaseException as exc:
                        connection.sendall(channels.encode({"error": (type(exc).__name__ + ": " + str(exc))[:4096]}))
        finally:
            self.stop_guest()
            for fd in self.fds: os.close(fd)


class NativeHostTests(unittest.TestCase):
    def run_chain(self, mode):
        with tempfile.TemporaryDirectory(prefix="radishlink-native-host-", dir="/private/tmp") as directory:
            root = Path(directory)
            (root / "task-result").mkdir()
            parent = root / "evidence"
            parent.mkdir(mode=0o700)
            fixture, review, config, system = delivery_fixture()
            self.assertTrue(review["consistency_passed"])
            self.assertEqual(review["host_feasibility"], "blocked-host-system-writes")
            path = root / "rpc.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(path)); listener.listen(8)
            server = os.fork()
            if server == 0:
                try:
                    os.setsid()
                    channels.close_except((listener.fileno(),))
                    GuestServer(root, config, system, mode).serve(listener)
                    os._exit(0)
                except BaseException as exc:
                    root.joinpath("server-error").write_text((type(exc).__name__ + ": " + str(exc))[:4096])
                    os._exit(3)
            listener.close()
            pid, writer, reader, server_code = None, None, None, None
            try:
                rpc = OfflineGuestRPC(path, config.nonce, config.digest)
                limits = host.Budget(total=40, silence=3, init=2, start=2, readiness=2, active=18,
                    watchdog_cleanup=2, watchdog_report=1, shutdown=2, persist=2, output=1, reap=0.5)
                pid, writer, reader = host.fork_lifecycle(parent, transport.native_transport_request(fixture.descriptor),
                    rpc=rpc, start=rpc.action, readiness=rpc.action, shutdown=rpc.action, budget=limits)
                raw, code, cancelled = bytearray(), None, False
                until = time.monotonic() + 35
                while time.monotonic() < until:
                    if mode == "cancel" and not cancelled and root.joinpath("native-worker").exists():
                        os.write(writer, b"cancel")
                        cancelled = True
                    readable, _, _ = select.select([reader], [], [], 0.02)
                    if readable:
                        data = os.read(reader, 65536)
                        if not data: break
                        raw.extend(data)
                        self.assertLessEqual(len(raw), 2 * evidence.RECEIPT_LIMIT)
                code = channels.wait_child(pid, min(until, time.monotonic() + 2))
                self.assertIsNotNone(code, "host owner reap unconfirmed")
                self.assertTrue(raw, root.joinpath("server-error").read_text() if root.joinpath("server-error").exists() else "empty host result")
                result = apt.decode(bytes(raw), 2 * evidence.RECEIPT_LIMIT)
                snapshot = apt.decode(exchange(path, {"admin": "snapshot"}), transport.RPC_LIMIT)
                self.assertIsNone(snapshot["guest_error"], snapshot)
                self.assertEqual(snapshot["executes"], 1, snapshot)
                self.assertEqual(snapshot["calls"].count("execute-native"), 1)
                self.assertNotIn("execute", snapshot["calls"])
                self.assertEqual(snapshot["actions"], ["start", "readiness", "shutdown"])
                self.assertIsNotNone(snapshot["code"], snapshot)
                native_raw = base64.b64decode(snapshot["output"], validate=True)
                exported = channels.validate_export(native_raw, config.nonce, config.digest)
                facts = exported["native_lifecycle"]
                self.assertEqual(facts["delivery_sha256"], fixture.descriptor["delivery_sha256"])
                self.assertEqual(facts["backend_kind"], "injected-offline")
                self.assertTrue(facts["owner_reaped"])
                for process in facts["processes"].values():
                    if process is not None:
                        with self.assertRaises(ProcessLookupError): os.kill(process, 0)
                self.assertFalse(system.calls, "test controller must never execute the native backend")
                self.assertEqual(evidence.read_evidence(parent / config.nonce, config.nonce, config.digest), result["receipt"])
                persisted = apt.decode((parent / config.nonce / "host-report.bin").read_bytes(), channels.HOST_REPORT_LIMIT)
                if mode == "normal":
                    self.assertEqual(code, 0, result)
                    self.assertTrue(result["passed"], result)
                    self.assertEqual(persisted["export"], exported)
                    self.assertTrue(exported["passed"], exported)
                    self.assertEqual(facts["pending"], {})
                    self.assertEqual(facts["cleanup"]["errors"], [])
                    self.assertEqual(facts["initialization"], facts["independent_readback"])
                else:
                    self.assertEqual(code, 2, result)
                    self.assertFalse(result["passed"], result)
                    self.assertFalse(exported["passed"], exported)
                    self.assertTrue(result["lifecycle"]["first_failure"], result)
                    if mode == "cancel": self.assertTrue(cancelled)
                    else: self.assertIn("RPC response limit", result["lifecycle"]["first_failure"])
                self.assertFalse(result["receipt"]["i5_ready"])
            finally:
                for fd in (writer, reader):
                    if fd is not None:
                        try: os.close(fd)
                        except OSError: pass
                if pid is not None:
                    try:
                        if channels.wait_child(pid, time.monotonic() + 1) is None:
                            os.kill(pid, signal.SIGTERM)
                            if channels.wait_child(pid, time.monotonic() + 2) is None: os.killpg(pid, signal.SIGKILL); os.waitpid(pid, 0)
                    except (ProcessLookupError, ChildProcessError): pass
                try: exchange(path, {"admin": "stop"})
                finally:
                    server_code = channels.wait_child(server, time.monotonic() + 2)
                    if server_code is None:
                        os.kill(server, signal.SIGKILL); os.waitpid(server, 0)
                self.assertEqual(server_code, 0, root.joinpath("server-error").read_text() if root.joinpath("server-error").exists() else "server not reaped")

    def test_delivery_native_transport_host_and_persisted_receipt(self): self.run_chain("normal")

    def test_explicit_host_control_cancel_stops_actual_native_task(self): self.run_chain("cancel")

    def test_lost_execute_response_does_not_repeat_native_initialization(self): self.run_chain("lost")


if __name__ == "__main__": unittest.main()
