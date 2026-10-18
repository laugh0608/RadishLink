"""Synthetic mapped guest + real owner/IPC/subprocess/filesystem chain only."""

import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels
import sw_i5_preparation_evidence as evidence
import sw_i5_preparation_initialization as initialization
import sw_i5_preparation_lifecycle as lifecycle
import sw_i5_preparation_rpc as rpc
import sw_i5_preparation_transport as transport
import test_sw_i5_preparation_plan as plans
import test_sw_i5_transport as fixtures
import test_sw_i5_lifecycle as old

NONCE, DIGEST = plans.NONCE, plans.DIGEST


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radishlink-init-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.children = []
        self.addCleanup(self.reap)
        self.setup("case")

    def setup(self, name):
        root = self.root / name
        root.mkdir(mode=0o700)
        self.case = root
        self.parent, self.jxa_parent, self.guest_parent, self.input = [root / value for value in ("evidence", "jxa", "mapped", "input")]
        for path in (self.parent, self.jxa_parent, self.guest_parent, self.input): path.mkdir(mode=0o700)
        (self.input / "payload.bin").write_bytes(b"synthetic readonly input")
        (self.input / "payload.bin").chmod(0o600)
        output = root / "export"
        output.mkdir()
        self.raw = channels.encode(fixtures.export_fixture(output))
        self.source = (Path(__file__).parent / "sw_i5_utm_result.js").read_bytes()
        self.ledger = plans.capacity()
        self.plan = plans.initialization(self.ledger)
        self.plan.update(host_uid=os.getuid(), host_gid=os.getgid(), host_evidence_parent=str(self.parent),
                         host_jxa_root=str(self.jxa_parent / NONCE), readonly_input=dict(path="/synthetic/input", **evidence.fingerprint((self.input / "payload.bin").read_bytes())),
                         jxa_source=evidence.fingerprint(self.source))
        self.plan["objects"] = plans.plan.object_specs(self.plan)
        for role, row in self.plan["offline_observations"]["objects"].items():
            for item in row.values():
                if item is None: continue
                for key in ("path", "uid", "gid", "bytes", "sha256"): item[key] = self.plan["objects"][role][key]
                if role in ("host_evidence_parent", "readonly_input"):
                    info = (self.parent if role == "host_evidence_parent" else self.input).stat()
                    item.update(dev=info.st_dev, ino=info.st_ino)
        self.backend = initialization.MappedSyntheticGuest(self.guest_parent, self.input)
        self.log = root / "actions.jsonl"
        self.state = root / "rpc-state.json"
        self.state.write_text(json.dumps(dict(slots={}, calls=[], executes=0, polls=0, lost=False)))

    def config(self):
        return initialization.SyntheticInitialization(plans.encode(self.plan), plans.encode(self.ledger), self.source, guest_backend=self.backend)

    def api(self, *, lost=False, launch_mode=None):
        helper, payload = self.case / "rpc.py", self.case / "payload.json"
        payload.write_bytes(self.raw)
        source = fixtures.RPC_CHILD_SOURCE
        source = source.replace('r = json.loads(sys.stdin.buffer.read())', 'r = json.loads(sys.stdin.buffer.read())\nslotroot = Path(sys.argv[3])')
        source = source.replace('s["slots"][str(a["handle"])] = a["data"]', '(slotroot / "lease.slot").write_bytes(base64.b64decode(a["data"]))')
        source = source.replace('s["slots"]["11"] = base64.b64encode(prefix + bytes(1024 - len(prefix))).decode()',
                                '(slotroot / "ack.slot").write_bytes(prefix + bytes(1024 - len(prefix)))')
        source = source.replace('value = s["slots"][str(a["handle"])]',
                                'value = base64.b64encode((slotroot / ("lease.slot" if a["handle"] == 10 else "ack.slot")).read_bytes()).decode()')
        source = source.replace('elif action == "open": value = 10 if a["role"] == "lease" else 11',
                                'elif action == "open":\n    assert len((slotroot / (a["role"] + ".slot")).read_bytes()) == 1024\n    value = 10 if a["role"] == "lease" else 11')
        helper.write_text(source)
        if lost:
            value = json.loads(self.state.read_text()); value["lost"] = True
            self.state.write_text(json.dumps(value))
        def launch(argv, **kwargs):
            path = Path(argv[3])
            # The actual source is inside the initialized root, not a separate
            # tempfile fixture. The replacement program consumes the same slots.
            assert path.parent == self.jxa_parent / NONCE
            assert path.read_bytes().startswith(b"var i5InternalRPC")
            if launch_mode == "replace":
                path.unlink(); path.write_bytes(b"replacement"); path.chmod(0o600)
                raise OSError("synthetic launch failure before source cleanup")
            if launch_mode == "kill":
                os.kill(os.getpid(), signal.SIGKILL)
            return subprocess.Popen((sys.executable, "-I", "-B", str(helper), str(self.state), str(payload),
                                     str(self.guest_parent / "guest/control")), **kwargs)
        return rpc.JXAProcessRPC(self.source, hashlib.sha256(self.source).hexdigest(), NONCE, DIGEST, launcher=launch)

    def adapter(self, request):
        with self.log.open("a") as output: output.write(json.dumps(request) + "\n")
        if request["action"] == "shutdown":
            # Guest cleanup precedes stop; readonly input is retained.
            if not getattr(self, "allow_guest_residue", False): assert not (self.guest_parent / "guest").exists()
            assert (self.input / "payload.bin").read_bytes() == b"synthetic readonly input"
        return old.result(request)

    def start(self, *, api=None, config=None, limits=None):
        values = lifecycle.fork_lifecycle(self.parent, transport.transport_request(NONCE, DIGEST, b"synthetic"),
            rpc=api or self.api(), start=self.adapter, readiness=self.adapter, shutdown=self.adapter,
            initialization=config or self.config(), budget=limits or old.budget(init=2, readiness=2, shutdown=3, persist=2, total=30))
        self.children.append(values)
        return values

    def collect(self, values, seconds=22):
        pid, writer, reader = values
        raw, deadline = bytearray(), time.monotonic() + seconds
        while time.monotonic() < deadline:
            ready, _, _ = select.select([reader], [], [], 0.02)
            if not ready: continue
            data = os.read(reader, 65536)
            if not data: break
            raw.extend(data)
        code = channels.wait_child(pid, deadline)
        self.assertIsNotNone(code, "owner remained alive")
        self.assertTrue(raw, "owner returned no packet")
        return json.loads(raw), code

    def reap(self):
        for pid, writer, reader in self.children:
            for fd in (writer, reader):
                try: os.close(fd)
                except OSError: pass
            try:
                code = channels.wait_child(pid, time.monotonic() + 0.2)
                if code is None:
                    os.kill(pid, signal.SIGTERM)
                    code = channels.wait_child(pid, time.monotonic() + 5)
                    if code is None: os.killpg(pid, signal.SIGKILL); os.waitpid(pid, 0)
            except (ChildProcessError, ProcessLookupError): pass

    def test_complete_actual_process_chain_bound_source_slots_cleanup_and_v3(self):
        value, code = self.collect(self.start())
        self.assertEqual(code, 0, value)
        self.assertTrue(value["passed"], value)
        self.assertEqual(value["receipt"]["schema_version"], 3)
        self.assertEqual(value["initialization"]["pending"], 0)
        self.assertEqual(len(value["initialization"]["objects"]), 13)
        self.assertEqual(value["initialization"]["guest_cleanup"], "complete")
        self.assertEqual(value["initialization"]["host_cleanup"], "complete")
        self.assertFalse((self.jxa_parent / NONCE).exists())
        self.assertFalse((self.guest_parent / "guest").exists())
        self.assertTrue((self.parent / NONCE / "attempt.json").exists())
        self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])
        state = json.loads(self.state.read_text())
        self.assertEqual(state["executes"], 1)
        self.assertEqual([a[0] for a in state["calls"]].count("open"), 2)
        self.assertGreater(value["initialization"]["registrations"], 30)

    def test_prevalidation_bindings_unknown_capacity_and_mutated_snapshot(self):
        for mode in ("nonce", "hash", "source", "unknown", "kind", "mutated"):
            with self.subTest(mode=mode):
                plan, ledger, source = copy.deepcopy(self.plan), copy.deepcopy(self.ledger), self.source
                if mode == "nonce": plan["nonce"] = "f" * 32
                if mode == "hash": ledger["envelope_bytes"] += 1
                if mode == "source": source += b"x"
                if mode == "unknown":
                    plans.unknown(ledger["surfaces"]["host_backing_metadata"])
                    plan["capacity_sha256"] = hashlib.sha256(plans.encode(ledger)).hexdigest()
                if mode == "kind": plan["kind"] = "offline-candidate"
                with self.assertRaises(ValueError):
                    config = initialization.SyntheticInitialization(plans.encode(plan), plans.encode(ledger), source, guest_backend=self.backend)
                    if mode == "mutated": config.ledger_raw += b" "
                    self.start(config=config)
        self.assertFalse((self.parent / NONCE).exists())

    def test_existing_root_wrong_parent_and_input_identity_do_not_continue(self):
        for mode in ("root", "parent", "input"):
            if mode != "root": self.setup(mode)
            if mode == "root": (self.jxa_parent / NONCE).mkdir()
            elif mode == "parent":
                self.parent.rename(self.parent.with_name("replaced-parent")); self.parent.mkdir(mode=0o700)
            else:
                self.input.rename(self.input.with_name("replaced-input")); self.input.mkdir(mode=0o700)
                (self.input / "payload.bin").write_bytes(b"synthetic readonly input"); (self.input / "payload.bin").chmod(0o600)
            value, code = self.collect(self.start())
            self.assertEqual(code, 2, value)
            self.assertFalse(value["lifecycle"]["transport_registered"])
            self.assertEqual(json.loads(self.state.read_text())["executes"], 0)
            self.assertTrue((self.input / "payload.bin").exists())

    def test_lost_execute_and_sigkill_source_are_cleaned_by_owner(self):
        for mode in ("lost", "kill"):
            self.setup(mode)
            value, code = self.collect(self.start(api=self.api(lost=mode == "lost", launch_mode="kill" if mode == "kill" else None)))
            self.assertEqual(code, 2, value)
            self.assertFalse(value["passed"])
            self.assertFalse((self.jxa_parent / NONCE).exists(), value)
            self.assertEqual(value["initialization"]["pending"], 0)
            self.assertEqual(sum(json.loads(line)["action"] == "shutdown" for line in self.log.read_text().splitlines()), 1)

    def test_source_replacement_preserved_first_failure_and_cleanup_error(self):
        value, code = self.collect(self.start(api=self.api(launch_mode="replace")))
        self.assertEqual(code, 2, value)
        self.assertIn("synthetic launch failure", value["lifecycle"]["first_failure"])
        self.assertTrue(value["lifecycle"]["cleanup_errors"], value)
        self.assertTrue(any((self.jxa_parent / NONCE).iterdir()))
        self.assertFalse(value["receipt"]["passed"])
        self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])

    def test_control_slots_short_write_and_readback_failures(self):
        for role in ("lease", "ack", "cgroup_worker", "work"):
            self.setup("fail-" + role)
            original = initialization.MappedSyntheticGuest.readback
            def readback(backend, actual, spec, **kwargs):
                if actual == role: raise ValueError("synthetic independent readback failure " + role)
                return original(backend, actual, spec, **kwargs)
            with patch.object(initialization.MappedSyntheticGuest, "readback", readback):
                value, code = self.collect(self.start())
            self.assertEqual(code, 2, value)
            self.assertFalse(value["lifecycle"]["transport_registered"])
            self.assertEqual(value["initialization"]["guest_cleanup"], "complete", value)
            self.assertFalse((self.guest_parent / "guest").exists())

    def test_duplicate_nonce_and_version_downgrade_and_semantic_tampering(self):
        value, code = self.collect(self.start())
        self.assertEqual(code, 0, value)
        path = self.parent / NONCE
        original = (path / "receipt.json").read_bytes()
        second, code = self.collect(self.start())
        self.assertEqual(code, 2, second)
        self.assertEqual((path / "receipt.json").read_bytes(), original)
        for mode in ("downgrade", "hash", "pending", "ready", "extra", "missing", "boolean"):
            changed = json.loads(original)
            if mode == "downgrade": changed["schema_version"] = 2; changed.pop("initialization")
            elif mode == "hash": changed["initialization"]["plan_sha256"] = "f" * 64
            elif mode == "pending": changed["initialization"]["pending"] = 1
            elif mode == "ready": changed["initialization"]["guest_ready"] = False
            elif mode == "extra": changed["initialization"]["unknown"] = True
            elif mode == "missing": changed["initialization"].pop("registry_sha256")
            else: changed["initialization"]["authorized"] = True
            (path / "receipt.json").write_bytes(channels.encode(changed))
            with self.subTest(mode=mode), self.assertRaises(ValueError): evidence.read_evidence(path, NONCE, DIGEST)
        (path / "receipt.json").write_bytes(original)

    def test_no_mapped_overlap_native_or_unbound_rpc(self):
        for path in (self.parent, self.parent / "child", self.jxa_parent / NONCE, self.input):
            with self.subTest(path=path), self.assertRaises(ValueError):
                initialization.SyntheticInitialization(plans.encode(self.plan), plans.encode(self.ledger), self.source,
                    guest_backend=initialization.MappedSyntheticGuest(path, self.input))
        with self.assertRaises(ValueError):
            initialization.SyntheticInitialization(plans.encode(self.plan), plans.encode(self.ledger), self.source, guest_backend=lambda: None)
        with self.assertRaisesRegex(ValueError, "RPC source identity"):
            self.start(api=fixtures.FakeUTM(self.raw))
        self.assertFalse((self.parent / NONCE).exists())

    def test_host_symlink_and_permission_and_root_replacement(self):
        for mode in ("symlink", "permissions", "root-replaced"):
            self.setup(mode)
            if mode == "symlink":
                self.jxa_parent.rename(self.case / "actual-jxa"); self.jxa_parent.symlink_to(self.case / "actual-jxa", target_is_directory=True)
            elif mode == "permissions": self.jxa_parent.chmod(0o755)
            original = initialization.InitializationWorker.guest
            def guest(worker):
                result = original(worker)
                if mode == "root-replaced":
                    root = Path(worker.value["host_jxa_root"])
                    root.rename(root.with_name("retained-original")); root.mkdir(mode=0o700)
                    (root / "foreign").write_bytes(b"preserve")
                return result
            with patch.object(initialization.InitializationWorker, "guest", guest):
                value, code = self.collect(self.start())
            self.assertEqual(code, 2, value)
            if mode == "root-replaced": self.assertEqual((self.jxa_parent / NONCE / "foreign").read_bytes(), b"preserve")
            else: self.assertFalse(value["lifecycle"]["start_attempted"])

    def test_cgroup_child_and_slot_replacement_preserved_stop_once(self):
        self.allow_guest_residue = True
        for mode in ("limit", "slot"):
            self.setup("replace-" + mode)
            original = initialization.InitializationWorker.guest
            def guest(worker):
                result = original(worker)
                target = worker.config.guest_backend.path("cgroup_worker") / "pids.max" if mode == "limit" else worker.config.guest_backend.path("lease")
                target.unlink(); target.write_bytes(b"replacement"); target.chmod(0o600)
                return result
            with patch.object(initialization.InitializationWorker, "guest", guest):
                value, code = self.collect(self.start())
            self.assertEqual(code, 2, value)
            self.assertTrue(value["lifecycle"]["cleanup_errors"], value)
            self.assertEqual(sum(json.loads(line)["action"] == "shutdown" for line in self.log.read_text().splitlines()), 1)
            target = self.guest_parent / ("cgroup/worker/pids.max" if mode == "limit" else "guest/control/lease.slot")
            self.assertEqual(target.read_bytes(), b"replacement")
            self.assertEqual(value["initialization"]["host_cleanup"], "complete")

    def test_parent_replacement_before_populate_never_follows_symlink(self):
        self.allow_guest_residue = True
        original = initialization.MappedSyntheticGuest.populate
        for mode in ("cgroup", "control"):
            self.setup("parent-before-write-" + mode)
            foreign = self.case / "foreign"
            foreign.mkdir(mode=0o700)
            def populate(backend, role, spec, expected):
                if role == ("cgroup_worker" if mode == "cgroup" else "lease"):
                    target = backend.path("cgroup_worker" if mode == "cgroup" else "control")
                    retained = self.case / "retained-original"
                    target.rename(retained)
                    target.symlink_to(foreign if mode == "cgroup" else retained, target_is_directory=True)
                return original(backend, role, spec, expected)
            with patch.object(initialization.MappedSyntheticGuest, "populate", populate):
                value, code = self.collect(self.start())
            self.assertEqual(code, 2, value)
            self.assertFalse(value["lifecycle"]["transport_registered"])
            self.assertEqual(list(foreign.iterdir()), [])
            if mode == "control": self.assertEqual((self.case / "retained-original/lease.slot").read_bytes(), b"")
            self.assertEqual(sum(json.loads(line)["action"] == "shutdown" for line in self.log.read_text().splitlines()), 1)

    def test_source_enospc_short_write_and_control_short_write(self):
        original = os.write
        for mode in ("source-enospc", "source-short", "slot-short"):
            self.setup(mode)
            def write(fd, raw):
                info = os.fstat(fd)
                if stat.S_ISREG(info.st_mode) and ((mode.startswith("source") and len(raw) > 8192) or
                                                  (mode == "slot-short" and len(raw) == 1024)):
                    if mode == "source-enospc": raise OSError(errno.ENOSPC, "synthetic quota exhausted")
                    return original(fd, raw[:max(1, len(raw) // 2)])
                return original(fd, raw)
            with patch.object(os, "write", write): value, code = self.collect(self.start())
            self.assertEqual(code, 2, value)
            self.assertFalse(value["passed"])
            self.assertFalse((self.jxa_parent / NONCE).exists(), value)
            self.assertEqual(value["initialization"]["pending"], 0, value)
            self.assertIn("short" if mode.endswith("short") else "quota exhausted", value["lifecycle"]["first_failure"])

    def test_staging_filesystem_block_rpc_deadline_and_controller_cancel(self):
        original = evidence.read_file
        self.allow_guest_residue = True
        for mode in ("timeout", "cancel"):
            self.setup("block-" + mode)
            entered = self.case / "io-entered"
            def read(fd, info, name, limit):
                if name.startswith("rpc-"):
                    entered.write_bytes(b"entered")
                    time.sleep(20)
                return original(fd, info, name, limit)
            with patch.object(evidence, "read_file", read):
                values = self.start(limits=old.budget(total=30, silence=5, init=2, readiness=2, shutdown=2, persist=0.5))
                until = time.monotonic() + 5
                while not entered.exists() and time.monotonic() < until: time.sleep(0.01)
                self.assertTrue(entered.exists())
                if mode == "cancel": os.write(values[1], b"1")
                value, code = self.collect(values)
            self.assertEqual(code, 2, value)
            self.assertFalse(value["passed"])
            self.assertIsNone(value["receipt"])
            self.assertTrue(value["initialization"]["pending"])
            self.assertIn("controller cancelled" if mode == "cancel" else "deadline", value["lifecycle"]["first_failure"])
            self.assertLess(value["lifecycle"]["total_seconds"], 900)

    def test_guest_initialization_lost_reply_and_shared_deadline(self):
        original = initialization.InitializationWorker.guest
        for mode in ("lost", "slow"):
            self.setup("guest-" + mode)
            self.allow_guest_residue = True
            def guest(worker):
                result = original(worker)
                if mode == "lost": os._exit(0)
                time.sleep(2)
                return result
            with patch.object(initialization.InitializationWorker, "guest", guest):
                value, code = self.collect(self.start(limits=old.budget(total=30, init=2, readiness=1, shutdown=2, persist=0.5)))
            self.assertEqual(code, 2, value)
            self.assertFalse(value["lifecycle"]["transport_registered"])
            self.assertFalse(value["initialization"]["guest_ready"])
            self.assertEqual(sum(json.loads(line)["action"] == "shutdown" for line in self.log.read_text().splitlines()), 1)

    def test_registration_ack_loss_does_not_write_source_payload(self):
        original = lifecycle._Owner.register
        def register(owner, message, deadline):
            row = message["registration"]
            if row["role"] == "source" and row["state"] == "bound":
                # Record the exact identity, suppress only its ACK.
                with patch.object(staging, "send", return_value=None): original(owner, message, deadline)
                return
            return original(owner, message, deadline)
        from sw_i5_preparation_initialization import staging
        with patch.object(lifecycle._Owner, "register", register):
            value, code = self.collect(self.start())
        self.assertEqual(code, 2, value)
        self.assertFalse(value["passed"])
        sources = list((self.jxa_parent / NONCE).glob("rpc-*.js")) if (self.jxa_parent / NONCE).exists() else []
        self.assertTrue(all(path.stat().st_size == 0 for path in sources))
        self.assertEqual(json.loads(self.state.read_text())["executes"], 0)

    def test_combined_unicode_failures_pending_sources_and_receipt_total_bound(self):
        self.allow_guest_residue = True
        first = "synthetic primary failure 原始🧪" * 3000
        cleanup = "synthetic cleanup failure 清理🧪" * 3000
        def launch(*args, **kwargs): raise OSError(first)
        api = rpc.JXAProcessRPC(self.source, hashlib.sha256(self.source).hexdigest(), NONCE, DIGEST, launcher=launch)
        with patch.object(initialization.MappedSyntheticGuest, "remove", side_effect=OSError(cleanup)), \
             patch.object(initialization.InitializationWorker, "clean_source", side_effect=OSError(cleanup)):
            value, code = self.collect(self.start(api=api))
        self.assertEqual(code, 2, value)
        self.assertFalse(value["passed"])
        self.assertIn("synthetic primary failure", value["lifecycle"]["first_failure"])
        self.assertTrue(value["lifecycle"]["failure_truncated"])
        self.assertTrue(value["lifecycle"]["cleanup_errors"])
        self.assertTrue(value["lifecycle"]["cleanup_truncated"])
        self.assertEqual(value["initialization"]["pending"], 11)
        self.assertEqual(len(value["initialization"]["pending_objects"]), 11)
        self.assertIn("source", value["initialization"]["pending_objects"])
        self.assertEqual(value["receipt"]["schema_version"], 3, value)
        self.assertLessEqual(len(channels.encode(value["receipt"])), 8192)
        self.assertLessEqual(len(channels.encode(value)), 16384)
        self.assertLessEqual(len(channels.encode(value["initialization"])), 2500)
        self.assertEqual(evidence.read_evidence(self.parent / NONCE, NONCE, DIGEST), value["receipt"])
        self.assertTrue((self.input / "payload.bin").exists())
        self.assertEqual(sum(json.loads(line)["action"] == "shutdown" for line in self.log.read_text().splitlines()), 1)
        for mode in ("slot-size", "source-size", "bound-as-intent", "realm-cleaned"):
            changed = copy.deepcopy(value["initialization"])
            if mode == "slot-size": changed["pending_objects"]["lease"][2] = 0
            elif mode == "source-size": changed["pending_objects"]["source"][2] = 0
            elif mode == "bound-as-intent": changed["pending_objects"]["lease"][:2] = ["intent", None]
            else: changed["guest_cleanup"] = "complete"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                evidence.validate_initialization(changed, NONCE, DIGEST, value["lifecycle"])


if __name__ == "__main__": unittest.main()
