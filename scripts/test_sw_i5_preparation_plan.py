"""Synthetic-only review contract tests. No application, VM or real input access."""

import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import sw_i5_apt as apt
import sw_i5_preparation_isolation as isolation
import sw_i5_preparation_plan as plan
import sw_i5_preparation_rpc as rpc
import sw_i5_resources as resources
import sw_i5_utm_control as control

NONCE, DIGEST = "a" * 32, "b" * 64
MIB = apt.MIB


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def common(scope):
    return dict(schema_version=1, scope=scope, kind="synthetic", uuid=apt.UUID,
                nonce=NONCE, manifest_sha256=DIGEST, **{name: False for name in plan.FLAGS})


def capacity(profile="preparation"):
    value = common("i5-review-capacity")
    value["profile"] = profile
    caps = dict(input=4 * MIB, work=128 * MIB, result=8 * MIB, host_retention=32 * MIB,
                environment=64 * MIB) if profile == "preparation" else dict(resources.CAPS, node_tmpfs=plan.NODE_BYTES)
    value["domains"] = {name: dict(cap_bytes=cap, guest_device_bytes=(4 * MIB if name == "input" else
        32 * MIB if name == "environment" else cap - 12 * MIB if name in resources.CAPS else 0)) for name, cap in caps.items()}
    names = plan.PREP_SURFACES if profile == "preparation" else plan.I5_SURFACES
    owners = plan.PREP_OWNERS if profile == "preparation" else plan.I5_OWNERS
    value["surfaces"] = {}
    for name in names:
        owner = owners.get(name, "environment" if profile == "preparation" else "diagnostic")
        charge = "D" if name in ("guest_root_var", "efi_firmware", "readonly_input", "build", "daemon", "containerd", "builder", "evidence", "diagnostic") else "H"
        backing = "noswap-tmpfs" if name in ("guest_system_tmpfs", "preparation_work", "preparation_result", "node_tmpfs") else "readonly-media" if name == "readonly_input" else "host-quota" if charge == "H" else "fixed-block"
        size = plan.PREP_CAPS[name.removeprefix("preparation_")] if name in ("preparation_work", "preparation_result") else plan.NODE_BYTES if name == "node_tmpfs" else plan.STORE_LIMIT if name in ("host_evidence_export_source", "host_evidence_retained") else MIB
        row = dict(owner_domain=owner, charge=charge, state="bounded", logical_bytes=size,
                   copies=1, peak_bytes=size, hard_limit_bytes=size, representation="synthetic:" + name,
                   backing=backing, mechanism=plan.HARD_MECHANISMS[backing],
                   observation_source=dict(kind="synthetic", reference="synthetic:" + name))
        if name in plan.DISABLED:
            row.update(state="disabled", logical_bytes=0, copies=0, peak_bytes=0, hard_limit_bytes=0,
                       representation=None, backing="disabled", mechanism=plan.DISABLED[name])
        value["surfaces"][name] = row
    value["envelope_bytes"] = sum(caps.values())
    return value


def initialization(ledger=None):
    ledger = capacity() if ledger is None else ledger
    value = common("i5-review-initialization")
    value.update(capacity_sha256=hashlib.sha256(encode(ledger)).hexdigest(), host_uid=501, host_gid=20,
                 guest_uid=61000, guest_gid=61000, host_jxa_root="/synthetic/jxa/" + NONCE,
                 host_evidence_parent="/synthetic/evidence", readonly_input=dict(path="/synthetic/input", bytes=MIB, sha256="c" * 64),
                 jxa_source=dict(bytes=32768, sha256="d" * 64), used_nonces=[])
    value["objects"] = copy.deepcopy(plan.object_specs(value))
    value["stage_allocations"] = dict(init=dict(jxa_parent=2, evidence_parent=1, attempt_create_readback=3),
        readiness=dict(guest_directories=12, cgroup_hierarchy=16, control_slots=8, readonly_input=8, independent_readback=16),
        active=dict(order=list(plan.ACTIVE_ORDER), rpc_seconds=2, close_seconds=4, output_seconds=2, work_seconds=594,
                    source_policy="exclusive-per-rpc-create-readback-cleanup-inside-rpc-deadline"))
    observations = {}
    for index, (role, spec) in enumerate(value["objects"].items()):
        snapshot = {key: copy.deepcopy(spec[key]) for key in ("realm", "path", "uid", "gid", "mode", "kind", "bytes", "sha256", "limits")}
        snapshot.update(observer="creator", role=role, nonce=NONCE, manifest_sha256=DIGEST,
                        dev=1, ino=100 + index, nlink=1, symlink=False)
        before = dict(snapshot, observer="preexisting-observer") if spec["policy"] == "bind" else None
        observations[role] = dict(before=before, after=snapshot, independent_readback=dict(snapshot, observer="independent-reader"))
    value["offline_observations"] = dict(kind="synthetic", objects=observations)
    return value


