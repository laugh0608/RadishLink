"""Offline UTM RPC/mailbox and evidence persistence; no Apple events or VM."""

import base64
import copy
import errno
import json
import os
from pathlib import Path
import select
import tempfile
import sys
import time
import unittest
from unittest.mock import Mock, patch

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels
import sw_i5_preparation_evidence as evidence
import sw_i5_preparation_supervisor as supervision
import sw_i5_preparation_rpc as process_rpc
import sw_i5_preparation_transport as transport
import sw_i5_utm_control as control
import test_sw_i5_channels as fixtures

NONCE, DIGEST = fixtures.NONCE, fixtures.DIGEST


def export_fixture(root):
    fixtures.result_files(root)
    exporter = fixtures.SyntheticExport(root)
    exporter.pin(0, None)
    try: return exporter.collect(fixtures.success_report(), lambda: None)
    finally: exporter.close()


RPC_CHILD_SOURCE = r'''import base64, json, os, sys
from pathlib import Path
state_path, payload_path = map(Path, sys.argv[1:3])
r = json.loads(sys.stdin.buffer.read())
s = json.loads(state_path.read_text())
s["calls"].append([r["action"], r["args"], os.getpid(), os.getpgrp()])
action, a = r["action"], r["args"]
if action == "identify": value = {"uuid": r["uuid"], "status": "started"}
elif action == "open": value = 10 if a["role"] == "lease" else 11
elif action == "write":
    s["slots"][str(a["handle"])] = a["data"]
    slot = base64.b64decode(a["data"])
    frame = json.loads(slot[40:40 + int.from_bytes(slot[4:8], "big")])
    ack = dict(frame, scope="i5-preparation-guest-ack"); ack.pop("action")
    import hashlib
    data = json.dumps(ack, separators=(",", ":")).encode()
    prefix = b"I5M1" + len(data).to_bytes(4, "big") + hashlib.sha256(data).digest() + data
    s["slots"]["11"] = base64.b64encode(prefix + bytes(1024 - len(prefix))).decode()
    value = None
elif action == "read": value = s["slots"][str(a["handle"])]
elif action == "execute": s["executes"] += 1; value = 777
elif action == "result":
    assert a["process"] == 777
    s["polls"] += 1
    value = {"exited": False} if s["polls"] == 1 else {"exited": True, "exit_code": 0, "signal_code": 0,
        "stdout_base64": base64.b64encode(payload_path.read_bytes()).decode(), "stderr_base64": ""}
elif action == "close": value = None
else: raise AssertionError(action)
state_path.write_text(json.dumps(s))
if s["lost"] and action == "execute": sys.exit(0)
v = dict(r, scope="i5-preparation-utm-rpc-result", value=value); v.pop("args")
sys.stdout.buffer.write(json.dumps(v).encode())
'''

def host_report(export):
    return dict(schema_version=1, scope="i5-preparation-host-report", nonce=NONCE, uuid=apt.UUID,
        manifest_sha256=DIGEST, evidence_kind="synthetic", i5_ready=False, passed=True, export=export,
        watchdog=dict(transport_complete=True, failure=None, recovery=None, i5_ready=False), transport_exit=0, cleanup_errors=[])


