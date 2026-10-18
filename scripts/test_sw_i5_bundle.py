"""Synthetic artifact/binding checks; no native guest, VM, tools or input reads."""

import copy
import importlib.util
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import sw_i5_apt as apt
import sw_i5_preparation_bundle as bundle
import sw_i5_preparation_execution as execution
import sw_i5_preparation_native as native
import sw_i5_preparation_plan as plan
import sw_i5_preparation_transport as transport
import sw_i5_utm_control as control
from test_sw_i5_execution import NOW, SyntheticFixture
import test_sw_i5_native as native_test
from test_sw_i5_preparation_plan import initialization, coverage, unknown

STATUS = b"Package: synthetic-example\nArchitecture: arm64\nStatus: install ok installed\nVersion: 1.0\n\n"


def runtime_sources():
    return {name: (Path(__file__).parents[1] / name).read_bytes() for name in bundle.RUNTIME}


class DeliveryFixture:
    """Six synthetic media members; no image, mount or supplied code execution."""
    def __init__(self):
        old = SyntheticFixture()
        self.sources = {name: (Path(__file__).parents[1] / name).read_bytes() for name in bundle.LIFECYCLE_RUNTIME}
        artifact = bundle.assemble_lifecycle(self.sources)
        self.manifest_hash = execution.fingerprint(old.blobs["manifest"])["sha256"]
        self.nonce = old.contract["nonce"]
        ledger = old.ledger
        ledger["domains"]["input"].update(cap_bytes=8 * apt.MIB, guest_device_bytes=8 * apt.MIB)
        for name in ("readonly_input", "input_media_creation", "input_media_staging_copy", "host_jxa_source"):
            ledger["surfaces"][name].update(logical_bytes=8 * apt.MIB, peak_bytes=8 * apt.MIB, hard_limit_bytes=8 * apt.MIB)
        ledger["surfaces"]["guest_system_tmpfs"].update(logical_bytes=2 * apt.MIB, peak_bytes=2 * apt.MIB, hard_limit_bytes=2 * apt.MIB)
        for name in plan.MACOS_UNBOUNDED_SURFACES: unknown(ledger["surfaces"][name])
        ledger["envelope_bytes"] = sum(row["cap_bytes"] for row in ledger["domains"].values())
        self.capacity_raw = execution.encode(ledger)
        self.plan_value = old.initialization
        self.plan_value["capacity_sha256"] = execution.fingerprint(self.capacity_raw)["sha256"]
        self.plan_raw = execution.encode(self.plan_value)
        self.coverage, self.coverage_blobs = coverage(ledger, "macos-utm")
        row = self.coverage["surfaces"]["readonly_input"]
        domains = row["physical_domains"]
        apt_domain = domains[row["components"]["apt_media"]["physical_domain"]]
        library_domain = domains[row["components"]["library_media"]["physical_domain"]]
        apt_domain["path"] = self.plan_value["readonly_input"]["path"]
        library_domain["path"] = bundle.LIBRARY_ROOT
        root_row = self.coverage["surfaces"]["guest_system_tmpfs"]
        root_domain = root_row["physical_domains"][root_row["components"]["initialization_root"]["physical_domain"]]
        root_domain["path"] = "/run/radishlink-i5-preparation"
        self.native_expected = dict(root_parent={key: root_domain[key] for key in ("dev", "ino", "mount_id")}, cgroup_root=dict(dev=1002, ino=1002, mount_id=1002),
            readonly_input={key: apt_domain[key] for key in ("dev", "ino", "mount_id")})
        self.library_expected = {key: library_domain[key] for key in ("dev", "ino", "mount_id")}
        self.rebind_coverage()
        contract = dict(schema_version=1, scope="i5-preparation-isolation", uuid=apt.UUID, nonce=self.nonce, manifest_sha256=self.manifest_hash,
            root=self.plan_value["objects"]["guest_root"]["path"], input=self.plan_value["readonly_input"]["path"],
            uid=self.plan_value["guest_uid"], gid=self.plan_value["guest_gid"], i5_ready=False)
        self.files = {"library.zip": artifact["program"], "library-manifest.json": artifact["manifest"],
            "isolation.json": execution.encode(contract), "apt-manifest.json": old.blobs["manifest"], "expected.json": execution.encode(self.native_expected)}
        self.value = dict(schema_version=1, scope=bundle.DELIVERY_SCOPE, kind="offline-candidate", uuid=apt.UUID, nonce=self.nonce,
            manifest_sha256=self.manifest_hash, plan=execution.fingerprint(self.plan_raw), capacity=execution.fingerprint(self.capacity_raw),
            host_coverage=execution.fingerprint(self.coverage_raw), library_expected=self.library_expected, native_expected=self.native_expected,
            library_filesystem=dict(path=bundle.LIBRARY_ROOT, filesystem="iso9660", filesystem_magic=0x9660,
                mount_options=["nodev", "noexec", "nosuid", "ro"], super_options=["ro"], capacity_bytes=4 * apt.MIB, inodes=4096),
            members={}, **bundle.FALSE)
        self.rebind()

    def rebind_coverage(self):
        for name, row in self.coverage["surfaces"].items():
            if row["state"] == "unknown": continue
            for role in ("configuration", "observation"):
                key = role + "." + name
                fact = execution.decode(self.coverage_blobs[key])
                fact.update(components=row["components"], physical_domains=row["physical_domains"])
                if role == "observation": fact["configuration"] = row["configuration"]
                self.coverage_blobs[key] = execution.encode(fact)
                row[role] = execution.fingerprint(self.coverage_blobs[key])
        self.coverage_raw = execution.encode(self.coverage)

    def rebind(self):
        self.value["members"] = {name: execution.fingerprint(self.files[name]) for name in bundle.DELIVERY_FILES[:-1]}
        self.value["host_coverage"] = execution.fingerprint(self.coverage_raw)
        self.raw = execution.encode(self.value)
        self.files["delivery.json"] = self.raw
        self.descriptor = bundle.invocation_descriptor(self.raw)

    def review(self):
        return bundle.validate_delivery(self.raw, files=self.files, sources=self.sources, plan_raw=self.plan_raw,
            capacity_raw=self.capacity_raw, coverage_raw=self.coverage_raw, coverage_blobs=self.coverage_blobs, descriptor=self.descriptor)


