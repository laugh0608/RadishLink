"""Pure candidate-contract and claimed-native evidence consistency checks.

No runner, CLI, native initializer or authorization is supplied here. Caller
source bytes are parsed, never imported or executed. Imported repository
validators below are used only through their existing pure review functions.
Every accepted claim remains an unauthenticated declaration, including a JSON
claim that a tool was native or that an OpenPGP signature verified.
"""

import ast
import datetime
import hashlib
import json
import math
import re

import sw_i5_apt as apt
import sw_i5_preparation_lifecycle as lifecycle
import sw_i5_preparation_plan as plan

CONTRACT_SCOPE = "i5-preparation-execution-candidate"
EVIDENCE_SCOPE = "i5-preparation-native-evidence-candidate"
FLAGS = ("execution_authorized", "install_authorized", "physical_verified", "i5_ready")
STOP = (
    "current preparation-apt, host observation and I5-R entry points remain STOP",
    "no current-task execution or installation authorization is established",
    "native initialization backend is absent; candidate bootstrap is not a backend",
    "source and evidence consistency cannot authenticate native provenance or signatures",
    "Linux/UTM physical limits and rejection behavior remain unverified",
    "external binary provenance and program/bootstrap source inclusion require independent review",
    "guest status-derived package projection is a declaration, not exported baseline truth",
)
PYTHON_SOURCES = tuple("scripts/" + name + ".py" for name in (
    "inspect-sw-i5-guest", "sw_i5_apt", "sw_i5_preparation_channels",
    "sw_i5_preparation_evidence", "sw_i5_preparation_initialization",
    "sw_i5_preparation_isolation", "sw_i5_preparation_lifecycle", "sw_i5_preparation_plan",
    "sw_i5_preparation_rpc", "sw_i5_preparation_staging", "sw_i5_preparation_supervisor",
    "sw_i5_preparation_transport", "sw_i5_resources", "sw_i5_utm_control"))
JXA = "scripts/sw_i5_utm_result.js"
VALIDATOR = "scripts/sw_i5_preparation_execution.py"
REVIEW_TESTS = tuple("scripts/test_sw_i5_" + name for name in (
    "apt.py", "channels.py", "guest.py", "initialization.py", "lifecycle.py",
    "preparation.py", "preparation_plan.py", "rpc_process.py", "staging.py",
    "transport.py", "utm_control.py", "utm_rpc.js", "execution.py"))
# Reviewed standard-library roots, not a way to classify arbitrary imports as
# external. Unknown imports fail even when they have no sw_i5 prefix.
STDLIB = frozenset((
    "argparse ast base64 ctypes dataclasses datetime email errno hashlib importlib json lzma math "
    "os pathlib platform plistlib re resource select selectors signal socket stat subprocess sys "
    "threading time zlib __future__").split())
EXTERNALS = ("host-python", "python-stdlib", "osascript", "Foundation", "UTM", "utmctl",
             "guest-agent", "guest-python", "guest-kernel") + tuple("guest-" + x for x in apt.TOOLS)
INPUTS = ("plan", "capacity", "manifest", "config", "utmctl", "media", "program", "bootstrap", "jxa")
PAYLOADS = ("plan", "capacity", "manifest", "program", "bootstrap", "jxa")
JSON_LIMIT = 256 * 1024
TOTAL_LIMIT = 32 * apt.MIB
EVENTS = (
    ("preboot", "init"), ("start", "start"), ("bootstrap", "readiness"),
    ("independent_readback", "readiness"), ("transport_open", "active"),
    ("execute_once", "active"), ("guest_result", "active"), ("export", "active"),
    ("transport_reap", "watchdog_cleanup"), ("guest_cleanup", "shutdown"),
    ("shutdown", "shutdown"), ("host_cleanup", "shutdown"), ("freeze", "shutdown"))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def fields(value, names, path):
    require(type(value) is dict and set(value) == set(names.split()), path + ": unknown/missing fields")


def integer(value, path, minimum=0, maximum=2**63 - 1):
    require(type(value) is int and minimum <= value <= maximum, path + ": integer range")


def number(value, path, minimum=0, maximum=900):
    require(type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum,
            path + ": finite number range")


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def same(left, right):
    """JSON equality that preserves the distinction between bool and number."""
    return encode(left) == encode(right)


def fingerprint(raw):
    require(type(raw) is bytes, "immutable bytes required")
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def decode(raw):
    require(type(raw) is bytes and len(raw) <= JSON_LIMIT, "bounded JSON bytes required")
    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=apt.unique,
                           parse_constant=lambda x: require(False, "nonfinite JSON constant " + x))
        # Also rejects float overflow (1e999), unpaired surrogates and huge ints.
        def walk(item, depth=0):
            require(depth <= 40, "JSON nesting limit")
            if type(item) is float:
                require(math.isfinite(item), "nonfinite JSON number")
            elif type(item) is int:
                integer(item, "JSON integer", -(2**63), 2**63 - 1)
            elif type(item) is str:
                item.encode("utf-8", "strict")
            elif type(item) in (dict, list):
                for child in (list(item.keys()) + list(item.values()) if type(item) is dict else item):
                    walk(child, depth + 1)
        walk(value)
        require(type(value) is dict, "JSON object required")
        return value
    except (UnicodeError, RecursionError, OverflowError, TypeError) as exc:
        raise ValueError("invalid JSON: " + str(exc)) from exc


def blob(value, path, maximum=TOTAL_LIMIT):
    fields(value, "bytes sha256", path)
    integer(value["bytes"], path + ".bytes", 0, maximum)
    require(apt.digest(value["sha256"]), path + ": SHA256 required")


def bound_payload(name, expected, blobs):
    blob(expected, name)
    require(name in blobs and type(blobs[name]) is bytes and fingerprint(blobs[name]) == expected,
            name + ": raw evidence hash/length mismatch or absent")
    return blobs[name]


