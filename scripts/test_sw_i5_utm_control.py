"""Offline lifecycle regressions. All external processes and clocks are mocked."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import sw_i5_utm_control as control


class ControlTests(unittest.TestCase):
    def scenario(self, mode):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-control.") as directory:
            repo = Path(directory).resolve()
            nonce = "a" * 32
            root = repo / ".tmp" / ("i5-guest-return-" + nonce)
            root.mkdir(parents=True)
            for name in control.SOURCES:
                path = repo / name
                path.parent.mkdir(exist_ok=True)
                path.write_text("# synthetic source\n")
            script = repo / "scripts/inspect-sw-i5-guest.py"
            script.write_text('def check_utm_config(): pass\ndef parse_execution(*args): return {"fixture":True}, b"{}", b""\ndef verify_case(*args): pass\n')
            config = repo / "VirtualMachines/RadishLink-I5-Debian13-ARM64.utm/config.plist"
            config.parent.mkdir(parents=True)
            config.write_bytes(b"synthetic config")
            binary = repo / "utmctl"
            binary.write_bytes(b"synthetic executable; never executed")
            record = {"schema_version": 1, "scope": "i5-preparation-lifecycle-operation",
                      "authorized": mode != "unauthorized", "nonce": nonce, "uuid": control.UUID,
                      "base_revision": "b" * 40,
                      "hashes": {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in control.SOURCES},
                      "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                      "utmctl_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
            if mode == "missing-hash": record["hashes"].pop(control.SOURCES[0])
            if mode == "unknown-field": record["extra"] = True
            if mode == "wrong-schema": record["schema_version"] = True
            if mode == "wrong-target": record["uuid"] = "other-vm"
            (root / "operation.json").write_text(json.dumps(record))
            if mode == "source-changed": script.write_text("# changed\n")
            if mode == "tool-changed": binary.write_bytes(b"changed")
            if mode == "config-changed": config.write_bytes(b"changed")
            if mode == "stale-evidence": (root / "start.stdout").write_bytes(b"old")
            if mode == "redirected-record":
                outside = repo / "operation.json"
                (root / "operation.json").rename(outside)
                (root / "operation.json").symlink_to(outside)
            calls, clock = [], [0.0]
            shutdown = [False]

            def run(argv, **kwargs):
                calls.append((argv, clock[0]))
                out, err, code = b"", b"", 0
                if argv[0] == str(binary):
                    verb = argv[1]
                    if verb == "list":
                        out = control.UUID.encode() + b" stopped"
                        if mode == "other-state-changed" and shutdown[0]: out += b" other-started"
                        if mode == "list-stderr":
                            err = b"TISFileInterrogator synthetic cache diagnostic\nKeyboard Layouts: duplicate keyboard layout identifier -12345.\n"
                        if mode == "list-nonzero": code = 1
                        if mode == "list-timeout": raise subprocess.TimeoutExpired(argv, 15)
                        if mode == "list-oversized": out += b"x" * 65536
                        if mode == "list-no-target": out = b"other-vm stopped"
                    elif verb == "start":
                        self.assertEqual(argv, [str(binary), "start", control.UUID])
                        if mode == "start-stderr": err = b"OSStatus error -10004"
                        if mode == "start-timeout":
                            clock[0] += kwargs["timeout"]
                            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                        if mode == "start-oserror": raise OSError("fixture launch error")
                    elif verb == "status":
                        started = any(c[0][1] == "start" for c in calls)
                        forced = any("--force" in c[0] for c in calls)
                        out = b"started" if started and not shutdown[0] else b"stopped"
                        if mode == "already-started": out = b"started"
                        if mode == "status-stderr": err = b"synthetic status diagnostic"
                        if mode == "status-nonzero": code = 1
                        if mode == "status-unknown": out = b"starting"
                        if mode == "status-timeout": raise subprocess.TimeoutExpired(argv, 15)
                        if mode == "started-unconfirmed" and started and not shutdown[0]: out = b"starting"
                        if mode in {"force", "force-failed"} and shutdown[0] and (not forced or mode == "force-failed"):
                            out = b"started"
                    elif verb == "stop":
                        shutdown[0] = True
                        if mode == "post-config-changed": config.write_bytes(b"changed")
                        if mode == "force-failed" and "--force" in argv: code, err = 1, b"fixture stop error"
                else:
                    self.assertIn("--collect-utm", argv)
                    self.assertIn("details", argv)
                    if mode == "details-timeout": raise subprocess.TimeoutExpired(argv, 65)
                    if mode == "details-failed": code, err = 2, b"fixture failure"
                    else:
                        evidence = root / "details"
                        evidence.mkdir()
                        (evidence / "execution.json").write_text('{"fixture":true}')
                        (evidence / "guest.stdout").write_bytes(b"wrong" if mode == "evidence-mismatch" else b"{}")
                        (evidence / "guest.stderr").write_bytes(b"")
                return subprocess.CompletedProcess(argv, code, out, err)

            original_write = Path.write_bytes
            original_text_write = Path.write_text

            def write(path, data):
                if mode in {"shutdown-log-error", "start-log-error"} and path.name == (
                        "shutdown-request.stdout" if mode == "shutdown-log-error" else "start.stdout"):
                    raise OSError("fixture disk full")
                if (mode == "list-log-error" and path.name == "list-before.stdout") or \
                        (mode == "status-log-error" and path.name == "status-before.stdout"):
                    raise OSError("fixture baseline evidence full")
                return original_write(path, data)

            def write_text(path, data, *args, **kwargs):
                if mode == "result-write-error" and path.name == "result.json":
                    raise OSError("fixture result evidence full")
                return original_text_write(path, data, *args, **kwargs)

            pre_reject = {"unauthorized", "missing-hash", "unknown-field", "wrong-schema", "wrong-target",
                          "source-changed", "tool-changed", "config-changed", "stale-evidence", "redirected-record"}
            baseline_reject = {"already-started", "list-stderr", "list-nonzero", "list-timeout",
                               "list-oversized", "list-no-target", "list-log-error", "status-stderr",
                               "status-nonzero", "status-unknown", "status-timeout", "status-log-error"}
            output = io.StringIO()
            with patch.object(control, "REPO", repo), patch.object(control, "SCRIPT", script), \
                    patch.object(control, "UTMCTL", binary), patch.object(Path, "home", return_value=repo), \
                    patch.object(sys, "argv", ["control", "--authorized-once", "--nonce", nonce]), \
                    patch.object(control.subprocess, "run", side_effect=run), \
                    patch.object(control.time, "monotonic", side_effect=lambda: clock[0]), \
                    patch.object(control.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
                    patch.object(Path, "write_bytes", write), patch.object(Path, "write_text", write_text), \
                    redirect_stdout(output):
                if mode in pre_reject:
                    with self.assertRaises((ValueError, FileExistsError, RuntimeError)): control.main()
                    self.assertFalse(any(c[0][1] in {"start", "stop"} for c in calls))
                    self.assertEqual(calls, [])
                    return
                code = control.main()
                if mode != "post-config-changed":
                    count = len(calls)
                    with self.assertRaises(FileExistsError): control.main()
                    self.assertEqual(len(calls), count)
            self.assertEqual(code, 0 if mode == "success" else 2)
            if mode == "result-write-error":
                self.assertFalse((root / "result.json").exists())
                emitted = output.getvalue()
                result = json.loads(emitted[emitted.index("{"):])
                self.assertFalse(result["passed"])
                self.assertEqual(result["failure_phase"], "result-write")
                self.assertTrue(any("result evidence write:" in error for error in result["errors"]))
            else:
                result = json.loads((root / "result.json").read_text())
            if mode in baseline_reject:
                self.assertEqual([c[0][1] for c in calls], ["list", "status"])
                self.assertFalse(result["passed"])
                self.assertFalse(result["start_attempted"])
                self.assertFalse(result["guest_details_verified"])
                self.assertFalse(result["forced_stop"])
                self.assertEqual(result["failure_phase"], "pre-boot-baseline")
                self.assertIsNone(result["all_vm_states_unchanged"])
                self.assertTrue(result["config_unchanged"])
                if mode.startswith("status-"):
                    self.assertIsNone(result["status_before"])
                    self.assertIsNone(result["stopped"])
                else:
                    self.assertEqual(result["status_before"], "started" if mode == "already-started" else "stopped")
                    self.assertEqual(result["stopped"], mode != "already-started")
                self.assertEqual([e["stage"] for e in result["events"]], ["baseline-attempt", "baseline-rejected"])
                self.assertTrue(result["errors"])
                if mode == "list-stderr":
                    self.assertIn(b"TISFileInterrogator", (root / "list-before.stderr").read_bytes())
                return
            self.assertEqual(sum(c[0][1] == "start" for c in calls), 1)
            no_details = mode in {"start-stderr", "start-timeout", "start-oserror", "start-log-error", "started-unconfirmed"}
            self.assertEqual(sum(c[0][0] != str(binary) for c in calls), 0 if no_details else 1)
            self.assertEqual(sum("--request" in c[0] for c in calls), 1)
            self.assertEqual(result["passed"], mode == "success")
            self.assertEqual(result["stopped"], mode != "force-failed")
            self.assertEqual(result["forced_stop"], mode in {"force", "force-failed"})
            events = {e["stage"]: e["elapsed_seconds"] for e in result["events"]}
            self.assertGreaterEqual(events["shutdown-request"] - events["start-returned"], 30)
            self.assertEqual("guest-details-verified" in events, result["guest_details_verified"])
            if no_details: self.assertFalse(result["guest_details_verified"])
            if result["forced_stop"]:
                self.assertGreaterEqual(events["shutdown-force"] - events["shutdown-request"], 120)
                self.assertEqual(sum("--force" in c[0] for c in calls), 1)
            if mode == "success":
                self.assertLessEqual(events["vm-started-observed"], events["boot-grace-complete"])
                self.assertLessEqual(events["boot-grace-complete"], events["details-attempt"])
                self.assertLessEqual(events["details-attempt"], events["guest-details-verified"])

    def test_lifecycle(self):
        for mode in ("success", "start-stderr", "start-timeout", "start-oserror", "start-log-error",
                     "started-unconfirmed", "details-failed", "details-timeout", "evidence-mismatch",
                     "force", "force-failed", "shutdown-log-error", "already-started",
                     "post-config-changed", "other-state-changed", "result-write-error"):
            with self.subTest(mode=mode): self.scenario(mode)

    def test_preconditions(self):
        for mode in ("unauthorized", "missing-hash", "unknown-field", "wrong-schema", "wrong-target",
                     "source-changed", "tool-changed", "config-changed", "stale-evidence", "redirected-record"):
            with self.subTest(mode=mode): self.scenario(mode)

    def test_baseline_failure_report(self):
        for mode in ("list-stderr", "list-nonzero", "list-timeout", "list-oversized", "list-no-target",
                     "list-log-error", "status-stderr", "status-nonzero", "status-unknown", "status-timeout",
                     "status-log-error"):
            with self.subTest(mode=mode): self.scenario(mode)

    def test_invalid_nonce(self):
        for nonce in ("../elsewhere", "a" * 31, "A" * 32, "a" * 33):
            with self.subTest(nonce=nonce), self.assertRaises(ValueError): control.read_operation(nonce)


if __name__ == "__main__":
    unittest.main()
