"""Offline preparation contracts and staged verification; no standalone CLI.

The public guest/UTM entry remains closed until preparation isolation exists.
The staged executor requires an injected runner; tests use synthetic tools.
This module implements neither OpenPGP nor Debian dependency resolution.
"""

import email.utils
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
import zlib

MIB = 1024 * 1024
UUID = "B86E1A47-9A67-4ECF-A51F-2B2F29CDB726"
SCOPE = "guest-preparation-apt"
STOP = "I5_PREPARATION_ISOLATION_REQUIRED"
RESULT_LIMIT = 2 * MIB
TRANSPORT_LIMIT = 6 * MIB
GUEST_SECONDS = 540
ADAPTER_SECONDS = 600
HOST_SECONDS = 620
SOURCES = {
    "debian": ("debian", "trixie", "main", "xz", "debian-archive-13", "04B54C3CDCA79751B16BC6B5225629DF75B188BD"),
    "updates": ("debian", "trixie-updates", "main", "xz", "debian-archive-13", "04B54C3CDCA79751B16BC6B5225629DF75B188BD"),
    "security": ("security", "trixie-security", "main", "xz", "debian-security-13", "5E04A1E3223A19A20706E20F9904613D4CCE68C6"),
    "docker": ("docker", "trixie", "stable", "gz", "docker", "9DC858229FC7DD38854AE2D88D81803C0EBFCD88"),
}
ROOTS = {
    "docker-ce:arm64": "5:29.8.2-1~debian.13~trixie",
    "docker-ce-cli:arm64": "5:29.8.2-1~debian.13~trixie",
    "containerd.io:arm64": "2.3.6-1~debian.13~trixie",
    "docker-buildx-plugin:arm64": "0.37.1-1~debian.13~trixie",
    "git:arm64": "1:2.47.3-0+deb13u1", "iptables:arm64": "1.8.11-2",
}
TOOLS = {"gpg": "gpg", "sqv": "sqv", "apt-get": "apt", "apt-config": "apt",
         "dpkg": "dpkg", "dpkg-query": "dpkg"}
BASE_PATHS = {"status": "/var/lib/dpkg/status", "extended_states": "/var/lib/apt/extended_states",
              "crypto_policy": "/etc/crypto-policies/back-ends/sequoia.config"}
STEP_LABELS = ("native-arch", "foreign-arch") + tuple(
    label + name for name in TOOLS for label in ("owner-", "version-")) + tuple(
    label + name for name in SOURCES for label in ("key-", "verify-")) + ("apt-config", "apt-update", "apt-simulate")


def require(value, message):
    if not value:
        raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field: " + key)
        result[key] = value
    return result


def decode(raw, limit=RESULT_LIMIT):
    require(len(raw) <= limit, "JSON byte limit")
    def constant(_):
        raise ValueError("nonfinite JSON value")
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except RecursionError as exc:
        raise ValueError("JSON nesting limit") from exc


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()), "unknown or missing fields")


def digest(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def blob(value, limit):
    fields(value, "bytes sha256")
    require(type(value["bytes"]) is int and 0 < value["bytes"] <= limit and digest(value["sha256"]),
            "invalid bounded blob")


def source_paths(spec):
    repo, suite, component, codec, key, _ = spec
    base = f"{repo}/dists/{suite}"
    index = f"{base}/{component}/binary-arm64/Packages.{codec}"
    return f"{base}/InRelease", index, f"keys/{key}.asc"


def validate_manifest(raw, nonce):
    value = decode(raw, 64 * 1024)
    fields(value, "schema_version scope nonce uuid files baseline install_authorized i5_ready")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["scope"] == "i5-preparation-apt-input" and value["uuid"] == UUID and
            re.fullmatch("[0-9a-f]{32}", nonce) is not None and value["nonce"] == nonce,
            "manifest scope/schema/nonce/UUID mismatch")
    require(value["install_authorized"] is False and value["i5_ready"] is False, "preparation only")
    expected = {p for spec in SOURCES.values() for p in source_paths(spec)}
    require(type(value["files"]) is dict and set(value["files"]) == expected, "exact source whitelist required")
    for path, record in value["files"].items():
        blob(record, 64 * MIB if path.endswith((".xz", ".gz")) else MIB)
    require(sum(v["bytes"] for v in value["files"].values()) <= 128 * MIB,
            "input budget including by-hash copies exceeds 256 MiB")
    baseline = value["baseline"]
    fields(baseline, "status extended_states crypto_policy architecture foreign_architectures tools")
    blob(baseline["status"], 16 * MIB)
    for name in ("extended_states", "crypto_policy"):
        if baseline[name] is not None:
            blob(baseline[name], MIB)
    require(baseline["architecture"] == "arm64" and baseline["foreign_architectures"] == [],
            "native arm64 without foreign architectures required")
    require(type(baseline["tools"]) is dict and set(baseline["tools"]) == set(TOOLS), "tool baseline required")
    for name, record in baseline["tools"].items():
        fields(record, "package version sha256")
        require(record["package"] == TOOLS[name] and version(record["version"]) and digest(record["sha256"]),
                "tool ownership/version/hash binding required")
    return value