def header(value, scope, nonce=None):
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["scope"] == scope,
            "candidate scope/schema mismatch; old artifacts cannot be upgraded")
    require(type(value["nonce"]) is str and re.fullmatch(r"[0-9a-f]{32}", value["nonce"]) is not None and
            (nonce is None or value["nonce"] == nonce) and value["uuid"] == apt.UUID, "run nonce/UUID mismatch")


def false_flags(value):
    for key in FLAGS:
        require(value[key] is False, key + ": candidate flag must be false")


def output(scope, nonce, consistent=True, blockers=(), **extra):
    return dict(schema_version=1, scope=scope, uuid=apt.UUID, nonce=nonce,
                consistency_passed=consistent, authenticity_verified=False,
                conclusion="input declaration/evidence consistency only",
                blockers=list(STOP) + list(blockers), **{key: False for key in FLAGS}, **extra)


def bounded_inputs(blobs, sources):
    require(type(blobs) is dict and type(sources) is dict, "explicit bytes mappings required")
    require(all(type(k) is str and type(v) is bytes for k, v in list(blobs.items()) + list(sources.items())),
            "bytes mapping values required")
    require(sum(map(len, blobs.values())) + sum(map(len, sources.values())) <= TOTAL_LIMIT,
            "aggregate source/evidence byte ceiling")


def call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return call_name(node.value) + "." + node.attr
    return ""


def validate_sources(manifest, sources):
    """AST consistency only; source completeness is bounded to reviewed local edges."""
    fields(manifest, "execution validator review_tests dynamic_edges", "sources")
    roles = {"execution": set(PYTHON_SOURCES) | {JXA}, "validator": {VALIDATOR}, "review_tests": set(REVIEW_TESTS)}
    require(type(sources) is dict and set(sources) == set().union(*roles.values()) and
            all(type(v) is bytes for v in sources.values()), "complete exact source byte closure required")
    require(sum(len(v) for v in sources.values() if type(v) is bytes) <= TOTAL_LIMIT, "source byte ceiling")
    for role, names in roles.items():
        require(type(manifest[role]) is dict and set(manifest[role]) == names, "source role closure: " + role)
        for name in names:
            blob(manifest[role][name], name, 2 * apt.MIB)
            require(fingerprint(sources[name]) == manifest[role][name], "source fingerprint: " + name)
    expected_edges = [dict(source="scripts/sw_i5_utm_control.py", target="scripts/inspect-sw-i5-guest.py", kind="python-spec"),
                      dict(source="scripts/inspect-sw-i5-guest.py", target="scripts/sw_i5_apt.py", kind="python-spec"),
                      dict(source="scripts/inspect-sw-i5-guest.py", target=JXA, kind="jxa-source")]
    require(manifest["dynamic_edges"] == expected_edges, "exact reviewed dynamic edges required")
    local = {name.removeprefix("scripts/").removesuffix(".py"): name for name in PYTHON_SOURCES + (VALIDATOR,)}
    graph, dynamic = {}, []
    for name in PYTHON_SOURCES + (VALIDATOR,):
        try:
            tree = ast.parse(sources[name].decode("utf-8", "strict"), filename=name)
        except (SyntaxError, UnicodeError, RecursionError) as exc:
            raise ValueError("source AST: " + name + ": " + str(exc)) from exc
        edges, loaders = set(), []
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                require(node.id not in ("exec", "eval", "compile", "__import__", "__builtins__", "globals", "locals"), "dynamic builtin reference/alias")
            if isinstance(node, ast.Attribute) and node.attr in ("spec_from_file_location", "module_from_spec", "exec_module"):
                parent = parents.get(node)
                require(isinstance(parent, ast.Call) and parent.func is node, "dynamic loader may only be a reviewed direct call")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                require(not isinstance(node, ast.ImportFrom) or node.level == 0, "relative/unknown local import: " + name)
                modules = [x.name for x in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for module in modules:
                    root = module.split(".")[0]
                    require(root in local or root in STDLIB, "unknown import dependency: " + module)
                    require(root != "importlib" or isinstance(node, ast.Import) and module == "importlib.util" and
                            all(x.asname is None for x in node.names), "dynamic import aliases are not reviewed")
                    if root in local:
                        require(module == root, "unknown local submodule")
                        edges.add(local[root])
            if isinstance(node, ast.Call):
                called = call_name(node.func)
                require(called not in ("exec", "eval", "compile", "__import__") and
                        not called.endswith((".import_module", ".run_path", ".run_module", ".load_module")),
                        "unknown dynamic code loading: " + name)
                if called.endswith(".spec_from_file_location"):
                    require(called == "importlib.util.spec_from_file_location", "unknown loader alias")
                    require(len(node.args) == 2 and not node.keywords, "dynamic loader arguments")
                    expression = ast.unparse(node.args[1])
                    permitted = {"scripts/sw_i5_utm_control.py": ("i5_inventory", "SCRIPT", "scripts/inspect-sw-i5-guest.py"),
                                 "scripts/inspect-sw-i5-guest.py": ("i5_apt", "Path(__file__).with_name('sw_i5_apt.py')", "scripts/sw_i5_apt.py")}
                    require(name in permitted, "unreviewed dynamic loader")
                    label, expr, target = permitted[name]
                    require(isinstance(node.args[0], ast.Constant) and node.args[0].value == label and expression == expr,
                            "changed dynamic loader target")
                    edges.add(target)
                    dynamic.append((name, target))
                    loaders.append(ast.unparse(node))
                elif called.endswith((".module_from_spec", ".exec_module")):
                    loaders.append(ast.unparse(node))
        if name == "scripts/sw_i5_utm_control.py":
            assignments = [ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                           any(isinstance(t, ast.Name) and t.id == "SCRIPT" for t in n.targets)]
            require(assignments == ["REPO / 'scripts/inspect-sw-i5-guest.py'"], "changed SCRIPT dynamic edge")
            require([ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                     any(isinstance(t, ast.Name) and t.id == "REPO" for t in n.targets)] ==
                    ["Path(__file__).resolve().parents[1]"], "changed dynamic repository anchor")
            for anchor in ("SCRIPT", "REPO"):
                require(len([n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == anchor and isinstance(n.ctx, ast.Store)]) == 1 and
                        not any(isinstance(n, ast.arg) and n.arg == anchor or isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == anchor
                                or isinstance(n, ast.alias) and n.asname == anchor for n in ast.walk(tree)), "dynamic source anchor shadowed")
        expected_loaders = {
            "scripts/sw_i5_utm_control.py": ["importlib.util.spec_from_file_location('i5_inventory', SCRIPT)",
                "importlib.util.module_from_spec(spec)", "spec.loader.exec_module(collector)"],
            "scripts/inspect-sw-i5-guest.py": ["importlib.util.spec_from_file_location('i5_apt', Path(__file__).with_name('sw_i5_apt.py'))",
                "importlib.util.module_from_spec(spec)", "spec.loader.exec_module(apt)"]}
        require(sorted(loaders) == sorted(expected_loaders.get(name, [])), "unpaired/unknown dynamic source execution")
        if name in expected_loaders:
            for target in ("spec", "collector" if name.endswith("sw_i5_utm_control.py") else "apt"):
                require(len([n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == target and isinstance(n.ctx, ast.Store)]) == 1 and
                        not any(isinstance(n, ast.arg) and n.arg == target or isinstance(n, ast.alias) and n.asname == target
                                for n in ast.walk(tree)), "dynamic loader object shadowed")
        for target, expression in (("spec", expected_loaders.get(name, [None])[0]),
                                   ("collector" if name.endswith("sw_i5_utm_control.py") else "apt", "importlib.util.module_from_spec(spec)")):
            if name in expected_loaders:
                require([ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign) and
                         isinstance(n.value, ast.Call) and call_name(n.value.func).startswith("importlib.util.") and
                         any(isinstance(t, ast.Name) and t.id == target for t in n.targets)] == [expression], "dynamic loader assignment changed")
        if name == "scripts/inspect-sw-i5-guest.py":
            collectors = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "collect_utm"]
            require(len(collectors) == 1, "fixed JXA collector function")
            for target, expression in (("source", "Path(__file__).resolve()"), ("adapter", "source.with_name('sw_i5_utm_result.js')")):
                require([ast.unparse(n.value) for n in ast.walk(collectors[0]) if isinstance(n, ast.Assign) and
                         any(isinstance(t, ast.Name) and t.id == target for t in n.targets)] == [expression], "changed JXA asset AST edge")
        graph[name] = sorted(edges)
    require(sorted(dynamic) == sorted((e["source"], e["target"]) for e in expected_edges if e["kind"] == "python-spec"),
            "missing/duplicate dynamic edge")
    reachable, pending = set(), ["scripts/sw_i5_utm_control.py", "scripts/inspect-sw-i5-guest.py",
                                 "scripts/sw_i5_preparation_lifecycle.py", "scripts/sw_i5_preparation_initialization.py"]
    while pending:
        name = pending.pop()
        if name not in reachable:
            reachable.add(name)
            pending.extend(graph[name])
    require(reachable == set(PYTHON_SOURCES), "missing/unreachable executable dependency closure")
    return dict(local_graph=graph, execution_python_count=len(PYTHON_SOURCES),
                external_binary_closure_verified=False, review_tests_executed=False,
                consistency_passed=True, authenticity_verified=False, blockers=list(STOP),
                **{key: False for key in FLAGS})


