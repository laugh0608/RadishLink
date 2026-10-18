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


def coverage(ledger=None, backend="injected-offline"):
    ledger = capacity() if ledger is None else ledger
    ref = lambda raw: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    value = common(plan.HOST_COVERAGE_SCOPE)
    value["manifest_sha256"] = ledger["manifest_sha256"]
    value.update(capacity=ref(encode(ledger)), backend=backend, surfaces={})
    blobs = {}
    for index, (name, budget) in enumerate(ledger["surfaces"].items()):
        components = {}
        for component, owner in plan.COVERAGE_COMPONENTS[name].items():
            size = None if budget["state"] == "unknown" else 0 if budget["state"] == "disabled" else budget["logical_bytes"] // len(plan.COVERAGE_COMPONENTS[name])
            components[component] = dict(owner=owner, logical_bytes=size, copies=None if size is None else 0 if size == 0 else 1, peak_bytes=size,
                physical_domain=None if budget["state"] != "bounded" else "domain:" + name + (":" + component if name in ("readonly_input", "guest_system_tmpfs") else ""))
        domains = {}
        for component_index, part in enumerate(components.values()):
            domain_id = part["physical_domain"]
            if domain_id is not None:
                domains[domain_id] = dict(realm="host" if name in plan.COVERAGE_HOST_SURFACES else "guest",
                    path="/synthetic/physical/" + domain_id.replace(":", "_"), dev=index * 10 + component_index + 1,
                    mount_id=None if name in plan.COVERAGE_HOST_SURFACES else index * 10 + component_index + 1,
                    inode_limit=1024 if budget["backing"] == "noswap-tmpfs" else None,
                    ino=index * 10 + component_index + 100, filesystem_id="filesystem:" + domain_id, representation=budget["representation"])
        for domain in domains.values():
            domain["hard_reserve_bytes"] = budget["hard_limit_bytes"] // len(domains)
            domain["whole_device_bytes"] = domain["hard_reserve_bytes"] if budget["charge"] == "D" else 0
        row = dict(owner_domain=budget["owner_domain"], charge=budget["charge"], state=budget["state"],
                   components=components, physical_domains=domains, configuration=None, observation=None)
        if budget["state"] != "unknown":
            configured = dict(schema_version=1, scope="i5-preparation-boundary-configuration-claim", uuid=apt.UUID,
                nonce=NONCE, manifest_sha256=ledger["manifest_sha256"], capacity=value["capacity"], surface=name,
                owner_domain=row["owner_domain"], charge=row["charge"], state=row["state"], mechanism=budget["mechanism"],
                hard_limit_bytes=budget["hard_limit_bytes"], components=components, physical_domains=domains, configured_before_start=True)
            blobs["configuration." + name] = encode(configured)
            row["configuration"] = ref(blobs["configuration." + name])
            observed = dict(configured, scope="i5-preparation-boundary-observation-claim", configuration=row["configuration"], evidence_kind="injected-offline")
            blobs["observation." + name] = encode(observed)
            row["observation"] = ref(blobs["observation." + name])
        value["surfaces"][name] = row
    return value, blobs


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


