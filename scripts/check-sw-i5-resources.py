#!/usr/bin/env python3
"""Read-only I5 local block-domain inspection and synthetic offline tests."""

from __future__ import annotations

import sys

# Before importing local helpers: inspection must not create __pycache__.
sys.dont_write_bytecode = True

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sw_i5_resources import (CAPS, Config, DomainGuard, HOST_FREE, LinuxProbe, MIB,
                             ResourceError, inspect_domains, parse_mounts)
from sw_i5_build import BuildProcess, build_environment, build_pair, confine_child, supervise_build


class FakeProbe:
    """All kernel/filesystem facts are synthetic; no Linux operations."""

    def __init__(self):
        self.config = Config.decode(json.dumps({
            "schema_version": 1, "root": "/i5", "host_path": "/host",
            "devices": {name: f"8:{i + 1}" for i, name in enumerate(CAPS)}}))
        self.raw = "1 0 8:0 / / rw - ext4 /dev/sda rw\n" + "".join(
            f"{i + 2} 1 8:{i + 1} / /i5/{name} rw,nosuid,nodev - ext4 /dev/sd{chr(98+i)} rw\n"
            for i, name in enumerate(CAPS))
        self.inventory = parse_mounts(self.raw)
        self.stats = {}
        self.spaces = {}
        self.sizes = {}
        for path in (Path("/i5"), Path("/host"), *(Path("/i5") / n for n in CAPS)):
            name = path.name
            minor = list(CAPS).index(name) + 1 if name in CAPS else 0
            cap = CAPS.get(name, 4 * HOST_FREE)
            self.stats[path] = SimpleNamespace(st_dev=os.makedev(8, minor), st_ino=100 + minor,
                                               st_uid=os.geteuid(), st_mode=stat.S_IFDIR | 0o700)
            self.spaces[path] = SimpleNamespace(f_frsize=4096, f_blocks=cap // 4096,
                                                f_bavail=cap // 8192, f_bfree=cap // 8192,
                                                f_files=1000, f_favail=900, f_ffree=900,
                                                f_fsid=minor + 100)
            self.sizes[name] = cap

    def mounts(self):
        return self.inventory

    def directory(self, path):
        return self.stats[path]

    def space(self, path):
        return self.spaces[path]

    def device(self, mount):
        return "/sys/devices/fixture/" + mount.source.rsplit("/", 1)[-1], self.sizes[mount.path.name]