def validate_contract(raw, blobs, sources, *, now):
    """Check supplied declarations, with explicit UTC epoch now; no observations are made."""
    bounded_inputs(blobs, sources)
    integer(now, "now", 1, 253402214399)
    value = decode(raw)
    fields(value, "schema_version scope kind uuid nonce revision issued_at valid_until inputs sources external "
           "preboot bootstrap_policy native_backend authorization budgets " + " ".join(FLAGS), "contract")
    header(value, CONTRACT_SCOPE)
    false_flags(value)
    nonce = value["nonce"]
    require(value["kind"] == "offline-candidate", "candidate kind required")
    require(type(value["revision"]) is str and re.fullmatch(r"[0-9a-f]{40}", value["revision"]), "exact revision required")
    integer(value["issued_at"], "issued_at", 1)
    integer(value["valid_until"], "valid_until", value["issued_at"] + 1, value["issued_at"] + 86400)
    require(value["issued_at"] <= now < value["valid_until"], "contract expired or not yet valid")
    require(same(value["authorization"], {"state": "not-granted", "reference": None}), "declaration cannot grant authorization")
    require(value["native_backend"] == "absent", "no native backend exists in this package")
    require(value["bootstrap_policy"] == "independent-fixed-readiness-operation-no-lease", "bootstrap cannot require nonexistent lease")
    fields(value["inputs"], " ".join(INPUTS), "inputs")
    for name, ref in value["inputs"].items():
        blob(ref, "inputs." + name)
        require(ref["bytes"] > 0, "empty bound input: " + name)
    fields(value["external"], " ".join(EXTERNALS), "external environment")
    for name, ref in value["external"].items():
        blob(ref, "external." + name)
        require(ref["bytes"] > 0, "external identity cannot be absent")
    require(value["external"]["utmctl"] == value["inputs"]["utmctl"], "utmctl identity mismatch")
    fields(value["budgets"], "caps reap_slots worst_seconds absolute_seconds guest_seconds rpc_seconds", "budgets")
    budget = value["budgets"]
    require(type(budget["caps"]) is dict and set(budget["caps"]) == set(lifecycle.CAPS), "fixed budget fields")
    for key, cap in lifecycle.CAPS.items():
        require(type(budget["caps"][key]) is int and budget["caps"][key] == cap, "fixed budget: " + key)
    require(budget["reap_slots"] == list(lifecycle.REAP_SLOTS), "fixed reap accounting")
    for key, expected in (("worst_seconds", lifecycle.Budget().worst_seconds), ("absolute_seconds", 900),
                          ("guest_seconds", apt.GUEST_SECONDS), ("rpc_seconds", 2)):
        require(type(budget[key]) is int and budget[key] == expected, "fixed nested budget: " + key)
    source_report = validate_sources(value["sources"], sources)
    fields(value["preboot"], " ".join(plan.PREP_SURFACES), "preboot surfaces")
    allowed = set(PAYLOADS) | {"preboot." + name for name, row in value["preboot"].items()
                               if type(row) is dict and row.get("evidence") is not None}
    require(set(blobs) == allowed, "exact allowed payloads; no baseline database/binary export required")
    for name in PAYLOADS:
        bound_payload(name, value["inputs"][name], blobs)
    require(value["inputs"]["jxa"] == value["sources"]["execution"][JXA] and blobs["jxa"] == sources[JXA], "JXA source mismatch")
    decode(blobs["manifest"])
    manifest = apt.validate_manifest(blobs["manifest"].decode("utf-8", "strict"), nonce)
    manifest_hash = value["inputs"]["manifest"]["sha256"]
    reviewed = plan.review(blobs["plan"], blobs["capacity"], nonce, manifest_hash)
    initialization, capacity = decode(blobs["plan"]), decode(blobs["capacity"])
    require(capacity["profile"] == "preparation", "preparation envelope cannot use I5 runtime 768 MiB profile")
    require(initialization["jxa_source"] == value["inputs"]["jxa"] and
            initialization["readonly_input"]["bytes"] == value["inputs"]["media"]["bytes"] and
            initialization["readonly_input"]["sha256"] == value["inputs"]["media"]["sha256"], "plan media/JXA binding")
    for name in apt.TOOLS:
        require(value["external"]["guest-" + name]["sha256"] == manifest["baseline"]["tools"][name]["sha256"], "baseline tool fingerprint")
    fields(value["preboot"], " ".join(plan.PREP_SURFACES), "preboot surfaces")
    blockers = list(reviewed["review_blockers"])
    for name, row in value["preboot"].items():
        fields(row, "configured_before_start evidence", "preboot." + name)
        require(row["configured_before_start"] in (True, None) and type(row["configured_before_start"]) in (bool, type(None)),
                "preboot must already be configured, never create limits in init6")
        if row["evidence"] is None:
            require(row["configured_before_start"] is None, "unobserved preboot cannot claim complete")
            blockers.append("preboot." + name + ": unknown; no zero/default completion")
            continue
        observation = decode(bound_payload("preboot." + name, row["evidence"], blobs))
        fields(observation, "schema_version scope nonce uuid capacity_sha256 surface state mechanism hard_limit_bytes configured_before_start", "preboot observation")
        header(observation, "i5-preboot-boundary-claim", nonce)
        expected = capacity["surfaces"][name]
        require(observation["capacity_sha256"] == value["inputs"]["capacity"]["sha256"] and
                observation["surface"] == name and observation["configured_before_start"] is True and
                row["configured_before_start"] is True and
                all(same(observation[k], expected[k]) for k in ("state", "mechanism", "hard_limit_bytes")), "preboot raw declaration binding")
        require(expected["state"] in ("bounded", "disabled"), "unknown physical boundary cannot be observed as complete")
    return output("i5-preparation-execution-candidate-report", nonce, blockers=blockers,
                  source_review=source_report, contract=fingerprint(raw), baseline=manifest["baseline"],
                  timing=reviewed["initialization"]["timing"], review_passed=reviewed["review_passed"])


