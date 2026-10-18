"""Synthetic declarations only: no native provenance, VM, APT or signatures."""

import copy
import datetime
import email.utils
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sw_i5_apt as apt
import sw_i5_preparation_execution as execution
import sw_i5_preparation_lifecycle as lifecycle
import sw_i5_preparation_plan as plan
import sw_i5_utm_control as control
from test_sw_i5_preparation_plan import capacity, initialization, DIGEST, NONCE

NOW = 1792300000
FLAGS = dict.fromkeys(execution.FLAGS, False)


class SyntheticFixture:
    """All raw tool/event data in this fixture is fabricated for offline tests."""
    def __init__(self):
        self.sources = {name: (Path(__file__).parents[1] / name).read_bytes() for name in
                        execution.PYTHON_SOURCES + (execution.JXA, execution.VALIDATOR) + execution.REVIEW_TESTS}
        self.releases, files = {}, {}
        for name, spec in apt.SOURCES.items():
            release, index, key = apt.source_paths(spec)
            compressed, packages = execution.fingerprint(("synthetic-compressed-" + name).encode()), execution.fingerprint(b"synthetic-packages")
            files.update({release: execution.fingerprint(("synthetic-signed-" + name).encode()),
                          index: compressed, key: execution.fingerprint(("synthetic-key-" + name).encode())})
            date = email.utils.format_datetime(datetime.datetime.fromtimestamp(NOW - 60, datetime.timezone.utc), usegmt=True)
            expiry = email.utils.format_datetime(datetime.datetime.fromtimestamp(NOW + 3600, datetime.timezone.utc), usegmt=True)
            prefix = spec[2] + "/binary-arm64/Packages"
            self.releases[name] = (f"{'Suite' if name == 'docker' else 'Codename'}: {spec[1]}\nArchitectures: arm64 all\n"
                f"Components: {spec[2]}\nDate: {date}\nValid-Until: {expiry}\nSHA256:\n"
                f" {compressed['sha256']} {compressed['bytes']} {prefix}.{spec[3]}\n"
                f" {packages['sha256']} {packages['bytes']} {prefix}\n").encode()
        self.manifest = dict(schema_version=1, scope="i5-preparation-apt-input", nonce=NONCE, uuid=apt.UUID,
            files=files, install_authorized=False, i5_ready=False,
            baseline=dict(status=execution.fingerprint(b"synthetic private guest-only status"),
                extended_states=execution.fingerprint(b"synthetic private guest-only extended states"),
                crypto_policy=None, architecture="arm64", foreign_architectures=[],
                tools={name: dict(package=owner, version="1.0", sha256=execution.fingerprint(("synthetic-tool-" + name).encode())["sha256"])
                       for name, owner in apt.TOOLS.items()}))
        self.blobs = {"manifest": execution.encode(self.manifest), "program": b"# synthetic candidate program\n",
                      "bootstrap": b"# synthetic independent bootstrap candidate\n", "jxa": self.sources[execution.JXA]}
        manifest_hash = execution.fingerprint(self.blobs["manifest"])["sha256"]
        self.ledger = json.loads(execution.encode(capacity()).replace(DIGEST.encode(), manifest_hash.encode()))
        self.initialization = initialization(self.ledger)
        self.initialization = json.loads(execution.encode(self.initialization).replace(DIGEST.encode(), manifest_hash.encode()))
        self.initialization["jxa_source"] = execution.fingerprint(self.blobs["jxa"])
        self.blobs.update(plan=execution.encode(self.initialization), capacity=execution.encode(self.ledger))
        self.contract = dict(schema_version=1, scope=execution.CONTRACT_SCOPE, kind="offline-candidate", uuid=apt.UUID,
            nonce=NONCE, revision="a" * 40, issued_at=NOW - 1, valid_until=NOW + 600,
            inputs={name: execution.fingerprint(self.blobs[name]) if name in self.blobs else
                    dict(bytes=apt.MIB, sha256="c" * 64) if name == "media" else execution.fingerprint(("synthetic-" + name).encode())
                    for name in execution.INPUTS},
            sources=dict(execution={name: execution.fingerprint(self.sources[name]) for name in execution.PYTHON_SOURCES + (execution.JXA,)},
                validator={execution.VALIDATOR: execution.fingerprint(self.sources[execution.VALIDATOR])},
                review_tests={name: execution.fingerprint(self.sources[name]) for name in execution.REVIEW_TESTS},
                dynamic_edges=[dict(source="scripts/sw_i5_utm_control.py", target="scripts/inspect-sw-i5-guest.py", kind="python-spec"),
                    dict(source="scripts/inspect-sw-i5-guest.py", target="scripts/sw_i5_apt.py", kind="python-spec"),
                    dict(source="scripts/inspect-sw-i5-guest.py", target=execution.JXA, kind="jxa-source")]),
            external={name: execution.fingerprint(("synthetic-" + name).encode()) for name in execution.EXTERNALS},
            preboot={}, bootstrap_policy="independent-fixed-readiness-operation-no-lease", native_backend="absent",
            authorization=dict(state="not-granted", reference=None), budgets=dict(caps=dict(lifecycle.CAPS),
                reap_slots=list(lifecycle.REAP_SLOTS), worst_seconds=lifecycle.Budget().worst_seconds,
                absolute_seconds=900, guest_seconds=apt.GUEST_SECONDS, rpc_seconds=2), **FLAGS)
        self.contract["external"]["utmctl"] = self.contract["inputs"]["utmctl"]
        for name in apt.TOOLS:
            self.contract["external"]["guest-" + name] = execution.fingerprint(("synthetic-tool-" + name).encode())
        for name, row in self.ledger["surfaces"].items():
            observation = dict(schema_version=1, scope="i5-preboot-boundary-claim", nonce=NONCE, uuid=apt.UUID,
                capacity_sha256=self.contract["inputs"]["capacity"]["sha256"], surface=name,
                state=row["state"], mechanism=row["mechanism"], hard_limit_bytes=row["hard_limit_bytes"], configured_before_start=True)
            self.blobs["preboot." + name] = execution.encode(observation)
            self.contract["preboot"][name] = dict(configured_before_start=True, evidence=execution.fingerprint(self.blobs["preboot." + name]))

    def contract_raw(self):
        return execution.encode(self.contract)

    def contract_review(self):
        return execution.validate_contract(self.contract_raw(), self.blobs, self.sources, now=NOW)

    def source_change(self, name, before, after):
        self.sources[name] = self.sources[name].replace(before, after)
        role = "validator" if name == execution.VALIDATOR else "execution"
        self.contract["sources"][role][name] = execution.fingerprint(self.sources[name])

    def native_claim(self):
        """Structurally native-labelled, but entirely synthetic: never real evidence."""
        self.artifacts = {}
        def retain(name, raw):
            self.blobs[name] = raw
            self.artifacts[name] = execution.fingerprint(raw)
            return name
        self.retain = retain
        contract_fp = execution.fingerprint(self.contract_raw())
        windows, cursor = {}, 0
        for name, cap in lifecycle.CAPS.items():
            if name != "reap":
                windows[name] = dict(begin=cursor, end=cursor + cap)
                cursor += cap
        windows["reap_slots"] = dict.fromkeys(lifecycle.REAP_SLOTS, 2)
        settings = execution.apt_settings(self.initialization["readonly_input"]["path"], execution.apt_work(self.initialization))
        self.report = dict(schema_version=1, scope="i5-preparation-native-report-candidate", uuid=apt.UUID, nonce=NONCE,
            contract=contract_fp, evidence_kind="native-claim-unverified", outcome="success", first_error=None,
            cleanup_errors=[], clock_domain="host-supervisor-monotonic-elapsed-seconds", phase_windows=windows,
            events=[], baseline_readbacks=dict(before=copy.deepcopy(self.manifest["baseline"]), after=copy.deepcopy(self.manifest["baseline"])),
            tools=[], release_chains={}, artifacts=self.artifacts,
            apt_projection=dict(status=self.manifest["baseline"]["status"], installed={"base-package:all": "1.0"}, added=dict(apt.ROOTS), settings=settings), **FLAGS)
        moments = [1, 7, 67, 69, 127, 129, 600, 602, 727, 754, 756, 758, 760]
        for index, ((name, phase), begin) in enumerate(zip(execution.EVENTS, moments)):
            details = {}
            if name == "bootstrap":
                details = dict(input=self.contract["inputs"]["bootstrap"], lease_required=False, execute_count=1)
            elif name == "independent_readback":
                details = dict(observer="independent-reader", objects={role: dict(created=row["after"], readback=row["independent_readback"])
                    for role, row in self.initialization["offline_observations"]["objects"].items()}, slots=dict(lease=1024, ack=1024))
            elif name == "execute_once":
                details = dict(program=self.contract["inputs"]["program"], count=1, handle="synthetic-handle", lease_slot="lease", ack_slot="ack", rpc_seconds=1)
            elif name == "guest_result":
                details = dict(handle="synthetic-handle", guest_elapsed_seconds=500, exit_code=0, signal_code=0, complete=True, reaped=True)
            elif name in ("transport_reap", "guest_cleanup", "host_cleanup"):
                details = dict(remaining=0, identity_bound=True)
            elif name == "shutdown":
                details = dict(count=1, stopped=True, forced=False)
            self.report["events"].append(dict(name=name, phase=phase, sequence=index, nonce=NONCE, uuid=apt.UUID,
                contract=contract_fp, previous={}, begin=begin, end=begin + 1, status="ok", raw="event-" + name, details=details))
        for index, label in enumerate(apt.STEP_LABELS):
            argv = execution.tool_argv(label, self.initialization)
            stdout = b""
            if label == "native-arch":
                stdout = b"arm64\n"
            elif label.startswith("owner-"):
                name = label[6:]
                stdout = f"{apt.TOOLS[name]}: /usr/bin/{name}\n".encode()
            elif label.startswith("version-"):
                stdout = b"1.0\n"
            elif label.startswith("key-"):
                stdout = ("pub:::::::::\nfpr:::::::::" + apt.SOURCES[label[4:]][5] + ":\n").encode()
            elif label == "apt-config":
                stdout = "".join(f'{key} "{value}";\n' for key, value in settings.items()).encode()
            elif label == "apt-simulate":
                stdout = (f"0 upgraded, {len(apt.ROOTS)} newly installed, 0 to remove and 0 not upgraded.\n" +
                    "".join(f"{action} {name.split(':')[0]} ({version} Synthetic:fixture [arm64])\n"
                        for action in ("Inst", "Conf") for name, version in apt.ROOTS.items())).encode()
            self.report["tools"].append(dict(label=label, tool=argv[0].rsplit("/", 1)[1], tool_identity=self.contract["external"]["guest-" + argv[0].rsplit("/", 1)[1]],
                inputs=dict(manifest=self.contract["inputs"]["manifest"], baseline=self.manifest["baseline"], files=self.manifest["files"]),
                argv=argv, cwd=execution.apt_work(self.initialization),
                env=dict(PATH="/usr/bin:/bin", LANG="C", LC_ALL="C", HOME=execution.apt_work(self.initialization) + "/home",
                         TMPDIR=execution.apt_work(self.initialization) + "/tmp", APT_CONFIG=execution.apt_work(self.initialization) + "/apt.conf"),
                stdout=retain(label + ".stdout", stdout), stderr=retain(label + ".stderr", b""),
                original_bytes=dict(stdout=len(stdout), stderr=0), truncated=dict(stdout=False, stderr=False),
                exit_code=0, signal_code=0, complete=True, reaped=True, begin=140 + index * 2, end=141 + index * 2))
        for name, spec in apt.SOURCES.items():
            release, index, key = apt.source_paths(spec)
            compressed, packages = apt.release_index(self.releases[name], spec, datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc))
            self.report["release_chains"][name] = dict(inrelease=self.manifest["files"][release], key=self.manifest["files"][key],
                authenticated_release=retain("release-" + name, self.releases[name]), compressed=compressed, packages=packages,
                by_hash=index.rsplit("/", 1)[0] + "/by-hash/SHA256/" + compressed["sha256"], valid_until=NOW + 3600,
                verifier_stdout="verify-" + name + ".stdout", verifier_stderr="verify-" + name + ".stderr")
        self.seal()

    def seal(self, receipt=True):
        previous = execution.fingerprint(self.contract_raw())
        for index, event in enumerate(self.report["events"]):
            event["sequence"], event["previous"] = index, previous
            raw = execution.encode(dict({k: v for k, v in event.items() if k != "raw"}, schema_version=1, scope="i5-native-event-claim"))
            self.retain(event["raw"], raw)
            previous = execution.fingerprint(execution.encode(event))
        self.blobs["report"] = execution.encode(self.report)
        receipt_value = dict(schema_version=1, scope="i5-preparation-native-receipt-candidate", uuid=apt.UUID,
            nonce=NONCE, contract=execution.fingerprint(self.contract_raw()), report=execution.fingerprint(self.blobs["report"]),
            artifacts=self.artifacts, frozen=True, persisted=True, begin=874, end=875, **FLAGS)
        if receipt:
            self.blobs["receipt"] = execution.encode(receipt_value)
        else:
            self.blobs.pop("receipt", None)
        self.envelope = dict(schema_version=1, scope=execution.EVIDENCE_SCOPE, uuid=apt.UUID, nonce=NONCE,
            contract=execution.fingerprint(self.contract_raw()), report=execution.fingerprint(self.blobs["report"]),
            receipt=execution.fingerprint(self.blobs["receipt"]) if receipt else None, **FLAGS)

    def prune_unproduced_artifacts(self):
        referenced = {e["raw"] for e in self.report["events"]} | {s[stream] for s in self.report["tools"] for stream in ("stdout", "stderr")} | {
            r["authenticated_release"] for r in self.report["release_chains"].values()}
        for name in list(self.artifacts):
            if name not in referenced:
                del self.artifacts[name]
                self.blobs.pop(name, None)

    def evidence_review(self):
        return execution.validate_evidence(execution.encode(self.envelope), self.contract_raw(), self.blobs, self.sources, now=NOW)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = SyntheticFixture()

    def test_complete_candidate_remains_stop(self):
        result = self.fixture.contract_review()
        self.assertTrue(result["consistency_passed"])
        self.assertEqual(result["timing"]["worst_seconds"], 897)
        self.assertEqual(result["source_review"]["execution_python_count"], 14)
        self.assertTrue(result["blockers"])
        self.assertTrue(all(result[k] is False for k in execution.FLAGS))

    def test_complete_synthetic_native_label_is_only_consistency(self):
        self.fixture.native_claim()
        result = self.fixture.evidence_review()
        self.assertTrue(result["claimed_success_consistent"])
        self.assertFalse(result["authenticity_verified"])
        self.assertTrue(all(result[k] is False for k in execution.FLAGS))

    def test_pure_validators_never_call_environment(self):
        self.fixture.native_claim()
        with patch("builtins.open", side_effect=AssertionError("FS")), patch("os.open", side_effect=AssertionError("FS")), \
             patch("pathlib.Path.resolve", side_effect=AssertionError("FS")), patch("subprocess.Popen", side_effect=AssertionError("process")), \
             patch("os.stat", side_effect=AssertionError("FS")), patch("os.getenv", side_effect=AssertionError("environment")), \
             patch("ctypes.CDLL", side_effect=AssertionError("syscall")), patch("time.monotonic", side_effect=AssertionError("clock")), \
             patch("importlib.util.spec_from_file_location", side_effect=AssertionError("source execution")):
            self.assertTrue(self.fixture.evidence_review()["consistency_passed"])

    def test_settings_mirror_existing_generator(self):
        root, work = Path("/synthetic/input"), Path("/synthetic/work")
        with patch("pathlib.Path.resolve", lambda x: x):
            _, expected = apt.apt_files(root, work, {"base:all": "1.0"})
        self.assertEqual(execution.apt_settings(str(root), str(work)), expected)

    def test_apt_child_passes_existing_fresh_disjoint_workspace_checks(self):
        # The existing orchestration creates its own work directory. An empty
        # synthetic input stops it before any runner call, after that mkdir.
        with tempfile.TemporaryDirectory(prefix="i5-execution-apt-child-") as directory:
            root = Path(directory).resolve()
            initialized_work, readonly = root / "work", root / "input"
            initialized_work.mkdir()
            readonly.mkdir()
            value = copy.deepcopy(self.fixture.initialization)
            value["objects"]["work"]["path"] = str(initialized_work)
            child = Path(execution.apt_work(value))
            self.assertEqual(child.parent, initialized_work)
            baseline_paths = {name: root / name for name in apt.BASE_PATHS}
            baseline_paths["status"].write_bytes(b"synthetic private guest-only status")
            baseline_paths["extended_states"].write_bytes(b"synthetic private guest-only extended states")
            tool_paths = {name: root / ("tool-" + name) for name in apt.TOOLS}
            for name, path in tool_paths.items():
                path.write_bytes(("synthetic-tool-" + name).encode())
            def no_runner(*args, **kwargs):
                raise AssertionError("synthetic missing input must stop before tools")
            result = apt.exercise_preparation(self.fixture.blobs["manifest"], NONCE, readonly, child,
                runner=no_runner, baseline_paths=baseline_paths, tool_paths=tool_paths,
                now=lambda: datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc))
            self.assertTrue(child.is_dir())
            self.assertFalse(result["passed"])
            with self.assertRaisesRegex(ValueError, "fresh disjoint"):
                apt.exercise_preparation(self.fixture.blobs["manifest"], NONCE, readonly, initialized_work,
                    runner=no_runner, baseline_paths=baseline_paths, tool_paths=tool_paths,
                    now=lambda: datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc))

    def test_native_tools_cannot_use_initialized_work_root(self):
        self.fixture.native_claim()
        work = self.fixture.initialization["objects"]["work"]["path"]
        step = self.fixture.report["tools"][-1]
        step["cwd"] = work
        step["env"].update(HOME=work + "/home", TMPDIR=work + "/tmp", APT_CONFIG=work + "/apt.conf")
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, "environment"):
            self.fixture.evidence_review()

    def test_bad_json_and_explicit_now(self):
        for raw in (b"[]", b"null", b"\xff", b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                    b'{"x":"\\ud800"}', b" " * (execution.JSON_LIMIT + 1)):
            with self.subTest(raw=repr(raw)[:30]), self.assertRaises(ValueError):
                execution.validate_contract(raw, {}, {}, now=NOW)
        for now in (True, None, 0, NOW + 600, 2**62):
            with self.subTest(now=now), self.assertRaises(ValueError):
                execution.validate_contract(self.fixture.contract_raw(), self.fixture.blobs, self.fixture.sources, now=now)

    def test_unknown_and_malformed_fields(self):
        for key, bad in (("preboot", []), ("inputs", None), ("sources", {}), ("external", []), ("budgets", True), ("schema_version", True)):
            value = copy.deepcopy(self.fixture.contract)
            value[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                execution.validate_contract(execution.encode(value), self.fixture.blobs, self.fixture.sources, now=NOW)
        self.fixture.contract["unexpected"] = True
        with self.assertRaises(ValueError):
            self.fixture.contract_review()

    def test_source_closure_roles_hash_and_unknown_imports(self):
        for name in ("scripts/sw_i5_resources.py", "scripts/sw_i5_preparation_rpc.py", execution.VALIDATOR):
            fixture = SyntheticFixture()
            del fixture.sources[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                fixture.contract_review()
        fixture = SyntheticFixture()
        fixture.sources["scripts/sw_i5_apt.py"] += b"\nimport unrelated_local_helper\n"
        fixture.contract["sources"]["execution"]["scripts/sw_i5_apt.py"] = execution.fingerprint(fixture.sources["scripts/sw_i5_apt.py"])
        with self.assertRaisesRegex(ValueError, "unknown import"):
            fixture.contract_review()

    def test_dynamic_source_edges_are_ast_checked(self):
        mutations = [("scripts/sw_i5_utm_control.py", b"exec_module(collector)", b"exec_module(other)"),
                     ("scripts/sw_i5_utm_control.py", b"module_from_spec(spec)", b"module_from_spec(other)"),
                     ("scripts/inspect-sw-i5-guest.py", b'adapter = source.with_name("sw_i5_utm_result.js")',
                      b'adapter = source.with_name("other.js") # with_name("sw_i5_utm_result.js")'),
                     ("scripts/sw_i5_apt.py", b"import hashlib", b"import hashlib\nfrom importlib.util import spec_from_file_location as hidden")]
        for name, before, after in mutations:
            fixture = SyntheticFixture()
            fixture.source_change(name, before, after)
            with self.subTest(after=after), self.assertRaises(ValueError):
                fixture.contract_review()

    def test_dynamic_aliases_and_local_anchor_shadowing(self):
        mutations = [
            ("scripts/sw_i5_utm_control.py", b"def main():", b"def main():\n    SCRIPT = Path('/tmp/other.py')"),
            ("scripts/sw_i5_utm_control.py", b"spec.loader.exec_module(collector)", b"spec = other\n    spec.loader.exec_module(collector)"),
            ("scripts/sw_i5_apt.py", b"import hashlib", b"import hashlib\nload = __import__\nload('unlisted_helper')"),
            ("scripts/sw_i5_apt.py", b"import hashlib", b"import hashlib\nimport importlib.util\nload = importlib.util.spec_from_file_location\nspec = load('other','/tmp/other.py')"),
        ]
        for name, before, after in mutations:
            fixture = SyntheticFixture()
            fixture.source_change(name, before, after)
            with self.subTest(after=after), self.assertRaises(ValueError):
                fixture.contract_review()

    def test_tools_cannot_change_configuration_cwd_or_environment(self):
        for mode in ("apt-config", "proxy", "cwd"):
            fixture = SyntheticFixture()
            fixture.native_claim()
            step = fixture.report["tools"][-1]
            if mode == "apt-config":
                step["env"]["APT_CONFIG"] = "/etc/apt/apt.conf"
            elif mode == "proxy":
                step["env"]["http_proxy"] = "http://synthetic.invalid"
            else:
                step["cwd"] = "/tmp"
            fixture.seal()
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "environment"):
                fixture.evidence_review()

    def test_unreferenced_raw_payload_is_rejected(self):
        self.fixture.native_claim()
        self.fixture.retain("unrelated-raw-database", b"synthetic private database")
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, "referenced artifacts"):
            self.fixture.evidence_review()

    def test_unknown_preboot_is_blocker_not_zero(self):
        name = "host_swap_crash"
        self.fixture.contract["preboot"][name] = dict(configured_before_start=None, evidence=None)
        del self.fixture.blobs["preboot." + name]
        result = self.fixture.contract_review()
        self.assertTrue(any("preboot.host_swap_crash" in b for b in result["blockers"]))
        self.assertFalse(result["physical_verified"])

    def test_raw_preboot_hash_and_number_bool(self):
        key = "preboot.guest_swap"
        observation = execution.decode(self.fixture.blobs[key])
        observation["hard_limit_bytes"] = False
        self.fixture.blobs[key] = execution.encode(observation)
        self.fixture.contract["preboot"]["guest_swap"]["evidence"] = execution.fingerprint(self.fixture.blobs[key])
        with self.assertRaises(ValueError):
            self.fixture.contract_review()

    def test_runtime_profile_cannot_replace_preparation(self):
        self.fixture.ledger["profile"] = "i5-runtime"
        self.fixture.blobs["capacity"] = execution.encode(self.fixture.ledger)
        self.fixture.contract["inputs"]["capacity"] = execution.fingerprint(self.fixture.blobs["capacity"])
        with self.assertRaises(ValueError):
            self.fixture.contract_review()

    def test_old_operation_consumer_rejects_new_schema(self):
        with self.assertRaises(ValueError):
            control.validate_apt_operation(self.fixture.contract, NONCE, {})

    def test_flags_cannot_authorize(self):
        for key in execution.FLAGS:
            fixture = SyntheticFixture()
            fixture.contract[key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                fixture.contract_review()

    def test_full_raw_hash_and_nonce_chain_required(self):
        for mode in ("wrong-bytes", "nonce", "previous", "sequence", "unrelated-event"):
            fixture = SyntheticFixture()
            fixture.native_claim()
            if mode == "wrong-bytes":
                fixture.blobs["native-arch.stdout"] = b"different"
            elif mode == "unrelated-event":
                fixture.blobs["event-start"] = b"unrelated"
                fixture.artifacts["event-start"] = execution.fingerprint(b"unrelated")
                fixture.blobs["report"] = execution.encode(fixture.report)
                fixture.envelope["report"] = execution.fingerprint(fixture.blobs["report"])
            else:
                event = fixture.report["events"][1]
                event[mode] = "b" * 32 if mode == "nonce" else {} if mode == "previous" else True
                fixture.blobs["report"] = execution.encode(fixture.report)
                fixture.envelope["report"] = execution.fingerprint(fixture.blobs["report"])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fixture.evidence_review()

    def test_native_apt_install_and_arbitrary_stdout_rejected(self):
        for mode in ("install", "solver", "owner", "config", "expiry", "byhash", "before-execute"):
            fixture = SyntheticFixture()
            fixture.native_claim()
            if mode == "install":
                fixture.report["tools"][-1]["argv"] = ["/usr/bin/apt-get", "install"]
            elif mode in ("solver", "owner", "config"):
                label = {"solver": "apt-simulate", "owner": "owner-gpg", "config": "apt-config"}[mode]
                step = next(s for s in fixture.report["tools"] if s["label"] == label)
                fixture.retain(step["stdout"], b"arbitrary success\n")
                step["original_bytes"]["stdout"] = len(fixture.blobs[step["stdout"]])
            elif mode == "expiry":
                fixture.report["release_chains"]["debian"]["valid_until"] = NOW
            elif mode == "byhash":
                fixture.report["release_chains"]["debian"]["by_hash"] += "0"
            else:
                fixture.report["tools"][0].update(begin=128, end=129)
            fixture.seal()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fixture.evidence_review()

    def test_success_rejects_timeout_truncation_force_unknown_cleanup(self):
        for mode in ("timeout", "truncation", "force", "unknown", "first-error", "cleanup-error", "repeat", "readback", "bootstrap-bool"):
            fixture = SyntheticFixture()
            fixture.native_claim()
            if mode == "timeout":
                fixture.report["events"][6]["status"] = "timeout"
            elif mode == "truncation":
                fixture.report["tools"][0]["original_bytes"]["stdout"] += 1
                fixture.report["tools"][0]["truncated"]["stdout"] = True
            elif mode == "force":
                fixture.report["events"][10]["details"]["forced"] = True
            elif mode == "unknown":
                fixture.report["events"][9]["details"]["remaining"] = None
            elif mode == "first-error":
                fixture.report["first_error"] = "original timeout"
            elif mode == "cleanup-error":
                fixture.report["cleanup_errors"] = ["cleanup failed"]
            elif mode == "repeat":
                fixture.report["events"][5]["details"]["count"] = 2
            elif mode == "bootstrap-bool":
                fixture.report["events"][2]["details"]["execute_count"] = True
            else:
                fixture.report["events"][3]["details"]["objects"]["lease"]["readback"]["ino"] += 1
            fixture.seal()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fixture.evidence_review()

    def test_failure_can_skip_unstarted_work_and_retains_cleanup_errors(self):
        self.fixture.native_claim()
        self.fixture.report.update(outcome="failure", first_error="start failed", cleanup_errors=["guest cleanup unknown"],
                                   tools=[], release_chains={}, apt_projection=None)
        self.fixture.report["events"] = [event for event in self.fixture.report["events"] if event["name"] in
            ("preboot", "start", "transport_reap", "guest_cleanup", "shutdown", "host_cleanup", "freeze")]
        self.fixture.report["events"][1]["status"] = "failed"
        self.fixture.prune_unproduced_artifacts()
        self.fixture.seal()
        result = self.fixture.evidence_review()
        self.assertEqual(result["first_error"], "start failed")
        self.assertEqual(result["cleanup_errors"], ["guest cleanup unknown"])
        self.assertFalse(result["claimed_success_consistent"])

    def test_failure_without_receipt_is_incomplete_never_success(self):
        self.fixture.native_claim()
        self.fixture.report.update(outcome="cancelled", first_error="cancelled", cleanup_errors=["persist failed"])
        self.fixture.seal(receipt=False)
        self.assertFalse(self.fixture.evidence_review()["claimed_success_consistent"])

    def test_native_tool_failures_are_valid_failed_evidence(self):
        for label, mode in (("native-arch", "exit"), ("key-debian", "truncated"), ("apt-simulate", "semantic")):
            fixture = SyntheticFixture()
            fixture.native_claim()
            position = next(i for i, step in enumerate(fixture.report["tools"]) if step["label"] == label)
            fixture.report["tools"] = fixture.report["tools"][:position + 1]
            step = fixture.report["tools"][-1]
            fixture.report.update(outcome="failure", first_error="native " + label + " failed", cleanup_errors=["cleanup diagnostic retained"])
            fixture.report["release_chains"] = {name: row for name, row in fixture.report["release_chains"].items()
                if any(x["label"] == "verify-" + name for x in fixture.report["tools"])}
            fixture.prune_unproduced_artifacts()
            if mode == "exit":
                step["exit_code"] = 2
                fixture.retain(step["stdout"], b"")
                fixture.retain(step["stderr"], b"synthetic native tool error\n")
                step["original_bytes"] = dict(stdout=0, stderr=len(fixture.blobs[step["stderr"]]))
            elif mode == "truncated":
                fixture.retain(step["stdout"], b"incomplete key")
                step["original_bytes"]["stdout"] = 2000
                step["truncated"]["stdout"] = True
                step["complete"] = False
            else:
                fixture.retain(step["stdout"], b"E: unresolved synthetic dependency\n")
                step["original_bytes"]["stdout"] = len(fixture.blobs[step["stdout"]])
            fixture.seal()
            with self.subTest(label=label):
                result = fixture.evidence_review()
                self.assertFalse(result["claimed_success_consistent"])
                self.assertEqual(result["first_error"], "native " + label + " failed")
                self.assertEqual(result["cleanup_errors"], ["cleanup diagnostic retained"])
                self.assertEqual(len(result["tool_diagnostics"]), 1)
                diagnostic = result["tool_diagnostics"][0]
                self.assertEqual(diagnostic["label"], label)
                if mode == "exit":
                    self.assertEqual(diagnostic["exit_code"], 2)
                    self.assertEqual(diagnostic["retained_bytes"]["stderr"], len(b"synthetic native tool error\n"))
                elif mode == "truncated":
                    self.assertTrue(diagnostic["truncated"]["stdout"])
                    self.assertFalse(diagnostic["complete"])
                    self.assertEqual(diagnostic["original_bytes"]["stdout"], 2000)
                else:
                    self.assertEqual(diagnostic["semantic_error"], "APT removal/error/warning")
                    self.assertFalse(diagnostic["semantic_error_truncated"])

    def test_native_tool_cannot_continue_after_failure(self):
        self.fixture.native_claim()
        self.fixture.report.update(outcome="failure", first_error="native arch failed")
        self.fixture.report["tools"][0]["exit_code"] = 2
        self.fixture.seal()
        with self.assertRaisesRegex(ValueError, "cannot continue"):
            self.fixture.evidence_review()

    def test_shared_phase_budget_and_clock_domain(self):
        for mode in ("phase", "rpc", "guest", "clock", "tool-after-result", "skip-cleanup"):
            fixture = SyntheticFixture()
            fixture.native_claim()
            if mode == "phase":
                fixture.report["phase_windows"]["active"]["end"] += 1
            elif mode == "rpc":
                fixture.report["events"][5]["details"]["rpc_seconds"] = 3
            elif mode == "guest":
                fixture.report["events"][6]["details"]["guest_elapsed_seconds"] = 541
            elif mode == "clock":
                fixture.report["clock_domain"] = "guest-clock-plus-host"
            elif mode == "tool-after-result":
                fixture.report["tools"][-1].update(begin=601, end=602)
            else:
                fixture.report.update(outcome="failure", first_error="cleanup absent")
                fixture.report["events"] = [event for event in fixture.report["events"] if event["name"] != "guest_cleanup"]
            fixture.seal()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fixture.evidence_review()

    def test_no_sensitive_baseline_export_payload(self):
        self.fixture.blobs["raw-status"] = b"synthetic baseline database must remain guest-side"
        with self.assertRaisesRegex(ValueError, "allowed payloads"):
            self.fixture.contract_review()

    def test_baseline_fingerprint_and_zero_slot_hash_are_bound(self):
        for mode in ("baseline", "slot-sha", "slot-bool", "nlink-bool"):
            fixture = SyntheticFixture()
            fixture.native_claim()
            if mode == "baseline":
                fixture.report["baseline_readbacks"]["after"]["status"]["sha256"] = "a" * 64
            else:
                objects = fixture.report["events"][3]["details"]["objects"]
                for snapshot in objects["lease"].values():
                    if mode == "slot-sha":
                        snapshot["sha256"] = "d" * 64
                    elif mode == "slot-bool":
                        snapshot["bytes"] = True
                    else:
                        snapshot["nlink"] = True
            fixture.seal()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fixture.evidence_review()

    def test_old_artifact_validators_reject_native_candidate(self):
        import sw_i5_preparation_channels as channels
        import sw_i5_preparation_evidence as evidence
        self.fixture.native_claim()
        manifest_hash = self.fixture.contract["inputs"]["manifest"]["sha256"]
        raw = execution.encode(self.fixture.envelope)
        for validator in (apt.validate_result, channels.validate_export, evidence.validate_host_report, evidence.validate_attempt):
            with self.subTest(validator=validator.__name__), self.assertRaises(ValueError):
                validator(raw, NONCE, manifest_hash)

    def test_receipt_report_hash_and_persist_timing(self):
        for mode in ("hash", "early", "late"):
            fixture = SyntheticFixture()
            fixture.native_claim()
            receipt = execution.decode(fixture.blobs["receipt"])
            if mode == "hash":
                receipt["report"]["sha256"] = "e" * 64
            elif mode == "early":
                receipt.update(begin=759, end=760)
            else:
                receipt.update(begin=879, end=880)
            fixture.blobs["receipt"] = execution.encode(receipt)
            fixture.envelope["receipt"] = execution.fingerprint(fixture.blobs["receipt"])
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                fixture.evidence_review()

    def test_evidence_unknown_fields_and_old_scope_rejected(self):
        self.fixture.native_claim()
        self.fixture.envelope["scope"] = "i5-preparation-export"
        with self.assertRaises(ValueError):
            self.fixture.evidence_review()

    def test_aggregate_bytes_before_parsing(self):
        with self.assertRaisesRegex(ValueError, "aggregate"):
            execution.validate_contract(b"{}", {"extra": bytes(execution.TOTAL_LIMIT + 1)}, {}, now=NOW)


if __name__ == "__main__":
    unittest.main()
