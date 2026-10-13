"""Offline channel tests: synthetic files, owned fork/pipe children, no VM/APT."""

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
import sw_i5_preparation_supervisor as supervision
import sw_i5_utm_control as control
import test_sw_i5_apt as apt_fixtures

NONCE, DIGEST = "a" * 32, "b" * 64


def success_summary(nonce=NONCE, digest=DIGEST):
    value = apt.blocked_result(nonce, digest)
    value.update(evidence_kind="synthetic", passed=True, failure=None,
                 steps=[dict(label=label, exit_code=0, failure=None, cleanup_errors=[]) for label in apt.STEP_LABELS])
    return value


def success_report(nonce=NONCE, digest=DIGEST):
    return dict(schema_version=1, scope="i5-preparation-supervision", uuid=apt.UUID, nonce=nonce,
                manifest_sha256=digest, i5_ready=False, passed=True, failure=None, cleanup_errors=[],
                admitted=True, worker_exit=0, population_empty=True, reaped=True)


def result_files(root, summary=None):
    summary = success_summary() if summary is None else summary
    (root / "result.json").write_bytes(channels.encode(summary))
    for name in channels.ARTIFACTS[1:]:
        (root / name.split("/")[1]).write_bytes(b"synthetic\n")


class SyntheticExport(channels.ResultExport):
    """Only tests map procfs identity to an explicitly owned temp directory."""
    def __init__(self, root, nonce=NONCE, digest=DIGEST):
        super().__init__(nonce, digest)
        self.root = root

    def pin(self, pid, guard):
        info = self.root.stat()
        self.pin_directory("result", self.root, f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}", info.st_ino)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radishlink-channel-export-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "result"
        self.root.mkdir()
        result_files(self.root)
        self.exporter = SyntheticExport(self.root)
        self.exporter.pin(0, None)
        self.addCleanup(self.exporter.close)

    def collect(self, report=None):
        packet = self.exporter.collect(report or success_report(), lambda: None)
        return channels.validate_export(channels.encode(packet), NONCE, DIGEST)

    def test_pinned_directory_survives_path_replacement(self):
        old = self.root.with_name("pinned-old")
        self.root.rename(old)
        self.root.mkdir()
        (self.root / "result.json").write_bytes(b"attacker replacement")
        value = self.collect()
        self.assertTrue(value["passed"], value)
        self.assertEqual(value["preparation"], success_summary())
        self.assertLessEqual(len(channels.encode(value)), channels.EXPORT_LIMIT)

    def test_wrong_device_inode_and_directory_symlink_rejected(self):
        export = channels.ResultExport(NONCE, DIGEST)
        info = self.root.stat()
        with self.assertRaises(ValueError):
            export.pin_directory("result", self.root, "99:99", info.st_ino)
        link = self.root.with_name("link")
        link.symlink_to(self.root)
        with self.assertRaises(OSError):
            export.pin_directory("result", link, f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}", info.st_ino)
        self.assertFalse(export.dirs)

    def test_symlink_hardlink_fifo_and_missing_diagnostics_fail_without_block(self):
        path = self.root / "worker.stdout"
        for kind in ("symlink", "hardlink", "fifo", "missing"):
            with self.subTest(kind=kind):
                path.unlink(missing_ok=True)
                if kind == "symlink": path.symlink_to(self.root / "result.json")
                if kind == "hardlink": os.link(self.root / "worker.stderr", path)
                if kind == "fifo": os.mkfifo(path)
                started = time.monotonic()
                value = self.collect()
                self.assertFalse(value["passed"])
                self.assertTrue(value["export_errors"])
                self.assertLess(time.monotonic() - started, 0.5)

    def test_file_and_aggregate_quota_preserve_prefix_and_fail(self):
        (self.root / "worker.stdout").write_bytes(b"x" * (channels.FILE_LIMIT + 1))
        value = self.collect()
        entry = next(e for e in value["artifacts"] if e["name"] == "result/worker.stdout")
        self.assertEqual(entry["saved_bytes"], channels.FILE_LIMIT)
        self.assertEqual(entry["bytes"], channels.FILE_LIMIT + 1)
        self.assertTrue(entry["truncated"])
        self.assertFalse(value["passed"])
        for name in channels.ARTIFACTS[1:]:
            (self.root / name.split("/")[1]).write_bytes(b"x" * channels.FILE_LIMIT)
        value = self.collect()
        self.assertEqual(sum(e["saved_bytes"] for e in value["artifacts"]), channels.DATA_LIMIT)
        self.assertFalse(value["passed"])

    def test_exit_failure_retains_artifacts_and_live_descendants_block_read(self):
        report = success_report()
        report.update(passed=False, failure="worker failed", worker_exit=2)
        value = self.collect(report)
        self.assertTrue(value["artifacts"])
        self.assertFalse(value["passed"])
        report["population_empty"] = False
        with patch.object(os, "open", side_effect=AssertionError("read before cleanup")):
            value = self.collect(report)
        self.assertEqual(value["artifacts"], [])
        self.assertIn("descendants", value["export_errors"][0])

    def test_corrupt_summary_is_retained_as_failure_evidence(self):
        (self.root / "result.json").write_bytes(b"not JSON")
        value = self.collect()
        self.assertIsNone(value["preparation"])
        self.assertFalse(value["passed"])
        self.assertEqual(value["artifacts"][0]["saved_bytes"], 8)

    def test_mutation_during_read_and_expired_lease_fail(self):
        original = os.read
        def changing(fd, cap):
            raw = original(fd, cap)
            (self.root / "result.json").write_bytes(b"replaced")
            return raw
        with patch.object(os, "read", side_effect=changing):
            value = self.collect()
        self.assertFalse(value["passed"])
        self.assertIn("changed", value["export_errors"][0])
        value = self.exporter.collect(success_report(), Mock(side_effect=ValueError("lease expired")))
        self.assertIn("lease expired", value["export_errors"])

    def test_export_tamper_replay_unknown_fields_and_truncation_rejected(self):
        valid = self.collect()
        mutations = [lambda p: p.update(nonce="c" * 32), lambda p: p.update(schema_version=True),
            lambda p: p.update(extra=1), lambda p: p.update(i5_ready=True),
            lambda p: p["artifacts"][0].update(sha256="f" * 64),
            lambda p: p["artifacts"][0].update(name="../escape"),
            lambda p: p["artifacts"].append(p["artifacts"][0]),
            lambda p: p["artifacts"].pop(), lambda p: p["preparation"].update(apt_resolved=True),
            lambda p: p["supervision"].update(reaped=False)]
        for mutate in mutations:
            value = copy.deepcopy(valid)
            mutate(value)
            with self.assertRaises((ValueError, TypeError)):
                channels.validate_export(channels.encode(value), NONCE, DIGEST)