def artifact_refs(value, path="evidence"):
    require(type(value) is dict and len(value) <= 256, path + ": artifact mapping")
    for name, ref in value.items():
        require(type(name) is str and re.fullmatch(r"[a-z0-9_.-]{1,100}", name), path + ": artifact identifier")
        blob(ref, path + "." + name, 2 * apt.MIB)


def validate_evidence(raw, contract_raw, blobs, sources, *, now):
    """Validate future native *claims*, not native origin or cryptographic truth.

    Envelope -> report raw bytes -> ordered events/tool raw streams; a separate
    receipt points back to report bytes. The report never hashes its receipt.
    Host-supervisor elapsed seconds are the only cross-stage clock domain.
    """
    bounded_inputs(blobs, sources)
    contract = decode(contract_raw)
    require(type(contract.get("preboot")) is dict and all(type(v) is dict and "evidence" in v for v in contract["preboot"].values()), "contract preboot structure")
    contract_blob_names = set(PAYLOADS) | {"preboot." + name for name, row in contract["preboot"].items() if row["evidence"] is not None}
    review = validate_contract(contract_raw, {k: v for k, v in blobs.items() if k in contract_blob_names}, sources, now=now)
    envelope = decode(raw)
    fields(envelope, "schema_version scope uuid nonce contract report receipt " + " ".join(FLAGS), "evidence envelope")
    header(envelope, EVIDENCE_SCOPE, contract["nonce"])
    false_flags(envelope)
    require(envelope["contract"] == fingerprint(contract_raw), "evidence contract fingerprint mismatch")
    report_raw = bound_payload("report", envelope["report"], blobs)
    report = decode(report_raw)
    fields(report, "schema_version scope uuid nonce contract evidence_kind outcome first_error cleanup_errors "
           "clock_domain phase_windows events baseline_readbacks tools release_chains apt_projection artifacts " + " ".join(FLAGS), "native claim report")
    header(report, "i5-preparation-native-report-candidate", contract["nonce"])
    false_flags(report)
    require(report["contract"] == fingerprint(contract_raw) and report["evidence_kind"] == "native-claim-unverified", "native report binding/kind")
    require(report["clock_domain"] == "host-supervisor-monotonic-elapsed-seconds", "guest/host clock domains cannot be added")
    require(report["outcome"] in ("success", "failure", "cancelled", "forced-stop", "unknown"), "explicit run outcome")
    require(report["first_error"] is None or type(report["first_error"]) is str and 0 < len(report["first_error"].encode()) <= 1536, "first error bound")
    require(type(report["cleanup_errors"]) is list and len(report["cleanup_errors"]) <= 16 and
            all(type(x) is str and 0 < len(x.encode()) <= 768 for x in report["cleanup_errors"]), "cleanup errors retained separately")
    artifact_refs(report["artifacts"])
    referenced = {e["raw"] for e in report["events"]} | {s[stream] for s in report["tools"] for stream in ("stdout", "stderr")} | {
        r["authenticated_release"] for r in report["release_chains"].values()}
    require(set(report["artifacts"]) == referenced, "exact referenced artifacts only; no raw databases or unrelated payloads")
    require(not set(report["artifacts"]) & (contract_blob_names | {"report", "receipt"}), "artifact identifier collision")
    require(set(blobs) == contract_blob_names | {"report"} | ({"receipt"} if envelope["receipt"] is not None else set()) |
            set(report["artifacts"]), "unknown/missing raw evidence payload")
    for name, ref in report["artifacts"].items():
        bound_payload(name, ref, blobs)
    windows = report["phase_windows"]
    fields(windows, " ".join(k for k in lifecycle.CAPS if k != "reap") + " reap_slots", "phase windows")
    last = 0
    for name in (k for k in lifecycle.CAPS if k != "reap"):
        row = windows[name]
        fields(row, "begin end", "phase." + name)
        number(row["begin"], name + ".begin")
        number(row["end"], name + ".end", row["begin"])
        require(row["begin"] >= last and row["end"] - row["begin"] <= lifecycle.CAPS[name], "shared phase window overlap/ceiling: " + name)
        last = row["end"]
    fields(windows["reap_slots"], " ".join(lifecycle.REAP_SLOTS), "reap slots")
    for name, duration in windows["reap_slots"].items():
        number(duration, "reap." + name, 0, lifecycle.CAPS["reap"])
    require(last + sum(windows["reap_slots"].values()) <= 900, "absolute lifecycle budget")
    events = report["events"]
    require(type(events) is list and len(events) <= len(EVENTS), "bounded fixed event sequence")
    previous, event_end, failed = fingerprint(contract_raw), 0, False
    handle = None
    order, stage_index, seen = dict((name, i) for i, (name, _) in enumerate(EVENTS)), -1, []
    for index, event in enumerate(events):
        fields(event, "name phase sequence nonce uuid contract previous begin end status raw details", "event")
        name = event["name"]
        require(type(name) is str and name in order and order[name] > stage_index, "event order/duplicate")
        stage_index, phase = order[name], EVENTS[order[name]][1]
        seen.append(name)
        require(event["phase"] == phase and type(event["sequence"]) is int and event["sequence"] == index,
                "event order/sequence")
        require(event["nonce"] == contract["nonce"] and event["uuid"] == apt.UUID and
                event["contract"] == fingerprint(contract_raw) and event["previous"] == previous, "event run/hash chain binding")
        number(event["begin"], "event.begin", event_end)
        number(event["end"], "event.end", event["begin"])
        require(windows[phase]["begin"] <= event["begin"] <= event["end"] <= windows[phase]["end"], "event outside shared stage")
        require(event["status"] in ("ok", "failed", "cancelled", "timeout", "truncated", "missing", "unknown", "forced"), "event status")
        failed |= event["status"] != "ok"
        require(type(event["raw"]) is str and event["raw"] in report["artifacts"], "event raw evidence required")
        details = event["details"]
        fact = decode(blobs[event["raw"]])
        require(same(fact, dict({k: v for k, v in event.items() if k != "raw"}, schema_version=1, scope="i5-native-event-claim")), "event raw fact/details/time/run mismatch")
        if name == "independent_readback":
            fields(details, "observer objects slots", name)
            specs = decode(blobs["plan"])["objects"]
            fields(details["objects"], " ".join(specs), "readback objects")
            identities = set()
            for role, spec in specs.items():
                observed = details["objects"][role]
                fields(observed, "created readback", "readback." + role)
                for who, snapshot in observed.items():
                    ident = plan.observation(snapshot, spec, role, contract["nonce"],
                                             contract["inputs"]["manifest"]["sha256"], "native-readback." + role)
                    require(snapshot["observer"] == ("creator" if who == "created" else "independent-reader"), "independent native reader role")
                require(same({k: v for k, v in observed["created"].items() if k != "observer"},
                             {k: v for k, v in observed["readback"].items() if k != "observer"}) and ident not in identities,
                        "native readback object replaced/aliased")
                identities.add(ident)
            require(details["observer"] == "independent-reader" and details["slots"] == {"lease": 1024, "ack": 1024} and
                    all(type(x) is int for x in details["slots"].values()), "13 objects/slots independent readback")
        elif name == "bootstrap":
            require(same(details, {"input": contract["inputs"]["bootstrap"], "lease_required": False, "execute_count": 1}), "independent fixed bootstrap")
        elif name == "execute_once":
            fields(details, "program count handle lease_slot ack_slot rpc_seconds", name)
            require(details["program"] == contract["inputs"]["program"] and type(details["count"]) is int and details["count"] == 1 and
                    type(details["handle"]) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", details["handle"]), "single execute/program/handle")
            require(details["lease_slot"] == "lease" and details["ack_slot"] == "ack", "same fixed slots required")
            number(details["rpc_seconds"], "RPC duration", 0, 2)
            handle = details["handle"]
        elif name == "guest_result":
            fields(details, "handle guest_elapsed_seconds exit_code signal_code complete reaped", name)
            require(details["handle"] == handle and type(details["exit_code"]) in (int, type(None)) and
                    type(details["signal_code"]) in (int, type(None)) and type(details["complete"]) is bool and
                    type(details["reaped"]) is bool, "guest result completeness/handle/reap")
            number(details["guest_elapsed_seconds"], "nested guest elapsed", 0, apt.GUEST_SECONDS)
            failed |= details["exit_code"] != 0 or details["signal_code"] != 0 or not details["complete"] or not details["reaped"]
        elif name in ("transport_reap", "guest_cleanup", "host_cleanup"):
            fields(details, "remaining identity_bound", name)
            require(details["remaining"] in (0, None) and type(details["remaining"]) in (int, type(None)) and
                    details["identity_bound"] is True, "cleanup identity/readback")
            failed |= details["remaining"] is None
        elif name == "shutdown":
            fields(details, "count stopped forced", name)
            require(type(details["count"]) is int and details["count"] == 1 and type(details["stopped"]) in (bool, type(None)) and
                    type(details["forced"]) is bool, "unique shutdown observation")
            failed |= details["stopped"] is not True or details["forced"]
        else:
            require(details == {}, "fixed event details")
        previous, event_end = fingerprint(encode(event)), event["end"]
    baseline = review["baseline"]
    fields(report["baseline_readbacks"], "before after", "guest-only frozen baseline readbacks")
    for when, snapshot in report["baseline_readbacks"].items():
        require(same(snapshot, baseline) or snapshot is None and report["outcome"] != "success",
                "guest baseline raw fingerprints/architecture/tools changed: " + when)
    tool_review = validate_tools(report, contract, blobs, now)
    failed |= tool_review["failed"]
    if envelope["receipt"] is not None:
        receipt = decode(bound_payload("receipt", envelope["receipt"], blobs))
        fields(receipt, "schema_version scope uuid nonce contract report artifacts frozen persisted begin end " + " ".join(FLAGS), "receipt")
        header(receipt, "i5-preparation-native-receipt-candidate", contract["nonce"])
        false_flags(receipt)
        require(receipt["contract"] == fingerprint(contract_raw) and receipt["report"] == fingerprint(report_raw) and
                same(receipt["artifacts"], report["artifacts"]) and receipt["frozen"] is True and receipt["persisted"] is True,
                "receipt binds exact preceding report/artifacts, never itself")
        require("freeze" in seen, "receipt requires a frozen report")
        number(receipt["begin"], "receipt.begin", event_end)
        number(receipt["end"], "receipt.end", receipt["begin"])
        require(windows["persist"]["begin"] <= receipt["begin"] <= receipt["end"] <= windows["persist"]["end"], "receipt outside persist window")
    else:
        failed = True
    complete = len(events) == len(EVENTS) and envelope["receipt"] is not None
    required_cleanup = {"host_cleanup"} | ({"transport_reap", "guest_cleanup", "shutdown"} if "start" in seen else set())
    require(required_cleanup <= set(seen), "failure/cancellation still requires explicit recovery observations")
    require("execute_once" not in seen or "guest_result" in seen, "execute attempt requires explicit result/missing-result observation")
    if report["outcome"] == "success":
        require(complete and not failed and report["first_error"] is None and report["cleanup_errors"] == [] and
                review["review_passed"] and len(review["blockers"]) == len(STOP), "success requires full consistent chain; no timeout/truncation/unknown/cleanup error")
    else:
        require(report["first_error"] is not None, "failed/cancelled/unknown outcome must retain original error")
    return output("i5-preparation-native-evidence-candidate-report", contract["nonce"],
                  consistent=True, blockers=review["blockers"][len(STOP):],
                  chain_complete=complete, claimed_success_consistent=report["outcome"] == "success",
                  outcome=report["outcome"], first_error=report["first_error"], cleanup_errors=report["cleanup_errors"],
                  tool_diagnostics=tool_review["diagnostics"])


def apt_settings(root, work):
    """Finite declaration mirror of apt_files settings; parity is tested offline.

    apt_files itself resolves filesystem paths and is never called here.
    """
    return {
        "Dir::Etc::main": "/dev/null", "Dir::Etc::parts": work + "/empty",
        "Dir::Etc::sourcelist": work + "/sources.list", "Dir::Etc::sourceparts": work + "/empty",
        "Dir::Etc::preferences": work + "/preferences", "Dir::Etc::preferencesparts": work + "/empty",
        "Dir::Etc::trusted": "/dev/null", "Dir::Etc::trustedparts": work + "/empty",
        "Dir::Etc::netrc": "/dev/null", "Dir::Etc::netrcparts": work + "/empty",
        "Dir::State": work + "/state", "Dir::State::lists": work + "/state/lists",
        "Dir::State::status": work + "/status", "Dir::State::extended_states": work + "/extended_states",
        "Dir::Cache": work + "/cache", "Dir::Cache::archives": work + "/cache/archives",
        "Dir::Cache::pkgcache": "", "Dir::Cache::srcpkgcache": "", "Dir::Log": work + "/log",
        "APT::Architecture": "arm64", "APT::Install-Recommends": "false", "APT::Install-Suggests": "false",
        "Acquire::Languages::": "none", "Acquire::PDiffs": "false", "Acquire::Check-Date": "true",
        "Acquire::Check-Valid-Until": "true", "Acquire::AllowInsecureRepositories": "false",
        "Acquire::AllowWeakRepositories": "false", "Acquire::AllowDowngradeToInsecureRepositories": "false",
        "APT::Get::AllowUnauthenticated": "false", "APT::Architectures::": "arm64",
        "Acquire::IndexTargets::deb::Packages::MetaKey": "$(COMPONENT)/binary-$(ARCHITECTURE)/Packages",
        "Acquire::IndexTargets::deb::Packages::ShortDescription": "Packages",
        "Acquire::IndexTargets::deb::Packages::Description": "$(RELEASE)/$(COMPONENT) $(ARCHITECTURE) Packages",
    }


def apt_work(initialization):
    """APT owns a fresh child of the already initialized, charged WORK root."""
    return initialization["objects"]["work"]["path"] + "/apt"


def tool_argv(label, initialization):
    root = initialization["readonly_input"]["path"]
    work = apt_work(initialization)
    if label in ("native-arch", "foreign-arch"):
        return ["/usr/bin/dpkg", "--print-architecture" if label == "native-arch" else "--print-foreign-architectures"]
    if label.startswith("owner-"):
        return ["/usr/bin/dpkg-query", "-S", "/usr/bin/" + label[6:]]
    if label.startswith("version-"):
        return ["/usr/bin/dpkg-query", "-W", "-f=${Version}\\n", apt.TOOLS[label[8:]]]
    if label.startswith(("key-", "verify-")):
        name = label.split("-", 1)[1]
        release, _, key = apt.source_paths(apt.SOURCES[name])
        if label.startswith("key-"):
            return ["/usr/bin/gpg", "--no-options", "--batch", "--no-autostart", "--disable-dirmngr", "--homedir",
                    work + "/gnupg", "--with-colons", "--with-fingerprint", "--with-subkey-fingerprint", "--show-keys", root + "/" + key]
        return ["/usr/bin/sqv", "--keyring", root + "/" + key, "--signatures", "1", "--cleartext", "--output",
                work + "/verified/" + name + ".Release", root + "/" + release]
    if label == "apt-config":
        return ["/usr/bin/apt-config", "dump"]
    if label == "apt-update":
        return ["/usr/bin/apt-get", "--error-on=any", "update"]
    return ["/usr/bin/apt-get", "-s", "--no-download", "--no-install-recommends", "--no-remove", "-o",
            "APT::Install-Suggests=false", "install"] + [name + "=" + version for name, version in apt.ROOTS.items()]


def validate_tools(report, contract, blobs, now):
    """Bind fixed native-tool claims to raw streams and authenticated-chain claims.

    OpenPGP is deliberately not implemented. Parsed Release/Packages linkage
    is conditional on the caller's unverified claim of native authentication.
    Baseline databases remain in the guest; only frozen fingerprints cross.
    """
    steps = report["tools"]
    require(type(steps) is list and len(steps) <= len(apt.STEP_LABELS), "tool step sequence bound")
    manifest = apt.validate_manifest(blobs["manifest"].decode(), contract["nonce"])
    initialization = decode(blobs["plan"])
    projection = report["apt_projection"]
    if projection is not None:
        fields(projection, "status installed added settings", "guest-derived APT projection")
        require(same(projection["status"], manifest["baseline"]["status"]), "projection must bind raw guest status, never inventory TSV")
        require(type(projection["installed"]) is dict and len(projection["installed"]) <= 8192 and
                all(type(k) is str and re.fullmatch(r"[a-z0-9][a-z0-9+.-]*:(?:arm64|all)", k) and apt.version(v)
                    for k, v in projection["installed"].items()), "bounded guest-derived installed projection")
        settings = apt_settings(initialization["readonly_input"]["path"], apt_work(initialization))
        require(same(projection["settings"], settings), "exact isolated APT effective settings")
    elif report["outcome"] == "success":
        raise ValueError("success requires guest-derived APT semantic projection")
    failed, previous_end, diagnostics = False, 0, []
    for index, step in enumerate(steps):
        require(not failed, "business tools cannot continue after first failed tool")
        fields(step, "label tool tool_identity inputs argv cwd env stdout stderr original_bytes truncated exit_code signal_code complete reaped begin end", "tool step")
        label = apt.STEP_LABELS[index]
        require(step["label"] == label and step["tool"] in apt.TOOLS, "fixed tool sequence/name")
        tool = "dpkg" if label in ("native-arch", "foreign-arch") else "dpkg-query" if label.startswith(("owner-", "version-")) else "gpg" if label.startswith("key-") else "sqv" if label.startswith("verify-") else "apt-config" if label == "apt-config" else "apt-get"
        require(step["tool"] == tool and step["tool_identity"] == contract["external"]["guest-" + tool], "exact tool binary identity")
        require(same(step["argv"], tool_argv(label, initialization)), "exact read-only/simulation argv required")
        work = apt_work(initialization)
        require(step["cwd"] == work and same(step["env"], dict(PATH="/usr/bin:/bin", LANG="C", LC_ALL="C", HOME=work + "/home",
                TMPDIR=work + "/tmp", APT_CONFIG=work + "/apt.conf")), "exact isolated tool cwd/environment")
        require(same(step["inputs"], dict(manifest=contract["inputs"]["manifest"],
                baseline=manifest["baseline"], files=manifest["files"])), "complete tool input fingerprints")
        fields(step["original_bytes"], "stdout stderr", "original stream lengths")
        fields(step["truncated"], "stdout stderr", "stream truncation")
        for stream in ("stdout", "stderr"):
            require(type(step[stream]) is str and step[stream] in report["artifacts"], "original tool stream required")
            retained = len(blobs[step[stream]])
            integer(step["original_bytes"][stream], "original stream length", retained, 7 * apt.MIB)
            require(type(step["truncated"][stream]) is bool and
                    step["truncated"][stream] == (step["original_bytes"][stream] != retained), "raw stream truncation/retention mismatch")
            require(retained <= (apt.RESULT_LIMIT if stream == "stdout" else 65536), "native stream byte ceiling")
            failed |= step["truncated"][stream]
        require(type(step["exit_code"]) is int and 0 <= step["exit_code"] <= 255 and
                type(step["signal_code"]) is int and step["signal_code"] >= 0 and
                type(step["complete"]) is bool and type(step["reaped"]) is bool, "tool exit/completeness/reap state")
        number(step["begin"], "tool.begin", previous_end)
        number(step["end"], "tool.end", step["begin"])
        active = report["phase_windows"]["active"]
        require(active["begin"] <= step["begin"] <= step["end"] <= active["end"], "tool outside active window")
        execute = [e for e in report["events"] if e["name"] == "execute_once"]
        result = [e for e in report["events"] if e["name"] == "guest_result"]
        require(len(execute) == len(result) == 1 and execute[0]["end"] <= step["begin"] <= step["end"] <= result[0]["begin"], "tool outside single execute/result interval")
        previous_end = step["end"]
        failed |= step["exit_code"] != 0 or step["signal_code"] != 0 or not step["complete"] or not step["reaped"]
        semantic_error, semantic_error_truncated = None, False
        if not failed:
            try:
                validate_tool_output(label, step, blobs, manifest, projection)
            except ValueError as exc:
                # A malformed *claim* is rejected above. Native tool failure
                # and an unsuccessful solver output are valid failed evidence.
                failed = True
                error_bytes = str(exc).encode("utf-8")
                semantic_error = error_bytes[:768].decode("utf-8", errors="ignore")
                semantic_error_truncated = len(error_bytes) > len(semantic_error.encode("utf-8"))
        if failed:
            # At most one tool diagnostic: subsequent business steps are
            # forbidden above. Preserve the derived cause separately from
            # the caller's first_error and from cleanup failures.
            diagnostics.append(dict(label=label, exit_code=step["exit_code"], signal_code=step["signal_code"],
                complete=step["complete"], reaped=step["reaped"], truncated=dict(step["truncated"]),
                original_bytes=dict(step["original_bytes"]),
                retained_bytes={stream: len(blobs[step[stream]]) for stream in ("stdout", "stderr")},
                semantic_error=semantic_error, semantic_error_truncated=semantic_error_truncated))
    require(type(report["release_chains"]) is dict and set(report["release_chains"]) <= set(apt.SOURCES), "unknown Release chain")
    for name, row in report["release_chains"].items():
        fields(row, "inrelease key authenticated_release compressed packages by_hash valid_until verifier_stdout verifier_stderr", "release chain")
        release_path, index_path, key_path = apt.source_paths(apt.SOURCES[name])
        require(row["inrelease"] == manifest["files"][release_path] and row["key"] == manifest["files"][key_path] and
                row["compressed"] == manifest["files"][index_path], "signed input/key/index chain mismatch")
        digest = row["compressed"]["sha256"]
        require(row["by_hash"] == index_path.rsplit("/", 1)[0] + "/by-hash/SHA256/" + digest, "by-hash exact index identity")
        integer(row["valid_until"], "Release valid_until", now + 1)
        release = row["authenticated_release"]
        require(type(release) is str and release in report["artifacts"], "raw authenticated Release claim missing")
        compressed, packages = apt.release_index(blobs[release], apt.SOURCES[name], datetime.datetime.fromtimestamp(now, datetime.timezone.utc))
        require(compressed == row["compressed"] and packages == row["packages"], "authenticated Release/Packages SHA256/length mismatch")
        parsed = list(apt.deb822(blobs[release]))[0]
        require("Valid-Until" in parsed and int(apt.email.utils.parsedate_to_datetime(parsed["Valid-Until"]).timestamp()) == row["valid_until"], "expiry must come from exact Release bytes")
        verify = [x for x in steps if x["label"] == "verify-" + name]
        if verify:
            require(row["verifier_stdout"] == verify[0]["stdout"] and row["verifier_stderr"] == verify[0]["stderr"], "native verifier raw stream chain")
        elif report["outcome"] == "success":
            raise ValueError("success missing native verifier evidence")
    if report["outcome"] == "success":
        require(len(steps) == len(apt.STEP_LABELS) and set(report["release_chains"]) == set(apt.SOURCES), "success missing native tool steps/chains")
    return dict(failed=failed, diagnostics=diagnostics)


def validate_tool_output(label, step, blobs, manifest, projection):
    stdout = blobs[step["stdout"]]
    if label == "native-arch":
        require(stdout == b"arm64\n", "native architecture raw stdout")
    if label == "foreign-arch":
        require(stdout == b"", "foreign architecture raw stdout")
    if label.startswith("key-"):
        apt.key_fingerprints(stdout, apt.SOURCES[label[4:]][5])
    if label.startswith("owner-"):
        name = label[6:]
        require(stdout == f"{apt.TOOLS[name]}: /usr/bin/{name}\n".encode(), "raw tool owner evidence")
    if label.startswith("version-"):
        require(stdout == (manifest["baseline"]["tools"][label[8:]]["version"] + "\n").encode(), "raw tool version evidence")
    if label == "apt-config":
        require(projection is not None, "APT config missing semantic projection")
        apt.validate_config_dump(stdout, projection["settings"])
    if label == "apt-simulate":
        require(projection is not None and same(apt.simulation(stdout, projection["installed"]), projection["added"]), "native solver raw stdout/projection mismatch")
    if not label.startswith(("key-", "verify-")):
        require(blobs[step["stderr"]] == b"", "unexpected native tool stderr")


def malformed_as_value_error(function):
    def validate(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (KeyError, TypeError, AttributeError, IndexError, UnicodeError, OverflowError) as exc:
            raise ValueError("malformed candidate input: " + str(exc)) from exc
    return validate


validate_sources = malformed_as_value_error(validate_sources)
validate_contract = malformed_as_value_error(validate_contract)
validate_evidence = malformed_as_value_error(validate_evidence)
