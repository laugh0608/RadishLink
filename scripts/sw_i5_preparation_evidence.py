"""Bounded, non-overwriting preparation evidence in an explicitly owned directory.

No default destination, directory discovery, VM access or resume. A receipt is
written last; missing receipts and partial records are interrupted attempts.
Logical byte limits do not substitute for a host filesystem hard quota.
"""

import hashlib
import os
from pathlib import Path
import select
import signal
import stat
import time

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels

STORE_LIMIT = 4 * apt.MIB
RECEIPT_LIMIT = 8192
PERSIST_SECONDS = 6
LIFECYCLE_LIMIT = 5 * 1024
FIRST_ERROR_BYTES = 1536
CLEANUP_BYTES = 768


def validate_host_report(raw, nonce, manifest_sha256):
    value = apt.decode(raw, channels.HOST_REPORT_LIMIT)
    apt.fields(value, "schema_version scope nonce uuid manifest_sha256 evidence_kind i5_ready passed export watchdog "
               "transport_exit cleanup_errors")
    apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["scope"] == "i5-preparation-host-report" and value["uuid"] == apt.UUID and
                value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256 and
                value["evidence_kind"] == "synthetic" and value["i5_ready"] is False and type(value["passed"]) is bool,
                "host report binding")
    apt.require((value["transport_exit"] is None or type(value["transport_exit"]) is int) and
                type(value["cleanup_errors"]) is list and len(value["cleanup_errors"]) <= 16 and
                all(type(e) is str and 0 < len(e) <= 2048 for e in value["cleanup_errors"]), "host cleanup fields")
    watch = value["watchdog"]
    apt.fields(watch, "transport_complete failure recovery i5_ready")
    apt.require(type(watch["transport_complete"]) is bool and watch["i5_ready"] is False and
                (watch["failure"] is None or (type(watch["failure"]) is str and 0 < len(watch["failure"]) <= 2048)),
                "watchdog fields")
    if watch["recovery"] is not None:
        recovery = watch["recovery"]
        apt.require(type(recovery) is dict and type(recovery.get("stopped")) is bool and
                    recovery.get("passed", False) is False and recovery.get("i5_ready", False) is False,
                    "recovery cannot grant success")
    export = None
    if value["export"] is not None:
        export = channels.validate_export(channels.encode(value["export"]), nonce, manifest_sha256)
    if watch["transport_complete"]:
        apt.require(export is not None and export["passed"], "complete transport requires valid export")
    expected = bool(watch["transport_complete"] and watch["failure"] is None and watch["recovery"] is None and
                    value["transport_exit"] == 0 and not value["cleanup_errors"])
    apt.require(value["passed"] == expected and
                (expected or watch["failure"] or value["cleanup_errors"] or value["transport_exit"] != 0),
                "contradictory host result")
    return value


def fingerprint(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def validate_action_result(value, nonce, manifest_sha256, action, mode=None):
    apt.fields(value, "schema_version scope uuid nonce manifest_sha256 action mode status forced_stop")
    apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["scope"] == "i5-preparation-lifecycle-action-result" and value["uuid"] == apt.UUID and
                value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256 and value["action"] == action and
                value["status"] == {"start": "started", "readiness": "ready", "shutdown": "stopped"}[action] and
                type(value["forced_stop"]) is bool and (action == "shutdown" or value["forced_stop"] is False) and
                value["mode"] in (("normal", "recovery") if action == "shutdown" else ("work",)) and
                (mode is None or value["mode"] == mode), "lifecycle action binding/status")
    return value