def version(value):
    return type(value) is str and len(value) <= 256 and re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", value) is not None


def regular(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and stat.S_ISREG(path.lstat().st_mode),
            "regular canonical file required: " + str(path))
    return path


def file_blob(path, limit):
    path = regular(path)
    size, h = 0, hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            size += len(chunk)
            require(size <= limit, "file byte limit: " + str(path))
            h.update(chunk)
    return {"bytes": size, "sha256": h.hexdigest()}


def read_bounded(path, limit):
    with regular(path).open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "file read limit")
    return data


def check_inputs(root, manifest):
    root = Path(root)
    require(root.is_absolute() and root.resolve() == root and root.is_dir(), "canonical input root required")
    expected = dict(manifest["files"])
    for spec in SOURCES.values():
        _, index, _ = source_paths(spec)
        item = expected[index]
        expected[str(Path(index).parent / "by-hash/SHA256" / item["sha256"])] = item
    # No alternate source files, devices, symlinks or unaccounted data on media.
    actual = set()
    directories = {str(parent) for name in expected for parent in Path(name).parents if str(parent) != "."}
    for path in root.rglob("*"):
        require(not path.is_symlink(), "symlink on input media")
        relative = str(path.relative_to(root))
        if path.is_dir():
            require(relative in directories, "input media directory set mismatch")
        else:
            require(relative in expected, "input media file set mismatch")
            actual.add(relative)
    require(actual == set(expected), "input media file set mismatch")
    for path, item in expected.items():
        require(file_blob(root / path, item["bytes"]) == item, "input digest mismatch: " + path)


def run_bounded(argv, *, cwd, env, timeout, stdout_limit=RESULT_LIMIT, stderr_limit=65536,
                cancelled=lambda: False, cleanup_seconds=2):
    """Stream budgets precede storage. Process group control is not a sandbox.

    A setsid escape needs the future cgroup/namespace boundary. Unconfirmed
    group cleanup (including unreaped descendants) is always a failure.
    """
    require(timeout > 0 and stdout_limit >= 0 and stderr_limit >= 0, "invalid execution budget")
    result = {"exit_code": None, "stdout": b"", "stderr": b"", "failure": None, "cleanup_errors": []}
    if cancelled():
        result["failure"] = "cancelled"
        return result
    deadline = time.monotonic() + timeout
    process, poller = None, selectors.DefaultSelector()
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": stdout_limit, "stderr": stderr_limit}
    previous_handlers, interrupted = {}, []
    def interrupt(number, _frame):
        if not interrupted:
            interrupted.append(number)
    try:
        # Keep the wrapper alive long enough to reap its group on normal
        # cancellation. SIGKILL/setsid escapes still require external isolation.
        for number in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[number] = signal.signal(number, interrupt)
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True, close_fds=True)
        for name in buffers:
            stream = getattr(process, name)
            os.set_blocking(stream.fileno(), False)
            poller.register(stream, selectors.EVENT_READ, name)
        while poller.get_map() or process.poll() is None:
            if interrupted or cancelled():
                result["failure"] = "cancelled-signal-" + str(interrupted[0]) if interrupted else "cancelled"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["failure"] = "deadline"
                break
            for key, _ in poller.select(min(remaining, 0.05)):
                name = key.data
                budget = limits[name] - len(buffers[name])
                chunk = os.read(key.fd, min(65536, budget + 1))
                if not chunk:
                    poller.unregister(key.fileobj)
                elif len(chunk) > budget:
                    buffers[name].extend(chunk[:budget])
                    result["failure"] = name + "-limit"
                    break
                else:
                    buffers[name].extend(chunk)
            if result["failure"]:
                break
    except (OSError, KeyboardInterrupt) as exc:
        result["failure"] = type(exc).__name__ + ": " + str(exc)
    finally:
        if process is not None:
            # Also kill descendants after a successful leader exit, even if
            # they closed both pipes. Never signal the caller's process group.
            leader_exited = process.poll() is not None
            try:
                os.killpg(process.pid, 0)
                if leader_exited and not result["failure"]:
                    result["failure"] = "descendants-remained"
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                result["cleanup_errors"].append(str(exc))
            try:
                result["exit_code"] = process.wait(timeout=cleanup_seconds)
            except subprocess.TimeoutExpired:
                result["cleanup_errors"].append("leader wait timeout")
            until = time.monotonic() + cleanup_seconds
            while True:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    break
                except OSError as exc:
                    result["cleanup_errors"].append(str(exc))
                    break
                if time.monotonic() >= until:
                    result["cleanup_errors"].append("process group still present")
                    break
                time.sleep(0.02)
            for stream in (process.stdout, process.stderr):
                stream.close()
        poller.close()
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)
    if interrupted and not result["failure"]:
        result["failure"] = "cancelled-signal-" + str(interrupted[0])
    result.update({name: bytes(data) for name, data in buffers.items()})
    return result