def unknown(row):
    row.update(state="unknown", logical_bytes=None, copies=None, peak_bytes=None, hard_limit_bytes=None,
               representation=None, backing="unknown", mechanism="unknown", observation_source=None)


class ReviewTests(unittest.TestCase):
    def reject_plan(self, value, match):
        with self.assertRaisesRegex(ValueError, match):
            plan.validate_plan(encode(value), NONCE, DIGEST)

    def reject_capacity(self, value, match, profile="preparation"):
        with self.assertRaisesRegex(ValueError, match):
            plan.validate_capacity(encode(value), profile, NONCE, DIGEST)

    def test_complete_synthetic_plan_and_both_profiles(self):
        ledger, value = capacity(), initialization()
        reviewed = plan.review(encode(value), encode(ledger), NONCE, DIGEST)
        self.assertTrue(reviewed["review_passed"])
        self.assertEqual(reviewed["initialization"]["object_count"], 13)
        self.assertEqual(reviewed["initialization"]["timing"], dict(worst_seconds=897, absolute_seconds=900, stage_allocations_are_subsets=True))
        for profile in ("preparation", "i5-runtime"):
            result = plan.validate_capacity(encode(capacity(profile)), profile, NONCE, DIGEST)
            self.assertTrue(result["review_passed"])
            self.assertTrue(result["review_only"])
            self.assertTrue(result["execution_blockers"])
            self.assertEqual(result["budget_status"], "review-declaration-only")
            self.assertTrue(all(result[name] is False for name in plan.FLAGS))
        self.assertEqual(sum(resources.CAPS.values()) + plan.NODE_BYTES, 768 * MIB)
        self.assertEqual(plan.NODE_BYTES, 48 * MIB)
        self.assertEqual(value["objects"]["lease"]["path"], "/run/radishlink-i5-preparation/" + NONCE + "/control/lease.slot")
        self.assertEqual(value["objects"]["ack"]["bytes"], 1024)
        self.assertEqual(value["objects"]["work"]["uid"], 0)  # Existing mountpoint, before worker tmpfs.
        self.assertEqual(value["objects"]["cgroup_worker"]["limits"], isolation.LIMITS["worker"])
        self.assertEqual(reviewed["uuid"], apt.UUID)
        self.assertEqual(reviewed["nonce"], NONCE)
        self.assertEqual(reviewed["manifest_sha256"], DIGEST)

    def test_incomplete_real_candidate_stays_offline_and_blocked(self):
        ledger = capacity()
        ledger["kind"] = "offline-candidate"
        for surface in ("guest_root_var", "guest_swap", "host_swap_crash", "host_backing_metadata", "utm_qemu_logs_state"):
            unknown(ledger["surfaces"][surface])
        value = initialization(ledger)
        value["kind"] = "offline-candidate"
        for row in value["offline_observations"]["objects"].values():
            row.update(before=None, after=None, independent_readback=None)
        result = plan.review(encode(value), encode(ledger), NONCE, DIGEST)
        self.assertFalse(result["review_passed"])
        self.assertTrue(any("host_backing_metadata" in x for x in result["review_blockers"]))
        self.assertTrue(any("guest_swap" in x for x in result["review_blockers"]))
        self.assertTrue(any("host_attempt" in x for x in result["review_blockers"]))
        self.assertTrue(all(result[name] is False for name in plan.FLAGS))
        self.assertTrue(result["execution_blockers"])

    def test_json_framing_types_and_bounded_decode(self):
        for validator, value in ((lambda raw: plan.validate_plan(raw, NONCE, DIGEST), initialization()),
                                 (lambda raw: plan.validate_capacity(raw, "preparation", NONCE, DIGEST), capacity())):
            raw = encode(value)
            bad_inputs = [raw[:-1], raw + raw, b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
                          b'\xff', raw.decode().encode("utf-16"), raw.decode(), bytearray(raw),
                          b" " * (256 * 1024 + 1), b"[]", b"null", b"true"]
            for bad in bad_inputs:
                with self.subTest(bad=repr(bad)[:60]), self.assertRaises(ValueError):
                    validator(bad)

    def test_host_and_guest_identity_ranges_are_distinct(self):
        for gid in (0, 20, 501):
            value = initialization()
            value["host_gid"] = gid
            value["objects"] = copy.deepcopy(plan.object_specs(value))
            for role, row in value["offline_observations"]["objects"].items():
                if value["objects"][role]["realm"] == "host":
                    for snapshot in row.values():
                        if snapshot is not None:
                            snapshot["gid"] = gid
            self.assertTrue(plan.validate_plan(encode(value), NONCE, DIGEST)["review_passed"])
        for key, bad in (("host_uid", 0), ("host_gid", -1), ("guest_uid", 501), ("guest_gid", 20), ("guest_uid", True)):
            value = initialization()
            value[key] = bad
            self.reject_plan(value, "plan\\." + key)

    def test_assembled_source_full_peak_is_reserved(self):
        source = b"/" * (128 * 1024)
        program = b"x" * (48 * 1024)
        request = dict(schema_version=1, scope="i5-preparation-utm-rpc", uuid=apt.UUID,
                       nonce=NONCE, manifest_sha256=DIGEST, sequence=1, action="execute",
                       args=dict(program_base64=base64.b64encode(program).decode(), program_sha256=hashlib.sha256(program).hexdigest()))
        assembled = rpc.assemble_jxa(source, hashlib.sha256(source).hexdigest(), request)
        self.assertLessEqual(len(assembled), plan.assembled_source_bound(len(source)))
        self.assertGreater(len(assembled), len(source))
        ledger = capacity()
        ledger["surfaces"]["host_jxa_source"].update(logical_bytes=32768, peak_bytes=32768, hard_limit_bytes=32768)
        with self.assertRaisesRegex(ValueError, "host_jxa_source.*bound source/input"):
            plan.review(encode(initialization(ledger)), encode(ledger), NONCE, DIGEST)
        self.assertEqual(plan.assembled_source_bound(32768), 32768 + 6 * rpc.REQUEST_LIMIT + 4096)

    def test_top_binding_unknown_missing_flags(self):
        for original, check_bad in ((initialization(), self.reject_plan), (capacity(), self.reject_capacity)):
            changes = [("schema_version", True), ("schema_version", 2), ("scope", "i5-preparation-apt-operation"),
                       ("uuid", "other"), ("nonce", "b" * 32), ("manifest_sha256", "e" * 64),
                       ("kind", "real"), ("commands", []), ("argv", []), ("authorized", True),
                       ("install_authorized", True), ("i5_ready", True), ("physical_verified", True)]
            for key, replacement in changes:
                value = copy.deepcopy(original)
                value[key] = replacement
                with self.subTest(key=key, replacement=replacement):
                    check_bad(value, "scope|schema|uuid|nonce|manifest|kind|fields|flag|authorized|ready|verified")
            for key in original:
                value = copy.deepcopy(original)
                del value[key]
                with self.subTest(missing=key):
                    check_bad(value, "fields")
        for nonce, digest in ((True, DIGEST), ("A" * 32, DIGEST), (NONCE, None), (NONCE, "F" * 64)):
            with self.subTest(nonce=nonce, digest=digest), self.assertRaises(ValueError):
                plan.validate_plan(encode(initialization()), nonce, digest)
            with self.assertRaises(ValueError):
                plan.validate_capacity(encode(capacity()), "preparation", nonce, digest)

    def test_every_object_required_and_fixed(self):
        original = initialization()
        for role, row in original["objects"].items():
            value = copy.deepcopy(original)
            del value["objects"][role]
            self.reject_plan(value, "objects.*fields")
            for key in row:
                value = copy.deepcopy(original)
                value["objects"][role][key] = "invalid" if row[key] is None else None
                with self.subTest(role=role, key=key):
                    self.reject_plan(value, "objects\\." + role)
        value = copy.deepcopy(original)
        value["objects"]["host_jxa_source"] = dict(original["objects"]["host_jxa_root"])
        self.reject_plan(value, "objects.*fields")  # Source is a per-RPC obligation, never pre-created.

    def test_paths_are_lexical_disjoint_and_bound(self):
        for field in ("host_jxa_root", "host_evidence_parent"):
            for bad in ("/", "relative", "/synthetic//x", "/synthetic/../x", "/synthetic/./x", "/synthetic/x/", "/synthetic/x y"):
                value = initialization()
                value[field] = bad
                with self.subTest(field=field, bad=bad):
                    self.reject_plan(value, "plan\\." + field)
        for root in ("/synthetic/other", "/synthetic/evidence/" + NONCE,
                     "/synthetic/evidence/" + NONCE + "/" + NONCE):
            value = initialization()
            value["host_jxa_root"] = root
            self.reject_plan(value, "nonce|overlap|aliases")
        for path in ("/run/radishlink-i5-preparation/" + NONCE, "/run/radishlink-i5-preparation/" + NONCE + "/work"):
            value = initialization()
            value["readonly_input"]["path"] = path
            self.reject_plan(value, "disjoint")
        value = initialization()
        value["host_evidence_parent"] = "/run/radishlink-i5-preparation/" + NONCE
        value["objects"] = copy.deepcopy(plan.object_specs(value))
        value["offline_observations"]["objects"] = {role: dict(before=None, after=None, independent_readback=None) for role in value["objects"]}
        result = plan.validate_plan(encode(value), NONCE, DIGEST)
        self.assertFalse(result["review_passed"])  # Same spelling in host and guest is not a cross-realm alias.

    def test_consumed_nonce_existing_objects_and_replacements(self):
        for used in ([NONCE], ["c" * 32, "c" * 32], ["invalid"], [True], "not-list"):
            value = initialization()
            value["used_nonces"] = used
            self.reject_plan(value, "used_nonces")
        value = initialization()
        value["offline_observations"]["objects"]["guest_root"]["before"] = copy.deepcopy(value["offline_observations"]["objects"]["guest_root"]["after"])
        self.reject_plan(value, "guest_root.before.*already exists")
        for role in ("readonly_input", "host_evidence_parent"):
            value = initialization()
            value["offline_observations"]["objects"][role]["before"]["ino"] += 1
            self.reject_plan(value, role + ".*replaced")
        value = initialization()
        value["offline_observations"]["objects"]["lease"]["independent_readback"]["ino"] += 1
        self.reject_plan(value, "lease.*replacement")
        value = initialization()
        value["offline_observations"]["objects"]["ack"]["after"]["ino"] = value["offline_observations"]["objects"]["lease"]["after"]["ino"]
        self.reject_plan(value, "ack.*aliases")

    def test_every_snapshot_field_strict_and_independent(self):
        mutations = dict(observer="creator", role="ack", realm="host", path="/replaced", nonce="c" * 32,
                         manifest_sha256="c" * 64, dev=True, ino=0, uid=True, gid=1, mode=True,
                         kind="directory", nlink=2, bytes=512, sha256="c" * 64, symlink=True, limits={})
        for key, replacement in mutations.items():
            value = initialization()
            value["offline_observations"]["objects"]["lease"]["independent_readback"][key] = replacement
            with self.subTest(key=key):
                self.reject_plan(value, "lease")
        value = initialization()
        value["offline_observations"]["kind"] = "real"
        self.reject_plan(value, "synthetic only")
        value = initialization()
        value["offline_observations"]["objects"]["lease"]["after"]["verified"] = True
        self.reject_plan(value, "lease.after.*fields")

    def test_stages_share_existing_budgets_and_order(self):
        for phase, task in (("init", "jxa_parent"), ("readiness", "guest_directories")):
            for bad in (True, 0, -1, 1.5, 1000):
                value = initialization()
                value["stage_allocations"][phase][task] = bad
                self.reject_plan(value, "stage_allocations\\." + phase)
            value = initialization()
            value["stage_allocations"][phase][task] += 1
            self.reject_plan(value, "shared existing phase")
        for phase in ("before-start", "guest-init", "extra_initialization"):
            value = initialization()
            value["stage_allocations"][phase] = 60
            self.reject_plan(value, "stage_allocations.*fields")
        for key, replacement in (("order", ["execute_once", "open_lease", "open_ack"]), ("order", ["open_lease", "open_ack", "execute_once", "execute_once"]),
                                 ("rpc_seconds", 3), ("work_seconds", 600), ("source_policy", "preexisting-source")):
            value = initialization()
            value["stage_allocations"]["active"][key] = replacement
            self.reject_plan(value, "stage_allocations.active")

    def test_fixed_surface_coverage_and_domain_ownership(self):
        for profile in ("preparation", "i5-runtime"):
            original = capacity(profile)
            for name in original["surfaces"]:
                value = copy.deepcopy(original)
                del value["surfaces"][name]
                self.reject_capacity(value, "surfaces.*fields", profile)
                value = copy.deepcopy(original)
                value["surfaces"][name]["owner_domain"] = None
                self.reject_capacity(value, name + ".owner_domain", profile)
            value = copy.deepcopy(original)
            value["surfaces"]["unaccounted_free_area"] = {}
            self.reject_capacity(value, "surfaces.*fields", profile)
        for name in resources.CAPS:
            value = capacity("i5-runtime")
            value["surfaces"]["host_backing_" + name]["owner_domain"] = "diagnostic" if name != "diagnostic" else "build"
            self.reject_capacity(value, "host_backing_" + name, "i5-runtime")
        value = capacity("i5-runtime")
        value["surfaces"]["guest_system_tmpfs"]["owner_domain"] = "node_tmpfs"
        self.reject_capacity(value, "node_tmpfs.*D plus", "i5-runtime")

    def test_whole_device_not_small_payload_controls_D_plus_H(self):
        for domain in resources.CAPS:
            value = capacity("i5-runtime")
            value["domains"][domain]["guest_device_bytes"] = resources.CAPS[domain]
            self.reject_capacity(value, domain + ".*D plus", "i5-runtime")
        value = capacity("i5-runtime")
        value["domains"]["build"]["guest_device_bytes"] = MIB // 2
        self.reject_capacity(value, "build.*surface reservations", "i5-runtime")
        value = capacity("i5-runtime")
        value["domains"]["build"]["guest_device_bytes"] = 0
        self.reject_capacity(value, "build.guest_device_bytes", "i5-runtime")
        value = capacity("i5-runtime")
        value["surfaces"]["host_backing_build"]["hard_limit_bytes"] = 20 * MIB
        self.reject_capacity(value, "build.*D plus", "i5-runtime")

    def test_profiles_caps_and_complete_preparation_envelope(self):
        self.reject_capacity(capacity("i5-runtime"), "profile")
        self.reject_capacity(capacity(), "profile", "i5-runtime")
        for domain in resources.CAPS:
            value = capacity("i5-runtime")
            value["domains"][domain]["cap_bytes"] += 1
            self.reject_capacity(value, domain + ".cap_bytes", "i5-runtime")
        for domain, ceiling in plan.PREP_CAPS.items():
            value = capacity()
            value["domains"][domain]["cap_bytes"] = ceiling + 1
            self.reject_capacity(value, domain + ".cap_bytes")
        value = capacity()
        del value["domains"]["environment"]
        self.reject_capacity(value, "domains.*fields")
        value = capacity()
        value["envelope_bytes"] = sum(plan.PREP_CAPS.values())
        # Candidate maxima alone may be larger than this fixture's complete budget;
        # use exact sum of its known domains to expose omitted system/host budget.
        value["envelope_bytes"] = sum(row["cap_bytes"] for name, row in value["domains"].items() if name != "environment")
        self.reject_capacity(value, "complete envelope")
        value = capacity("i5-runtime")
        value["envelope_bytes"] += 1
        self.reject_capacity(value, "768", "i5-runtime")
        for bad in (True, 0, -1, 1.5, float("inf")):
            value = capacity()
            value["domains"]["environment"]["cap_bytes"] = bad
            self.reject_capacity(value, "integer|nonfinite")

    def test_copy_peaks_backing_unknown_and_reservation_types(self):
        for field in ("logical_bytes", "copies", "peak_bytes", "hard_limit_bytes"):
            for bad in (True, 0, -1, 0.5, "100", None):
                value = capacity()
                value["surfaces"]["input_media_creation"][field] = bad
                with self.subTest(field=field, bad=bad):
                    self.reject_capacity(value, "input_media_creation")
        value = capacity()
        value["surfaces"]["input_media_creation"]["copies"] = 2
        self.reject_capacity(value, "copy peak")
        row = value["surfaces"]["input_media_creation"]
        row.update(peak_bytes=2 * MIB, hard_limit_bytes=2 * MIB)
        self.assertTrue(plan.validate_capacity(encode(value), "preparation", NONCE, DIGEST)["review_passed"])
        for backing in ("unknown", "du", "sample", "logical-file-limit", "sparse-qcow2", True, []):
            value = capacity()
            value["surfaces"]["host_backing_metadata"]["backing"] = backing
            self.reject_capacity(value, "host_backing_metadata.*hard mechanism")
        for field in ("backing", "mechanism"):
            value = capacity()
            value["surfaces"]["input_media_creation"][field] = "du"
            self.reject_capacity(value, "input_media_creation.*hard mechanism")
        value = capacity()
        value["surfaces"]["host_jxa_source"]["representation"] = value["surfaces"]["host_backing_metadata"]["representation"]
        self.reject_capacity(value, "duplicate representation")
        value = capacity()
        unknown(value["surfaces"]["host_backing_metadata"])
        result = plan.validate_capacity(encode(value), "preparation", NONCE, DIGEST)
        self.assertFalse(result["review_passed"])
        value["surfaces"]["host_backing_metadata"]["peak_bytes"] = 0
        self.reject_capacity(value, "unknown cannot be counted as zero")

    def test_disabled_readonly_and_observation_escape_rejected(self):
        for name in capacity()["surfaces"]:
            if name in plan.DISABLED:
                continue
            value = capacity()
            value["surfaces"][name].update(state="disabled", logical_bytes=0, copies=0, peak_bytes=0,
                                          hard_limit_bytes=0, representation=None, backing="disabled", mechanism="host-swap-and-crash-disabled")
            self.reject_capacity(value, name + ".*only independently")
        for name in ("input_media_creation", "input_media_staging_copy", "host_jxa_source", "guest_root_var"):
            value = capacity()
            value["surfaces"][name].update(backing="readonly-media", mechanism="existing-readonly-bound-input")
            self.reject_capacity(value, name + ".*readonly cannot")
        value = capacity()
        value["surfaces"]["host_swap_crash"]["mechanism"] = "guest-all-swap-disabled"
        self.reject_capacity(value, "host_swap_crash.*independently")
        for name in ("host_swap_crash", "guest_swap", "host_backing_metadata"):
            value = capacity()
            value["surfaces"][name]["observation_source"] = None
            self.reject_capacity(value, name + ".observation_source")
            value = capacity()
            value["surfaces"][name]["observation_source"]["kind"] = "physical-verified"
            self.reject_capacity(value, name + ".observation_source.kind")
        value = capacity("i5-runtime")
        value["surfaces"]["node_tmpfs"]["hard_limit_bytes"] -= 1
        self.reject_capacity(value, "copy peak", "i5-runtime")
        value = capacity("i5-runtime")
        value["surfaces"]["node_tmpfs"].update(logical_bytes=MIB, peak_bytes=MIB, hard_limit_bytes=MIB)
        self.reject_capacity(value, "fixed three-node", "i5-runtime")

    def test_cross_table_binding_copy_budget_and_profile(self):
        ledger, value = capacity(), initialization()
        with self.assertRaisesRegex(ValueError, "exact ledger bytes"):
            plan.review(encode(value), encode(ledger) + b" ", NONCE, DIGEST)
        wrong = capacity("i5-runtime")
        value = initialization(wrong)
        with self.assertRaisesRegex(ValueError, "profile mismatch"):
            plan.review(encode(value), encode(wrong), NONCE, DIGEST)
        for name in ("readonly_input", "input_media_creation", "input_media_staging_copy", "host_jxa_source",
                     "guest_system_tmpfs", "host_evidence_export_source", "host_evidence_retained"):
            ledger = capacity()
            row = ledger["surfaces"][name]
            row.update(logical_bytes=1, peak_bytes=1, hard_limit_bytes=1)
            value = initialization(ledger)
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name + ".*bound source/input"):
                plan.review(encode(value), encode(ledger), NONCE, DIGEST)
        for name in ("preparation_work", "preparation_result"):
            ledger = capacity()
            ledger["surfaces"][name].update(logical_bytes=MIB, peak_bytes=MIB, hard_limit_bytes=MIB)
            self.reject_capacity(ledger, name + ".*fully reserved")

    def test_old_contracts_reject_both_new_schemas(self):
        for value in (initialization(), capacity(), capacity("i5-runtime")):
            raw = encode(value)
            for validator in (lambda: apt.validate_manifest(raw, NONCE),
                              lambda: isolation.Contract.parse(raw, NONCE, DIGEST),
                              lambda: resources.Config.decode(raw.decode()),
                              lambda: control.validate_apt_operation(value, NONCE, {})):
                with self.subTest(scope=value["scope"], validator=repr(validator)), self.assertRaises((ValueError, resources.ResourceError)):
                    validator()

    def test_validation_has_no_external_side_effects_and_no_cli(self):
        ledger, value, runtime = encode(capacity()), encode(initialization()), encode(capacity("i5-runtime"))
        forbidden = ["builtins.open", "os.open", "os.stat", "os.lstat", "os.mkdir", "os.makedirs", "os.system",
                     "os.getuid", "os.getgid", "os.scandir", "os.listdir", "os.fork", "subprocess.Popen",
                     "subprocess.run", "pathlib.Path.resolve", "pathlib.Path.stat", "pathlib.Path.open"]
        from contextlib import ExitStack
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError("forbidden I/O: " + name))) for name in forbidden]
            self.assertTrue(plan.review(value, ledger, NONCE, DIGEST)["review_passed"])
            self.assertTrue(plan.validate_capacity(runtime, "i5-runtime", NONCE, DIGEST)["review_passed"])
            for mock in mocks:
                mock.assert_not_called()
        tree = ast.parse(Path(plan.__file__).read_text())
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        self.assertTrue(imports.isdisjoint({"os", "subprocess", "tempfile", "ctypes", "argparse"}))
        self.assertFalse(any(isinstance(node, ast.If) and "__name__" in ast.unparse(node.test) for node in tree.body))


if __name__ == "__main__":
    unittest.main()