class HostCoverageTests(unittest.TestCase):
    def review(self, value, blobs, ledger=None):
        return plan.review_host_coverage(encode(value), encode(capacity() if ledger is None else ledger), NONCE, DIGEST, blobs=blobs)

    def test_full_synthetic_inventory_is_consistent_but_always_blocked(self):
        value, blobs = coverage()
        result = self.review(value, blobs)
        self.assertFalse(result["review_passed"])
        self.assertEqual(result["feasibility"], "injected-offline-only")
        self.assertFalse(result["complete_write_boundary"])
        self.assertFalse(result["authenticity_verified"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(all(result[key] is False for key in plan.FLAGS))
        self.assertEqual(set(plan.COVERAGE_COMPONENTS), set(plan.PREP_SURFACES))

    def test_macos_global_logs_swap_crash_are_required_unknown(self):
        ledger = capacity()
        for name in plan.MACOS_UNBOUNDED_SURFACES:
            unknown(ledger["surfaces"][name])
        value, blobs = coverage(ledger, "macos-utm")
        result = self.review(value, blobs, ledger)
        self.assertEqual(result["feasibility"], "blocked-host-system-writes")
        self.assertTrue(any("APFS" in item for item in result["review_blockers"]))
        value, blobs = coverage(backend="macos-utm")
        with self.assertRaisesRegex(ValueError, "no complete hard boundary"):
            self.review(value, blobs)
        # Even a fully self-consistent disabled/zero claim cannot close this gate.
        ledger = capacity()
        unknown(ledger["surfaces"]["utm_qemu_logs_state"])
        value, blobs = coverage(ledger, "macos-utm")
        with self.assertRaisesRegex(ValueError, "host_swap_crash.*no complete hard boundary"):
            self.review(value, blobs, ledger)

    def test_capacity_profile_bytes_flags_and_inventory_are_bound(self):
        value, blobs = coverage()
        for key, bad in (("backend", "apfs-volume-quota-verified"), ("physical_verified", True), ("authorized", True), ("schema_version", True)):
            mutated = copy.deepcopy(value)
            mutated[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError): self.review(mutated, blobs)
        with self.assertRaisesRegex(ValueError, "exact capacity bytes"):
            plan.review_host_coverage(encode(value), encode(capacity()) + b" ", NONCE, DIGEST, blobs=blobs)
        for surface in plan.PREP_SURFACES:
            mutated = copy.deepcopy(value)
            del mutated["surfaces"][surface]
            with self.subTest(surface=surface), self.assertRaisesRegex(ValueError, "surfaces.*fields"):
                self.review(mutated, blobs)
        mutated = copy.deepcopy(value)
        mutated["surfaces"]["host_jxa_source"]["owner_domain"] = "host_retention"
        with self.assertRaisesRegex(ValueError, "existing capacity projection"):
            self.review(mutated, blobs)

    def test_components_cover_all_writes_and_sum_concurrent_copy_peaks(self):
        value, blobs = coverage()
        name = "host_jxa_source"
        for change in ("missing", "owner", "copy", "peak", "bool"):
            mutated = copy.deepcopy(value)
            parts = mutated["surfaces"][name]["components"]
            if change == "missing": del parts["library_source_assembly"]
            elif change == "owner": parts["library_source_assembly"]["owner"] = "evidence-owner"
            elif change == "copy": parts["library_source_assembly"].update(copies=2, peak_bytes=MIB)
            elif change == "peak": parts["library_source_assembly"]["peak_bytes"] = MIB
            else: parts["library_source_assembly"]["copies"] = True
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "components|copy peaks"):
                self.review(mutated, blobs)
        # One whole device cannot be represented by two independent payload peaks.
        mutated = copy.deepcopy(value)
        for row in mutated["surfaces"]["readonly_input"]["components"].values(): row.update(logical_bytes=MIB, peak_bytes=MIB)
        with self.assertRaisesRegex(ValueError, "component copy peaks"):
            self.review(mutated, blobs)

    def test_physical_domain_alias_and_ancestor_escape_are_rejected(self):
        value, blobs = coverage()
        left, right = "host_jxa_source", "host_evidence_export_source"
        for change in ("identity", "device", "filesystem", "ancestor", "representation", "bool", "realm"):
            mutated = copy.deepcopy(value)
            a = next(iter(mutated["surfaces"][left]["physical_domains"].values()))
            b = next(iter(mutated["surfaces"][right]["physical_domains"].values()))
            if change == "identity": b.update(dev=a["dev"], ino=a["ino"])
            elif change == "device": b["dev"] = a["dev"]
            elif change == "filesystem": b["filesystem_id"] = a["filesystem_id"]
            elif change == "ancestor": b["path"] = a["path"] + "/child"
            elif change == "representation": b["representation"] = a["representation"]
            elif change == "realm": b["realm"] = "guest"
            else: b["dev"] = True
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "physical|integer"):
                self.review(mutated, blobs)

    def test_separate_media_and_physical_reserves_use_existing_surface_and_D(self):
        value, blobs = coverage()
        for mutation in ("same_media", "reserve_peak", "reserve_sum", "whole_bool", "D_missing", "H_device"):
            modified = copy.deepcopy(value)
            row = modified["surfaces"]["readonly_input"]
            domains = list(row["physical_domains"].values())
            if mutation == "same_media":
                row["components"]["library_media"]["physical_domain"] = row["components"]["apt_media"]["physical_domain"]
                del row["physical_domains"][next(key for key in row["physical_domains"] if key.endswith("library_media"))]
            elif mutation == "reserve_peak": domains[0]["hard_reserve_bytes"] -= 1
            elif mutation == "reserve_sum":
                for domain in domains: domain.update(hard_reserve_bytes=MIB, whole_device_bytes=MIB)
            elif mutation == "whole_bool": domains[0]["whole_device_bytes"] = True
            elif mutation == "D_missing": domains[0]["whole_device_bytes"] = 0
            else: next(iter(modified["surfaces"]["host_jxa_source"]["physical_domains"].values()))["whole_device_bytes"] = 1
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, "physical|reserve|integer|device|distinct"):
                self.review(modified, blobs)
        # Correctly rehash every observation, yet whole media devices exceed D.
        ledger = capacity()
        ledger["domains"]["input"]["guest_device_bytes"] = MIB
        modified, facts = coverage(ledger)
        row = modified["surfaces"]["readonly_input"]
        for domain in row["physical_domains"].values(): domain["whole_device_bytes"] = MIB
        for role in ("configuration", "observation"):
            key = role + ".readonly_input"
            fact = json.loads(facts[key])
            fact["physical_domains"] = row["physical_domains"]
            if role == "observation": fact["configuration"] = row["configuration"]
            facts[key] = encode(fact)
            row[role] = dict(bytes=len(facts[key]), sha256=hashlib.sha256(facts[key]).hexdigest())
        with self.assertRaisesRegex(ValueError, "complete physical devices exceed existing D"):
            self.review(modified, facts, ledger)

    def test_raw_configuration_and_independent_observation_are_exact(self):
        value, blobs = coverage()
        name = "host_jxa_source"
        ref = lambda raw: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        for role, mutation in (("configuration", "surface"), ("observation", "physical_domains"), ("observation", "configuration"),
                               ("observation", "evidence_kind"), ("observation", "configured_before_start"), ("observation", "schema_version")):
            modified, facts = copy.deepcopy(value), dict(blobs)
            key = role + "." + name
            raw = json.loads(facts[key])
            if mutation == "physical_domains": next(iter(raw[mutation].values()))["dev"] += 1
            elif mutation == "configuration": raw[mutation]["sha256"] = "e" * 64
            elif mutation == "configured_before_start": raw[mutation] = 1
            elif mutation == "schema_version": raw[mutation] = True
            else: raw[mutation] = "native-verified"
            facts[key] = encode(raw)
            modified["surfaces"][name][role] = ref(facts[key])
            with self.subTest(role=role, mutation=mutation), self.assertRaisesRegex(ValueError, "configuration|observation"):
                self.review(modified, facts)
        with self.assertRaisesRegex(ValueError, "exact fact set"):
            self.review(value, dict(blobs, extra=b"{}"))
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            self.review(value, {key: raw + b" " if key == "observation." + name else raw for key, raw in blobs.items()})

    def test_unknown_is_not_zero_or_a_completion_fact(self):
        ledger = capacity()
        unknown(ledger["surfaces"]["host_backing_metadata"])
        value, blobs = coverage(ledger)
        for key, bad in (("physical_domains", {"unbound": {}}), ("configuration", {}), ("observation", {})):
            mutated = copy.deepcopy(value)
            mutated["surfaces"]["host_backing_metadata"][key] = bad
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "completion facts"):
                self.review(mutated, blobs, ledger)
        value["surfaces"]["host_backing_metadata"]["components"]["backing_snapshots_metadata"]["logical_bytes"] = 0
        with self.assertRaisesRegex(ValueError, "unknown component"):
            self.review(value, blobs, ledger)

    def test_pure_candidate_has_no_io_and_no_legacy_acceptance(self):
        value, blobs = coverage()
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name in ("builtins.open", "os.open", "os.stat", "os.lstat", "subprocess.Popen", "subprocess.run"):
                stack.enter_context(patch(name, side_effect=AssertionError("forbidden I/O")))
            self.assertFalse(self.review(value, blobs)["review_passed"])
        for validator in (lambda: plan.validate_capacity(encode(value), "preparation", NONCE, DIGEST),
                          lambda: plan.validate_plan(encode(value), NONCE, DIGEST),
                          lambda: isolation.Contract.parse(encode(value), NONCE, DIGEST)):
            with self.assertRaises(ValueError): validator()


if __name__ == "__main__":
    unittest.main()