class MailboxTests(unittest.TestCase):
    def test_torn_slot_does_not_renew_and_repeated_slot_is_not_renewal(self):
        lease = supervision.Lease(NONCE, DIGEST, started=0)
        raw = transport.pack_slot(lease.frame(0))
        self.assertEqual(transport.unpack_slot(raw), lease.frame(0))
        for position in (0, 5, 9, 80, 1023):
            changed = bytearray(raw)
            changed[position] ^= 1
            self.assertIsNone(transport.unpack_slot(bytes(changed)))
        with tempfile.TemporaryDirectory(prefix="radishlink-mailbox-") as directory:
            root = Path(directory).resolve()
            for name in ("lease.slot", "ack.slot"):
                (root / name).write_bytes(b"\0" * transport.SLOT_BYTES)
                (root / name).chmod(0o600)
            reader = transport.SlotFile(root / "lease.slot", owner=os.getuid(), writable=False)
            writer = transport.SlotFile(root / "ack.slot", owner=os.getuid(), writable=True)
            try:
                mailbox = transport.GuestMailbox(reader, writer, NONCE, DIGEST)
                with (root / "lease.slot").open("r+b") as file: file.write(raw[:100])
                self.assertFalse(supervision.drain_lease(mailbox, lease, 1, require_started=False))
                self.assertEqual(lease.sequence, -1)
                with (root / "lease.slot").open("r+b") as file: file.write(raw)
                lease.acknowledge = mailbox.acknowledge
                self.assertTrue(supervision.drain_lease(mailbox, lease, 2))
                self.assertFalse(supervision.drain_lease(mailbox, lease, 10))
                self.assertEqual(lease.last, 2)
                self.assertEqual(json.loads(transport.unpack_slot(writer.read()))["sequence"], 0)
                with self.assertRaisesRegex(ValueError, "expired"):
                    supervision.drain_lease(mailbox, lease, 17)
            finally:
                reader.close()
                writer.close()

    def test_slot_owner_mode_identity_size_and_short_write_rejection(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-mailbox-") as directory:
            path = Path(directory).resolve() / "slot"
            path.write_bytes(b"\0" * transport.SLOT_BYTES)
            path.chmod(0o600)
            slot = transport.SlotFile(path, owner=os.getuid(), writable=True)
            try:
                with patch.object(os, "pwrite", return_value=1), self.assertRaisesRegex(ValueError, "short write"):
                    slot.write(b"x")
                path.rename(path.with_name("old"))
                path.write_bytes(b"\0" * transport.SLOT_BYTES)
                path.chmod(0o600)
                with self.assertRaisesRegex(ValueError, "identity"):
                    slot.read()
            finally: slot.close()
            path.chmod(0o644)
            with self.assertRaises(ValueError): transport.SlotFile(path, owner=os.getuid(), writable=True)
            path.chmod(0o600)
            path.write_bytes(b"x")
            with self.assertRaises(ValueError): transport.SlotFile(path, owner=os.getuid(), writable=True)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radishlink-evidence-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        output = self.root / "output"
        output.mkdir()
        self.raw = channels.encode(host_report(export_fixture(output)))

    def store(self):
        value = evidence.EvidenceStore(self.root, NONCE, DIGEST)
        self.addCleanup(value.close)
        return value

    def test_sync_publish_reopen_and_never_overwrite(self):
        store = self.store()
        receipt = store.persist(self.raw, 0)
        self.assertTrue(receipt["accepted"])
        self.assertTrue(receipt["passed"])
        store.close()
        self.assertEqual(evidence.read_evidence(store.path, NONCE, DIGEST), receipt)
        with self.assertRaises(FileExistsError): self.store()
        with self.assertRaisesRegex(ValueError, "consumed"): store.persist(self.raw, 0)

    def test_persistence_process_bounds_stalled_fsync_and_preserves_failure(self):
        store = self.store()
        with patch.object(os, "fsync", side_effect=lambda fd: time.sleep(5)):
            with self.assertRaisesRegex(ValueError, "persistence deadline"):
                evidence.persist_bounded(store, self.raw, 0, seconds=0.3)
        self.assertTrue(store.consumed)
        self.assertFalse((store.path / "receipt.json").exists())
        with self.assertRaises(ValueError): evidence.read_evidence(store.path, NONCE, DIGEST)

    def test_invalid_report_and_exit_mismatch_are_durable_failed_evidence(self):
        for index, (raw, code) in enumerate(((b"broken", 2), (self.raw, 2))):
            directory = self.root / str(index)
            directory.mkdir(mode=0o700)
            store = evidence.EvidenceStore(directory, NONCE, DIGEST)
            try:
                receipt = store.persist(raw, code)
                self.assertFalse(receipt["accepted"])
                self.assertFalse(receipt["passed"])
                self.assertTrue(receipt["failure"])
                self.assertEqual((store.path / "host-report.bin").read_bytes(), raw)
            finally: store.close()

    def test_disk_full_and_fsync_failure_leave_attempt_consumed_without_receipt(self):
        for failure in ("write", "fsync", "link"):
            directory = self.root / failure
            directory.mkdir(mode=0o700)
            store = evidence.EvidenceStore(directory, NONCE, DIGEST)
            try:
                with patch.object(os, failure, side_effect=OSError(errno.ENOSPC, "synthetic disk full")):
                    with self.assertRaises(OSError): store.persist(self.raw, 0)
                self.assertFalse((store.path / "receipt.json").exists())
                with self.assertRaises(ValueError): evidence.read_evidence(store.path, NONCE, DIGEST)
                with self.assertRaises(FileExistsError): evidence.EvidenceStore(directory, NONCE, DIGEST)
            finally: store.close()

    def test_short_writes_complete_but_zero_write_and_oversize_fail(self):
        store = self.store()
        write = os.write
        with patch.object(os, "write", side_effect=lambda fd, data: write(fd, data[:17])):
            self.assertTrue(store.persist(self.raw, 0)["passed"])
        other = self.root / "other"
        other.mkdir(mode=0o700)
        second = evidence.EvidenceStore(other, NONCE, DIGEST)
        try:
            with patch.object(os, "write", return_value=0), self.assertRaisesRegex(ValueError, "zero"):
                second.persist(self.raw, 0)
            with self.assertRaises(ValueError): evidence.read_evidence(second.path, NONCE, DIGEST)
            with self.assertRaisesRegex(ValueError, "quota"):
                second.write("host-report.bin", b"x" * (channels.HOST_REPORT_LIMIT + 1))
        finally: second.close()

    def test_tampered_payload_receipt_extra_file_and_path_replacement(self):
        store = self.store()
        store.persist(self.raw, 0)
        path = store.path / "host-report.bin"
        path.write_bytes(self.raw[:-1] + b"x")
        with self.assertRaises(ValueError): evidence.read_evidence(store.path, NONCE, DIGEST)
        path.write_bytes(self.raw)
        (store.path / "extra").touch()
        with self.assertRaises(ValueError): evidence.read_evidence(store.path, NONCE, DIGEST)
        (store.path / "extra").unlink()
        saved = store.path.with_name("moved")
        store.path.rename(saved)
        store.path.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "replaced"): store.check()

    def test_symlinks_hardlinks_and_interrupted_attempts_not_accepted(self):
        store = self.store()
        with self.assertRaises(ValueError): evidence.read_evidence(store.path, NONCE, DIGEST)
        store.persist(self.raw, 0)
        os.link(store.path / "host-report.bin", self.root / "alias")
        with self.assertRaises(ValueError): evidence.read_evidence(store.path, NONCE, DIGEST)

    def test_host_report_cannot_forge_completion_or_upgrade_evidence(self):
        value = json.loads(self.raw)
        for change in (lambda p: p.update(i5_ready=True), lambda p: p.update(extra=True),
                       lambda p: p.update(nonce="c" * 32), lambda p: p.update(transport_exit=2),
                       lambda p: p["watchdog"].update(transport_complete=False),
                       lambda p: p["watchdog"].update(recovery={"stopped": True, "passed": True}),
                       lambda p: p.update(export=None)):
            modified = copy.deepcopy(value)
            change(modified)
            with self.assertRaises(ValueError): evidence.validate_host_report(channels.encode(modified), NONCE, DIGEST)