class LifecycleDeliveryTests(unittest.TestCase):
    def test_deterministic_seven_source_library_and_historical_artifact_remain_distinct(self):
        fixture = DeliveryFixture()
        actual = bundle.assemble_lifecycle(fixture.sources)
        self.assertEqual(actual, bundle.assemble_lifecycle(dict(reversed(list(fixture.sources.items())))))
        with zipfile.ZipFile(io.BytesIO(actual["program"])) as archive:
            self.assertEqual(set(archive.namelist()), {name.removeprefix("scripts/") for name in bundle.LIFECYCLE_RUNTIME} | {bundle.MANIFEST})
            self.assertNotIn("__main__.py", archive.namelist())
        with self.assertRaises(ValueError): bundle.validate_artifact(actual["manifest"], actual["program"], bundle.BOOTSTRAP, runtime_sources())
        old = bundle.assemble(runtime_sources())
        with self.assertRaises(ValueError): bundle.validate_lifecycle_artifact(old["manifest"], old["program"], fixture.sources)

    def test_six_files_bind_actual_native_config_and_all_flags_stay_false(self):
        fixture = DeliveryFixture()
        result = fixture.review()
        self.assertTrue(result["consistency_passed"])
        self.assertEqual(result["host_feasibility"], "blocked-host-system-writes")
        self.assertEqual(result["library_file_bytes"], sum(map(len, fixture.files.values())))
        self.assertEqual(result["config_fingerprints"], {name: execution.fingerprint(fixture.files[name]) for name in ("isolation.json", "apt-manifest.json", "expected.json")})
        self.assertFalse(result["loader_verified"])
        self.assertFalse(result["authenticity_verified"])
        self.assertTrue(all(result[name] is False for name in bundle.FALSE))
        # This instantiates our reviewed config, never any source in the ZIP.
        import sw_i5_preparation_native_lifecycle as lifecycle_native
        config = lifecycle_native.NativeGuestConfig(fixture.files["isolation.json"], fixture.files["apt-manifest.json"],
            expected=execution.decode(fixture.files["expected.json"]), delivery_sha256=fixture.descriptor["delivery_sha256"])
        self.assertEqual(config.delivery_sha256, fixture.descriptor["delivery_sha256"])

    def test_small_invocation_has_fixed_fields_and_no_hash_cycle(self):
        fixture = DeliveryFixture()
        self.assertLess(len(execution.encode(fixture.descriptor)), 1024)
        self.assertEqual(set(fixture.descriptor), {"schema_version", "scope", "uuid", "nonce", "manifest_sha256", "delivery_sha256"})
        self.assertNotIn("delivery.json", fixture.value["members"])
        for key, value in (("library_path", "/tmp/untrusted.zip"), ("entrypoint", "arbitrary.run"), ("argv", []), ("schema_version", True), ("delivery_sha256", "x" * 64)):
            descriptor = dict(fixture.descriptor)
            descriptor[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                bundle.validate_invocation_descriptor(descriptor, fixture.nonce, fixture.manifest_hash)
        fixture.descriptor["delivery_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "exact delivery bytes"): fixture.review()

    def test_source_closure_nested_import_and_supplied_sources_never_execute(self):
        fixture = DeliveryFixture()
        fixture.sources[bundle.LIFECYCLE_SOURCE] += b'\nraise AssertionError("must not execute supplied source")\n'
        with patch("builtins.open", side_effect=AssertionError("no source read")), patch("subprocess.Popen", side_effect=AssertionError("no launch")):
            artifact = bundle.assemble_lifecycle(fixture.sources)
            self.assertIn(b"must not execute supplied source", artifact["program"])
        for extra in (b"\ndef hidden():\n import arbitrary_dependency\n", b"\ndef hidden():\n from sw_i5_preparation_plan import assembled_source_bound\n"):
            sources = dict(fixture.sources)
            sources[bundle.LIFECYCLE_SOURCE] += extra
            with self.assertRaises(ValueError): bundle.assemble_lifecycle(sources)
        for name in bundle.LIFECYCLE_RUNTIME:
            sources = dict(fixture.sources)
            del sources[name]
            with self.assertRaises(ValueError): bundle.assemble_lifecycle(sources)

    def test_config_and_media_mutations_rejected_after_rehash(self):
        for mutation in ("uid", "input", "expected", "library_alias", "mount_alias", "rw", "magic", "path", "extra_member", "main"):
            fixture = DeliveryFixture()
            if mutation in ("uid", "input"):
                contract = execution.decode(fixture.files["isolation.json"])
                contract[mutation] = 61001 if mutation == "uid" else bundle.LIBRARY_ROOT
                fixture.files["isolation.json"] = execution.encode(contract)
            elif mutation == "expected":
                expected = execution.decode(fixture.files["expected.json"])
                expected["root_parent"]["dev"] += 1
                fixture.files["expected.json"] = execution.encode(expected)
            elif mutation == "library_alias": fixture.value["library_expected"] = dict(fixture.native_expected["readonly_input"])
            elif mutation == "mount_alias": fixture.value["library_expected"]["mount_id"] = fixture.native_expected["root_parent"]["mount_id"]
            elif mutation == "rw": fixture.value["library_filesystem"]["mount_options"] = ["rw"]
            elif mutation == "magic": fixture.value["library_filesystem"]["filesystem_magic"] = True
            elif mutation == "path": fixture.value["library_filesystem"]["path"] = fixture.plan_value["readonly_input"]["path"]
            elif mutation == "main":
                with zipfile.ZipFile(io.BytesIO(fixture.files["library.zip"])) as archive: members = {name: archive.read(name) for name in archive.namelist()}
                members["__main__.py"] = b"print('bad')\n"
                fixture.files["library.zip"] = bundle.zip_bytes(members)
            else: fixture.files["extra"] = b"not an allowed library member"
            fixture.rebind()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): fixture.review()

    def test_entire_media_not_zip_and_each_copy_are_charged(self):
        for mutation in ("creation", "staging", "source_peak", "jxa_peak", "device", "reserve", "all_files"):
            fixture = DeliveryFixture()
            if mutation in ("creation", "staging", "source_peak", "jxa_peak"):
                surface, component = ("input_media_creation", "library_media_creation") if mutation == "creation" else ("input_media_staging_copy", "library_media_staging") if mutation == "staging" else ("host_jxa_source", "library_source_assembly") if mutation == "source_peak" else ("host_jxa_source", "jxa_source")
                part = fixture.coverage["surfaces"][surface]["components"][component]
                part["logical_bytes"] = part["peak_bytes"] = 1
            elif mutation in ("device", "reserve"):
                row = fixture.coverage["surfaces"]["readonly_input"]
                domain = row["physical_domains"][row["components"]["library_media"]["physical_domain"]]
                domain["whole_device_bytes" if mutation == "device" else "hard_reserve_bytes"] -= 1
            else: fixture.value["library_filesystem"]["capacity_bytes"] = len(fixture.files["library.zip"])
            fixture.rebind_coverage()
            fixture.rebind()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): fixture.review()

    def test_validation_has_no_filesystem_or_execution_effects(self):
        fixture = DeliveryFixture()
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in ("builtins.open", "os.open", "os.stat", "os.lstat", "os.mkdir", "os.fork", "subprocess.Popen", "subprocess.run"):
                stack.enter_context(patch(name, side_effect=AssertionError("forbidden I/O")))
            self.assertTrue(fixture.review()["consistency_passed"])

    def test_rehashed_apt_and_root_binding_cannot_omit_complete_domains(self):
        for mutation in ("apt_tree", "apt_logical", "apt_creation", "apt_staging", "root_identity", "root_inode", "root_reserve"):
            fixture = DeliveryFixture()
            if mutation == "apt_tree":
                fixture.plan_value["readonly_input"]["bytes"] = 1
                fixture.plan_value["objects"]["readonly_input"]["bytes"] = 1
                for snapshot in fixture.plan_value["offline_observations"]["objects"]["readonly_input"].values(): snapshot["bytes"] = 1
                fixture.plan_raw = execution.encode(fixture.plan_value)
                fixture.value["plan"] = execution.fingerprint(fixture.plan_raw)
            elif mutation in ("apt_logical", "apt_creation", "apt_staging"):
                surface, component = ("readonly_input", "apt_media") if mutation == "apt_logical" else ("input_media_creation", "apt_media_creation") if mutation == "apt_creation" else ("input_media_staging_copy", "apt_media_staging")
                part = fixture.coverage["surfaces"][surface]["components"][component]
                part["logical_bytes"] = part["peak_bytes"] = apt.MIB
            else:
                root = fixture.coverage["surfaces"]["guest_system_tmpfs"]
                domain = root["physical_domains"][root["components"]["initialization_root"]["physical_domain"]]
                if mutation == "root_identity":
                    fixture.value["native_expected"]["root_parent"]["ino"] += 1
                    fixture.files["expected.json"] = execution.encode(fixture.value["native_expected"])
                elif mutation == "root_inode": domain["inode_limit"] += 1
                else: domain["hard_reserve_bytes"] += 1
            fixture.rebind_coverage()
            fixture.rebind()
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "APT|media|native root|physical reserves"):
                fixture.review()