class SyntheticBoundary:
    pid = None
    killed = False
    def attach(self, pid): self.pid = pid
    def populated(self):
        if self.pid is None or self.killed: return False
        # waitid WNOWAIT is absent on macOS; the supervisor calls poll() before
        # this observation. An exited/reaped exact PID is no longer visible.
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False
    def kill(self):
        if self.pid:
            try: os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        self.killed = True


class ChannelProcessTests(unittest.TestCase):
    def run_session(self, mode, full=False):
        with tempfile.TemporaryDirectory(prefix="radishlink-channel-session-") as directory:
            root = Path(directory).resolve()
            result_dir = root / "result"
            result_dir.mkdir()
            recovery_file, marker = root / "recovery", root / "worker"
            fixture = None
            if full:
                fixture = apt_fixtures.PreparationTests(methodName="test_complete_synthetic_stages_keep_real_claims_false")
                fixture.setUp()
                raw = fixture.raw()
                digest = hashlib.sha256(raw).hexdigest()
            else:
                digest = DIGEST
            def recover():
                with recovery_file.open("ab") as stream: stream.write(b"recovered\n")
                return {"stopped": True, "passed": False}
            def work():
                marker.write_text(str(os.getpid()))
                if mode in {"worker-hang", "silent", "active-eof", "signal"}: time.sleep(3)
                else: time.sleep(0.24)
                if full:
                    outcome = apt.exercise_preparation(raw, NONCE, fixture.inputs, fixture.work,
                        runner=fixture.runner, baseline_paths=fixture.baseline_paths,
                        tool_paths=fixture.tool_paths, now=lambda: apt_fixtures.NOW, evidence_root=result_dir)
                    return 0 if outcome["passed"] else 2
                result_files(result_dir)
                return 2 if mode == "worker-failed" else 0
            def prepare():
                if mode == "setup-failed": raise OSError("synthetic setup failure")
                if full:
                    (result_dir / "worker.stdout").write_bytes(b"")
                    (result_dir / "worker.stderr").write_bytes(b"")
            def transport(lease_fd, output_fd, ack_fd):
                if mode == "transport-hang":
                    time.sleep(3)
                    return 0
                if mode == "invalid":
                    os.write(output_fd, b"{}")
                    return 0
                if mode == "empty": return 0
                if mode in {"bad-ack", "terminal-race", "oversize"}:
                    incoming = json.loads(os.read(lease_fd, supervision.MAX_FRAME))
                    receipt = dict(schema_version=1, scope="i5-preparation-guest-ack", uuid=apt.UUID,
                        nonce=NONCE, manifest_sha256=digest, sequence=incoming["sequence"] + (1 if mode == "bad-ack" else 0))
                    channels.write_frame(ack_fd, channels.encode(receipt))
                    os.close(ack_fd)
                    os.close(lease_fd)
                    if mode == "bad-ack": return 2
                    if mode == "oversize":
                        for _ in range(7):
                            channels.write_bounded(output_fd, b"x" * apt.MIB, deadline=time.monotonic() + 1)
                        return 0
                    result_files(result_dir)
                    export = SyntheticExport(result_dir)
                    export.pin(0, None)
                    value = export.collect(success_report(), lambda: None)
                    export.close()
                    time.sleep(0.25)
                    channels.write_bounded(output_fd, channels.encode(value), deadline=time.monotonic() + 1)
                    return 0
                return channels.serve_preparation(lease_fd, output_fd, ack_fd, work=work, boundary=SyntheticBoundary(),
                    guard=Mock(), nonce=NONCE, manifest_sha256=digest, prepare=prepare,
                    exporter=SyntheticExport(result_dir, digest=digest), total=2, silence=0.6, subreaper=lambda: None)
            pid, writer, reader, ack = channels.fork_watchdog(transport, recover, NONCE, digest,
                total=2, silence=0.6, cleanup_seconds=0.35)
            lease = supervision.Lease(NONCE, digest, started=time.monotonic(), total=2, silence=0.6, side="host")
            data, sequence, next_renew, until = bytearray(), 0, 0, time.monotonic() + 6
            acknowledged = True
            steered = False
            try:
                while time.monotonic() < until:
                    now = time.monotonic()
                    if mode in {"active-eof", "signal"} and marker.exists() and not steered:
                        steered = True
                        if mode == "active-eof":
                            os.close(writer)
                            writer = None
                        else:
                            os.kill(pid, signal.SIGTERM)
                    if writer is not None and acknowledged and now >= next_renew:
                        action = "cancel" if mode == "cancel" and sequence == 1 else "renew"
                        try: channels.write_frame(writer, lease.frame(0 if mode == "replay" else sequence, action))
                        except BrokenPipeError:
                            os.close(writer)
                            writer = None
                        sequence += 1
                        acknowledged = False
                        next_renew = now + 0.12
                        if mode in {"eof", "result-lost"}:
                            if mode == "eof":
                                os.close(writer)
                                writer = None
                            else:
                                os.close(reader)
                                reader = None
                        if mode in {"silent", "cancel"}: next_renew = until + 1 if sequence >= (2 if mode == "cancel" else 1) else next_renew
                    if reader is None:
                        # Wait without consuming; watchdog must recover even if
                        # its otherwise successful result consumer disappeared.
                        code = channels.wait_child(pid, until)
                        self.assertEqual(code, 2)
                        break
                    ready, _, _ = select.select([reader], [], [], 0.01)
                    ack_ready, _, _ = select.select([ack], [], [], 0)
                    if ack_ready:
                        response = os.read(ack, supervision.MAX_FRAME)
                        if response:
                            receipt = json.loads(response)
                            self.assertEqual(receipt, dict(schema_version=1, scope="i5-preparation-host-ack",
                                uuid=apt.UUID, nonce=NONCE, manifest_sha256=digest, sequence=sequence - 1))
                            acknowledged = True
                    if ready:
                        chunk = os.read(reader, 65536)
                        if not chunk: break
                        data.extend(chunk)
                        self.assertLessEqual(len(data), channels.HOST_REPORT_LIMIT)
                else:
                    self.fail("watchdog exceeded test deadline")
                if reader is not None:
                    code = channels.wait_child(pid, until)
                    packet = json.loads(data)
                    expected = mode in {"ok", "terminal-race"}
                    detail = {k: v for k, v in packet.items() if k != "export"}
                    if packet["export"]:
                        detail["export_errors"] = packet["export"]["export_errors"]
                        detail["supervision"] = packet["export"]["supervision"]
                    self.assertEqual(packet["passed"], expected, detail)
                    self.assertEqual(code, 0 if expected else 2, detail)
                    self.assertFalse(packet["i5_ready"])
                    if packet["export"]:
                        channels.validate_export(channels.encode(packet["export"]), NONCE, digest)
                    if full:
                        self.assertTrue(packet["export"]["preparation"]["passed"])
                        self.assertFalse(packet["export"]["preparation"]["signature_verified"])
                self.assertEqual(recovery_file.read_bytes() if recovery_file.exists() else b"",
                                 b"" if mode in {"ok", "terminal-race"} else b"recovered\n")
                if marker.exists():
                    with self.assertRaises(ProcessLookupError): os.kill(int(marker.read_text()), 0)
            finally:
                for fd in (writer, reader, ack):
                    if fd is not None: os.close(fd)
                try:
                    done, _ = os.waitpid(pid, os.WNOHANG)
                    if not done:
                        os.kill(pid, signal.SIGTERM)
                        channels.wait_child(pid, time.monotonic() + 3)
                except ChildProcessError:
                    pass
                if fixture: fixture.doCleanups()

    def test_real_pipe_chain_and_complete_synthetic_apt_evidence(self):
        self.run_session("ok", full=True)

    def test_control_and_transport_failure_matrix_no_repeat_recovery(self):
        for mode in ("eof", "silent", "cancel", "invalid", "empty", "transport-hang", "worker-hang", "result-lost",
                     "active-eof", "signal", "replay", "bad-ack", "oversize", "worker-failed", "setup-failed"):
            with self.subTest(mode=mode): self.run_session(mode)

    def test_guest_control_eof_during_final_result_does_not_invent_failure(self):
        self.run_session("terminal-race")

    def test_nonblocking_result_writer_rejects_stalled_consumer(self):
        reader, writer = os.pipe()
        try:
            with self.assertRaisesRegex(ValueError, "consumer deadline"):
                channels.write_bounded(writer, b"x" * channels.EXPORT_LIMIT, deadline=time.monotonic() + 0.03)
        finally:
            os.close(reader)
            os.close(writer)

    def test_recovery_adapter_hang_failure_and_invalid_report_are_bounded(self):
        for mode in ("ok", "hang", "throw", "invalid", "oversize"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="radishlink-recovery-adapter-") as directory:
                marker = Path(directory) / "pid"
                def recover():
                    marker.write_text(str(os.getpid()))
                    if mode == "hang": time.sleep(3)
                    if mode == "throw": raise OSError("synthetic recovery error")
                    if mode == "oversize": return {"data": "x" * 65537}
                    return {"passed": mode == "invalid", "stopped": True}
                result = channels.bounded_recovery(recover, seconds=0.3)
                self.assertEqual(result["stopped"], mode == "ok", result)
                self.assertFalse(result["passed"])
                if mode != "ok": self.assertTrue(result["failure"])
                if mode == "throw": self.assertIn("synthetic recovery error", result["failure"])
                if marker.exists():
                    with self.assertRaises(ProcessLookupError): os.kill(int(marker.read_text()), 0)

    def test_v3_contract_binds_channels_quotas_and_keeps_old_versions(self):
        observed = {"base_revision": "a" * 40, "hashes": {name: "a" * 64 for name in control.CHANNEL_SOURCES},
            "config_sha256": "b" * 64, "utmctl_sha256": "c" * 64, "manifest_sha256": DIGEST,
            "isolation_sha256": "f" * 64,
            "media": {"path": "/synthetic/input.iso", "bytes": 1234, "sha256": "e" * 64, "read_only": True}}
        record = dict(observed, schema_version=3, scope="i5-preparation-apt-operation", nonce=NONCE,
            uuid=apt.UUID, authorized=True, guest_seconds=540, host_seconds=620, total_seconds=900,
            lease_seconds=15, cleanup_seconds=20, export_bytes=channels.EXPORT_LIMIT,
            export_data_bytes=channels.DATA_LIMIT, export_file_bytes=channels.FILE_LIMIT)
        control.validate_apt_operation(record, NONCE, observed)
        for field, value in (("export_bytes", True), ("export_data_bytes", channels.DATA_LIMIT + 1),
                             ("schema_version", 2), ("hashes", {n: "a" * 64 for n in control.ISOLATION_SOURCES})):
            with self.assertRaises(ValueError): control.validate_apt_operation(dict(record, **{field: value}), NONCE, observed)


if __name__ == "__main__":
    unittest.main()