class FakeUTM:
    def __init__(self, output, mode="ok"):
        self.output, self.mode, self.actions = output, mode, []
        self.slots = {10: b"\0" * 1024, 11: b"\0" * 1024}
        self.started, self.polls = 0, 0

    def __call__(self, request, timeout, limit):
        assert 0 < timeout <= 2 and limit == transport.RPC_LIMIT
        action, args = request["action"], request["args"]
        self.actions.append((action, args))
        if self.mode == "rpc-lost" and action == "execute":
            self.started += 1
            raise OSError("synthetic lost execute response")
        if action == "identify": value = {"uuid": apt.UUID, "status": "stopped" if self.mode == "stopped" else "started"}
        elif action == "open": value = 10 if args["role"] == "lease" else 11
        elif action == "write":
            self.slots[args["handle"]] = base64.b64decode(args["data"])
            frame = json.loads(transport.unpack_slot(self.slots[10]))
            ack = dict(frame, scope="i5-preparation-guest-ack")
            ack.pop("action")
            if self.mode == "bad-ack": ack["nonce"] = "f" * 32
            self.slots[11] = transport.pack_slot(channels.encode(ack))
            value = None
        elif action == "read":
            value = base64.b64encode(self.slots[args["handle"]]).decode()
            if self.mode == "bad-readback" and self.slots[10] != b"\0" * 1024 and args["handle"] == 10:
                value = base64.b64encode(b"\0" * 1024).decode()
        elif action == "execute":
            self.started += 1
            value = 777
        elif action == "result":
            assert args["process"] == 777
            self.polls += 1
            if self.polls == 1 and self.mode == "ok": value = {"exited": False}
            else:
                value = {"exited": True, "exit_code": 2 if self.mode == "exit" else 0, "signal_code": 0,
                    "stdout_base64": base64.b64encode(self.output).decode(), "stderr_base64": ""}
                if self.mode == "signal": value["signal_code"] = 9
                if self.mode == "stderr": value["stderr_base64"] = "eA=="
        elif action == "close":
            if self.mode == "close": raise OSError("synthetic close failure")
            value = None
        else: raise AssertionError(action)
        response = dict(request, scope="i5-preparation-utm-rpc-result", value=value)
        response.pop("args")
        if self.mode == "replay": response["sequence"] += 1
        return channels.encode(response)


