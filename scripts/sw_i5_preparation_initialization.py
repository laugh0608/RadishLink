"""Explicit synthetic initialization, fixed roles, and identity-bound cleanup.

This module has no native backend. MappedSyntheticGuest writes ordinary files
under an explicitly supplied temporary tree: guest uid/cgroup/readonly claims
are simulated metadata, never Linux isolation or execution authorization.
Only the supervised evidence worker calls filesystem methods below.
"""

import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import time

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels
import sw_i5_preparation_evidence as evidence
import sw_i5_preparation_isolation as isolation
import sw_i5_preparation_staging as staging


def identity(info):
    return [info.st_dev, info.st_ino]


def directory(path, *, uid=None, gid=None, mode=None):
    """Open every ancestor without following links, including intermediate ones."""
    path = Path(path)
    apt.require(path.is_absolute() and str(path) == str(path.absolute()) and ".." not in path.parts, "canonical initialization path")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in path.parts[1:]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        apt.require((uid is None or info.st_uid == uid) and (gid is None or info.st_gid == gid) and
                    (mode is None or stat.S_IMODE(info.st_mode) == mode), "initialization directory ownership/mode")
        return fd
    except BaseException:
        os.close(fd)
        raise


class SyntheticInitialization:
    def __init__(self, plan_raw, ledger_raw, jxa_source, *, guest_backend):
        # Delayed import: the pure review module imports lifecycle for its caps.
        import sw_i5_preparation_plan as plan
        apt.require(type(plan_raw) is bytes and type(ledger_raw) is bytes and type(jxa_source) is bytes,
                    "initialization immutable bytes required")
        declaration = plan.decode(plan_raw, "i5-review-initialization")
        reviewed = plan.review(plan_raw, ledger_raw, declaration["nonce"], declaration["manifest_sha256"])
        apt.require(declaration["kind"] == "synthetic" and plan.decode(ledger_raw, "capacity")["kind"] == "synthetic" and
                    reviewed["review_passed"], "synthetic initialization requires complete offline review; no execution authority")
        apt.require(declaration["jxa_source"] == evidence.fingerprint(jxa_source), "initialization exact JXA source binding")
        apt.require(type(guest_backend) is MappedSyntheticGuest, "explicit mapped synthetic guest backend required; no native backend")
        paths = [plan.lexical(str(path), "synthetic backend") for path in
                 (guest_backend.root, guest_backend.input, declaration["host_jxa_root"], declaration["host_evidence_parent"])]
        for index, left in enumerate(paths):
            for right in paths[index + 1:]:
                apt.require(left != right and left not in right.parents and right not in left.parents,
                            "mapped synthetic paths overlap host evidence/source/input")
        self.plan_raw, self.ledger_raw, self.jxa_source, self.guest_backend = plan_raw, ledger_raw, jxa_source, guest_backend
        self.value = declaration
        self.source_limit = plan.assembled_source_bound(len(jxa_source))

    def snapshot(self):
        return SyntheticInitialization(self.plan_raw, self.ledger_raw, self.jxa_source, guest_backend=self.guest_backend.snapshot())

    def facts(self):
        return dict(schema_version=1, scope="i5-synthetic-initialization", kind="synthetic", uuid=apt.UUID,
                    nonce=self.value["nonce"], manifest_sha256=self.value["manifest_sha256"],
                    plan_sha256=hashlib.sha256(self.plan_raw).hexdigest(), ledger_sha256=hashlib.sha256(self.ledger_raw).hexdigest(),
                    source_sha256=hashlib.sha256(self.jxa_source).hexdigest(), host_ready=False, guest_ready=False,
                    guest_cleanup="not-attempted", host_cleanup="not-attempted", objects={},
                    registry_sha256=hashlib.sha256(b"").hexdigest(), registrations=0, pending=0, pending_objects={},
                    authorized=False, install_authorized=False, physical_verified=False, i5_ready=False)