def validate_lifecycle(value, nonce, manifest_sha256, host_passed):
    apt.fields(value, "schema_version scope uuid nonce manifest_sha256 evidence_kind i5_ready total_seconds "
               "attempt_ready start_attempted start readiness shutdown_attempted shutdown transport_registered "
               "sessions_reaped frozen first_failure failure_truncated cleanup_errors cleanup_truncated passed")
    apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["scope"] == "i5-preparation-lifecycle" and value["uuid"] == apt.UUID and
                value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256 and
                value["evidence_kind"] == "synthetic" and value["i5_ready"] is False and value["frozen"] is True and
                type(value["total_seconds"]) in (int, float) and 0 < value["total_seconds"] <= 900 and
                all(type(value[k]) is bool for k in ("attempt_ready", "start_attempted", "shutdown_attempted",
                    "transport_registered", "sessions_reaped", "frozen", "passed", "failure_truncated", "cleanup_truncated")), "lifecycle fields/binding")
    apt.require(value["first_failure"] is None or (type(value["first_failure"]) is str and
                0 < len(value["first_failure"]) <= 2048), "lifecycle first failure")
    apt.require(type(value["cleanup_errors"]) is list and len(value["cleanup_errors"]) <= 16 and
                all(type(e) is str and 0 < len(e) <= 2048 for e in value["cleanup_errors"]), "lifecycle cleanup errors")
    apt.require(len(channels.encode(value)) <= LIFECYCLE_LIMIT and
                len(channels.encode(value["first_failure"])) <= FIRST_ERROR_BYTES and
                len(channels.encode(value["cleanup_errors"])) <= CLEANUP_BYTES and
                (not value["failure_truncated"] or (value["first_failure"] is not None and value["first_failure"].endswith(" [truncated]"))),
                "lifecycle diagnostic byte limits")
    for action, key in (("start", "start"), ("readiness", "readiness"), ("shutdown", "shutdown")):
        if value[key] is not None: validate_action_result(value[key], nonce, manifest_sha256, action)
    apt.require((value["start_attempted"] or (value["start"] is None and value["readiness"] is None and
                not value["shutdown_attempted"] and not value["transport_registered"])) and
                (not value["start_attempted"] or value["attempt_ready"]) and
                (value["start"] is not None or value["readiness"] is None) and
                (not value["transport_registered"] or value["readiness"] is not None) and
                (value["shutdown_attempted"] or value["shutdown"] is None) and
                value["shutdown_attempted"] == value["start_attempted"] and
                (not host_passed or (value["transport_registered"] and value["start"] is not None and value["readiness"] is not None)) and
                value["sessions_reaped"] == (not value["cleanup_errors"] and not value["cleanup_truncated"]), "lifecycle attempt ordering")
    apt.require(value["shutdown"] is None or value["shutdown"]["mode"] != "normal" or host_passed, "normal stop requires host success")
    stopped = value["shutdown"] is not None and value["shutdown"]["mode"] == "normal" and not value["shutdown"]["forced_stop"]
    expected = bool(host_passed and value["attempt_ready"] and value["start_attempted"] and value["start"] is not None and
                    value["readiness"] is not None and value["shutdown_attempted"] and stopped and
                    value["transport_registered"] and value["sessions_reaped"] and value["first_failure"] is None and
                    not value["cleanup_errors"] and not value["cleanup_truncated"])
    apt.require(value["passed"] == expected and (expected or value["first_failure"] or value["cleanup_errors"]),
                "lifecycle passed/failure contradiction")
    return value


def read_file(fd, info, name, limit):
    stream = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    try:
        before = os.fstat(stream)
        apt.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid() and
                    before.st_dev == info.st_dev and before.st_mode & 0o077 == 0 and before.st_size <= limit,
                    "unsafe evidence file")
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(stream, min(65536, limit - len(data) + 1))
            if not chunk: break
            data.extend(chunk)
        after = os.fstat(stream)
        apt.require(len(data) == before.st_size and len(data) <= limit and
                    (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) and
                    os.stat(name, dir_fd=fd, follow_symlinks=False).st_ino == after.st_ino, "evidence changed while reading")
        return bytes(data)
    finally:
        os.close(stream)


def validate_attempt(raw, nonce, manifest_sha256):
    value = apt.decode(raw, RECEIPT_LIMIT)
    apt.require(value == {"schema_version": 1, "scope": "i5-preparation-evidence-attempt", "nonce": nonce,
                "uuid": apt.UUID, "manifest_sha256": manifest_sha256, "i5_ready": False} and
                type(value["schema_version"]) is int, "evidence attempt binding")