def key_fingerprints(raw, expected):
    primary, subkeys, pending = [], [], None
    for line in raw.decode("utf-8").splitlines():
        row = line.split(":")
        if row[0] in {"pub", "sub"}:
            require(pending is None, "missing full fingerprint")
            pending = row[0]
        elif row[0] == "fpr":
            require(pending is not None and len(row) > 9 and re.fullmatch("[0-9A-F]{40}", row[9]),
                    "invalid full fingerprint")
            (primary if pending == "pub" else subkeys).append(row[9])
            pending = None
        elif row[0] not in {"uid", "uat", "tru", "grp", "rvk"}:
            raise ValueError("unknown key listing record")
    require(pending is None and primary == [expected] and len(set(subkeys)) == len(subkeys),
            "wrong or multiple primary certificates")
    return {"primary": primary[0], "subkeys": subkeys}


def deb822(raw):
    """Only field framing; dependency/version semantics remain with APT."""
    record, last = {}, None
    for line in raw.decode("utf-8").splitlines():
        if not line:
            if record:
                yield record
            record, last = {}, None
        elif line.startswith((" ", "\t")):
            require(last is not None, "orphan continuation")
            record[last] += "\n" + line[1:]
        else:
            name, sep, value = line.partition(":")
            require(sep and re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", name) and name not in record,
                    "invalid/duplicate deb822 field")
            record[name], last = value.strip(), name
    if record:
        yield record


def release_index(raw, spec, now):
    records = list(deb822(raw))
    require(len(records) == 1, "single authenticated Release required")
    release = records[0]
    identity_field = "Suite" if spec[0] == "docker" else "Codename"
    require(release.get(identity_field) == spec[1] and "arm64" in release.get("Architectures", "").split() and
            spec[2] in release.get("Components", "").split(), "Release source identity mismatch")
    def date(name):
        parsed = email.utils.parsedate_to_datetime(release[name])
        require(parsed.tzinfo is not None, "Release timezone required")
        return parsed
    require(date("Date") <= now, "future Release")
    if spec[1] in {"trixie-updates", "trixie-security"}:
        require("Valid-Until" in release, "Release expiry required")
    if "Valid-Until" in release:
        require(date("Date") < date("Valid-Until") and now < date("Valid-Until"), "expired Release")
    hashes = {}
    for line in release.get("SHA256", "").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        require(len(parts) == 3 and digest(parts[0]) and parts[1].isdigit() and parts[2] not in hashes,
                "invalid/duplicate Release SHA256 entry")
        hashes[parts[2]] = {"sha256": parts[0], "bytes": int(parts[1])}
    prefix = f"{spec[2]}/binary-arm64/Packages"
    require(prefix in hashes and prefix + "." + spec[3] in hashes, "missing complete Packages hashes")
    blob(hashes[prefix], 64 * MIB)
    return hashes[prefix + "." + spec[3]], hashes[prefix]