class BindingFixture:
    """Entire fact set is fabricated, marked injected-offline, never native evidence."""
    def __init__(self):
        self.old = SyntheticFixture()
        self.sources = dict(self.old.sources)
        self.sources.update({name: (Path(__file__).parents[1] / name).read_bytes() for name in bundle.EXTENSIONS})
        self.artifact = bundle.assemble({name: self.sources[name] for name in bundle.RUNTIME})
        old_hash = execution.fingerprint(self.old.blobs["manifest"])["sha256"]
        self.old.manifest["baseline"]["status"] = execution.fingerprint(STATUS)
        manifest_raw = execution.encode(self.old.manifest)
        manifest_hash = execution.fingerprint(manifest_raw)["sha256"]
        self.old.ledger = json.loads(execution.encode(self.old.ledger).replace(old_hash.encode(), manifest_hash.encode()))
        ledger_raw = execution.encode(self.old.ledger)
        self.old.initialization = json.loads(execution.encode(self.old.initialization).replace(old_hash.encode(), manifest_hash.encode()))
        self.old.initialization["capacity_sha256"] = execution.fingerprint(ledger_raw)["sha256"]
        self.blobs = dict(self.old.blobs)
        self.blobs.update(self.artifact)
        self.blobs.update(manifest=manifest_raw, capacity=ledger_raw, plan=execution.encode(self.old.initialization))
        # assemble returns manifest as its own key; retain APT manifest separately.
        self.blobs["bundle_manifest"] = self.artifact["manifest"]
        self.blobs["manifest"] = manifest_raw
        for name, row in self.old.contract["preboot"].items():
            fact = execution.decode(self.blobs["preboot." + name])
            fact["capacity_sha256"] = execution.fingerprint(ledger_raw)["sha256"]
            self.blobs["preboot." + name] = execution.encode(fact)
            row["evidence"] = execution.fingerprint(self.blobs["preboot." + name])
        for name in execution.PAYLOADS:
            self.old.contract["inputs"][name] = execution.fingerprint(self.blobs[name])
        self.core_raw = self.old.contract_raw()
        native_objects = {role: copy.deepcopy(self.old.initialization["offline_observations"]["objects"][role]) for role in bundle.GUEST_ROLES}
        files = dict(self.old.manifest["files"])
        for source in apt.SOURCES.values():
            _, index, _ = apt.source_paths(source)
            item = files[index]
            files[index.rsplit("/", 1)[0] + "/by-hash/SHA256/" + item["sha256"]] = dict(item)
        input_bytes = sum(item["bytes"] for item in files.values())
        for role, row in native_objects.items():
            for snapshot in row.values():
                if snapshot is not None:
                    snapshot["dev"] = 13 if role == "readonly_input" else 12 if role.startswith("cgroup_") else 11
        for snapshot in native_objects["readonly_input"].values():
            snapshot.update(bytes=input_bytes, sha256=manifest_hash)
        self.native = dict(schema_version=1, scope="i5-preparation-native-initialization", uuid=apt.UUID,
            nonce=self.old.contract["nonce"], manifest_sha256=manifest_hash, backend_kind="injected-offline", objects=native_objects,
            input_bytes=input_bytes, input_files_sha256=execution.fingerprint(execution.encode(files))["sha256"], **bundle.NATIVE_FALSE)
        self.native["cgroup_snapshots"] = {}
        for kind in ("parent", "supervisor", "worker"):
            observation = native_objects["cgroup_" + kind]["independent_readback"]
            self.native["cgroup_snapshots"][kind] = dict(path=observation["path"], identity=[observation["dev"], observation["ino"]],
                type="domain", procs=[], subtree="cpu memory pids" if kind == "parent" else "",
                children=["supervisor", "worker"] if kind == "parent" else [], limits=dict(observation["limits"]),
                events=dict(populated=0, frozen=0), memory_events=dict(max=0, oom=0, oom_kill=0, oom_group_kill=0), pids_events=dict(max=0))
        observed_input = native_objects["readonly_input"]["after"]
        self.expected = dict(root_parent=dict(dev=11, ino=900, mount_id=31), cgroup_root=dict(dev=12, ino=901, mount_id=32),
                             readonly_input=dict(dev=observed_input["dev"], ino=observed_input["ino"], mount_id=33))
        self.native["prerequisite_observations"] = {}
        for role, identity in self.expected.items():
            row = dict(identity, device="0:" + str(identity["dev"]), path="/run/radishlink-i5-preparation" if role == "root_parent" else
                "/sys/fs/cgroup/radishlink-i5-preparation" if role == "cgroup_root" else self.old.initialization["readonly_input"]["path"],
                filesystem="tmpfs" if role == "root_parent" else "cgroup2" if role == "cgroup_root" else "iso9660",
                filesystem_magic=0x01021994 if role == "root_parent" else 0x63677270 if role == "cgroup_root" else 0x9660,
                mount_options=["nodev", "noexec", "nosuid", "rw"] if role == "root_parent" else ["rw"] if role == "cgroup_root" else ["ro"],
                super_options=["noswap", "rw"] if role == "root_parent" else ["rw"] if role == "cgroup_root" else ["ro"],
                capacity_bytes=apt.MIB if role == "root_parent" else None if role == "cgroup_root" else 4 * apt.MIB,
                inodes=1024 if role == "root_parent" else None if role == "cgroup_root" else 4096)
            self.native["prerequisite_observations"][role] = row
        self.blobs["native_contract"] = execution.encode(dict(schema_version=1, scope="i5-preparation-isolation", uuid=apt.UUID,
            nonce=self.native["nonce"], manifest_sha256=manifest_hash, root=self.old.initialization["objects"]["guest_root"]["path"],
            input=self.old.initialization["readonly_input"]["path"], uid=self.old.initialization["guest_uid"], gid=self.old.initialization["guest_gid"], i5_ready=False))
        self.cleanup = dict(schema_version=1, scope="i5-preparation-native-cleanup", uuid=apt.UUID,
            nonce=self.native["nonce"], manifest_sha256=manifest_hash, backend_kind="injected-offline", errors=[], pending={},
            cleaned=list(reversed(bundle.GUEST_ROLES[:-1])), **bundle.NATIVE_FALSE)
        self.host = dict(schema_version=1, scope="i5-preparation-host-initialization-facts", uuid=apt.UUID,
            nonce=self.native["nonce"], manifest_sha256=manifest_hash, evidence_kind="injected-offline",
            objects={role: copy.deepcopy(self.old.initialization["offline_observations"]["objects"][role]) for role in bundle.HOST_ROLES},
            **bundle.NATIVE_FALSE)
        self.blobs.update(native_initialization=execution.encode(self.native), native_readback=execution.encode(self.native),
            native_cleanup=execution.encode(self.cleanup), host_initialization=execution.encode(self.host),
            status_projection=bundle.project_status(STATUS, self.old.manifest["baseline"]["status"]))
        names = "native_contract bundle_manifest program bootstrap native_initialization native_readback native_cleanup host_initialization status_projection"
        self.value = dict(schema_version=1, scope=bundle.SCOPE, uuid=apt.UUID, nonce=self.native["nonce"], core=execution.fingerprint(self.core_raw),
            source_extensions={name: execution.fingerprint(self.sources[name]) for name in bundle.EXTENSIONS}, native_expected=self.expected, **bundle.FALSE,
            **{name: execution.fingerprint(self.blobs[name]) for name in names.split()})

    def change(self, name, value):
        self.blobs[name] = execution.encode(value)
        self.value[name] = execution.fingerprint(self.blobs[name])

    def capacity(self, capacity):
        self.blobs["capacity"] = execution.encode(capacity)
        declaration = execution.decode(self.blobs["plan"])
        declaration["capacity_sha256"] = execution.fingerprint(self.blobs["capacity"])["sha256"]
        self.blobs["plan"] = execution.encode(declaration)
        core = execution.decode(self.core_raw)
        for name in ("capacity", "plan"): core["inputs"][name] = execution.fingerprint(self.blobs[name])
        for name, row in core["preboot"].items():
            raw_name = "preboot." + name
            fact = execution.decode(self.blobs[raw_name])
            fact["capacity_sha256"] = declaration["capacity_sha256"]
            fact.update({key: capacity["surfaces"][name][key] for key in ("state", "mechanism", "hard_limit_bytes")})
            self.blobs[raw_name] = execution.encode(fact)
            row["evidence"] = execution.fingerprint(self.blobs[raw_name])
        self.core_raw = execution.encode(core)
        self.value["core"] = execution.fingerprint(self.core_raw)

    def review(self):
        return bundle.validate_binding(execution.encode(self.value), self.core_raw, self.blobs, self.sources, now=NOW)