class MappedSyntheticGuest:
    """Ordinary temporary files; fixed virtual roles are never system paths.

    Input is an existing directory containing exactly payload.bin. Its digest
    and length are bound to the plan, and it is never modified or cleaned.
    """
    def __init__(self, root, readonly_input):
        self.root, self.input = str(root), str(readonly_input)
        self.metadata = {}
        self.limit_identities = {}
        self.pinned, self.limit_fds = {}, {}

    def snapshot(self):
        apt.require(type(self.root) is str and type(self.input) is str, "synthetic backend path snapshot")
        return MappedSyntheticGuest(self.root, self.input)

    def path(self, role):
        names = {"guest_root": "guest", "work": "guest/work", "result": "guest/result", "control": "guest/control",
                 "lease": "guest/control/lease.slot", "ack": "guest/control/ack.slot", "cgroup_parent": "cgroup",
                 "cgroup_supervisor": "cgroup/supervisor", "cgroup_worker": "cgroup/worker"}
        apt.require(role == "readonly_input" or role in names, "fixed synthetic guest role")
        return Path(self.input) if role == "readonly_input" else Path(self.root) / names[role]

    def create(self, role, spec):
        path = self.path(role)
        fd = directory(path.parent)
        try:
            if spec["kind"] == "regular":
                stream = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
                self.pinned[role] = stream
                self.metadata[role] = dict(spec)
                return identity(os.fstat(stream))
            os.mkdir(path.name, 0o700, dir_fd=fd)
            self.metadata[role] = dict(spec)
            self.pinned[role] = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            return identity(os.stat(path.name, dir_fd=fd, follow_symlinks=False))
        finally: os.close(fd)

    def populate(self, role, spec, expected):
        path = self.path(role)
        if spec["kind"] == "regular":
            parent = directory(path.parent)
            try:
                apt.require(identity(os.fstat(parent)) == identity(os.fstat(self.pinned["control"])), "synthetic control directory replaced")
                fd = os.open(path.name, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                try:
                    apt.require(identity(os.fstat(fd)) == expected, "synthetic slot changed before write")
                    apt.require(os.write(fd, bytes(1024)) == 1024, "short synthetic control slot write")
                finally: os.close(fd)
            finally: os.close(parent)
        elif role.startswith("cgroup_"):
            group = directory(path)
            try:
                apt.require(identity(os.fstat(group)) == expected == identity(os.fstat(self.pinned[role])), "synthetic cgroup directory replaced")
                for name, value in spec["limits"].items():
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=group)
                    self.limit_identities[(role, name)] = identity(os.fstat(fd))
                    self.limit_fds[(role, name)] = fd
                    apt.require(os.write(fd, value.encode()) == len(value), "short synthetic cgroup write")
            finally: os.close(group)

    def readback(self, role, spec, *, initial=False):
        path = self.path(role)
        fd = directory(path if spec["kind"] != "regular" else path.parent)
        try:
            info = os.fstat(fd) if spec["kind"] != "regular" else os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            apt.require(info.st_uid == os.getuid() and info.st_gid == os.getgid() and
                        stat.S_IMODE(info.st_mode) == (0o600 if spec["kind"] == "regular" else 0o700), "unsafe mapped synthetic object")
            apt.require(stat.S_ISREG(info.st_mode) if spec["kind"] == "regular" else stat.S_ISDIR(info.st_mode), "synthetic object type")
            if spec["kind"] == "regular":
                raw = evidence.read_file(fd, os.fstat(fd), path.name, 1024)
                apt.require(info.st_nlink == 1 and len(raw) == 1024 and (not initial or raw == bytes(1024)), "synthetic slot readback")
            if role == "readonly_input":
                apt.require(set(os.listdir(fd)) == {"payload.bin"}, "fixed synthetic input tree")
                raw = evidence.read_file(fd, info, "payload.bin", isolation.STORAGE["input"])
                apt.require(evidence.fingerprint(raw) == {"bytes": spec["bytes"], "sha256": spec["sha256"]}, "readonly input bytes changed")
            if role.startswith("cgroup_"):
                kind = role.removeprefix("cgroup_")
                limits = {name: evidence.read_file(fd, info, name, 64).decode() for name in isolation.LIMITS[kind]}
                children = sorted(name for name in os.listdir(fd) if stat.S_ISDIR(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode))
                isolation.verify_cgroup(dict(path=spec["path"], identity=tuple(identity(info)), type="domain", procs=[],
                    subtree="cpu memory pids" if kind == "parent" else "", children=children, limits=limits,
                    events=dict(populated=0, frozen=0), memory_events=dict(max=0, oom=0, oom_kill=0, oom_group_kill=0),
                    pids_events=dict(max=0)), kind)
            return identity(info)
        finally: os.close(fd)

    def remove(self, role, spec, expected):
        path = self.path(role)
        fd = directory(path.parent)
        try:
            info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            apt.require(identity(info) == expected and info.st_uid == os.getuid() and
                        role in self.pinned and identity(os.fstat(self.pinned[role])) == expected and
                        (stat.S_ISREG(info.st_mode) if spec["kind"] == "regular" else stat.S_ISDIR(info.st_mode)),
                        "synthetic cleanup identity mismatch")
            if role.startswith("cgroup_"):
                group = directory(path)
                try:
                    apt.require(set(os.listdir(group)) == set(spec["limits"]), "unexpected synthetic cgroup cleanup entry")
                    for name in spec["limits"]:
                        entry = os.stat(name, dir_fd=group, follow_symlinks=False)
                        apt.require(identity(entry) == self.limit_identities.get((role, name)) and
                                    stat.S_ISREG(entry.st_mode) and entry.st_nlink == 1 and entry.st_uid == os.getuid(),
                                    "synthetic cgroup limit replaced")
                    for name in spec["limits"]:
                        os.unlink(name, dir_fd=group)
                        os.close(self.limit_fds.pop((role, name)))
                finally: os.close(group)
            if spec["kind"] == "regular": os.unlink(path.name, dir_fd=fd)
            else: os.rmdir(path.name, dir_fd=fd)
            os.close(self.pinned.pop(role))
        finally: os.close(fd)

    def close(self):
        for mapping in (self.pinned, self.limit_fds):
            for fd in mapping.values(): os.close(fd)
            mapping.clear()


