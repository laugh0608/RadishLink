"""Synthetic preparation tests; never invokes APT, crypto tools, network or UTM."""

import copy
import base64
import datetime
import gzip
import hashlib
import importlib.util
import json
import lzma
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import sw_i5_apt as apt
import sw_i5_utm_control as control

NONCE = "a" * 32
NOW = datetime.datetime(2026, 10, 13, 12, tzinfo=datetime.timezone.utc)
SCRIPT = Path(__file__).with_name("inspect-sw-i5-guest.py")
spec = importlib.util.spec_from_file_location("guest_apt_test", SCRIPT)
guest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guest)


def blob(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def listing(fingerprint):
    return ("pub:::::::::\nfpr:::::::::" + fingerprint + ":\nsub:::::::::\nfpr:::::::::" + "B" * 40 + ":\n").encode()


def transaction():
    rows = [f"0 upgraded, {len(apt.ROOTS)} newly installed, 0 to remove and 0 not upgraded."]
    for action in ("Inst", "Conf"):
        rows.extend(f"{action} {name.split(':')[0]} ({version} Synthetic:fixture [arm64])"
                    for name, version in apt.ROOTS.items())
    return ("\n".join(rows) + "\n").encode()


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radishlink-apt-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.inputs = self.root / "input"
        self.inputs.mkdir()
        self.work = self.root / "work"
        self.releases = {}
        files = {}
        for name, source in apt.SOURCES.items():
            release, index, key = apt.source_paths(source)
            content = b"Package: synthetic-only\nVersion: 1\nArchitecture: all\n\n"
            compressed = lzma.compress(content) if source[3] == "xz" else gzip.compress(content, mtime=0)
            prefix = f"{source[2]}/binary-arm64/Packages"
            identity = "Suite" if name == "docker" else "Codename"
            self.releases[name] = (f"{identity}: {source[1]}\nArchitectures: arm64 all\nComponents: {source[2]}\n"
                "Date: Tue, 13 Oct 2026 07:00:00 +0000\nValid-Until: Tue, 20 Oct 2026 07:00:00 +0000\nSHA256:\n"
                f" {blob(compressed)['sha256']} {len(compressed)} {prefix}.{source[3]}\n"
                f" {blob(content)['sha256']} {len(content)} {prefix}\n").encode()
            for path, data in ((release, b"synthetic signed input; not OpenPGP"), (index, compressed), (key, b"synthetic key")):
                target = self.inputs / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                files[path] = blob(data)
            byhash = self.inputs / Path(index).parent / "by-hash/SHA256" / blob(compressed)["sha256"]
            byhash.parent.mkdir(parents=True, exist_ok=True)
            byhash.write_bytes(compressed)
        self.baseline_paths, baseline = {}, {}
        for name, data in (("status", b"Package: base-package\nVersion: 1.0\nArchitecture: all\nStatus: install ok installed\n\n"),
                           ("extended_states", b"Package: base-package\nAuto-Installed: 1\n"), ("crypto_policy", None)):
            path = self.root / name
            self.baseline_paths[name] = path
            if data:
                path.write_bytes(data)
            baseline[name] = blob(data) if data else None
        self.tool_paths, tools = {}, {}
        for name, owner in apt.TOOLS.items():
            path = self.root / ("tool-" + name)
            path.write_bytes(b"synthetic binary; not executed")
            self.tool_paths[name] = path
            tools[name] = {"package": owner, "version": "1.0", "sha256": blob(path.read_bytes())["sha256"]}
        baseline.update(architecture="arm64", foreign_architectures=[], tools=tools)
        self.manifest = {"schema_version": 1, "scope": "i5-preparation-apt-input", "nonce": NONCE, "uuid": apt.UUID,
                         "files": files, "baseline": baseline, "install_authorized": False, "i5_ready": False}
        self.calls = []
        self.mode = "ok"

    def raw(self):
        return json.dumps(self.manifest).encode()

    def runner(self, argv, **kwargs):
        self.calls.append(argv)
        self.assertNotIn("SEQUOIA_CRYPTO_POLICY", kwargs["env"])
        self.assertNotIn("http_proxy", kwargs["env"])
        self.assertLessEqual(kwargs["timeout"], apt.GUEST_SECONDS)
        out, err, code = b"", b"", 0
        tool = Path(argv[0]).name
        if tool == "dpkg":
            out = b"arm64\n" if argv[1] == "--print-architecture" else b""
            if self.mode == "foreign" and not out:
                out = b"amd64\n"
        elif tool == "dpkg-query":
            out = (f"{apt.TOOLS[Path(argv[-1]).name]}: {argv[-1]}\n" if argv[1] == "-S" else "1.0\n").encode()
            if self.mode == "ownership" and argv[1] == "-S":
                out = b"other: /usr/bin/gpg\n"
        elif tool == "gpg":
            source = next(s for s in apt.SOURCES.values() if argv[-1].endswith(apt.source_paths(s)[2]))
            out = listing(source[5] if self.mode != "fingerprint" else "0" * 40)
        elif tool == "sqv":
            path = Path(argv[argv.index("--output") + 1])
            data = self.releases[path.stem]
            if self.mode == "expired":
                data = data.replace(b"20 Oct 2026", b"12 Oct 2026")
            path.write_bytes(data)
            if self.mode == "signature":
                code, err = 7, b"synthetic signature rejected; partial output must not be read"
        elif tool == "apt-config":
            generated, settings = apt.apt_files(self.inputs, self.work, {"base-package:arm64": "1.0"})
            for path, content in generated.items():
                self.assertEqual((self.work / path).read_text(), content)
            out = "".join(f'{key} "{value}";\n' for key, value in settings.items()).encode()
            if self.mode == "hook":
                out += b'DPkg::Post-Invoke:: "bad";\n'
        elif tool == "apt-get":
            if argv[-1] == "update":
                self.assertEqual(argv, ["/usr/bin/apt-get", "--error-on=any", "update"])
                if self.mode == "apt-failure":
                    code, err = 100, b"synthetic dependency failure"
            else:
                self.assertIn("-s", argv)
                self.assertIn("--no-download", argv)
                self.assertIn("--no-remove", argv)
                out = transaction()
                if self.mode == "baseline-change":
                    self.baseline_paths["status"].write_bytes(b"changed")
                if self.mode == "remove":
                    out += b"Remv base-package [1.0]\n"
                if self.mode == "cleanup":
                    return {"stdout": out, "stderr": err, "exit_code": code, "failure": None,
                            "cleanup_errors": ["synthetic remaining descendant"]}
        else:
            self.fail("unexpected tool " + tool)
        return {"stdout": out, "stderr": err, "exit_code": code, "failure": None, "cleanup_errors": []}

    def exercise(self):
        return apt.exercise_preparation(self.raw(), NONCE, self.inputs, self.work, runner=self.runner,
                    baseline_paths=self.baseline_paths, tool_paths=self.tool_paths, now=lambda: NOW)

    def test_complete_synthetic_stages_keep_real_claims_false(self):
        with patch.object(subprocess, "Popen", side_effect=AssertionError("real tool forbidden")):
            result = self.exercise()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["added"], apt.ROOTS)
        for field in ("i5_ready", "install_authorized", "signature_verified", "apt_resolved"):
            self.assertIs(result[field], False)
        self.assertEqual(result["evidence_kind"], "synthetic")
        self.assertEqual((self.work / "status").read_bytes(), self.baseline_paths["status"].read_bytes())
        self.assertEqual(len(result["steps"]), 25)
        with self.assertRaisesRegex(ValueError, "fresh"):
            self.exercise()

    def test_stage_failures_preserve_evidence_and_stop(self):
        for mode in ("foreign", "ownership", "fingerprint", "expired", "signature", "hook", "apt-failure",
                     "baseline-change", "remove", "cleanup"):
            with self.subTest(mode=mode):
                # Independent owned workspace; no retries into previous evidence.
                self.work = self.root / ("work-" + mode)
                self.mode, self.calls = mode, []
                original = self.baseline_paths["status"].read_bytes()
                result = self.exercise()
                self.assertFalse(result["passed"])
                self.assertTrue(result["failure"])
                self.assertTrue((self.work / "result.json").is_file())
                if mode in {"foreign", "ownership", "fingerprint", "expired", "signature", "hook"}:
                    self.assertFalse(any(c[0] == "/usr/bin/apt-get" for c in self.calls))
                if mode == "signature":
                    self.assertEqual(result["steps"][-1]["exit_code"], 7)
                    self.assertIn(b"partial output", (self.work / "verify-debian.stderr").read_bytes())
                self.baseline_paths["status"].write_bytes(original)

    def test_baseline_changed_before_any_tools(self):
        self.baseline_paths["status"].write_bytes(b"changed")
        result = self.exercise()
        self.assertFalse(result["passed"])
        self.assertFalse(self.calls)

    def test_input_and_manifest_rejections(self):
        good = self.raw()
        mutations = [dict(scope="i5-metadata-input-review-only"), dict(nonce="b" * 32), dict(uuid="other"),
                     dict(schema_version=True), dict(install_authorized=True), dict(extra=1)]
        for delta in mutations:
            value = json.loads(good)
            value.update(delta)
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                apt.validate_manifest(json.dumps(value).encode(), NONCE)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            apt.validate_manifest(good[:-1] + b',"uuid":"duplicate"}', NONCE)
        for path in ("../outside", "https://example.invalid/Packages"):
            value = json.loads(good)
            value["files"][path] = blob(b"x")
            with self.assertRaisesRegex(ValueError, "whitelist"):
                apt.validate_manifest(json.dumps(value).encode(), NONCE)
        key = self.inputs / "keys/docker.asc"
        key.unlink()
        key.symlink_to(self.baseline_paths["status"])
        with self.assertRaisesRegex(ValueError, "symlink"):
            apt.check_inputs(self.inputs, self.manifest)

    def test_media_hash_and_unknown_file_rejection(self):
        (self.inputs / "keys/docker.asc").write_bytes(b"altered")
        with self.assertRaisesRegex(ValueError, "digest"):
            apt.check_inputs(self.inputs, self.manifest)
        (self.inputs / "keys/docker.asc").write_bytes(b"synthetic key")
        (self.inputs / "extra").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "file set"):
            apt.check_inputs(self.inputs, self.manifest)

    def test_release_dates_digest_duplicates_and_identity(self):
        source = apt.SOURCES["updates"]
        raw = self.releases["updates"]
        apt.release_index(raw, source, NOW)
        for data in (raw.replace(b"20 Oct", b"12 Oct"), raw.replace(b"13 Oct", b"14 Oct"),
                     raw.replace(b"Codename: trixie-updates", b"Codename: other"),
                     raw + b"Date: Tue, 13 Oct 2026 07:00:00 +0000\n",
                     raw.replace(b"Valid-Until:", b"Other:"), raw + raw.splitlines()[-1] + b"\n"):
            with self.assertRaises(ValueError):
                apt.release_index(data, source, NOW)

    def test_compression_limits_truncation_trailing_streams(self):
        for codec in ("gz", "xz"):
            data = gzip.compress(b"x" * 100000) if codec == "gz" else lzma.compress(b"x" * 100000)
            path = self.root / ("bomb." + codec)
            path.write_bytes(data)
            self.assertEqual(apt.unpacked_blob(path, codec, 100000), blob(b"x" * 100000))
            with self.assertRaisesRegex(ValueError, "limit"):
                apt.unpacked_blob(path, codec, 99999)
            for bad in (data[:-1], data + b"extra", data + data):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    apt.unpacked_blob(path, codec, 200000)

    def test_key_fingerprints_no_short_id_or_extra_certificate(self):
        fingerprint = apt.SOURCES["docker"][5]
        self.assertEqual(apt.key_fingerprints(listing(fingerprint), fingerprint)["subkeys"], ["B" * 40])
        for raw in (listing("A" * 40), listing(fingerprint[-16:]), listing(fingerprint) * 2,
                    b"pub:::::::::\n", listing(fingerprint) + b"unknown:\n"):
            with self.assertRaises(ValueError):
                apt.key_fingerprints(raw, fingerprint)

    def test_configuration_pins_and_transactions(self):
        files, settings = apt.apt_files(self.inputs, self.work, {"base-package:arm64": "1.0"})
        self.assertEqual(files["sources.list"].count("file:"), 4)
        self.assertNotIn("trusted=yes", files["sources.list"])
        self.assertIn("Pin: version 1.0\nPin-Priority: 1001\n\nPackage: base-package:arm64\nPin: version *\nPin-Priority: -1", files["preferences"])
        with self.assertRaisesRegex(ValueError, "change installed"):
            apt.apt_files(self.inputs, self.work, {"git:arm64": "0.1"})
        for line in (b"Remv base-package [1.0]\n", b"Inst base-package (1.0 fixture [arm64])\n",
                     b"Inst git [0.1] (1:2.47.3-0+deb13u1 fixture [arm64])\n", b"W: ignored\n"):
            with self.assertRaises(ValueError):
                apt.simulation(transaction() + line, {"base-package:arm64": "1.0"})
        with self.assertRaises(ValueError):
            apt.simulation(transaction().replace(b"0 upgraded", b"1 upgraded"), {})
        with self.assertRaises(ValueError):
            apt.simulation(b"", {})
        dump = "".join(f'{k} "{v}";\n' for k, v in settings.items()).encode()
        for extra in (b'Binary::apt-get::DPkg::Post-Invoke:: "bad";\n',
                      b'Acquire::IndexTargets::deb::Translations::MetaKey "bad";\n',
                      b'APT::Architectures:: "amd64";\n'):
            with self.assertRaises(ValueError):
                apt.validate_config_dump(dump + extra, settings)

    def test_cli_local_validation_and_all_public_stops_before_external_calls(self):
        completed = subprocess.run([sys.executable, "-B", str(SCRIPT), "--nonce", NONCE,
                                    "--validate-preparation-input"], input=self.raw(), capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = apt.validate_result(completed.stdout, NONCE, hashlib.sha256(self.raw()).hexdigest())
        self.assertEqual(result["failure"], apt.STOP)
        with patch.object(guest, "check_utm_config", side_effect=AssertionError("external config read")):
            with self.assertRaisesRegex(RuntimeError, apt.STOP):
                guest.collect_utm(NONCE, "preparation-apt")
        for argv in ([sys.executable, "-B", str(SCRIPT), "--nonce", NONCE, "--preparation-apt"],
                     [sys.executable, "-B", str(Path(control.__file__)), "--authorized-once", "--nonce", NONCE,
                      "--scope", "preparation-apt"]):
            completed = subprocess.run(argv, capture_output=True)
            self.assertEqual(completed.returncode, 2)
            self.assertIn(apt.STOP.encode(), completed.stderr)
        for key, value in (("signature_verified", True), ("apt_resolved", True), ("nonce", "b" * 32),
                           ("manifest_sha256", "b" * 64), ("passed", True), ("extra", 1)):
            changed = dict(result, **{key: value})
            with self.assertRaises(ValueError):
                apt.validate_result(json.dumps(changed).encode(), NONCE, hashlib.sha256(self.raw()).hexdigest())

    def test_operation_binding_and_deadlines(self):
        observed = {"base_revision": "a" * 40, "hashes": {name: "a" * 64 for name in control.APT_SOURCES},
                    "config_sha256": "b" * 64, "utmctl_sha256": "c" * 64, "manifest_sha256": "d" * 64,
                    "media": {"path": "/synthetic/input.iso", "bytes": 1234, "sha256": "e" * 64, "read_only": True}}
        record = dict(observed, schema_version=1, scope="i5-preparation-apt-operation", nonce=NONCE,
                      uuid=apt.UUID, authorized=True, guest_seconds=apt.GUEST_SECONDS,
                      host_seconds=apt.HOST_SECONDS, total_seconds=900)
        control.validate_apt_operation(record, NONCE, observed)
        for field in observed:
            changed = copy.deepcopy(observed)
            changed[field] = None
            with self.assertRaises(ValueError):
                control.validate_apt_operation(record, NONCE, changed)
        with self.assertRaises(ValueError):
            control.validate_apt_operation(record, "b" * 32, observed)
        with self.assertRaises(ValueError):
            control.validate_apt_operation(dict(record, guest_seconds=apt.HOST_SECONDS), NONCE, observed)
        self.assertLess(apt.GUEST_SECONDS, apt.ADAPTER_SECONDS)
        self.assertLess(apt.ADAPTER_SECONDS, apt.HOST_SECONDS)
        self.assertLessEqual(60 + 60 + apt.HOST_SECONDS + 120, 900)

    def test_utm_transport_scope_and_old_limits(self):
        raw = json.dumps(apt.blocked_result(NONCE, "a" * 64)).encode()
        envelope = {"schema_version": 1, "scope": "utm-guest-execution", "uuid": apt.UUID, "nonce": NONCE,
                    "case_name": "preparation-apt", "exited": True, "exit_code": 2, "signal_code": 0,
                    "stdout_base64": base64.b64encode(raw).decode(), "stderr_base64": "", "polls": 1,
                    "manifest_sha256": "a" * 64}
        _, output, _ = guest.parse_execution(json.dumps(envelope).encode(), NONCE, "preparation-apt", "a" * 64)
        self.assertEqual(output, raw)
        with self.assertRaisesRegex(ValueError, "binding"):
            guest.parse_execution(json.dumps(envelope).encode(), NONCE, "details")
        with self.assertRaisesRegex(ValueError, "manifest binding"):
            guest.parse_execution(json.dumps(envelope).encode(), NONCE, "preparation-apt", "b" * 64)
        self.assertEqual(guest.return_limits("details"), (512 * 1024, 2 * apt.MIB))
        self.assertEqual(guest.return_limits("inventory"), (128 * 1024, 512 * 1024))
        envelope["stdout_base64"] = base64.b64encode(b"x" * (apt.RESULT_LIMIT + 1)).decode()
        with self.assertRaisesRegex(ValueError, "oversized"):
            guest.parse_execution(json.dumps(envelope).encode(), NONCE, "preparation-apt", "a" * 64)

    def test_local_deadline_and_cancel_no_runner_calls(self):
        for mode in ("cancel", "deadline"):
            self.work = self.root / ("work-" + mode)
            with patch.object(apt, "GUEST_SECONDS", 0 if mode == "deadline" else 540):
                result = apt.exercise_preparation(self.raw(), NONCE, self.inputs, self.work, runner=self.runner,
                    baseline_paths=self.baseline_paths, tool_paths=self.tool_paths, now=lambda: NOW,
                    cancelled=lambda: mode == "cancel")
            self.assertFalse(result["passed"])
            self.assertIn(mode, result["failure"])
            self.assertFalse(self.calls)


class BoundedProcessTests(unittest.TestCase):
    def run_child(self, code, **kwargs):
        with tempfile.TemporaryDirectory(prefix="radishlink-process-") as directory:
            return apt.run_bounded([sys.executable, "-I", "-B", "-c", code], cwd=directory,
                    env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, timeout=kwargs.pop("timeout", 2),
                    stdout_limit=1024, stderr_limit=128, **kwargs)

    def test_exact_limits_exit_status_stdin_and_empty_environment(self):
        result = self.run_child("import os,sys; assert sys.stdin.read()==''; assert 'APT_CONFIG' not in os.environ; "
                                "os.write(1,b'x'*1024); os.write(2,b'y'*128); sys.exit(17)")
        self.assertEqual((len(result["stdout"]), len(result["stderr"]), result["exit_code"]), (1024, 128, 17))
        self.assertIsNone(result["failure"])
        self.assertFalse(result["cleanup_errors"])

    def test_floods_are_bounded_before_retention(self):
        for fd, limit, field in ((1, 1024, "stdout"), (2, 128, "stderr")):
            result = self.run_child(f"import os\nwhile True: os.write({fd},b'x'*65536)")
            self.assertEqual(result["failure"], field + "-limit")
            self.assertEqual(len(result[field]), limit)
            self.assertFalse(result["cleanup_errors"])

    def test_timeout_and_cancellation_cleanup(self):
        result = self.run_child("import time; time.sleep(60)", timeout=0.15)
        self.assertEqual(result["failure"], "deadline")
        self.assertFalse(result["cleanup_errors"])
        origin = time.monotonic()
        result = self.run_child("import time; time.sleep(60)", cancelled=lambda: time.monotonic() - origin > 0.15)
        self.assertEqual(result["failure"], "cancelled")
        self.assertFalse(result["cleanup_errors"])
        with patch.object(subprocess, "Popen") as launch:
            result = self.run_child("raise Exception('never')", cancelled=lambda: True)
            launch.assert_not_called()

    def test_closed_pipe_descendant_never_passes(self):
        code = ("import os,time\n"
                "pid=os.fork()\n"
                "if pid==0:\n os.close(1); os.close(2); time.sleep(1); os._exit(0)\n"
                "os.write(1,str(pid).encode())\n"
                "os._exit(0)\n")
        result = self.run_child(code, cleanup_seconds=0.5)
        self.assertEqual(result["failure"], "descendants-remained")
        # A zombie visible to killpg is explicitly unconfirmed, never PASS.
        self.assertTrue(result["exit_code"] == 0)

    def test_cleanup_error_preserves_first_failure(self):
        real = os.killpg
        def fail_probe(pgid, sig):
            if sig == 0:
                raise PermissionError("synthetic denied group probe")
            return real(pgid, sig)
        # Completed leader, no live child is left by this injection.
        with patch.object(apt.os, "killpg", side_effect=fail_probe):
            result = self.run_child("import os; os.write(1,b'x'*1025)")
        self.assertEqual(result["failure"], "stdout-limit")
        self.assertIn("synthetic denied group probe", result["cleanup_errors"][0])

    def test_sigterm_wrapper_reaps_owned_process_group(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-signal-") as directory:
            root = Path(directory).resolve()
            marker = root / "child-pid"
            child = "import os,time; from pathlib import Path; Path(" + repr(str(marker)) + ").write_text(str(os.getpid())); time.sleep(60)"
            wrapper = ("import sys,json; sys.path.insert(0," + repr(str(Path(apt.__file__).parent)) + "); "
                       "import sw_i5_apt as apt; r=apt.run_bounded([sys.executable,'-I','-B','-c'," + repr(child) + "],"
                       "cwd=" + repr(str(root)) + ",env={},timeout=5); "
                       "print(json.dumps({k:v for k,v in r.items() if k not in ('stdout','stderr')}))")
            process = subprocess.Popen([sys.executable, "-I", "-B", "-c", wrapper], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                until = time.monotonic() + 3
                while not marker.exists() and process.poll() is None and time.monotonic() < until:
                    time.sleep(0.01)
                self.assertTrue(marker.exists(), "child did not start")
                process.send_signal(signal.SIGTERM)
                out, err = process.communicate(timeout=4)
                self.assertEqual(process.returncode, 0, err)
                result = json.loads(out)
                self.assertEqual(result["failure"], "cancelled-signal-15")
                self.assertFalse(result["cleanup_errors"])
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(marker.read_text()), 0)
            finally:
                if process.poll() is None:
                    # Let the wrapper's bounded timer clean its own group.
                    process.communicate(timeout=8)

    def test_launch_failure_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-launch-") as directory:
            result = apt.run_bounded([str(Path(directory) / "absent")], cwd=directory, env={}, timeout=1)
        self.assertIn("FileNotFoundError", result["failure"])
        self.assertIsNone(result["exit_code"])


if __name__ == "__main__":
    unittest.main()