class ArtifactTests(unittest.TestCase):
    def test_reproducible_raw_bytes_and_zip_metadata(self):
        sources = runtime_sources()
        result = bundle.assemble(sources)
        self.assertEqual(result, bundle.assemble(dict(reversed(list(sources.items())))))
        with zipfile.ZipFile(io.BytesIO(result["program"])) as archive:
            self.assertEqual(archive.namelist(), sorted(archive.namelist()))
            self.assertNotIn("__main__.py", archive.namelist())
            for item in archive.infolist():
                self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(item.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(item.external_attr >> 16, stat.S_IFREG | 0o644)
                self.assertEqual(item.extra, b"")
                self.assertEqual(item.comment, b"")
            for name, raw in sources.items():
                self.assertEqual(archive.read(name.removeprefix("scripts/")), raw)
        self.assertFalse(bundle.validate_artifact(result["manifest"], result["program"], result["bootstrap"], sources)["authenticity_verified"])

    def test_source_bytes_are_not_executed_or_imported(self):
        sources = runtime_sources()
        sources[bundle.NATIVE] += b'\nraise AssertionError("supplied-source-must-never-execute")\n'
        with patch("builtins.open", side_effect=AssertionError("no file reads")), patch("subprocess.Popen", side_effect=AssertionError("no tool")):
            result = bundle.assemble(sources)
            bundle.validate_artifact(result["manifest"], result["program"], result["bootstrap"], sources)
        self.assertIn(b"supplied-source-must-never-execute", result["program"])

    def test_exact_runtime_closure_and_bounded_bytes(self):
        for mutation in (lambda x: x.pop(bundle.NATIVE), lambda x: x.update({"../other.py": b"x"}),
                         lambda x: x.update({bundle.NATIVE: b""}), lambda x: x.update({bundle.NATIVE: b"x" * (2 * apt.MIB + 1)}),
                         lambda x: x.update({bundle.NATIVE: bytearray(b"x")})):
            sources = runtime_sources()
            mutation(sources)
            with self.assertRaises(ValueError): bundle.assemble(sources)

    def test_nested_unknown_import_rejected_even_after_rehash(self):
        for extra in (b"\ndef hidden():\n import arbitrary_local_dependency\n", b"\ndef hidden():\n import importlib\n",
                      b"\ndef hidden():\n from . import local\n", b"\nx = eval\n", b"\nx = __import__\n",
                      b"\nimport runpy\n", b"\nx = obj.exec_module\n"):
            sources = runtime_sources()
            sources[bundle.NATIVE] += extra
            with self.subTest(extra=extra), self.assertRaises(ValueError): bundle.assemble(sources)

    def test_missing_transitive_edge_and_invalid_source(self):
        sources = runtime_sources()
        sources[bundle.NATIVE] = b"import sw_i5_apt\n"
        with self.assertRaisesRegex(ValueError, "unreachable"): bundle.assemble(sources)
        for raw in (b"not python : :", b"\xff"):
            sources = runtime_sources()
            sources[bundle.NATIVE] = raw
            with self.assertRaisesRegex(ValueError, "AST"): bundle.assemble(sources)

    def test_zip_duplicate_extra_compression_metadata_and_entry_mutations(self):
        sources = runtime_sources()
        result = bundle.assemble(sources)
        with zipfile.ZipFile(io.BytesIO(result["program"])) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        mutations = []
        changed = dict(members, **{"__main__.py": b"raise SystemExit(0)\n"})
        mutations.append(bundle.zip_bytes(changed))
        changed = dict(members)
        changed[bundle.ENTRY] += b"\n# replaced\n"
        mutations.append(bundle.zip_bytes(changed))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, raw in members.items(): archive.writestr(name, raw)
        mutations.append(stream.getvalue())
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in members.items(): archive.writestr(name, raw)
        mutations.append(stream.getvalue())
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, raw in members.items(): archive.writestr(name, raw)
            first = next(iter(members))
            with self.assertWarns(UserWarning): archive.writestr(first, members[first])
        mutations.append(stream.getvalue())
        for program in mutations + [result["program"] + b"trailing", result["program"][:-1]]:
            with self.assertRaisesRegex(ValueError, "deterministic"):
                bundle.validate_artifact(result["manifest"], program, result["bootstrap"], sources)
        with self.assertRaises(ValueError): bundle.validate_artifact(result["manifest"], result["program"], b"# changed", sources)

    def test_library_program_is_rejected_by_old_transport_size(self):
        result = bundle.assemble(runtime_sources())
        self.assertGreater(len(result["program"]), 48 * 1024)
        with self.assertRaisesRegex(ValueError, "program size"):
            transport.transport_request("a" * 32, "b" * 64, result["program"])


class BindingTests(unittest.TestCase):
    def test_complete_synthetic_binding_preserves_all_stops(self):
        fixture = BindingFixture()
        result = fixture.review()
        self.assertTrue(result["consistency_passed"])
        self.assertTrue(result["cleanup_complete"])
        self.assertEqual(result["complete_object_observations"], 13)
        self.assertFalse(result["legacy_core_upgraded"])
        self.assertFalse(result["authenticity_verified"])
        self.assertEqual(result["native_backend_kind"], "injected-offline")
        for flag in execution.FLAGS: self.assertIs(result[flag], False)
        self.assertEqual(execution.decode(fixture.core_raw)["native_backend"], "absent")

    def test_old_contract_and_operation_consumers_reject_new_scope(self):
        fixture = BindingFixture()
        raw = execution.encode(fixture.value)
        with self.assertRaises(ValueError): execution.validate_contract(raw, fixture.blobs, fixture.sources, now=NOW)
        with self.assertRaises(ValueError): control.validate_apt_operation(fixture.value, fixture.native["nonce"], {})

    def test_core_placeholder_program_cannot_be_independently_bound(self):
        fixture = BindingFixture()
        core = execution.decode(fixture.core_raw)
        core["inputs"]["program"] = execution.fingerprint(b"# synthetic placeholder")
        fixture.core_raw = execution.encode(core)
        fixture.value["core"] = execution.fingerprint(fixture.core_raw)
        with self.assertRaises(ValueError): fixture.review()

    def test_source_extension_missing_changed_and_boolean_length(self):
        for mutate in (lambda x: x.value["source_extensions"].pop(bundle.NATIVE),
                       lambda x: x.sources.update({bundle.NATIVE: x.sources[bundle.NATIVE] + b"\n# changed\n"}),
                       lambda x: x.value["source_extensions"][bundle.TEST].update(bytes=True)):
            fixture = BindingFixture()
            mutate(fixture)
            with self.assertRaises(ValueError): fixture.review()

    def test_rehashed_artifact_member_or_manifest_change_rejected(self):
        fixture = BindingFixture()
        fixture.blobs["bundle_manifest"] += b" "
        fixture.value["bundle_manifest"] = execution.fingerprint(fixture.blobs["bundle_manifest"])
        with self.assertRaisesRegex(ValueError, "deterministic"): fixture.review()

    def test_native_missing_role_duplicate_identity_and_readback_replacement(self):
        for change in (lambda x: x["objects"].pop("lease"),
                       lambda x: x["objects"]["ack"]["independent_readback"].update(ino=999),
                       lambda x: x["objects"]["ack"].update(after=copy.deepcopy(x["objects"]["lease"]["after"]))):
            fixture = BindingFixture()
            native = copy.deepcopy(fixture.native)
            change(native)
            fixture.change("native_initialization", native)
            fixture.change("native_readback", native)
            with self.assertRaises(ValueError): fixture.review()

    def test_native_kind_nonce_slot_and_full_tree_semantics(self):
        for change in (lambda x: x.update(backend_kind="synthetic"), lambda x: x.update(nonce="f" * 32),
                       lambda x: x["objects"]["lease"]["after"].update(bytes=0),
                       lambda x: x.update(input_bytes=x["input_bytes"] + 1),
                       lambda x: x.update(input_files_sha256="f" * 64),
                       lambda x: x["objects"]["readonly_input"]["after"].update(sha256="f" * 64)):
            fixture = BindingFixture()
            native = copy.deepcopy(fixture.native)
            change(native)
            fixture.change("native_initialization", native)
            fixture.change("native_readback", native)
            with self.assertRaises(ValueError): fixture.review()

    def test_independent_native_full_readback_must_match(self):
        fixture = BindingFixture()
        native = copy.deepcopy(fixture.native)
        native["backend_kind"] = "kernel"
        fixture.change("native_readback", native)
        with self.assertRaisesRegex(ValueError, "full readback"): fixture.review()

    def test_host_three_required_no_invented_completion(self):
        for change in (lambda x: x["objects"].pop("host_attempt"),
                       lambda x: x["objects"]["host_attempt"].update(independent_readback=None),
                       lambda x: x["objects"]["host_evidence_parent"]["after"].update(ino=888)):
            fixture = BindingFixture()
            host = copy.deepcopy(fixture.host)
            change(host)
            fixture.change("host_initialization", host)
            with self.assertRaises(ValueError): fixture.review()

    def test_cleanup_failure_retained_and_identity_bound(self):
        fixture = BindingFixture()
        cleanup = copy.deepcopy(fixture.cleanup)
        role = cleanup["cleaned"].pop(0)
        observed = fixture.native["objects"][role]["after"]
        cleanup["pending"][role] = dict(state="bound", identity=[observed["dev"], observed["ino"]])
        cleanup["errors"] = ["injected cleanup refusal"]
        fixture.change("native_cleanup", cleanup)
        result = fixture.review()
        self.assertFalse(result["cleanup_complete"])
        self.assertEqual(result["cleanup_errors"], cleanup["errors"])
        cleanup["pending"][role]["identity"][0] = True
        fixture.change("native_cleanup", cleanup)
        with self.assertRaisesRegex(ValueError, "identity"): fixture.review()

    def test_cleanup_order_bound_input_and_unaccounted_roles(self):
        for change in (lambda x: x["cleaned"].reverse(), lambda x: x["cleaned"].append("readonly_input"),
                       lambda x: x["cleaned"].pop(), lambda x: x.update(pending=[])):
            fixture = BindingFixture()
            cleanup = copy.deepcopy(fixture.cleanup)
            change(cleanup)
            fixture.change("native_cleanup", cleanup)
            with self.assertRaises(ValueError): fixture.review()

    def test_unknown_blob_raw_private_database_and_false_flags(self):
        for change in (lambda x: x.blobs.update(raw_status=STATUS), lambda x: x.value.update(physical_verified=True),
                       lambda x: x.value.update(schema_version=True)):
            fixture = BindingFixture()
            change(fixture)
            with self.assertRaises(ValueError): fixture.review()

    def test_constructor_contract_and_expected_bindings(self):
        fixture = BindingFixture()
        contract = execution.decode(fixture.blobs["native_contract"])
        contract["uid"] = 62000
        fixture.change("native_contract", contract)
        with self.assertRaisesRegex(ValueError, "constructor contract"): fixture.review()
        for value in (True, 500):
            fixture = BindingFixture()
            fixture.value["native_expected"]["root_parent"]["mount_id"] = value
            with self.assertRaises(ValueError): fixture.review()

    def test_raw_cgroup_facts_strict_identity_counters_limits_population(self):
        for change in (lambda x: x["cgroup_snapshots"]["parent"]["identity"].__setitem__(0, True),
                       lambda x: x["cgroup_snapshots"]["worker"]["events"].update(populated=False),
                       lambda x: x["cgroup_snapshots"]["worker"].update(procs=[123]),
                       lambda x: x["cgroup_snapshots"]["worker"]["limits"].update(**{"memory.swap.max": "max"}),
                       lambda x: x["cgroup_snapshots"]["parent"].update(path="/wrong")):
            fixture = BindingFixture()
            changed = copy.deepcopy(fixture.native)
            change(changed)
            fixture.change("native_initialization", changed)
            fixture.change("native_readback", changed)
            with self.assertRaises(ValueError): fixture.review()

    def test_prerequisite_readbacks_not_physical_authority_and_reject_conflicts(self):
        for change in (lambda x: x["root_parent"].update(capacity_bytes=apt.MIB + 1),
                       lambda x: x["root_parent"].update(inodes=True),
                       lambda x: x["root_parent"]["super_options"].remove("noswap"),
                       lambda x: x["readonly_input"].update(mount_options=["ro", "rw"]),
                       lambda x: x["readonly_input"].update(device="9:9"),
                       lambda x: x["cgroup_root"].update(filesystem="ext4")):
            fixture = BindingFixture()
            changed = copy.deepcopy(fixture.native)
            change(changed["prerequisite_observations"])
            fixture.change("native_initialization", changed)
            fixture.change("native_readback", changed)
            with self.assertRaises(ValueError): fixture.review()

    def test_three_distinct_native_devices_and_created_role_device_required(self):
        fixture = BindingFixture()
        changed = copy.deepcopy(fixture.native)
        fixture.value["native_expected"]["cgroup_root"]["dev"] = 11
        changed["prerequisite_observations"]["cgroup_root"].update(dev=11, device="0:11")
        fixture.change("native_initialization", changed)
        fixture.change("native_readback", changed)
        with self.assertRaisesRegex(ValueError, "distinct"): fixture.review()
        fixture = BindingFixture()
        changed = copy.deepcopy(fixture.native)
        for snapshot in changed["objects"]["work"].values():
            if snapshot is not None: snapshot["dev"] = 99
        fixture.change("native_initialization", changed)
        fixture.change("native_readback", changed)
        with self.assertRaisesRegex(ValueError, "prerequisite device"): fixture.review()
        fixture = BindingFixture()
        changed = copy.deepcopy(fixture.native)
        changed["prerequisite_observations"]["cgroup_root"]["mount_id"] = 31
        fixture.value["native_expected"]["cgroup_root"]["mount_id"] = 31
        fixture.change("native_initialization", changed)
        fixture.change("native_readback", changed)
        with self.assertRaisesRegex(ValueError, "distinct"): fixture.review()

    def test_native_physical_readbacks_cannot_expand_declared_capacity(self):
        fixture = BindingFixture()
        capacity = execution.decode(fixture.blobs["capacity"])
        capacity["surfaces"]["guest_system_tmpfs"].update(logical_bytes=4096, peak_bytes=4096, hard_limit_bytes=4096)
        fixture.capacity(capacity)
        with self.assertRaisesRegex(ValueError, "tmpfs reserve"): fixture.review()
        fixture = BindingFixture()
        changed = copy.deepcopy(fixture.native)
        changed["prerequisite_observations"]["readonly_input"]["capacity_bytes"] = 5 * apt.MIB
        fixture.change("native_initialization", changed)
        fixture.change("native_readback", changed)
        with self.assertRaisesRegex(ValueError, "input domain/device"): fixture.review()
        fixture = BindingFixture()
        changed = copy.deepcopy(fixture.native)
        changed["prerequisite_observations"]["readonly_input"]["capacity_bytes"] = 1
        fixture.change("native_initialization", changed)
        fixture.change("native_readback", changed)
        with self.assertRaisesRegex(ValueError, "tree exceeds"): fixture.review()

    def test_native_producer_bytes_pass_complete_binding_with_injected_syscalls(self):
        fixture = BindingFixture()
        content = {}
        for name, source in apt.SOURCES.items():
            release, index, key = apt.source_paths(source)
            content.update({release: ("synthetic-signed-" + name).encode(), index: ("synthetic-compressed-" + name).encode(),
                            key: ("synthetic-key-" + name).encode()})
            content[index.rsplit("/", 1)[0] + "/by-hash/SHA256/" + fixture.old.manifest["files"][index]["sha256"]] = content[index]
        input_path = fixture.old.initialization["readonly_input"]["path"]
        with patch.object(native_test, "INPUT", input_path): system = native_test.MemorySyscalls(content)
        expected = {role: dict(dev=system.nodes[path].dev, ino=system.nodes[path].ino, mount_id=mount)
            for role, path, mount in (("root_parent", native_test.ROOT, 21), ("cgroup_root", native_test.GROUP, 22),
                                      ("readonly_input", input_path, 23))}
        owner = native.NativeGuestInitialization(fixture.blobs["native_contract"], fixture.blobs["manifest"], expected=expected, syscalls=system)
        events = []
        try:
            fixture.change("native_initialization", owner.initialize(deadline=50, register=events.append))
            fixture.change("native_readback", owner.readback(deadline=50))
            fixture.change("native_cleanup", owner.cleanup(deadline=60, register=events.append))
            fixture.value["native_expected"] = expected
            result = fixture.review()
            self.assertTrue(result["consistency_passed"])
            self.assertTrue(result["cleanup_complete"])
            self.assertFalse(result["authenticity_verified"])
            self.assertEqual(result["native_backend_kind"], "injected-offline")
            self.assertEqual(len(events), 27)
        finally:
            owner.close()
        self.assertEqual(system.fds, {})

    def test_actual_native_backend_injected_readbacks_bind_without_projection_fabrication(self):
        fixture = native_test.NativeTests()
        fixture.setUp()
        owner = native.NativeGuestInitialization(fixture.contract, fixture.manifest, expected=fixture.expected, syscalls=fixture.system)
        self.addCleanup(owner.close)
        try:
            initialized = owner.initialize(deadline=50, register=fixture.events.append)
            independent = owner.readback(deadline=50)
            declaration = initialization()
            declaration["manifest_sha256"] = fixture.digest
            declaration["readonly_input"]["path"] = native_test.INPUT
            declaration["objects"] = plan.object_specs(declaration)
            self.assertEqual(bundle.native_objects(initialized, declaration, fixture.manifest, fixture.expected),
                             bundle.native_objects(independent, declaration, fixture.manifest, fixture.expected))
            self.assertEqual(initialized["backend_kind"], "injected-offline")
        finally:
            cleanup = owner.cleanup(deadline=60, register=fixture.events.append)
            self.assertEqual(cleanup["errors"], [])
            self.assertEqual(cleanup["pending"], {})

    def test_projection_only_returns_semantics_and_digest(self):
        expected = execution.fingerprint(STATUS)
        raw = bundle.project_status(STATUS, expected)
        value = bundle.validate_projection(raw, {"status": expected})
        self.assertEqual(value["installed"], {"synthetic-example:arm64": "1.0"})
        self.assertNotIn(b"Status: install ok installed", raw)
        self.assertFalse(value["source_authenticity_verified"])
        with self.assertRaises(ValueError): bundle.project_status(STATUS + b" ", expected)
        with self.assertRaises(ValueError): bundle.project_status(STATUS, dict(expected, bytes=True))

    def test_projection_binding_and_required_presence(self):
        fixture = BindingFixture()
        projection = execution.decode(fixture.blobs["status_projection"])
        projection["status"]["sha256"] = "f" * 64
        fixture.change("status_projection", projection)
        with self.assertRaises(ValueError): fixture.review()
        fixture = BindingFixture()
        fixture.blobs.pop("status_projection")
        with self.assertRaises(ValueError): fixture.review()


class OwnerTests(unittest.TestCase):
    def load_fixed_entry(self, owner_type):
        # Only our exact reviewed constant is loaded; supplied runtime mapping is
        # never imported/executed in any test. Native syscalls are replaced here.
        temporary = tempfile.TemporaryDirectory(prefix="i5-fixed-entry-")
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "entry.py"
        path.write_bytes(bundle.BOOTSTRAP)
        spec = importlib.util.spec_from_file_location("i5_fixed_entry_test", path)
        module = importlib.util.module_from_spec(spec)
        fake = types.ModuleType("sw_i5_preparation_native")
        fake.NativeGuestInitialization = owner_type
        with patch.dict(sys.modules, sw_i5_preparation_native=fake): spec.loader.exec_module(module)
        return module

    def run_owner(self, *, fail_init=False, fail_task=False, cleanup_error=False, raise_cleanup=False):
        calls = []
        class Owner:
            def __init__(self, contract, manifest, *, expected, syscalls): calls.append(("construct", contract, manifest, expected, syscalls))
            def initialize(self, *, deadline, register):
                calls.append(("initialize", deadline))
                if fail_init: raise ValueError("first initialize failure")
                return {"init": 1}
            def readback(self, *, deadline):
                calls.append(("readback", deadline))
                return {"readback": 1}
            def cleanup(self, *, deadline, register):
                calls.append(("cleanup", deadline))
                if raise_cleanup: raise RuntimeError("later cleanup exception")
                return {"errors": ["later cleanup failure"] if cleanup_error else [], "pending": {}}
            def close(self): calls.append(("close",))
        def task(owner, initialized, readback):
            calls.append(("task", initialized, readback))
            if fail_task: raise ValueError("first task failure")
            return "explicit task result"
        result = self.load_fixed_entry(Owner).bootstrap_owner(b"contract", b"manifest", expected={"expected": 1},
            deadline=10, cleanup_deadline=20, register=lambda event: None, task=task, syscalls="injected")
        return calls, result

    def test_fixed_entry_single_callback_and_finally_cleanup(self):
        calls, result = self.run_owner()
        self.assertEqual([call[0] for call in calls], ["construct", "initialize", "readback", "task", "cleanup", "close"])
        self.assertEqual(calls[-2], ("cleanup", 20))
        self.assertEqual(result["task_calls"], 1)
        self.assertEqual(result["outcome"], "success")
        self.assertIs(result["physical_verified"], False)

    def test_fixed_entry_retains_primary_failure_and_cleanup_errors(self):
        calls, result = self.run_owner(fail_task=True, cleanup_error=True)
        self.assertIn("first task failure", result["first_error"])
        self.assertEqual(result["cleanup_errors"], ["later cleanup failure"])
        self.assertEqual(result["outcome"], "failure")
        self.assertEqual(calls[-1], ("close",))

    def test_fixed_entry_initialization_failure_skips_task_but_cleans(self):
        calls, result = self.run_owner(fail_init=True, raise_cleanup=True)
        self.assertEqual([call[0] for call in calls], ["construct", "initialize", "cleanup", "close"])
        self.assertIn("first initialize failure", result["first_error"])
        self.assertIn("later cleanup exception", result["cleanup_errors"][0])
        self.assertEqual(result["task_calls"], 0)

    def test_fixed_entry_with_actual_native_backend_and_injected_syscalls(self):
        fixture = native_test.NativeTests()
        fixture.setUp()
        calls = []
        def task(owner, initialized, independent):
            calls.append(owner)
            self.assertEqual(initialized, independent)
            self.assertEqual(initialized["backend_kind"], "injected-offline")
            return object()  # A caller-private result must not enter a report.
        result = self.load_fixed_entry(native.NativeGuestInitialization).bootstrap_owner(
            fixture.contract, fixture.manifest, expected=fixture.expected, deadline=50, cleanup_deadline=60,
            register=fixture.events.append, task=task, syscalls=fixture.system)
        self.assertEqual(result["outcome"], "success")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("task_result", result)
        self.assertEqual(result["cleanup"]["pending"], {})
        self.assertEqual(fixture.system.fds, {})

    def test_cleanup_failure_cannot_be_reported_as_success(self):
        _, result = self.run_owner(cleanup_error=True)
        self.assertEqual(result["outcome"], "failure")
        self.assertIn("cleanup failed", result["first_error"])


if __name__ == "__main__":
    unittest.main()