class InitializationWorker:
    def __init__(self, config, register):
        self.config, self.value, self.register = config, config.value, register
        self.root_fd, self.parent_fd, self.root_identity = None, None, None
        self.entries, self.sequence, self.source, self.source_fd = {}, -1, None, None

    def event(self, role, state, ident=None, size=0):
        value = dict(role=role, state=state, identity=ident, bytes=size, sequence=self.sequence if role == "source" else None)
        if state == "intent":
            apt.require(role not in self.entries, "initialization duplicate reservation")
            self.entries[role] = value
        elif state == "bound":
            apt.require(role in self.entries and self.entries[role]["state"] == "intent", "initialization binding order")
            self.entries[role] = value
        elif state == "cleaned": self.entries.pop(role)
        self.register(value)

    def host(self, store):
        value = self.value
        fd = directory(value["host_evidence_parent"], uid=value["host_uid"], gid=value["host_gid"], mode=0o700)
        try:
            before = value["offline_observations"]["objects"]["host_evidence_parent"]["before"]
            apt.require(identity(os.fstat(fd)) == [before["dev"], before["ino"]], "evidence parent actual identity changed")
        finally: os.close(fd)
        store.verify_attempt()
        root = Path(value["host_jxa_root"])
        self.parent_fd = directory(root.parent, uid=value["host_uid"], gid=value["host_gid"], mode=0o700)
        self.event("host_jxa_root", "intent")
        os.mkdir(root.name, 0o700, dir_fd=self.parent_fd)
        self.root_fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.parent_fd)
        self.root_identity = identity(os.fstat(self.root_fd))
        self.event("host_jxa_root", "bound", self.root_identity)
        reopened = directory(root, uid=value["host_uid"], gid=value["host_gid"], mode=0o700)
        try: apt.require(identity(os.fstat(reopened)) == self.root_identity and not os.listdir(reopened), "JXA root independent readback")
        finally: os.close(reopened)
        return dict(host_jxa_root=self.root_identity, host_evidence_parent=[before["dev"], before["ino"]], host_attempt=list(store.identity))

    def guest(self):
        specs, backend = self.value["objects"], self.config.guest_backend
        rootfd = directory(backend.root, uid=os.getuid(), gid=os.getgid(), mode=0o700)
        os.close(rootfd)
        created = {}
        # Input binding is independently checked before any new guest write.
        created["readonly_input"] = backend.readback("readonly_input", specs["readonly_input"], initial=True)
        before = self.value["offline_observations"]["objects"]["readonly_input"]["before"]
        apt.require(created["readonly_input"] == [before["dev"], before["ino"]], "readonly input actual identity changed")
        for role in ("guest_root", "work", "result", "cgroup_parent", "cgroup_supervisor", "cgroup_worker", "control", "lease", "ack"):
            self.event(role, "intent", size=specs[role]["bytes"])
            created[role] = backend.create(role, specs[role])
            self.event(role, "bound", created[role], specs[role]["bytes"])
            backend.populate(role, specs[role], created[role])
        for role, ident in created.items():
            apt.require(backend.readback(role, specs[role], initial=True) == ident, "guest independent readback identity changed: " + role)
        return created

    def check_root(self):
        apt.require(self.root_fd is not None and identity(os.fstat(self.root_fd)) == self.root_identity, "JXA root descriptor identity")
        fd = directory(self.value["host_jxa_root"], uid=self.value["host_uid"], gid=self.value["host_gid"], mode=0o700)
        try: apt.require(identity(os.fstat(fd)) == self.root_identity, "JXA root replaced")
        finally: os.close(fd)

    def stage(self, message, raw):
        apt.fields(message, "schema_version scope uuid nonce manifest_sha256 root_identity operation sequence deadline bytes sha256")
        expected = dict(schema_version=1, scope="i5-synthetic-staging", uuid=apt.UUID, nonce=self.value["nonce"],
                        manifest_sha256=self.value["manifest_sha256"], root_identity=self.root_identity)
        apt.require(all(type(message[key]) is type(value) and message[key] == value for key, value in expected.items()),
                    "staging worker identity binding")
        sequence, operation = message["sequence"], message["operation"]
        apt.require(type(sequence) is int and 0 <= sequence < 2 ** 53 and operation in ("stage", "clean"), "staging worker request")
        self.check_root()
        name = "rpc-" + str(sequence) + ".js"
        if operation == "stage":
            apt.require(sequence > self.sequence and self.source is None and type(raw) is bytes and
                        0 < len(raw) <= self.config.source_limit and len(raw) == message["bytes"] and
                        hashlib.sha256(raw).hexdigest() == message["sha256"], "staging exact bytes/reservation")
            self.sequence, self.source = sequence, name
            self.event("source", "intent", size=len(raw))
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.root_fd)
            self.source_fd = fd
            try:
                ident = identity(os.fstat(fd))
                self.event("source", "bound", ident, len(raw))
                offset = 0
                while offset < len(raw):
                    chunk = raw[offset:offset + 65536]
                    apt.require(os.write(fd, chunk) == len(chunk), "short staged source write")
                    offset += len(chunk)
            except BaseException: raise
            apt.require(evidence.read_file(self.root_fd, os.fstat(self.root_fd), name, self.config.source_limit) == raw,
                        "staged source independent readback")
            apt.require(identity(os.stat(name, dir_fd=self.root_fd, follow_symlinks=False)) == ident, "staged source replaced")
        else:
            apt.require(sequence == self.sequence and self.source == name and raw == b"" and message["bytes"] == 0 and
                        message["sha256"] == hashlib.sha256(b"").hexdigest(), "staging cleanup sequence")
            self.clean_source()
        return self.value["host_jxa_root"] + "/" + name

    def clean_source(self):
        if self.source is None: return
        self.check_root()
        entry = self.entries.get("source")
        apt.require(entry is not None and entry["state"] == "bound", "source creation identity unconfirmed; preserve residue")
        info = os.stat(self.source, dir_fd=self.root_fd, follow_symlinks=False)
        apt.require(identity(info) == entry["identity"] and stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                    self.source_fd is not None and identity(os.fstat(self.source_fd)) == entry["identity"] and
                    info.st_uid == self.value["host_uid"] and stat.S_IMODE(info.st_mode) == 0o600, "source cleanup identity mismatch")
        os.unlink(self.source, dir_fd=self.root_fd)
        os.close(self.source_fd); self.source_fd = None
        self.event("source", "cleaned", entry["identity"], entry["bytes"])
        self.source = None

    def cleanup(self, realm):
        errors = []
        def record(reason):
            from sw_i5_preparation_lifecycle import bounded_text
            text, _ = bounded_text(reason, 400)
            if len(channels.encode(errors + [text])) <= 1400: errors.append(text)
            elif not errors or errors[-1] != "cleanup diagnostics [truncated]": errors.append("cleanup diagnostics [truncated]")
        if realm == "guest":
            roles = ("ack", "lease", "control", "cgroup_worker", "cgroup_supervisor", "cgroup_parent", "result", "work", "guest_root")
            for role in roles:
                if role not in self.entries: continue
                try:
                    row = self.entries[role]
                    apt.require(row["state"] == "bound", role + " creation identity unconfirmed")
                    self.config.guest_backend.remove(role, self.value["objects"][role], row["identity"])
                    self.event(role, "cleaned", row["identity"], row["bytes"])
                except Exception as exc: record(role + ": " + str(exc))
        else:
            apt.require(realm == "host", "fixed cleanup realm")
            try:
                self.clean_source()
                if "host_jxa_root" in self.entries:
                    apt.require(self.entries["host_jxa_root"]["state"] == "bound", "JXA root creation identity unconfirmed")
                    self.check_root()
                    apt.require(not os.listdir(self.root_fd), "unexpected JXA root entries; preserve")
                    os.rmdir(Path(self.value["host_jxa_root"]).name, dir_fd=self.parent_fd)
                    self.event("host_jxa_root", "cleaned", self.root_identity)
            except Exception as exc: record("host: " + str(exc))
        return errors

    def close(self):
        self.config.guest_backend.close()
        for fd in (self.root_fd, self.parent_fd, self.source_fd):
            if fd is not None: os.close(fd)