class EvidenceStore:
    def __init__(self, parent, nonce, manifest_sha256):
        channels.supervision.Lease(nonce, manifest_sha256, started=0)
        parent = Path(parent)
        apt.require(parent.is_absolute() and parent.resolve(strict=True) == parent, "canonical evidence parent required")
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.fd, self.written, self.consumed = None, 0, False
        self.nonce, self.manifest_sha256 = nonce, manifest_sha256
        self.path = parent / nonce
        try:
            info = os.fstat(parent_fd)
            apt.require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, "private owned evidence parent required")
            os.mkdir(nonce, mode=0o700, dir_fd=parent_fd)  # Existing attempts, including failures, are never resumed.
            os.fsync(parent_fd)
            self.fd = os.open(nonce, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
            self.identity = (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino)
            self.write("attempt.json", channels.encode({"schema_version": 1, "scope": "i5-preparation-evidence-attempt",
                "nonce": nonce, "uuid": apt.UUID, "manifest_sha256": manifest_sha256, "i5_ready": False}))
        except BaseException:
            self.close()
            raise
        finally:
            os.close(parent_fd)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def check(self):
        apt.require(self.fd is not None, "evidence store closed")
        info = self.path.lstat()
        apt.require(stat.S_ISDIR(info.st_mode) and not self.path.is_symlink() and
                    self.path.resolve(strict=True) == self.path and
                    (info.st_dev, info.st_ino) == self.identity and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
                    "evidence directory replaced")

    def write(self, name, raw):
        self.check()
        apt.require(name in {"attempt.json", "host-report.bin", "receipt.json"} and type(raw) is bytes and
                    len(raw) <= (channels.HOST_REPORT_LIMIT if name == "host-report.bin" else RECEIPT_LIMIT) and
                    self.written + len(raw) <= STORE_LIMIT, "evidence write quota")
        self.written += len(raw)  # Charge before I/O; partial failures do not refund.
        partial = name + ".partial"
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        try:
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:offset + 65536])
                apt.require(written > 0, "zero evidence write")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        self.check()
        # link() publishes without overwriting an existing final file. The two
        # names share one inode; there is no second full-sized payload copy.
        os.link(partial, name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        os.fsync(self.fd)
        os.unlink(partial, dir_fd=self.fd)
        os.fsync(self.fd)

    def verify_attempt(self):
        self.check()
        apt.require(set(os.listdir(self.fd)) == {"attempt.json"}, "interrupted attempt initialization")
        validate_attempt(read_file(self.fd, os.fstat(self.fd), "attempt.json", RECEIPT_LIMIT), self.nonce, self.manifest_sha256)
        self.check()

    def persist(self, raw, process_exit, *, failure=None, lifecycle=None):
        apt.require(not self.consumed, "evidence attempt consumed")
        self.consumed = True
        apt.require(type(raw) is bytes and len(raw) <= channels.HOST_REPORT_LIMIT, "host evidence byte limit")
        apt.require(process_exit is None or type(process_exit) is int, "host process exit type")
        apt.require(failure is None or (type(failure) is str and 0 < len(failure) <= 2048), "evidence failure type")
        accepted, passed = False, False
        if failure is None:
            try:
                value = validate_host_report(raw, self.nonce, self.manifest_sha256)
                apt.require(process_exit == (0 if value["passed"] else 2), "host process/report exit mismatch")
                accepted, passed = True, value["passed"]
            except (OSError, ValueError, RuntimeError) as exc:
                failure = str(exc)[:2048]
        if lifecycle is not None:
            validate_lifecycle(lifecycle, self.nonce, self.manifest_sha256, passed)
        self.write("host-report.bin", raw)
        receipt = {"schema_version": 1, "scope": "i5-preparation-evidence-receipt", "nonce": self.nonce,
                   "uuid": apt.UUID, "manifest_sha256": self.manifest_sha256, "i5_ready": False,
                   "evidence_kind": "synthetic", "accepted": accepted, "passed": passed,
                   "process_exit": process_exit, "failure": failure, "payload": fingerprint(raw)}
        if lifecycle is not None:
            receipt.update(schema_version=2, lifecycle=lifecycle, passed=passed and lifecycle["passed"])
        self.write("receipt.json", channels.encode(receipt))
        return read_evidence(self.path, self.nonce, self.manifest_sha256)


def persist_bounded(store, raw, process_exit, *, failure=None, seconds=PERSIST_SECONDS):
    """Keep a stalled filesystem out of the lifecycle controller's process.

    An exception means persistence/cleanup is unconfirmed, even if some final
    files became visible. The caller must retain failure and perform recovery.
    No automatic retries, resume, unlink or compensating writes are attempted.
    """
    apt.require(not store.consumed and 0 < seconds <= PERSIST_SECONDS, "persistence attempt/deadline")
    reader, writer = os.pipe()
    deadline = time.monotonic() + seconds
    try:
        pid = os.fork()
    except BaseException:
        os.close(reader)
        os.close(writer)
        raise
    if pid == 0:
        try:
            channels.close_except((writer, store.fd))
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            receipt = store.persist(raw, process_exit, failure=failure)
            message = {"receipt": receipt, "error": None}
        except BaseException as exc:
            message = {"receipt": None, "error": (type(exc).__name__ + ": " + str(exc))[:2048]}
        try:
            channels.write_bounded(writer, channels.encode(message), deadline=deadline)
        except BaseException:
            os._exit(2)
        os._exit(0 if message["error"] is None else 2)
    store.consumed = True
    os.close(writer)
    data, code = bytearray(), None
    try:
        while True:
            apt.require(time.monotonic() < deadline, "persistence deadline; outcome unconfirmed")
            ready, _, _ = select.select([reader], [], [], 0.01)
            if not ready: continue
            chunk = os.read(reader, min(4096, RECEIPT_LIMIT - len(data) + 1))
            if not chunk: break
            data.extend(chunk)
            apt.require(len(data) <= RECEIPT_LIMIT, "persistence reply limit")
        code = channels.wait_child(pid, deadline)
        message = apt.decode(bytes(data), RECEIPT_LIMIT)
        apt.fields(message, "receipt error")
        apt.require(code == 0 and message["error"] is None, "persistence failed: " + str(message["error"]))
        # Child already performed bounded readback; never introduce a second
        # unbounded disk read on the lifecycle controller after the deadline.
        return message["receipt"]
    finally:
        os.close(reader)
        if code is None:
            try: os.kill(pid, signal.SIGKILL)
            except ProcessLookupError: pass
            code = channels.wait_child(pid, time.monotonic() + 2)
            apt.require(code is not None, "persistence child kill/reap unconfirmed: " + str(pid))


def read_evidence(path, nonce, manifest_sha256):
    channels.supervision.Lease(nonce, manifest_sha256, started=0)
    path = Path(path)
    apt.require(path.is_absolute() and path.resolve(strict=True) == path and path.name == nonce, "evidence path binding")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        apt.require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, "private evidence directory required")
        apt.require(set(os.listdir(fd)) == {"attempt.json", "host-report.bin", "receipt.json"}, "interrupted or extra evidence files")
        def read(name, limit): return read_file(fd, info, name, limit)
        validate_attempt(read("attempt.json", RECEIPT_LIMIT), nonce, manifest_sha256)
        raw = read("host-report.bin", channels.HOST_REPORT_LIMIT)
        receipt = apt.decode(read("receipt.json", RECEIPT_LIMIT), RECEIPT_LIMIT)
        version = receipt.get("schema_version") if type(receipt) is dict else None
        apt.require(type(version) is int and version in (1, 2), "evidence receipt version")
        apt.fields(receipt, "schema_version scope nonce uuid manifest_sha256 i5_ready evidence_kind accepted passed process_exit failure payload" +
                   (" lifecycle" if version == 2 else ""))
        apt.require(type(receipt["schema_version"]) is int and receipt["schema_version"] == version and
                    receipt["scope"] == "i5-preparation-evidence-receipt" and receipt["nonce"] == nonce and
                    receipt["uuid"] == apt.UUID and receipt["manifest_sha256"] == manifest_sha256 and
                    receipt["i5_ready"] is False and receipt["evidence_kind"] == "synthetic" and
                    type(receipt["accepted"]) is bool and type(receipt["passed"]) is bool and
                    (receipt["process_exit"] is None or type(receipt["process_exit"]) is int) and
                    receipt["payload"] == fingerprint(raw) and type(receipt["payload"]["bytes"]) is int,
                    "evidence receipt binding/digest")
        host_passed = False
        if receipt["accepted"]:
            value = validate_host_report(raw, nonce, manifest_sha256)
            host_passed = value["passed"]
            if version == 2: validate_lifecycle(receipt["lifecycle"], nonce, manifest_sha256, host_passed)
            expected = host_passed if version == 1 else host_passed and receipt["lifecycle"]["passed"]
            apt.require(receipt["failure"] is None and receipt["passed"] == expected and
                        receipt["process_exit"] == (0 if value["passed"] else 2), "evidence acceptance mismatch")
        else:
            apt.require(receipt["passed"] is False and type(receipt["failure"]) is str and
                        0 < len(receipt["failure"]) <= 2048, "failed evidence cannot pass")
        if version == 2:
            validate_lifecycle(receipt["lifecycle"], nonce, manifest_sha256, host_passed)
        current = path.lstat()
        apt.require(stat.S_ISDIR(current.st_mode) and path.resolve(strict=True) == path and
                    (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino) and
                    set(os.listdir(fd)) == {"attempt.json", "host-report.bin", "receipt.json"},
                    "evidence directory changed while reading")
        return receipt
    finally:
        os.close(fd)