def unpacked_blob(path, codec, limit, checkpoint=lambda: None):
    decoder = lzma.LZMADecompressor(memlimit=64 * MIB) if codec == "xz" else zlib.decompressobj(31)
    size, h = 0, hashlib.sha256()
    with regular(path).open("rb") as stream:
        while chunk := stream.read(65536):
            require(not decoder.eof, "trailing compressed stream")
            while True:
                checkpoint()
                output = decoder.decompress(chunk, max_length=min(65536, limit - size + 1))
                size += len(output)
                require(size <= limit, "uncompressed index limit")
                h.update(output)
                if decoder.eof:
                    require(not decoder.unused_data, "trailing compressed bytes")
                    break
                if codec == "xz":
                    if decoder.needs_input:
                        break
                    chunk = b""
                else:
                    chunk = decoder.unconsumed_tail
                    if not chunk:
                        break
    require(decoder.eof, "truncated compressed index")
    return {"bytes": size, "sha256": h.hexdigest()}


def installed_packages(raw):
    result = {}
    for row in deb822(raw):
        status_value = row.get("Status", "")
        require(status_value in {"install ok installed", "deinstall ok config-files", "purge ok not-installed"},
                "unsettled dpkg status")
        if status_value != "install ok installed":
            continue
        name, arch, ver = row.get("Package", ""), row.get("Architecture"), row.get("Version")
        require(len(name) <= 200 and re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", name) and
                arch in {"arm64", "all"} and version(ver),
                "invalid installed package")
        identity = name + ":" + ("arm64" if arch == "all" else arch)
        require(identity not in result, "duplicate installed package")
        result[identity] = ver
        require(len(result) <= 8192, "installed package count limit")
    require(result, "empty installed baseline")
    return result


def apt_files(input_root, work, installed):
    for path in (input_root, work):
        require(re.fullmatch(r"/[A-Za-z0-9_./-]+", str(path)) and path.resolve() == path,
                "safe canonical APT path required")
    pins = dict(installed)
    for name, ver in ROOTS.items():
        require(name not in pins or pins[name] == ver, "requested root would change installed package")
        pins[name] = ver
    preferences = "".join(f"Package: {name}\nPin: version {ver}\nPin-Priority: 1001\n\n"
                          f"Package: {name}\nPin: version *\nPin-Priority: -1\n\n"
                          for name, ver in sorted(pins.items()))
    sources = "".join(f"deb [arch=arm64 signed-by={input_root}/keys/{key}.asc] "
                      f"file:{input_root}/{repo} {suite} {component}\n"
                      for repo, suite, component, _, key, _ in SOURCES.values())
    settings = {
        "Dir::Etc::main": "/dev/null", "Dir::Etc::parts": str(work / "empty"),
        "Dir::Etc::sourcelist": str(work / "sources.list"), "Dir::Etc::sourceparts": str(work / "empty"),
        "Dir::Etc::preferences": str(work / "preferences"), "Dir::Etc::preferencesparts": str(work / "empty"),
        "Dir::Etc::trusted": "/dev/null", "Dir::Etc::trustedparts": str(work / "empty"),
        "Dir::Etc::netrc": "/dev/null", "Dir::Etc::netrcparts": str(work / "empty"),
        "Dir::State": str(work / "state"), "Dir::State::lists": str(work / "state/lists"),
        "Dir::State::status": str(work / "status"), "Dir::State::extended_states": str(work / "extended_states"),
        "Dir::Cache": str(work / "cache"), "Dir::Cache::archives": str(work / "cache/archives"),
        "Dir::Cache::pkgcache": "", "Dir::Cache::srcpkgcache": "", "Dir::Log": str(work / "log"),
        "APT::Architecture": "arm64", "APT::Install-Recommends": "false", "APT::Install-Suggests": "false",
        "Acquire::Languages::": "none", "Acquire::PDiffs": "false", "Acquire::Check-Date": "true",
        "Acquire::Check-Valid-Until": "true", "Acquire::AllowInsecureRepositories": "false",
        "Acquire::AllowWeakRepositories": "false", "Acquire::AllowDowngradeToInsecureRepositories": "false",
        "APT::Get::AllowUnauthenticated": "false", "APT::Architectures::": "arm64",
        "Acquire::IndexTargets::deb::Packages::MetaKey": "$(COMPONENT)/binary-$(ARCHITECTURE)/Packages",
        "Acquire::IndexTargets::deb::Packages::ShortDescription": "Packages",
        "Acquire::IndexTargets::deb::Packages::Description": "$(RELEASE)/$(COMPONENT) $(ARCHITECTURE) Packages",
    }
    config = "".join(f"#clear {key};\n" for key in ("Binary", "APT::Update", "DPkg::Pre-Install-Pkgs",
                      "DPkg::Pre-Invoke", "DPkg::Post-Invoke", "DPkg::Options", "Acquire::IndexTargets", "Acquire::Languages",
                      "APT::Architectures"))
    config += "".join(f'{key} "{value}";\n' for key, value in settings.items())
    files = {"sources.list": sources, "preferences": preferences, "apt.conf": config}
    require(sum(len(v.encode()) for v in files.values()) <= MIB, "generated configuration byte limit")
    return files, settings