def worker_main(parent, nonce, digest, command_fd, result_fd, stage_fd, config, init_deadline, absolute):
    """One existing evidence child; blocked FS never blocks the owner or RPC."""
    store, worker, current_deadline = None, None, init_deadline
    def reply(value):
        staging.send(result_fd, channels.encode(value), current_deadline)
    def register(value):
        reply(dict(schema_version=1, scope="i5-synthetic-registration", uuid=apt.UUID, nonce=nonce,
                   manifest_sha256=digest, deadline=current_deadline, registration=value))
        message = apt.decode(staging.receive(command_fd, current_deadline, evidence.RECEIPT_LIMIT), evidence.RECEIPT_LIMIT)
        apt.require(message == {"registered": value}, "initialization registration ACK lost/mismatched")
    def error(exc):
        from sw_i5_preparation_lifecycle import bounded_text
        return bounded_text(type(exc).__name__ + ": " + str(exc), 900)[0]
    try:
        channels.close_except((command_fd, result_fd, stage_fd))
        os.setsid()
        for number in (signal.SIGTERM, signal.SIGINT): signal.signal(number, signal.SIG_DFL)
        worker = InitializationWorker(config, register)
        attempt_ready, objects, failure = False, {}, None
        try:
            # Compare the bound parent BEFORE consuming a new attempt.
            value = config.value
            fd = directory(parent, uid=value["host_uid"], gid=value["host_gid"], mode=0o700)
            try:
                expected = value["offline_observations"]["objects"]["host_evidence_parent"]["before"]
                apt.require(identity(os.fstat(fd)) == [expected["dev"], expected["ino"]], "evidence parent actual identity changed")
            finally: os.close(fd)
            facts = config.facts()
            store = evidence.EvidenceStore(parent, nonce, digest, initialization_binding={
                key: facts[key] for key in ("plan_sha256", "ledger_sha256", "source_sha256")})
            store.verify_attempt()
            attempt_ready = True
            objects = worker.host(store)
        except Exception as exc: failure = error(exc)
        reply(dict(ready=objects, attempt_ready=attempt_ready, error=failure))
        stage_open = True
        while time.monotonic() < absolute:
            ready, _, _ = select.select([command_fd] + ([stage_fd] if stage_open else []), [], [], min(0.05, max(0, absolute - time.monotonic())))
            if not ready: continue
            if command_fd in ready:
                current_deadline = absolute
                message = apt.decode(staging.receive(command_fd, absolute, evidence.RECEIPT_LIMIT), evidence.RECEIPT_LIMIT)
                if "report_bytes" in message:
                    apt.fields(message, "report_bytes process_exit lifecycle initialization deadline")
                    apt.require(store is not None and type(message["report_bytes"]) is int and
                                0 <= message["report_bytes"] <= channels.HOST_REPORT_LIMIT, "initialized evidence report limit")
                    apt.require(type(message["deadline"]) in (int, float) and time.monotonic() < message["deadline"] <= absolute,
                                "initialized evidence commit deadline")
                    current_deadline = message["deadline"]
                    raw = staging.receive(command_fd, current_deadline, message["report_bytes"], line=False) if message["report_bytes"] else b""
                    # Nonblocking command transport: EOF may follow the final
                    # payload bytes a scheduler turn later. Wait within the
                    # original persist deadline, and reject any extra byte.
                    while True:
                        apt.require(time.monotonic() < current_deadline, "initialized evidence commit EOF deadline")
                        readable, _, _ = select.select([command_fd], [], [], 0.01)
                        if not readable: continue
                        try: extra = os.read(command_fd, 1)
                        except BlockingIOError: continue
                        apt.require(extra == b"", "one initialized evidence commit")
                        break
                    receipt = store.persist(raw, message["process_exit"], lifecycle=message["lifecycle"], initialization=message["initialization"])
                    reply(dict(receipt=receipt, error=None))
                    store.close(); worker.close()
                    os._exit(0)
                apt.fields(message, "operation deadline")
                apt.require(message["operation"] in ("guest", "guest-cleanup", "host-cleanup") and
                            type(message["deadline"]) in (int, float) and time.monotonic() < message["deadline"] <= absolute,
                            "fixed initialization command/deadline")
                current_deadline = message["deadline"]
                try:
                    result = worker.guest() if message["operation"] == "guest" else worker.cleanup(message["operation"].removesuffix("-cleanup"))
                    reply(dict(operation=message["operation"], result=result, error=None))
                except Exception as exc:
                    reply(dict(operation=message["operation"], result=None, error=error(exc)))
            elif stage_fd in ready:
                # Upload/registration/write/readback share the client's original
                # deadline. No helper may restart a two-second window.
                current_deadline = min(absolute, time.monotonic() + 2)
                header = staging.receive(stage_fd, current_deadline, allow_eof=True)
                if not header:
                    stage_open = False
                    continue
                message = apt.decode(header, staging.HEADER_LIMIT)
                apt.fields(message, "schema_version scope uuid nonce manifest_sha256 root_identity operation sequence deadline bytes sha256")
                apt.require(type(message["deadline"]) in (int, float) and
                            time.monotonic() < message["deadline"] <= current_deadline and
                            type(message["bytes"]) is int and 0 <= message["bytes"] <= config.source_limit,
                            "staging upload budget")
                current_deadline = message["deadline"]
                try:
                    raw = staging.receive(stage_fd, current_deadline, message["bytes"], line=False) if message["bytes"] else b""
                    path = worker.stage(message, raw)
                    packet = dict(operation=message["operation"], sequence=message["sequence"], path=path, error=None)
                except Exception as exc:
                    packet = dict(operation=message["operation"], sequence=message["sequence"], path=None, error=error(exc))
                for key in ("schema_version", "scope", "uuid", "nonce", "manifest_sha256", "root_identity"): packet[key] = message[key]
                try: staging.send(stage_fd, channels.encode(packet), current_deadline)
                except (ValueError, OSError):
                    # The RPC deadline/consumer may already be gone. Keep the
                    # registered residue for the owner's explicit cleanup.
                    pass
        raise ValueError("initialized evidence absolute deadline")
    except BaseException:
        os._exit(2)
    finally:
        if store is not None: store.close()
        if worker is not None: worker.close()