class TransportTests(unittest.TestCase):
    def test_transport_error_is_preserved_in_durable_host_failure(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-utm-failure-") as directory:
            store = evidence.EvidenceStore(Path(directory).resolve(), NONCE, DIGEST)
            def adapter(reader, writer, ack):
                raise OSError("synthetic Apple event failed after execute")
            pid, lease_write, report_read, ack_read = channels.fork_watchdog(adapter,
                lambda: {"stopped": True, "passed": False}, NONCE, DIGEST, total=3, silence=1)
            try:
                os.write(lease_write, supervision.Lease(NONCE, DIGEST, started=time.monotonic(), side="host").frame(0))
                raw = bytearray()
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    ready, _, _ = select.select([report_read], [], [], 0.05)
                    if ready:
                        data = os.read(report_read, 65536)
                        if not data: break
                        raw.extend(data)
                code = channels.wait_child(pid, until)
                self.assertEqual(code, 2)
                self.assertIn("synthetic Apple event failed", json.loads(raw)["watchdog"]["failure"])
                receipt = store.persist(bytes(raw), code)
                self.assertTrue(receipt["accepted"])
                self.assertFalse(receipt["passed"])
            finally:
                store.close()
                for fd in (lease_write, report_read, ack_read): os.close(fd)

    def test_v4_contract_binds_program_sources_and_fixed_budgets(self):
        observed = {"base_revision": "a" * 40, "hashes": {name: "a" * 64 for name in control.TRANSPORT_SOURCES},
            "config_sha256": "b" * 64, "utmctl_sha256": "c" * 64, "manifest_sha256": DIGEST,
            "isolation_sha256": "f" * 64, "program_sha256": "1" * 64,
            "media": {"path": "/synthetic/input.iso", "bytes": 1234, "sha256": "e" * 64, "read_only": True}}
        record = dict(observed, schema_version=4, scope="i5-preparation-apt-operation", nonce=NONCE,
            uuid=apt.UUID, authorized=True, guest_seconds=540, host_seconds=620, total_seconds=900,
            lease_seconds=15, cleanup_seconds=20, export_bytes=channels.EXPORT_LIMIT,
            export_data_bytes=channels.DATA_LIMIT, export_file_bytes=channels.FILE_LIMIT,
            slot_bytes=transport.SLOT_BYTES, evidence_bytes=evidence.STORE_LIMIT)
        control.validate_apt_operation(record, NONCE, observed)
        for name, value in (("slot_bytes", True), ("evidence_bytes", evidence.STORE_LIMIT + 1),
                            ("program_sha256", "2" * 64), ("schema_version", 3),
                            ("hashes", {n: "a" * 64 for n in control.CHANNEL_SOURCES})):
            with self.assertRaises(ValueError):
                control.validate_apt_operation(dict(record, **{name: value}), NONCE, observed)

    def test_rpc_success_failure_and_handle_close_no_execute_retry(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-utm-rpc-") as directory:
            output = channels.encode(export_fixture(Path(directory).resolve()))
            for mode in ("ok", "stopped", "rpc-lost", "bad-ack", "bad-readback", "exit", "signal", "stderr", "close", "replay"):
                with self.subTest(mode=mode):
                    api = FakeUTM(output, mode)
                    r, w = os.pipe()
                    out = tempfile.TemporaryFile()
                    ar, aw = os.pipe()
                    lease = supervision.Lease(NONCE, DIGEST, started=time.monotonic())
                    os.write(w, lease.frame(0))
                    try:
                        request = transport.transport_request(NONCE, DIGEST, b"synthetic reviewed source")
                        if mode == "ok":
                            self.assertEqual(transport.run_transport(r, out.fileno(), aw, request, rpc=api), 0)
                            out.seek(0)
                            self.assertEqual(out.read(), output)
                            self.assertEqual(api.polls, 2)
                            self.assertEqual(json.loads(os.read(ar, 512))["sequence"], 0)
                        else:
                            with self.assertRaises(ValueError):
                                transport.run_transport(r, out.fileno(), aw, request, rpc=api)
                        self.assertLessEqual(api.started, 1)
                        if mode not in {"stopped", "replay"}:
                            self.assertEqual([a[1]["handle"] for a in api.actions if a[0] == "close"], [10, 11])
                    finally:
                        for fd in (r, w, ar, aw): os.close(fd)
                        out.close()

    def test_real_single_rpc_process_chain_keeps_handles_and_never_reexecutes(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-rpc-process-chain-") as directory:
            root = Path(directory).resolve()
            payload = root / "payload"
            payload.mkdir()
            raw_export = channels.encode(export_fixture(payload))
            helper = root / "rpc-child.py"
            helper.write_text(RPC_CHILD_SOURCE)
            payload_file = root / "export.json"
            payload_file.write_bytes(raw_export)
            for lost in (False, True):
                state = root / ("lost.json" if lost else "ok.json")
                state.write_text(json.dumps({"slots": {str(i): base64.b64encode(bytes(1024)).decode() for i in (10, 11)},
                    "calls": [], "executes": 0, "polls": 0, "lost": lost}))
                bridge = process_rpc.ProcessRPC((sys.executable, "-I", "-B", str(helper), str(state), str(payload_file)), NONCE, DIGEST)
                reader, writer = os.pipe()
                ar, aw = os.pipe()
                out = tempfile.TemporaryFile()
                os.write(writer, supervision.Lease(NONCE, DIGEST, started=time.monotonic()).frame(0))
                try:
                    request = transport.transport_request(NONCE, DIGEST, b"synthetic reviewed source")
                    if lost:
                        with self.assertRaisesRegex(ValueError, "executed=True"):
                            transport.run_transport(reader, out.fileno(), aw, request, rpc=bridge, total=10)
                    else:
                        self.assertEqual(transport.run_transport(reader, out.fileno(), aw, request, rpc=bridge, total=10), 0)
                        out.seek(0)
                        self.assertEqual(out.read(), raw_export)
                    observed = json.loads(state.read_text())
                    self.assertEqual(observed["executes"], 1)
                    self.assertEqual([a[1]["handle"] for a in observed["calls"] if a[0] == "close"], [10, 11])
                    self.assertEqual({a[3] for a in observed["calls"]}, {os.getpgrp()})
                    if not lost:
                        self.assertEqual([a[1]["process"] for a in observed["calls"] if a[0] == "result"], [777, 777])
                finally:
                    for fd in (reader, writer, ar, aw): os.close(fd)
                    out.close()

    def test_host_watchdog_transport_and_persistence_chain(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-utm-chain-") as directory:
            root = Path(directory).resolve()
            payload = root / "payload"
            payload.mkdir()
            raw_export = channels.encode(export_fixture(payload))
            def adapter(reader, writer, ack):
                return transport.run_transport(reader, writer, ack,
                    transport.transport_request(NONCE, DIGEST, b"synthetic"), rpc=FakeUTM(raw_export))
            store = evidence.EvidenceStore(root, NONCE, DIGEST)
            pid, lease_write, report_read, ack_read = channels.fork_watchdog(adapter,
                lambda: {"stopped": True, "passed": False}, NONCE, DIGEST, total=3, silence=1)
            try:
                os.write(lease_write, supervision.Lease(NONCE, DIGEST, started=time.monotonic(), side="host").frame(0))
                raw = bytearray()
                until = time.monotonic() + 5
                while time.monotonic() < until:
                    ready, _, _ = select.select([report_read], [], [], 0.05)
                    if ready:
                        chunk = os.read(report_read, 65536)
                        if not chunk: break
                        raw.extend(chunk)
                code = channels.wait_child(pid, until)
                self.assertEqual(code, 0, bytes(raw))
                self.assertTrue(evidence.persist_bounded(store, bytes(raw), code)["passed"])
                self.assertTrue(evidence.read_evidence(store.path, NONCE, DIGEST)["passed"])
            finally:
                store.close()
                for fd in (lease_write, report_read, ack_read): os.close(fd)

    def test_mailbox_drives_independent_guest_supervisor(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-guest-mailbox-") as directory:
            root = Path(directory).resolve()
            output = root / "output"
            output.mkdir()
            for name in ("lease.slot", "ack.slot"):
                (root / name).write_bytes(b"\0" * 1024)
                (root / name).chmod(0o600)
            lease_slot = transport.SlotFile(root / "lease.slot", owner=os.getuid(), writable=True)
            ack_slot = transport.SlotFile(root / "ack.slot", owner=os.getuid(), writable=True)
            mailbox = transport.GuestMailbox(lease_slot, ack_slot, NONCE, DIGEST)
            def work():
                fixtures.result_files(output)
                return 0
            pid, writer, reader = supervision.fork_supervisor(work, fixtures.SyntheticBoundary(), Mock(), NONCE, DIGEST,
                exporter=fixtures.SyntheticExport(output), mailbox=mailbox, total=3, silence=1, subreaper=lambda: None)
            try:
                self.assertIsNone(writer)
                lease_slot.write(supervision.Lease(NONCE, DIGEST, started=0).frame(0))
                data = bytearray()
                until = time.monotonic() + 4
                while time.monotonic() < until:
                    ready, _, _ = select.select([reader], [], [], 0.05)
                    if ready:
                        raw = os.read(reader, 65536)
                        if not raw: break
                        data.extend(raw)
                self.assertEqual(channels.wait_child(pid, until), 0, bytes(data))
                self.assertTrue(channels.validate_export(bytes(data), NONCE, DIGEST)["passed"])
                self.assertEqual(json.loads(transport.unpack_slot(ack_slot.read()))["sequence"], 0)
            finally:
                os.close(reader)
                lease_slot.close()
                ack_slot.close()


if __name__ == "__main__":
    unittest.main()