def validate_config_dump(raw, settings):
    parsed = {}
    for line in raw.decode().splitlines():
        match = re.fullmatch(r'([A-Za-z0-9/.:_+\-]+) "([^"\\]*)";', line)
        require(match is not None, "unexpected apt-config dump syntax")
        key, value = match.groups()
        key = key.lower()
        require(key not in parsed, "duplicate apt-config key")
        parsed[key] = value
        require(not value or not (key.startswith("binary::") or
                key.startswith("dpkg::options") or re.search(r"(?:pre|post)-invoke|pre-install-pkgs", key)),
                "APT hook/Binary override")
        require(not value or not re.search(r"(?:^|::)(?:proxy|proxy-auto-detect|proxyautodetect)(?:$|::)", key),
                "APT proxy override")
        if key.startswith("acquire::indextargets::") and value:
            require(key in {k.lower() for k in settings if k.startswith("Acquire::IndexTargets::")},
                    "unexpected APT index target")
    for key, value in settings.items():
        require(parsed.get(key.lower()) == value, "effective APT config mismatch: " + key)


def simulation(raw, installed):
    added, configured, summary = {}, {}, None
    for line in raw.decode().splitlines():
        if line.startswith(("Remv ", "Purg ", "E:", "W:")):
            raise ValueError("APT removal/error/warning")
        if line.startswith(("Inst ", "Conf ")):
            match = re.fullmatch(r"(Inst|Conf) ([a-z0-9][a-z0-9+.-]+)(?::(arm64|all))? \(([^ ]+) .+ \[(arm64|all)\]\)", line)
            require(match is not None, "unsupported APT transaction record")
            action, name, _, ver, _ = match.groups()
            identity = name + ":arm64"
            require(identity not in installed and version(ver), "APT changes existing package")
            target = added if action == "Inst" else configured
            require(identity not in target, "duplicate APT action")
            target[identity] = ver
        elif re.match(r"[0-9]+ upgraded,", line):
            require(summary is None, "duplicate APT summary")
            match = re.fullmatch(r"0 upgraded, ([0-9]+) newly installed, 0 to remove and [0-9]+ not upgraded\.", line)
            require(match is not None, "APT non-additive transaction")
            summary = int(match[1])
    require(summary == len(added) and configured == added, "incomplete APT transaction")
    for name, ver in ROOTS.items():
        require(added.get(name, installed.get(name)) == ver, "missing exact requested root")
    return added


def blocked_result(nonce, manifest_sha256):
    return {"schema_version": 1, "scope": SCOPE, "nonce": nonce, "uuid": UUID,
            "manifest_sha256": manifest_sha256, "i5_ready": False, "install_authorized": False,
            "passed": False, "signature_verified": False, "apt_resolved": False,
            "failure": STOP, "evidence_kind": "blocked", "steps": [], "added": {}}