class DomainTests(unittest.TestCase):
    def test_snapshot_and_go_budget_match(self):
        probe = FakeProbe()
        result = inspect_domains(probe.config, probe)
        self.assertFalse(result["i5_ready"])
        self.assertEqual(sum(CAPS.values()) + 48 * MIB, 768 * MIB)
        go = (Path(__file__).resolve().parents[1] /
              "tools/t0/internal/harness/network_write_budget.go").read_text()
        for name, cap in CAPS.items():
            self.assertRegex(go, rf"Network{name.title()}StorageBytes\s+int64 = {cap // MIB} << 20")

    def test_invalid_configuration(self):
        valid = {"schema_version": 1, "root": "/i5", "host_path": "/host",
                 "devices": FakeProbe().config.devices}
        for key, value in (("schema_version", True), ("schema_version", 2),
                           ("root", "/"), ("root", "/i5/../i5"),
                           ("root", "/i5/"), ("host_path", "/i5/build"),
                           ("devices", {}), ("extra", 0)):
            with self.subTest(key=key, value=value), self.assertRaises(ResourceError):
                Config.decode(json.dumps({**valid, key: value}))
        with self.assertRaises(ResourceError):
            Config.decode('{"schema_version":1,"schema_version":1}')

    def test_mount_rejections(self):
        changes = [lambda m: replace(m, kind="tmpfs"), lambda m: replace(m, root="/subdir"),
                   lambda m: replace(m, device="8:99"), lambda m: replace(m, options=frozenset({"rw"})),
                   lambda m: replace(m, options=frozenset({"ro", "nosuid", "nodev"})),
                   lambda m: replace(m, super_options=frozenset({"ro"})),
                   lambda m: replace(m, path=Path("/other"))]
        for change in changes:
            probe = FakeProbe()
            probe.inventory = (probe.inventory[0], change(probe.inventory[1]), *probe.inventory[2:])
            with self.subTest(change=change), self.assertRaises(ResourceError):
                inspect_domains(probe.config, probe)
        for path, device in (("/i5/build/sub", "0:1"), ("/elsewhere", "8:1"),
                             ("/i5/extra", "0:1"), ("/i5/build", "0:1")):
            probe = FakeProbe()
            probe.inventory += (replace(probe.inventory[1], ident=99, path=Path(path), device=device),)
            with self.subTest(path=path), self.assertRaises(ResourceError):
                inspect_domains(probe.config, probe)

    def test_capacity_host_inodes_and_sticky_failure(self):
        for name, field, value in (("host", "f_bavail", HOST_FREE // 4096 - 1),
                                    ("build", "f_bavail", 0), ("build", "f_favail", 0),
                                    ("build", "f_blocks", 1 << 40), ("build", "f_bavail", -1),
                                    ("build", "f_frsize", 0)):
            probe = FakeProbe()
            path = Path("/host") if name == "host" else Path("/i5") / name
            setattr(probe.spaces[path], field, value)
            with self.subTest(field=field, name=name), self.assertRaises(ResourceError):
                inspect_domains(probe.config, probe)
        probe = FakeProbe()
        probe.sizes["build"] += 512
        with self.assertRaises(ResourceError):
            inspect_domains(probe.config, probe)
        probe = FakeProbe()
        guard = DomainGuard(probe.config, probe)
        guard.check()
        probe.inventory = (probe.inventory[0], replace(probe.inventory[1], ident=99), *probe.inventory[2:])
        with self.assertRaisesRegex(ResourceError, "identity changed"):
            guard.check()
        probe.inventory = parse_mounts(probe.raw)
        with self.assertRaisesRegex(ResourceError, "identity changed"):
            guard.check()

    def test_read_error_and_probe_race(self):
        probe = FakeProbe()
        guard = DomainGuard(probe.config, probe)
        with patch.object(probe, "space", side_effect=OSError("synthetic read failure")):
            with self.assertRaisesRegex(ResourceError, "synthetic read failure"):
                guard.check()
        with self.assertRaises(ResourceError):
            guard.check()
        changed = (replace(probe.inventory[0], ident=99), *probe.inventory[1:])
        with patch.object(probe, "mounts", side_effect=[probe.inventory, changed]):
            with self.assertRaisesRegex(ResourceError, "changed during probe"):
                inspect_domains(probe.config, probe)

    def test_build_scope_requires_readonly_everywhere_else(self):
        probe = FakeProbe()
        with self.assertRaises(ResourceError):
            inspect_domains(probe.config, probe, build_scope=True)
        probe.inventory = tuple(replace(m, options=frozenset({"ro", "nosuid", "nodev"}))
                                if m.path != Path("/i5/build") else m for m in probe.inventory)
        inspect_domains(probe.config, probe, build_scope=True)
        probe.inventory += (replace(probe.inventory[0], ident=99, path=Path("/tmp"), device="0:9",
                                    options=frozenset({"rw"})),)
        with self.assertRaisesRegex(ResourceError, "another writable mount"):
            inspect_domains(probe.config, probe, build_scope=True)

    def test_real_directory_symlink_rejected(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-probe.") as directory:
            root = Path(directory).resolve()
            (root / "actual").mkdir()
            (root / "alias").symlink_to(root / "actual")
            with self.assertRaisesRegex(ResourceError, "symlink"):
                LinuxProbe().directory(root / "alias")

    def test_kernel_block_source_and_sector_reader(self):
        mount = FakeProbe().inventory[1]
        device = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(8, 1))
        with patch.object(Path, "stat", return_value=device), \
                patch.object(Path, "resolve", return_value=Path("/sys/devices/fixture/vdb")), \
                patch.object(Path, "exists", return_value=False), \
                patch.object(Path, "read_text", return_value=str(CAPS["build"] // 512)):
            name, size = LinuxProbe().device(mount)
            self.assertTrue(name.endswith("vdb"))
            self.assertEqual(size, CAPS["build"])
            device.st_rdev = os.makedev(8, 2)
            with self.assertRaisesRegex(ResourceError, "differs from mountinfo"):
                LinuxProbe().device(mount)
            device.st_rdev = os.makedev(8, 1)
            for backend in ("loop0", "dm-0", "md0", "vdb1"):
                with patch.object(Path, "resolve", return_value=Path("/sys/devices") / backend):
                    with self.assertRaisesRegex(ResourceError, "unsupported block backend"):
                        LinuxProbe().device(mount)

    def test_mountinfo_malformed(self):
        for raw in ("", "broken", "1 0 x / / rw - ext4 /dev/a rw",
                    "1 0 8:0 / / rw - ext4 /dev/a", FakeProbe().raw * 2):
            with self.subTest(raw=raw), self.assertRaises(ResourceError):
                parse_mounts(raw)
        parsed = parse_mounts(r"1 0 8:0 / /a\040b rw - ext4 /dev/a rw")
        self.assertEqual(parsed[0].path, Path("/a b"))


class FakeProcess:
    def __init__(self, results, cleanup_error=None):
        self.results = iter(results)
        self.cleanup_error = cleanup_error
        self.cleaned = False

    def wait(self, _timeout):
        return next(self.results)

    def cleanup(self):
        self.cleaned = True
        if self.cleanup_error:
            raise self.cleanup_error


class BuildTests(unittest.TestCase):
    def test_launch_failure_preserves_confinement_reason_in_log(self):
        def popen(*_args, **kwargs):
            kwargs["preexec_fn"]()

        with patch("sw_i5_build.subprocess.Popen", side_effect=popen), \
                patch("sw_i5_build.confine_child", side_effect=OSError("synthetic Landlock denial")), \
                patch("sw_i5_build.os.write") as write:
            with self.assertRaisesRegex(ResourceError, "synthetic Landlock denial.*bootstrap.log"):
                BuildProcess([], {}, Path("/i5/build/go-stage"), SimpleNamespace(name="bootstrap.log"))
        self.assertIn(b"synthetic Landlock denial", write.call_args.args[1])

    def test_cleanup_waits_and_rejects_remaining_group(self):
        process = BuildProcess.__new__(BuildProcess)
        process.process = SimpleNamespace(pid=12345, wait=unittest.mock.Mock(return_value=0))
        with patch("sw_i5_build.os.killpg", side_effect=[None, ProcessLookupError()]) as kill:
            process.cleanup()
        self.assertEqual([call.args for call in kill.call_args_list], [(12345, 9), (12345, 0)])
        process.process.wait.assert_called_once_with(timeout=5)
        with patch("sw_i5_build.os.killpg"), patch("sw_i5_build.time.monotonic", side_effect=[0, 6]):
            with self.assertRaisesRegex(ResourceError, "group remains"):
                process.cleanup()

    def test_environment_does_not_inherit(self):
        with patch.dict(os.environ, {"GOFLAGS": "-toolexec=/evil", "GOCACHE": "/outside"}):
            env = build_environment(Path("/i5/build/go-stage"), Path("/opt/go/bin/go"), "arm64")
        self.assertNotIn("GOFLAGS", env)
        self.assertEqual(env["GOCACHE"], "/i5/build/go-stage/cache")
        self.assertEqual(env["GOENV"], "off")
        self.assertEqual(env["GOARCH"], "arm64")
        self.assertEqual(env["GOTELEMETRY"], "off")

    def test_success_and_failure_cleanup(self):
        for code in (0, 1, -9):
            probe = FakeProbe()
            process = FakeProcess([None, code])
            guard = DomainGuard(probe.config, probe)
            if code == 0:
                supervise_build(guard, lambda: process)
            else:
                with self.assertRaisesRegex(ResourceError, "exit code"):
                    supervise_build(guard, lambda: process)
            self.assertTrue(process.cleaned)

    def test_precheck_prevents_start(self):
        probe = FakeProbe()
        probe.sizes["build"] *= 2
        with patch("sw_i5_build.BuildProcess") as launch:
            with self.assertRaises(ResourceError):
                supervise_build(DomainGuard(probe.config, probe), launch)
            launch.assert_not_called()

    def test_hung_build_space_failure_and_cleanup_error(self):
        probe = FakeProbe()
        process = FakeProcess([None], ResourceError("synthetic cleanup failure"))
        original = process.wait

        def consume_space(timeout):
            probe.spaces[Path("/host")].f_bavail = 0
            return original(timeout)

        process.wait = consume_space
        with self.assertRaisesRegex(ResourceError, "insufficient available bytes.*cleanup failure"):
            supervise_build(DomainGuard(probe.config, probe), lambda: process)
        self.assertTrue(process.cleaned)

    def test_deadline_cancels_and_reaps(self):
        probe = FakeProbe()
        process = FakeProcess([None])
        ticks = iter([0, 301])
        with self.assertRaisesRegex(ResourceError, "deadline"):
            supervise_build(DomainGuard(probe.config, probe), lambda: process, clock=lambda: next(ticks))
        self.assertTrue(process.cleaned)

    def test_pair_keeps_logs_and_partial_outputs_on_failure(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-build.") as directory:
            root = Path(directory).resolve()
            (root / "build").mkdir()
            guard = SimpleNamespace(config=SimpleNamespace(root=root), check=lambda: None)

            def launch(argv, env, stage, log):
                log.write(b"synthetic build failure\n")
                Path(argv[argv.index("-o") + 1]).write_bytes(b"partial")
                return FakeProcess([1])

            with patch("sw_i5_build.check_build_inputs"), patch("sw_i5_build.BuildProcess", side_effect=launch), \
                    patch("sw_i5_build.os.uname", return_value=SimpleNamespace(machine="aarch64")):
                with self.assertRaisesRegex(ResourceError, "exit code 1"):
                    build_pair(guard, Path("/source"), Path("/opt/go/bin/go"), "amd64")
            self.assertEqual((root / "build/go-stage/bootstrap").read_bytes(), b"partial")
            self.assertEqual((root / "build/go-stage/bootstrap.log").read_bytes(), b"synthetic build failure\n")

    def test_landlock_unsupported_fails_before_ruleset(self):
        fake = SimpleNamespace(syscall=unittest.mock.Mock(return_value=4), prctl=unittest.mock.Mock())
        with patch("sw_i5_build.resource.setrlimit"), patch("sw_i5_build.ctypes.CDLL", return_value=fake), \
                patch("sw_i5_build.os.uname", return_value=SimpleNamespace(machine="x86_64")):
            with self.assertRaisesRegex(ResourceError, "ABI 5"):
                confine_child(Path("/i5/build"))
        self.assertEqual(fake.syscall.call_count, 1)

    def test_landlock_rights_and_failure_close(self):
        for fail in (False, True):
            calls = []

            def syscall(number, *args):
                n = number.value
                calls.append(n)
                if n == 444 and args[-1].value == 1:
                    return 5
                if n == 444:
                    handled = args[0]._obj.value
                    self.assertTrue(handled & (1 << 14))  # truncate
                    self.assertTrue(handled & (1 << 15))  # device ioctl
                    return 100
                if n == 445:
                    rule = args[2]._obj
                    self.assertEqual(rule.parent_fd, 101)
                    self.assertTrue(rule.allowed_access & (1 << 1))
                    for bit in (6, 9, 11, 15):
                        self.assertFalse(rule.allowed_access & (1 << bit))
                    return 0
                return -1 if fail else 0

            fake = SimpleNamespace(syscall=unittest.mock.Mock(side_effect=syscall),
                                   prctl=unittest.mock.Mock(return_value=0))
            with patch("sw_i5_build.resource.setrlimit"), patch("sw_i5_build.ctypes.CDLL", return_value=fake), \
                    patch("sw_i5_build.os.uname", return_value=SimpleNamespace(machine="x86_64")), \
                    patch("sw_i5_build.os.open", return_value=101), \
                    patch("sw_i5_build.os.O_PATH", 0x200000, create=True), \
                    patch("sw_i5_build.os.close") as close:
                if fail:
                    with self.assertRaises(OSError):
                        confine_child(Path("/i5/build"))
                else:
                    confine_child(Path("/i5/build"))
                self.assertEqual([c.args[0] for c in close.call_args_list], [101, 100])
            self.assertEqual(calls, [444, 444, 445, 446])

    def test_pair_shares_domain_and_cache(self):
        with tempfile.TemporaryDirectory(prefix="radishlink-i5-pair.") as directory:
            root = Path(directory).resolve()
            (root / "build").mkdir()
            guard = SimpleNamespace(config=SimpleNamespace(root=root), check=lambda: None)
            seen = []

            def launch(argv, env, stage, log):
                seen.append((env, stage))
                Path(argv[argv.index("-o") + 1]).write_bytes(b"synthetic binary")
                return FakeProcess([0])

            with patch("sw_i5_build.check_build_inputs"), patch("sw_i5_build.BuildProcess", side_effect=launch), \
                    patch("sw_i5_build.os.uname", return_value=SimpleNamespace(machine="aarch64")):
                outputs = build_pair(guard, Path("/source"), Path("/opt/go/bin/go"), "amd64")
                with self.assertRaises(FileExistsError):
                    build_pair(guard, Path("/source"), Path("/opt/go/bin/go"), "amd64")
            self.assertEqual([p.name for p in outputs], ["bootstrap", "node"])
            self.assertEqual(len(seen), 2)
            self.assertEqual(seen[0][0]["GOCACHE"], seen[1][0]["GOCACHE"])
            self.assertEqual(seen[0][0]["GOARCH"], "arm64")
            self.assertEqual(seen[1][0]["GOARCH"], "amd64")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test", help="synthetic offline tests; no mount/Go/Docker operations")
    inspect = sub.add_parser("inspect", help="read-only Linux block probe; never authorizes I5")
    inspect.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "self-test":
        suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        with args.config.open("r", encoding="utf-8") as stream:
            raw = stream.read(64 * 1024 + 1)
        if len(raw) > 64 * 1024:
            raise ResourceError("configuration exceeds 64 KiB")
        result = inspect_domains(Config.decode(raw))
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, ResourceError) as exc:
        print("I5_RESOURCE_PROBE_FAILED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
