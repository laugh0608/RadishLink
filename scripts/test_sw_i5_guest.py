#!/usr/bin/env python3
"""Synthetic guest-inventory regressions; no VM, network or real subprocesses."""

import sys

sys.dont_write_bytecode = True

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import base64
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "i5_guest", Path(__file__).with_name("inspect-sw-i5-guest.py"))
guest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guest)
NONCE = "a" * 32


class InventoryTests(unittest.TestCase):
    def collect(self, interfaces=None):
        facts = {
            "/etc/os-release": 'ID=debian\nVERSION_ID="13"\nPRETTY_NAME="Debian fixture"',
            "/sys/block/vda/size": "2048", "/sys/block/vda/ro": "0",
            "/proc/self/status": "CapEff:\t0\nCapPrm:\t0\nNoNewPrivs:\t1\nSeccomp:\t0",
            "/proc/meminfo": "MemTotal: 4096 kB\nMemAvailable: 2048 kB\nSwapTotal: 0 kB",
            "/proc/net/route": "fixture header", "/proc/net/ipv6_route": "",
        }
        net_reads = iter(interfaces or [[Path("lo")], [Path("lo")]])

        def entries(path):
            if str(path) == "/sys/class/net":
                return next(net_reads)
            if str(path) == "/sys/block":
                return [Path("/sys/block/vda")]
            raise AssertionError("unexpected directory: " + str(path))

        with ExitStack() as stack:
            stack.enter_context(patch.object(guest.platform, "system", return_value="Linux"))
            stack.enter_context(patch.object(guest.platform, "machine", return_value="aarch64"))
            stack.enter_context(patch.object(guest.platform, "release", return_value="fixture-kernel"))
            stack.enter_context(patch.object(guest.platform, "python_version", return_value="3.fixture"))
            reads = stack.enter_context(patch.object(guest, "read", side_effect=lambda p: facts[str(p)]))
            stack.enter_context(patch.object(Path, "iterdir", entries))
            stack.enter_context(patch.object(Path, "is_file", return_value=False))
            stack.enter_context(patch.object(Path, "glob", return_value=[Path("ssh_host_fixture_key.pub")]))
            stack.enter_context(patch.object(guest.os, "statvfs", return_value=SimpleNamespace(f_bavail=1024, f_frsize=4096)))
            stack.enter_context(patch.object(guest.os, "getuid", return_value=1000))
            stack.enter_context(patch.object(guest.os, "geteuid", return_value=1000))
            stack.enter_context(patch.object(guest, "landlock_abi", return_value={"abi": 5, "meets_build_minimum": True}))
            stack.enter_context(patch.object(guest, "package_inventory", return_value={"exit_code": 0, "rows": [], "diagnostic": []}))
            stack.enter_context(patch.object(guest.subprocess, "run", side_effect=AssertionError("real subprocess forbidden")))
            result = guest.inventory(NONCE)
            self.assertNotIn("/etc/machine-id", [str(c.args[0]) for c in reads.call_args_list])
            return result

    def test_complete_inventory_and_no_identity_contents(self):
        result = self.collect()
        self.assertEqual(result["block_devices"], [{"name": "vda", "bytes": 1048576, "read_only": False}])
        self.assertEqual(result["ssh_public_host_key_count"], 1)
        self.assertFalse(result["i5_ready"])
        self.assertFalse(result["identity_regeneration_verified"])
        self.assertEqual(guest.validate_result(json.dumps(result).encode(), NONCE), result)

    def test_extra_nic_rejected_before_other_reads(self):
        with patch.object(guest.platform, "system", return_value="Linux"), \
                patch.object(Path, "iterdir", return_value=[Path("lo"), Path("eth0")]), \
                patch.object(guest, "read") as reads, patch.object(guest, "package_inventory") as packages:
            with self.assertRaisesRegex(RuntimeError, "loopback-only"):
                guest.inventory(NONCE)
            reads.assert_not_called()
            packages.assert_not_called()

    def test_network_changes_during_collection_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "loopback-only"):
            self.collect([[Path("lo")], [Path("lo"), Path("eth0")]])

    def test_empty_network_and_read_failure_rejected(self):
        for value in ([], OSError("fixture network read error")):
            with patch.object(Path, "iterdir", **({"side_effect": value} if isinstance(value, Exception)
                                                 else {"return_value": value})):
                with self.assertRaises((OSError, RuntimeError)):
                    guest.require_loopback_only()

    def test_non_linux_rejected_before_probe(self):
        with patch.object(guest.platform, "system", return_value="Darwin"), \
                patch.object(guest, "require_loopback_only") as network:
            with self.assertRaisesRegex(RuntimeError, "Linux guest required"):
                guest.inventory(NONCE)
            network.assert_not_called()

    def test_missing_package_is_evidence_not_installed(self):
        response = SimpleNamespace(returncode=1, stdout="python3\t3.fixture\tinstalled\n",
                                   stderr="fixture missing package\n")
        with patch.object(guest.subprocess, "run", return_value=response) as run:
            result = guest.package_inventory()
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["diagnostic"], ["fixture missing package"])
        self.assertEqual(run.call_args.args[0][0], "/usr/bin/dpkg-query")
        self.assertEqual(run.call_args.kwargs["timeout"], 15)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_package_failure_and_timeout_propagate(self):
        with patch.object(guest.subprocess, "run", return_value=SimpleNamespace(returncode=2, stderr="fixture failure")):
            with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                guest.package_inventory()
        with patch.object(guest.subprocess, "run", side_effect=subprocess.TimeoutExpired("dpkg-query", 15)):
            with self.assertRaises(subprocess.TimeoutExpired):
                guest.package_inventory()

    def test_return_framing_rejections(self):
        good = self.collect()
        for key, value in (("nonce", "b" * 32), ("schema_version", True), ("schema_version", 2),
                           ("scope", "other"), ("i5_ready", True), ("i5_ready", 0),
                           ("identity_regeneration_verified", True), ("loopback_only", 1),
                           ("network_interfaces", ["lo", "eth0"]), ("kernel", None),
                           ("root_available_bytes", -1), ("uid", True)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                guest.validate_result(json.dumps({**good, key: value}).encode(), NONCE)
        for key in good:
            partial = dict(good)
            del partial[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                guest.validate_result(json.dumps(partial).encode(), NONCE)

    def test_invalid_json_duplicate_and_oversize_rejected(self):
        for raw in (b"", b"[]", b"{}", b"\xff", b'{"a":1,"a":2}',
                    b'{"nested":{"a":1,"a":2}}', b'{"a":NaN}', b'{"a":Infinity}',
                    b"{} trailing", b"[" * 2000 + b"]" * 2000,
                    b" " * (guest.MAX_RESULT_BYTES + 1)):
            with self.subTest(prefix=raw[:30]), self.assertRaises(ValueError):
                guest.validate_result(raw, NONCE)

    def test_cli_failure_has_no_success_json(self):
        for error in (RuntimeError("loopback-only fixture"), OSError("fixture read error"),
                      subprocess.TimeoutExpired("dpkg-query", 15)):
            output, diagnostic = io.StringIO(), io.StringIO()
            with patch.object(sys, "argv", ["probe", "--nonce", NONCE]), \
                    patch.object(guest, "inventory", side_effect=error), \
                    redirect_stdout(output), redirect_stderr(diagnostic):
                self.assertEqual(guest.main(), 2)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("I5_GUEST_INVENTORY_FAILED", diagnostic.getvalue())

    def test_cli_validator_does_not_probe_host(self):
        stream = SimpleNamespace(buffer=io.BytesIO(json.dumps(self.collect()).encode()))
        with patch.object(sys, "argv", ["probe", "--nonce", NONCE, "--validate-result"]), \
                patch.object(sys, "stdin", stream), patch.object(guest, "inventory") as probe, \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(guest.main(), 0)
        probe.assert_not_called()
        self.assertIn("I5 remains stopped", output.getvalue())

    def test_invalid_nonce_rejected_before_probe(self):
        with patch.object(sys, "argv", ["probe", "--nonce", "invalid"]), \
                patch.object(guest, "inventory") as probe, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                guest.main()
        self.assertEqual(error.exception.code, 2)
        probe.assert_not_called()


class UTMResultTests(unittest.TestCase):
    def envelope(self, case_name="success", stdout=None, stderr=None, code=None):
        return {
            "schema_version": 1, "scope": "utm-guest-execution", "uuid": guest.UTM_UUID,
            "nonce": NONCE, "case_name": case_name, "exited": True,
            "exit_code": (17 if case_name == "failure" else 0) if code is None else code,
            "signal_code": 0, "polls": 5,
            "stdout_base64": base64.b64encode(
                f"I5_UTM_{case_name.upper()}:{NONCE}\n".encode() if stdout is None else stdout).decode(),
            "stderr_base64": base64.b64encode(
                f"I5_UTM_{case_name.upper()}_STDERR:{NONCE}\n".encode() if stderr is None else stderr).decode(),
        }

    def decode(self, value, case_name="success"):
        return guest.parse_execution(json.dumps(value).encode(), NONCE, case_name)

    def test_both_streams_and_exit_17_preserved(self):
        for case_name in ("success", "failure"):
            result, stdout, stderr = self.decode(self.envelope(case_name), case_name)
            guest.verify_case(result, stdout, stderr, NONCE, case_name)
            self.assertEqual(result["exit_code"], 17 if case_name == "failure" else 0)
            self.assertIn(NONCE.encode(), stdout)
            self.assertIn(NONCE.encode(), stderr)

    def test_inventory_reuses_existing_validation(self):
        inventory = InventoryTests().collect()
        value = self.envelope("inventory", stdout=json.dumps(inventory).encode(), stderr=b"")
        result, stdout, stderr = self.decode(value, "inventory")
        guest.verify_case(result, stdout, stderr, NONCE, "inventory")
        inventory["nonce"] = "b" * 32
        with self.assertRaisesRegex(ValueError, "nonce mismatch"):
            guest.verify_case(result, json.dumps(inventory).encode(), stderr, NONCE, "inventory")

    def test_empty_and_partial_output_never_passes(self):
        for case_name in ("success", "failure", "inventory"):
            for stdout in (b"", b"{", b"unrelated"):
                value = self.envelope(case_name, stdout=stdout, stderr=b"")
                result, out, err = self.decode(value, case_name)
                with self.subTest(case_name=case_name, stdout=stdout), self.assertRaises(ValueError):
                    guest.verify_case(result, out, err, NONCE, case_name)

    def test_bad_execution_fields_rejected(self):
        good = self.envelope()
        for key, value in (("schema_version", True), ("schema_version", 2), ("scope", "other"),
                           ("uuid", "other"), ("nonce", "b" * 32), ("case_name", "failure"),
                           ("exited", False), ("exited", 1), ("exit_code", False),
                           ("exit_code", -1), ("exit_code", 256), ("signal_code", None),
                           ("polls", 0), ("stdout_base64", None), ("stderr_base64", 0)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.decode({**good, key: value})
        for key in good:
            value = dict(good)
            del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.decode(value)

    def test_invalid_json_and_base64_rejected(self):
        for raw in (b"", b"[]", b"\xff", b'{"schema_version":1,"schema_version":1}',
                    b'{"n":NaN}', b"[" * 2000 + b"]" * 2000,
                    b" " * (guest.MAX_TRANSPORT_BYTES + 1)):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                guest.parse_execution(raw, NONCE, "success")
        for stream in ("!", "eA", "eA==\n", "eB==",
                       base64.b64encode(b"a" * (guest.MAX_RESULT_BYTES + 1)).decode()):
            with self.subTest(stream=stream[:20]), self.assertRaises(ValueError):
                self.decode({**self.envelope(), "stdout_base64": stream})

    def test_guest_failure_signal_and_unexpected_stderr_rejected(self):
        for change, reason in (({"exit_code": 4}, "guest exit 4"), ({"signal_code": 15}, "signal 15")):
            result, stdout, stderr = self.decode({**self.envelope(), **change})
            with self.assertRaisesRegex(ValueError, reason):
                guest.verify_case(result, stdout, stderr, NONCE, "success")
        value = self.envelope("inventory", stdout=json.dumps(InventoryTests().collect()).encode(), stderr=b"unexpected")
        result, stdout, stderr = self.decode(value, "inventory")
        with self.assertRaisesRegex(ValueError, "unexpected inventory stderr"):
            guest.verify_case(result, stdout, stderr, NONCE, "inventory")

    def test_config_refuses_wrong_target_or_enabled_sharing(self):
        good = {"Information": {"UUID": guest.UTM_UUID, "Name": guest.UTM_NAME},
                "Network": [], "Sharing": {"ClipboardSharing": False, "DirectoryShareMode": "None"}}
        with patch.object(guest.platform, "system", return_value="Darwin"), \
                patch.object(Path, "read_bytes", return_value=guest.plistlib.dumps(good)):
            guest.check_utm_config()
        for field, value in (("Information", {"UUID": "other"}), ("Network", [{}]),
                             ("Sharing", {"ClipboardSharing": True, "DirectoryShareMode": "None"}),
                             ("Sharing", {"ClipboardSharing": False, "DirectoryShareMode": "VirtFS"})):
            with patch.object(guest.platform, "system", return_value="Darwin"), \
                    patch.object(Path, "read_bytes", return_value=guest.plistlib.dumps({**good, field: value})):
                with self.assertRaises(RuntimeError):
                    guest.check_utm_config()
        with patch.object(guest.platform, "system", return_value="Linux"), \
                patch.object(Path, "read_bytes") as read:
            with self.assertRaisesRegex(RuntimeError, "requires macOS"):
                guest.check_utm_config()
            read.assert_not_called()

    def collector_fixture(self, directory, case_name="success"):
        source = Path(directory).resolve() / "scripts" / "inspect-sw-i5-guest.py"
        source.parent.mkdir()
        source.write_bytes(b"fixture inventory source\n")
        source.with_name("sw_i5_utm_result.js").write_bytes(b"fixture adapter source\n")
        evidence = source.parents[1] / ".tmp" / ("i5-guest-return-" + NONCE) / case_name
        return source, evidence

    def test_collector_executes_once_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-return.") as directory:
            source, evidence = self.collector_fixture(directory)
            response = subprocess.CompletedProcess([], 0, json.dumps(self.envelope()).encode(), b"")
            with patch.object(guest, "__file__", str(source)), \
                    patch.object(guest, "check_utm_config") as check, \
                    patch.object(guest.subprocess, "run", return_value=response) as run:
                result = guest.collect_utm(NONCE, "success")
                self.assertEqual(check.call_count, 2)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0][0], "/usr/bin/osascript")
                self.assertEqual(run.call_args.kwargs["timeout"], 60)
                request = json.loads(run.call_args.kwargs["input"])
                self.assertEqual(base64.b64decode(request["program_base64"]), guest.probe_program("success"))
                self.assertEqual(json.loads((evidence / "execution.json").read_text()), result)
                self.assertEqual((evidence / "guest.stdout").read_bytes(), f"I5_UTM_SUCCESS:{NONCE}\n".encode())
                with self.assertRaises(FileExistsError):
                    guest.collect_utm(NONCE, "success")
                run.assert_called_once()

    def test_collector_timeout_records_partial_evidence_no_retry(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-return.") as directory:
            source, evidence = self.collector_fixture(directory)
            timeout = subprocess.TimeoutExpired("fixture osascript", 60, output=b"partial", stderr=b"timeout detail")
            with patch.object(guest, "__file__", str(source)), patch.object(guest, "check_utm_config"), \
                    patch.object(guest.subprocess, "run", side_effect=timeout) as run:
                with self.assertRaisesRegex(RuntimeError, "completion unknown"):
                    guest.collect_utm(NONCE, "success")
                run.assert_called_once()
            self.assertTrue(json.loads((evidence / "transport.json").read_text())["timeout"])
            self.assertEqual((evidence / "transport.stdout").read_bytes(), b"partial")
            self.assertEqual((evidence / "transport.stderr").read_bytes(), b"timeout detail")
            self.assertTrue((evidence / "failure.txt").exists())

    def test_transport_failure_and_empty_return_preserved(self):
        for code, stdout, stderr in ((1, b"", b"fixture event failure"), (0, b"", b""),
                                    (0, b"{}", b"fixture unexpected diagnostic")):
            with tempfile.TemporaryDirectory(prefix="radishlink-i5-return.") as directory:
                source, evidence = self.collector_fixture(directory)
                with patch.object(guest, "__file__", str(source)), patch.object(guest, "check_utm_config"), \
                        patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], code, stdout, stderr)) as run:
                    with self.assertRaises((RuntimeError, ValueError)):
                        guest.collect_utm(NONCE, "success")
                    run.assert_called_once()
                self.assertEqual((evidence / "transport.stdout").read_bytes(), stdout)
                self.assertEqual((evidence / "transport.stderr").read_bytes(), stderr)

    def test_cli_preserves_expected_nonzero_guest_exit(self):
        with patch.object(sys, "argv", ["probe", "--nonce", NONCE, "--collect-utm", "failure"]), \
                patch.object(guest, "collect_utm", return_value=self.envelope("failure")), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(guest.main(), 17)
        self.assertEqual(json.loads(output.getvalue())["exit_code"], 17)

    def test_no_collection_before_config_or_nonce_checks(self):
        with patch.object(guest.subprocess, "run") as run, patch.object(guest, "check_utm_config") as check:
            with self.assertRaises(ValueError):
                guest.collect_utm("bad", "success")
            check.assert_not_called()
            check.side_effect = RuntimeError("fixture config rejection")
            with self.assertRaisesRegex(RuntimeError, "config rejection"):
                guest.collect_utm(NONCE, "success")
            run.assert_not_called()


    def test_post_collection_config_change_rejects_preserved_result(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-return.") as directory:
            source, evidence = self.collector_fixture(directory)
            response = subprocess.CompletedProcess([], 0, json.dumps(self.envelope()).encode(), b"")
            with patch.object(guest, "__file__", str(source)), \
                    patch.object(guest, "check_utm_config", side_effect=[None, RuntimeError("fixture isolation changed")]), \
                    patch.object(guest.subprocess, "run", return_value=response):
                with self.assertRaisesRegex(RuntimeError, "isolation changed"):
                    guest.collect_utm(NONCE, "success")
            self.assertTrue((evidence / "execution.json").exists())
            self.assertIn("isolation changed", (evidence / "failure.txt").read_text())

    def test_evidence_write_failure_preserves_original_error(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-return.") as directory:
            source, _ = self.collector_fixture(directory)
            write_text = Path.write_text

            def write(path, *args, **kwargs):
                if path.name == "failure.txt":
                    raise OSError("fixture diagnostic disk full")
                return write_text(path, *args, **kwargs)

            with patch.object(guest, "__file__", str(source)), patch.object(guest, "check_utm_config"), \
                    patch.object(Path, "write_text", write), \
                    patch.object(guest.subprocess, "run", side_effect=OSError("fixture launch error")):
                with self.assertRaisesRegex(RuntimeError, "fixture launch error;.*fixture diagnostic disk full"):
                    guest.collect_utm(NONCE, "success")

    def test_oversized_transport_keeps_bounded_failure_evidence(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-return.") as directory:
            source, evidence = self.collector_fixture(directory)
            output = b"x" * (guest.MAX_TRANSPORT_BYTES + 1)
            with patch.object(guest, "__file__", str(source)), patch.object(guest, "check_utm_config"), \
                    patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, b"")):
                with self.assertRaisesRegex(ValueError, "oversized UTM transport"):
                    guest.collect_utm(NONCE, "success")
            self.assertEqual((evidence / "transport.stdout").stat().st_size, guest.MAX_TRANSPORT_BYTES)
            self.assertEqual(json.loads((evidence / "transport.json").read_text())["stdout_bytes"], len(output))


class PreparationDetailsTests(unittest.TestCase):
    def packages(self):
        values = {"binary:Package": "fixture:arm64", "Version": "1.0", "Architecture": "arm64",
                  "Status": "hold ok installed", "Pre-Depends": "init-system-helpers (>= 1.54~)",
                  "Depends": "libc6 (>= 2.38)", "Provides": "fixture-api (= 1)", "Installed-Size": "12"}
        return {"fields": list(guest.PACKAGE_FIELDS), "rows": [[values.get(f, "") for f in guest.PACKAGE_FIELDS]]}

    def services(self):
        return {"exit_code": 1, "policy_rc_d_present": False,
                "units": {name: {"Id": name, "LoadState": "not-found", "ActiveState": "inactive",
                                 "SubState": "dead", "UnitFileState": ""} for name in guest.SERVICE_UNITS}}

    def fixture(self):
        return {"schema_version": 1, "scope": guest.DETAILS_SCOPE, "nonce": NONCE, "i5_ready": False,
                "base_inventory": InventoryTests().collect(), "packages": self.packages(),
                "tools": {name: [] for name in guest.DETAIL_TOOLS}, "tool_ownership": [],
                "mounts": guest.mount_details("1 0 8:0 / / rw,relatime - ext4 /dev/vda rw\n"),
                "swaps": guest.swap_details("Filename Type Size Used Priority\n/swapfile file 1024 0 -2\n"),
                "filesystems": {p: {"device": "8:0", "available_bytes": 4096} for p in ("/", "/var", "/tmp", "/run")},
                "services": self.services()}

    def decode(self, value):
        return guest.validate_details(json.dumps(value).encode(), NONCE)

    def test_complete_details_and_separate_scope(self):
        value = self.fixture()
        self.assertEqual(self.decode(value), value)
        with self.assertRaises(ValueError):
            guest.validate_result(json.dumps(value).encode(), NONCE)
        with self.assertRaises(ValueError):
            self.decode(value["base_inventory"])
        self.assertEqual(value["packages"]["rows"][0][3], "hold ok installed")

    def test_full_package_query_preserves_relations_and_rejects_partial(self):
        expected = self.packages()
        output = "\t".join(expected["rows"][0]) + "\n"
        with patch.object(guest, "details_command", return_value=(output, 0)) as command:
            self.assertEqual(guest.package_details(), expected)
        argv = command.call_args.args[0]
        self.assertEqual(argv[:3], ["/usr/bin/dpkg-query", "--no-pager", "-W"])
        self.assertIn("${Pre-Depends}", argv[3])
        self.assertEqual(command.call_args.kwargs["operation"], "package-table")
        for output in ("", "pkg\t1\n", output + output):
            with patch.object(guest, "details_command", return_value=(output, 0)), self.assertRaises(ValueError):
                guest.package_details()

    def test_commands_fail_closed_and_do_not_use_shell_or_inherit_environment(self):
        argv = ["/usr/bin/dpkg-query", "-W"]
        with patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess(argv, 0, b"ok", b"")) as run:
            self.assertEqual(guest.details_command(argv, operation="package-table"), ("ok", 0))
            self.assertEqual(run.call_args.kwargs["timeout"], 8)
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertNotIn("HOME", run.call_args.kwargs["env"])
        for code, out, err in ((1, b"", b"fixture failure"), (0, b"partial", b"unexpected"),
                               (0, b"a" * (512 * 1024 + 1), b""), (0, b"", b"a" * 8193)):
            with patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess(argv, code, out, err)), \
                    self.assertRaises(RuntimeError):
                guest.details_command(argv, operation="package-table")
        with patch.object(guest.subprocess, "run", side_effect=subprocess.TimeoutExpired(argv, 8)), \
                self.assertRaises(subprocess.TimeoutExpired):
            guest.details_command(argv, operation="package-table")

    def test_details_overflow_identifies_operation_stream_sizes_and_exit(self):
        marker = b"synthetic-output-must-not-be-echoed"
        for operation in ("package-table", "tool-ownership"):
            limit = 524288 if operation == "package-table" else 262144
            cases = ((marker + b"x" * limit, b"", "stdout"),
                     (b"", marker + b"x" * 8192, "stderr"),
                     (b"\xff" * (limit + 1), b"\xff" * 8193, "stdout,stderr"))
            for out, err, exceeded in cases:
                for code in (0, 2):
                    with self.subTest(operation=operation, exceeded=exceeded, code=code), \
                            patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], code, out, err)), \
                            self.assertRaises(RuntimeError) as caught:
                        guest.details_command(["/usr/bin/dpkg-query", "synthetic-private-argument"], operation=operation)
                    message = str(caught.exception)
                    self.assertIn(f"operation={operation}; exceeded={exceeded};", message)
                    self.assertIn(f"stdout_bytes={len(out)}; stdout_limit={limit};", message)
                    self.assertIn(f"stderr_bytes={len(err)}; stderr_limit=8192;", message)
                    self.assertTrue(message.endswith(f"exit_code={code}"))
                    self.assertNotIn(marker.decode(), message)
                    self.assertNotIn("synthetic-private-argument", message)
                    self.assertLess(len(message.encode()), 512)

    def test_details_byte_boundary_does_not_raise_limits(self):
        # Two bytes per character: the acceptance bound is bytes, not text length.
        out = ("é" * 131072).encode()
        with patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, out, b"")):
            self.assertEqual(guest.details_command(["/usr/bin/dpkg-query"], operation="tool-ownership"),
                             (out.decode(), 0))
        for out, err, fragment in ((out + b"x", b"", "stdout_bytes=262145"),
                                   (b"", b"x" * 8192, "failed: exit=0")):
            with patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, out, err)), \
                    self.assertRaisesRegex(RuntimeError, fragment):
                guest.details_command(["/usr/bin/dpkg-query"], operation="tool-ownership")
        with patch.object(guest.subprocess, "run") as run, self.assertRaisesRegex(ValueError, "unknown details operation"):
            guest.details_command(["/usr/bin/dpkg-query"], operation="untrusted-label")
        run.assert_not_called()

    def test_only_package_table_stdout_has_the_reviewed_larger_bound(self):
        for size in (385968, 524288):
            with self.subTest(size=size), patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"x" * size, b"")):
                output, code = guest.details_command(["/usr/bin/dpkg-query", "-W"], operation="package-table")
                self.assertEqual(len(output), size)
                self.assertEqual(code, 0)
        for operation, program, size, limit in (("package-table", "dpkg-query", 524289, 524288),
                                              ("tool-ownership", "dpkg-query", 262145, 262144),
                                              ("service-state", "systemctl", 262145, 262144)):
            with self.subTest(operation=operation), patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"x" * size, b"")), \
                    self.assertRaisesRegex(RuntimeError, f"stdout_bytes={size}; stdout_limit={limit}"):
                guest.details_command(["/usr/bin/" + program], operation=operation)
        self.assertEqual(guest.return_limits("details"), (512 * 1024, 2 * 1024 * 1024))

    def test_real_package_and_ownership_call_sites_label_overflow(self):
        overflow = subprocess.CompletedProcess([], 0, b"x" * 524289, b"")
        with patch.object(guest.subprocess, "run", return_value=overflow) as run, \
                self.assertRaisesRegex(RuntimeError, "operation=package-table"):
            guest.package_details()
        self.assertIn("-W", run.call_args.args[0])
        self.assertEqual(run.call_count, 1)
        with patch.object(guest, "inventory", return_value={}), \
                patch.object(guest, "package_details", return_value=self.packages()), \
                patch.object(guest, "TOOL_DIRS", ("/usr/bin",)), \
                patch.object(Path, "is_file", return_value=True), \
                patch.object(Path, "resolve", return_value=Path("/synthetic/tools/dpkg-query")), \
                patch.object(guest.os, "access", return_value=True), \
                patch.object(guest.subprocess, "run", return_value=overflow) as run, \
                patch.object(guest, "read_details") as read, \
                self.assertRaisesRegex(RuntimeError, "operation=tool-ownership"):
            guest.preparation_details(NONCE)
        self.assertIn("-S", run.call_args.args[0])
        self.assertEqual(run.call_count, 1)
        read.assert_not_called()

    def test_overflow_diagnostic_reaches_failed_cli_and_saved_transport(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(guest.sys, "argv", ["probe", "--nonce", NONCE, "--details"]), \
                patch.object(guest, "preparation_details", side_effect=lambda nonce: guest.package_details()), \
                patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"x" * 524289, b"")), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(guest.main(), 2)
        self.assertEqual(stdout.getvalue(), "")
        error = stderr.getvalue().encode()
        self.assertTrue(error.startswith(b"I5_GUEST_INVENTORY_FAILED: "))
        self.assertIn(b"operation=package-table; exceeded=stdout", error)
        fixture = UTMResultTests()
        envelope = fixture.envelope("details", stdout=b"", stderr=error)
        envelope["exit_code"] = 2
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-overflow.") as directory:
            source, evidence = fixture.collector_fixture(directory, "details")
            response = subprocess.CompletedProcess([], 0, json.dumps(envelope).encode(), b"")
            with patch.object(guest, "__file__", str(source)), \
                    patch.object(guest, "check_utm_config"), \
                    patch.object(guest.subprocess, "run", return_value=response) as run, \
                    self.assertRaisesRegex(ValueError, "guest exit 2"):
                guest.collect_utm(NONCE, "details")
            run.assert_called_once()
            self.assertEqual((evidence / "guest.stdout").read_bytes(), b"")
            self.assertEqual((evidence / "guest.stderr").read_bytes(), error)
            self.assertEqual(json.loads((evidence / "execution.json").read_text())["exit_code"], 2)

    def test_mounts_omit_arbitrary_source_and_options(self):
        text = "7 1 0:5 / /run ro,nosuid shared:2 - tmpfs tmpfs rw,size=16M,nr_inodes=10,noswap\n"
        text += "8 1 0:6 / /fixture ro - cifs //fixture:synthetic-secret@server/share ro,password=synthetic-secret\n"
        rows = guest.mount_details(text)
        self.assertEqual(rows[0]["mount_flags"], ["ro"])
        self.assertEqual(rows[0]["super_flags"], ["noswap", "nr_inodes=10", "rw", "size=16M"])
        self.assertEqual(rows[0]["propagation"], ["shared:2"])
        self.assertIsNone(rows[1]["device_source"])
        self.assertNotIn("synthetic-secret", json.dumps(rows))
        for invalid in ("", "1 2 broken", text + text, "x 1 8:0 / / rw - ext4 /dev/vda rw"):
            with self.assertRaises(ValueError):
                guest.mount_details(invalid)

    def test_swaps_empty_negative_priority_and_invalid(self):
        header = "Filename Type Size Used Priority\n"
        self.assertEqual(guest.swap_details(header), [])
        self.assertEqual(guest.swap_details(header + "/dev/vda2 partition 42 1 -2\n")[0]["priority"], -2)
        for text in ("", "wrong header", header + "/swap file 1 2 -2", header + "/swap other 1 0 -2"):
            with self.assertRaises(ValueError):
                guest.swap_details(text)

    def test_service_query_accepts_explicit_not_found_and_rejects_partial(self):
        expected = self.services()
        text = "\n\n".join("\n".join(f"{key}={value}" for key, value in row.items())
                            for row in expected["units"].values()) + "\n"
        with patch.object(guest, "details_command", return_value=(text, 1)) as command, \
                patch.object(guest.os.path, "lexists", return_value=False):
            self.assertEqual(guest.service_details(), expected)
        argv = command.call_args.args[0]
        self.assertEqual(argv[:2], ["/usr/bin/systemctl", "show"])
        self.assertEqual(command.call_args.kwargs["operation"], "service-state")
        self.assertFalse(any("ExecStart" in arg or "Environment" in arg for arg in argv))
        for invalid, code in (("", 0), (text.split("\n\n")[0], 0), (text + text, 0),
                              (text.replace("not-found", "loaded"), 1), (text + "Environment=fixture\n", 0)):
            with patch.object(guest, "details_command", return_value=(invalid, code)), self.assertRaises(ValueError):
                guest.service_details()

    def test_details_read_limit(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-details.") as directory:
            path = Path(directory) / "synthetic-proc"
            path.write_bytes(b"x" * (256 * 1024 + 1))
            with self.assertRaisesRegex(RuntimeError, "read limit"):
                guest.read_details(path)

    def test_supplement_runs_after_base_guard_and_checks_network_again(self):
        value = self.fixture()
        with patch.object(guest, "inventory", side_effect=RuntimeError("fixture network rejection")), \
                patch.object(guest, "package_details") as packages:
            with self.assertRaisesRegex(RuntimeError, "network rejection"):
                guest.preparation_details(NONCE)
            packages.assert_not_called()
        facts = {"/proc/self/mountinfo": "1 0 8:0 / / rw - ext4 /dev/vda rw\n",
                 "/proc/swaps": "Filename Type Size Used Priority\n"}
        with patch.object(guest, "inventory", return_value=value["base_inventory"]), \
                patch.object(guest, "package_details", return_value=self.packages()), \
                patch.object(Path, "is_file", return_value=False), \
                patch.object(guest, "read_details", side_effect=lambda p: facts[p]), \
                patch.object(guest.os, "stat", return_value=SimpleNamespace(st_dev=0)), \
                patch.object(guest.os, "statvfs", return_value=SimpleNamespace(f_bavail=10, f_frsize=4096)), \
                patch.object(guest, "service_details", return_value=self.services()), \
                patch.object(guest, "require_loopback_only") as network:
            result = guest.preparation_details(NONCE)
            network.assert_called_once()
            self.decode(result)
            network.side_effect = RuntimeError("fixture changed network")
            with self.assertRaisesRegex(RuntimeError, "changed network"):
                guest.preparation_details(NONCE)

    def test_missing_unknown_and_malformed_nested_fields_rejected(self):
        value = self.fixture()
        for field in value:
            changed = dict(value)
            del changed[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.decode(changed)
        for field, bad in (("unexpected", 1), ("i5_ready", 0), ("schema_version", True),
                            ("nonce", "b" * 32), ("mounts", [{}]), ("swaps", [{}]),
                            ("services", {"exit_code": 0, "units": None, "policy_rc_d_present": False}),
                            ("tools", {name: [3] for name in guest.DETAIL_TOOLS}),
                            ("filesystems", {p: {} for p in ("/", "/var", "/tmp", "/run")})):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.decode({**value, field: bad})
        for raw in (b"", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}', b"[" * 2000 + b"]" * 2000,
                    b" " * (guest.DETAILS_RESULT_BYTES + 1)):
            with self.assertRaises(ValueError):
                guest.validate_details(raw, NONCE)

    def test_case_limits_and_details_transport_binding(self):
        value = self.fixture()
        # A larger valid table tests the real 128/512 KiB case separation.
        template = value["packages"]["rows"][0]
        value["packages"]["rows"] = [["fixture" + str(i), *template[1:]] for i in range(1000)]
        raw = json.dumps(value).encode()
        self.assertGreater(len(raw), guest.MAX_RESULT_BYTES)
        fixture = UTMResultTests()
        envelope = fixture.envelope("details", stdout=raw, stderr=b"")
        result, out, err = fixture.decode(envelope, "details")
        guest.verify_case(result, out, err, NONCE, "details")
        envelope["case_name"] = "inventory"
        with self.assertRaises(ValueError):
            fixture.decode(envelope, "inventory")
        with self.assertRaises(ValueError):
            guest.parse_execution(json.dumps(envelope).encode(), NONCE, "unknown")

    def test_details_cli_validator_never_probes_and_failure_has_no_success(self):
        raw = json.dumps(self.fixture()).encode()
        with patch.object(sys, "argv", ["probe", "--nonce", NONCE, "--validate-details"]), \
                patch.object(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw))), \
                patch.object(guest, "preparation_details") as probe, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(guest.main(), 0)
            probe.assert_not_called()
            self.assertIn("I5 remains stopped", output.getvalue())
        with patch.object(sys, "argv", ["probe", "--nonce", NONCE, "--details"]), \
                patch.object(guest, "preparation_details", return_value={}), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(guest.main(), 2)
            self.assertEqual(output.getvalue(), "")

    def test_details_program_and_adapter_input_size(self):
        program = guest.probe_program("details")
        self.assertEqual(program, Path(guest.__file__).read_bytes())
        self.assertLessEqual(len(base64.b64encode(program)), 64 * 1024)

    def test_details_collector_preserves_and_verifies_new_scope(self):
        value = self.fixture()
        fixture = UTMResultTests()
        envelope = fixture.envelope("details", stdout=json.dumps(value).encode(), stderr=b"")
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-details.") as directory:
            source, evidence = fixture.collector_fixture(directory, "details")
            with patch.object(guest, "__file__", str(source)), patch.object(guest, "check_utm_config"), \
                    patch.object(guest.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, json.dumps(envelope).encode(), b"")) as run:
                self.assertEqual(guest.collect_utm(NONCE, "details"), envelope)
                run.assert_called_once()
                self.assertEqual(json.loads(run.call_args.kwargs["input"])["case_name"], "details")
            self.assertEqual(json.loads((evidence / "guest.stdout").read_text()), value)


if __name__ == "__main__":
    unittest.main()