def validate_result(raw, nonce, manifest_sha256):
    result = decode(raw)
    fields(result, "schema_version scope nonce uuid manifest_sha256 i5_ready install_authorized passed "
           "signature_verified apt_resolved failure evidence_kind steps added")
    require(type(result["schema_version"]) is int and result["schema_version"] == 1 and result["scope"] == SCOPE and
            type(nonce) is str and re.fullmatch("[0-9a-f]{32}", nonce) and result["nonce"] == nonce and
            result["uuid"] == UUID and digest(manifest_sha256) and
            result["manifest_sha256"] == manifest_sha256, "preparation result binding mismatch")
    # Only blocked public results and synthetic executor results exist in v1.
    require(result["i5_ready"] is False and result["install_authorized"] is False and
            result["signature_verified"] is False and result["apt_resolved"] is False and
            result["evidence_kind"] in {"blocked", "synthetic"}, "no real verification evidence in v1")
    require(type(result["passed"]) is bool and type(result["steps"]) is list and type(result["added"]) is dict,
            "invalid preparation result")
    require((result["passed"] and result["evidence_kind"] == "synthetic" and result["failure"] is None) or
            (not result["passed"] and type(result["failure"]) is str and bool(result["failure"])), "invalid result state")
    require(len(result["steps"]) <= 32, "step count limit")
    for step in result["steps"]:
        fields(step, "label exit_code failure cleanup_errors")
        require(type(step["label"]) is str and re.fullmatch(r"[a-z-]+", step["label"]) and
                (step["exit_code"] is None or type(step["exit_code"]) is int) and
                (step["failure"] is None or type(step["failure"]) is str) and
                type(step["cleanup_errors"]) is list and all(type(e) is str for e in step["cleanup_errors"]),
                "invalid step evidence")
    for name, ver in result["added"].items():
        require(re.fullmatch(r"[a-z0-9][a-z0-9+.-]+:arm64", name) and version(ver), "invalid added package")
    labels = tuple(s["label"] for s in result["steps"])
    require(labels == STEP_LABELS[:len(labels)], "stage evidence order mismatch")
    if result["evidence_kind"] == "blocked":
        require(result["failure"] == STOP and not result["steps"] and not result["added"], "invalid blocked result")
    if result["passed"]:
        require(labels == STEP_LABELS and
                all(s["exit_code"] == 0 and s["failure"] is None and not s["cleanup_errors"] for s in result["steps"]),
                "failed or missing step cannot pass")
    return result


