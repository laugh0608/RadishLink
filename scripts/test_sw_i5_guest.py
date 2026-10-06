#!/usr/bin/env python3
"""Synthetic guest-inventory regressions; no VM, network or real subprocesses."""

import sys

sys.dont_write_bytecode = True

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
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


if __name__ == "__main__":
    unittest.main()