def exercise_preparation(raw, nonce, input_root, work, *, runner, baseline_paths,
                         tool_paths, now, cancelled=lambda: False, evidence_root=None):
    """Execute staged orchestration against injected synthetic tools only.

    No production runner is wired here. v1 never reports cryptographic or APT
    evidence as real. Failures preserve each bounded tool result in WORK.
    """
    manifest = validate_manifest(raw, nonce)
    result = blocked_result(nonce, hashlib.sha256(raw).hexdigest())
    result.update(evidence_kind="synthetic", failure=None)
    deadline = time.monotonic() + GUEST_SECONDS
    def checkpoint():
        require(not cancelled(), "cancelled")
        require(time.monotonic() < deadline, "guest preparation deadline")
    def baseline_check():
        for name, path in baseline_paths.items():
            expected = manifest["baseline"][name]
            if expected is None:
                require(not Path(path).exists() and not Path(path).is_symlink(), "baseline presence changed: " + name)
            else:
                require(file_blob(path, 16 * MIB) == expected, "baseline changed: " + name)
        for name, path in tool_paths.items():
            require(file_blob(path, 64 * MIB)["sha256"] == manifest["baseline"]["tools"][name]["sha256"],
                    "tool binary changed: " + name)
    require(set(baseline_paths) == set(BASE_PATHS) and set(tool_paths) == set(TOOLS), "complete baseline paths required")
    work, input_root = Path(work), Path(input_root)
    require(work.is_absolute() and work.resolve() == work and not work.exists() and
            not work.is_relative_to(input_root) and not input_root.is_relative_to(work), "fresh disjoint workspace required")
    work.mkdir(mode=0o700)
    evidence = work if evidence_root is None else Path(evidence_root)
    require(evidence.is_absolute() and evidence.resolve(strict=True) == evidence and evidence.is_dir() and
            not evidence.is_relative_to(input_root) and not input_root.is_relative_to(evidence),
            "canonical disjoint evidence directory required")
    def save_evidence(name, data):
        # Fresh files only; no replacement of earlier evidence or symlink follow.
        fd = os.open(evidence / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                require(stream.write(data) == len(data), "evidence short write")
        finally:
            os.close(fd)
    env = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "HOME": str(work / "home"),
           "TMPDIR": str(work / "tmp"), "APT_CONFIG": str(work / "apt.conf")}
    retained = 0
    def command(label, argv, seconds=30):
        nonlocal retained
        checkpoint()
        # Reserve 1 MiB of the 8 MiB result candidate for framing/config. This
        # is an evidence budget, not WORK filesystem or memory isolation.
        remaining_bytes = 7 * MIB - retained
        require(remaining_bytes >= 65536, "aggregate tool evidence limit")
        out_limit = min(RESULT_LIMIT, remaining_bytes - 65536)
        output = runner(argv, cwd=work, env=dict(env), timeout=min(seconds, deadline - time.monotonic()),
                        stdout_limit=out_limit, stderr_limit=65536, cancelled=cancelled)
        for name in ("stdout", "stderr"):
            require(type(output[name]) is bytes and len(output[name]) <= (out_limit if name == "stdout" else 65536),
                    "runner stream contract violated")
            save_evidence(label + "." + name, output[name])
            retained += len(output[name])
        event = {k: output[k] for k in ("exit_code", "failure", "cleanup_errors")}
        event["label"] = label
        result["steps"].append(event)
        require(output["failure"] is None and not output["cleanup_errors"] and output["exit_code"] == 0,
                label + ": tool failed; inspect retained streams")
        require(not output["stderr"] or label.startswith(("key-", "verify-")),
                label + ": unexpected stderr; inspect retained stream")
        checkpoint()
        return output["stdout"]
    try:
        checkpoint()
        check_inputs(input_root, manifest)
        baseline_check()
        for name in ("home", "tmp", "gnupg", "verified", "empty", "state/lists/partial", "cache/archives/partial", "log"):
            (work / name).mkdir(parents=True, mode=0o700)
        require(command("native-arch", ["/usr/bin/dpkg", "--print-architecture"]) == b"arm64\n", "wrong native architecture")
        require(command("foreign-arch", ["/usr/bin/dpkg", "--print-foreign-architectures"]) == b"", "foreign architecture")
        for name, owner in TOOLS.items():
            expected = manifest["baseline"]["tools"][name]
            require(command("owner-" + name, ["/usr/bin/dpkg-query", "-S", "/usr/bin/" + name]) ==
                    f"{owner}: /usr/bin/{name}\n".encode(), "tool ownership mismatch")
            require(command("version-" + name, ["/usr/bin/dpkg-query", "-W", "-f=${Version}\\n", owner]) ==
                    (expected["version"] + "\n").encode(), "tool version mismatch")
        installed = installed_packages(read_bounded(baseline_paths["status"], 16 * MIB))
        for name in ("status", "extended_states"):
            data = b"" if manifest["baseline"][name] is None else read_bounded(baseline_paths[name], 16 * MIB)
            (work / name).write_bytes(data)
        generated, settings = apt_files(input_root, work, installed)
        for name, content in generated.items():
            (work / name).write_text(content)
        for name, spec in SOURCES.items():
            release, index, key = source_paths(spec)
            listing = command("key-" + name, ["/usr/bin/gpg", "--no-options", "--batch", "--no-autostart",
                      "--disable-dirmngr", "--homedir", str(work / "gnupg"), "--with-colons", "--with-fingerprint",
                      "--with-subkey-fingerprint", "--show-keys", str(input_root / key)])
            key_fingerprints(listing, spec[5])
            authenticated = work / "verified" / (name + ".Release")
            command("verify-" + name, ["/usr/bin/sqv", "--keyring", str(input_root / key), "--signatures", "1",
                    "--cleartext", "--output", str(authenticated), str(input_root / release)])
            compressed, unpacked = release_index(read_bounded(authenticated, MIB), spec, now())
            require(compressed == manifest["files"][index], "authenticated compressed index mismatch")
            require(unpacked_blob(input_root / index, spec[3], unpacked["bytes"], checkpoint) == unpacked,
                    "authenticated uncompressed index mismatch")
        dump = command("apt-config", ["/usr/bin/apt-config", "dump"])
        validate_config_dump(dump, settings)
        command("apt-update", ["/usr/bin/apt-get", "--error-on=any", "update"], 150)
        output = command("apt-simulate", ["/usr/bin/apt-get", "-s", "--no-download", "--no-install-recommends",
                         "--no-remove", "-o", "APT::Install-Suggests=false", "install",
                         *(name + "=" + ver for name, ver in ROOTS.items())], 150)
        result["added"] = simulation(output, installed)
        check_inputs(input_root, manifest)
        checkpoint()
        result["passed"] = True
    except (OSError, ValueError, RuntimeError, KeyError, lzma.LZMAError, zlib.error) as exc:
        result["failure"] = str(exc)
    finally:
        try:
            baseline_check()
        except (OSError, ValueError) as exc:
            result["failure"] = (result["failure"] + "; " if result["failure"] else "") + "postflight: " + str(exc)
        if result["failure"]:
            result["passed"] = False
    validate_result(json.dumps(result).encode(), nonce, result["manifest_sha256"])
    save_evidence("result.json", (json.dumps(result, indent=2) + "\n").encode())
    return result
