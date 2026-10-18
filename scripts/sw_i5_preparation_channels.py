"""Offline preparation channel wiring; no public launcher or VM authorization.

Control -> independent host watchdog -> guest supervisor uses separate pipes.
The transport never owns a lease writer. Export uses directory FDs pinned while
worker admission is blocked, and reads only after complete worker reclamation.
All external transport/recovery and privileged setup are explicitly injected.
"""

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import time

import sw_i5_apt as apt
import sw_i5_preparation_supervisor as supervision
import sw_i5_preparation_isolation as isolation

EXPORT_LIMIT = apt.RESULT_LIMIT
DATA_LIMIT = 1024 * 1024
FILE_LIMIT = 64 * 1024
SUMMARY_LIMIT = 256 * 1024
HOST_REPORT_LIMIT = 3 * 1024 * 1024
EXPORT_SCOPE = "i5-preparation-export"
ARTIFACTS = ("result/result.json", "result/worker.stdout", "result/worker.stderr") + tuple(
    "result/" + label + "." + stream for label in apt.STEP_LABELS for stream in ("stdout", "stderr"))


def encode(value):
    return (json.dumps(value, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def send(fd, raw, deadline):
    os.set_blocking(fd, False)
    offset = 0
    while offset < len(raw):
        apt.require(time.monotonic() < deadline, "staging IPC write deadline")
        _, ready, _ = select.select([], [fd], [], min(0.01, max(0, deadline - time.monotonic())))
        if not ready: continue
        try: count = os.write(fd, raw[offset:offset + 65536])
        except (BlockingIOError, InterruptedError): continue
        apt.require(count > 0, "staging IPC zero write")
        offset += count


def receive(fd, deadline, limit=2048, *, line=True, allow_eof=False):
    os.set_blocking(fd, False)
    raw = bytearray()
    while True:
        apt.require(time.monotonic() < deadline, "staging IPC read deadline")
        ready, _, _ = select.select([fd], [], [], min(0.01, max(0, deadline - time.monotonic())))
        if not ready: continue
        try: chunk = os.read(fd, 1 if line else min(65536, limit - len(raw)))
        except (BlockingIOError, InterruptedError): continue
        if not chunk and not raw and allow_eof: return b""
        apt.require(chunk, "staging IPC EOF")
        raw.extend(chunk)
        apt.require(len(raw) <= limit, "staging IPC byte limit")
        if (line and raw.endswith(b"\n")) or (not line and len(raw) == limit):
            apt.require(time.monotonic() < deadline, "late staging IPC bytes")
            return bytes(raw)


def close_except(fds):
    first = 3
    for fd in sorted(set(fds)):
        apt.require(type(fd) is int and fd >= 3, "private descriptor required")
        os.closerange(first, fd)
        first = fd + 1
    os.closerange(first, os.sysconf("SC_OPEN_MAX"))


def write_frame(fd, raw):
    apt.require(type(raw) is bytes and 0 < len(raw) <= supervision.MAX_FRAME, "control frame limit")
    os.set_blocking(fd, False)
    apt.require(os.write(fd, raw) == len(raw), "control frame short write")


def write_bounded(fd, raw, *, deadline, checkpoint=lambda: None):
    apt.require(type(raw) is bytes and 0 < len(raw) <= HOST_REPORT_LIMIT, "channel output limit")
    os.set_blocking(fd, False)
    offset = 0
    while offset < len(raw):
        checkpoint()
        remaining = deadline - time.monotonic()
        apt.require(remaining > 0, "result consumer deadline")
        _, ready, _ = select.select([], [fd], [], min(remaining, 0.05))
        if ready:
            try:
                written = os.write(fd, memoryview(raw)[offset:offset + 65536])
            except BlockingIOError:
                continue
            apt.require(written > 0, "result channel zero write")
            offset += written


def initial_lease(fd, lease, checkpoint=lambda: None):
    while lease.sequence < 0:
        checkpoint()
        lease.check(time.monotonic(), require_started=False)
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            raw = os.read(fd, supervision.MAX_FRAME)
            apt.require(raw, "initial lease channel closed")
            lease.feed(raw, time.monotonic())


def wait_child(pid, deadline):
    while True:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.waitstatus_to_exitcode(status)
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.01)


def bounded_recovery(recover, seconds=120):
    """Enforce a wall deadline even if the recovery adapter itself blocks."""
    apt.require(0 < seconds <= 120, "host recovery deadline")
    reader, writer = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        os.close(reader)
        os.close(writer)
        raise
    if pid == 0:
        try:
            close_except((writer,))
            os.setsid()
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            value = recover()
            raw = encode(value)
            apt.require(len(raw) <= 65536, "recovery report limit")
            write_bounded(writer, raw, deadline=time.monotonic() + min(2, seconds))
            os._exit(0)
        except BaseException as exc:
            try:
                failure = {"passed": False, "stopped": False, "failure": (type(exc).__name__ + ": " + str(exc))[:2048],
                           "cleanup_errors": []}
                write_bounded(writer, encode(failure), deadline=time.monotonic() + min(2, seconds))
                os._exit(2)
            except BaseException:
                os._exit(2)
    os.close(writer)
    raw, code = bytearray(), None
    result = {"passed": False, "stopped": False, "failure": None, "cleanup_errors": []}
    deadline = time.monotonic() + seconds
    try:
        while True:
            apt.require(time.monotonic() < deadline, "host recovery adapter deadline")
            ready, _, _ = select.select([reader], [], [], 0.01)
            if not ready: continue
            chunk = os.read(reader, min(8192, 65536 - len(raw) + 1))
            if not chunk: break
            raw.extend(chunk)
            apt.require(len(raw) <= 65536, "recovery report overflow")
        code = wait_child(pid, deadline)
        apt.require(code in {0, 2}, "recovery adapter failed or did not exit")
        value = apt.decode(bytes(raw), 65536)
        apt.require(type(value) is dict and type(value.get("stopped")) is bool and value.get("passed") is False and
                    value.get("i5_ready", False) is False, "invalid recovery result")
        apt.require(code == 0 or (value["stopped"] is False and type(value.get("failure")) is str and value["failure"]),
                    "failed recovery process cannot claim stopped")
        # A callback that leaves children behind cannot establish clean recovery.
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return value
        raise ValueError("recovery adapter descendants remain")
    except (OSError, ValueError, RuntimeError) as exc:
        result["failure"] = str(exc)[:2048]
    finally:
        os.close(reader)
        if result["failure"]:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                if code is None:
                    try: os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            if code is None:
                code = wait_child(pid, time.monotonic() + 2)
                if code is None:
                    result["cleanup_errors"].append("recovery adapter kill/reap unconfirmed")
    return result


def validate_supervision(value, nonce, manifest_sha256):
    apt.fields(value, "schema_version scope uuid nonce manifest_sha256 i5_ready passed failure cleanup_errors "
               "admitted worker_exit population_empty reaped")
    apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["scope"] == "i5-preparation-supervision" and value["uuid"] == apt.UUID and
                value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256 and
                value["i5_ready"] is False, "supervision binding")
    apt.require(all(type(value[k]) is bool for k in ("passed", "admitted", "population_empty", "reaped")) and
                (value["worker_exit"] is None or type(value["worker_exit"]) is int) and
                (value["failure"] is None or (type(value["failure"]) is str and len(value["failure"]) <= 2048)) and
                type(value["cleanup_errors"]) is list and len(value["cleanup_errors"]) <= 16 and
                all(type(e) is str and len(e) <= 2048 for e in value["cleanup_errors"]), "supervision fields")
    expected = bool(value["admitted"] and value["worker_exit"] == 0 and value["population_empty"] and
                    value["reaped"] and not value["failure"] and not value["cleanup_errors"])
    apt.require(value["passed"] == expected, "contradictory supervision result")


class ResultExport:
    def __init__(self, nonce, manifest_sha256):
        # Reuse binding validation without granting an initial lease.
        supervision.Lease(nonce, manifest_sha256, started=0)
        self.nonce, self.manifest_sha256, self.dirs = nonce, manifest_sha256, {}

    def pin(self, pid, guard):
        apt.require(not self.dirs and guard.initial is not None, "validated worker before export pin")
        # /proc/<owned child>/root is intentional. Final directory must match
        # the device/inode independently checked by the isolation guard.
        for role, path in (("result", guard.contract.result),):
            expected = guard.initial[0][role]
            self.pin_directory(role, Path("/proc") / str(pid) / "root" / str(path).lstrip("/"),
                               expected[1], expected[2])

    def pin_directory(self, role, path, device, inode):
        apt.require(role == "result" and role not in self.dirs, "duplicate export directory")
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            apt.require(f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}" == device and info.st_ino == inode,
                        "export directory identity changed")
            self.dirs[role] = fd
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        for fd in self.dirs.values():
            os.close(fd)
        self.dirs.clear()

    def collect(self, report, checkpoint):
        packet = {"schema_version": 1, "scope": EXPORT_SCOPE, "nonce": self.nonce, "uuid": apt.UUID,
                  "manifest_sha256": self.manifest_sha256, "evidence_kind": "synthetic", "i5_ready": False,
                  "passed": False, "supervision": report, "preparation": None, "artifacts": [], "export_errors": []}
        used = 0
        try:
            validate_supervision(report, self.nonce, self.manifest_sha256)
            apt.require(report["population_empty"] and report["reaped"], "cannot export while worker descendants remain")
            apt.require(set(self.dirs) == {"result"}, "export directories not pinned")
            for name in ARTIFACTS:
                checkpoint()
                role, leaf = name.split("/")
                parent = self.dirs[role]
                try:
                    fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
                except FileNotFoundError:
                    continue  # Absence is checked against the completed step list below.
                try:
                    before = os.fstat(fd)
                    apt.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                                before.st_dev == os.fstat(parent).st_dev, "unsafe export file: " + name)
                    cap = min(SUMMARY_LIMIT if name == "result/result.json" else FILE_LIMIT, DATA_LIMIT - used)
                    chunks, size = [], 0
                    while size < cap:
                        checkpoint()
                        chunk = os.read(fd, min(65536, cap - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                    raw = b"".join(chunks)
                    after = os.fstat(fd)
                    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)
                    apt.require(identity(before) == identity(after) and
                                identity(after) == identity(os.stat(leaf, dir_fd=parent, follow_symlinks=False)),
                                "export file changed: " + name)
                    used += len(raw)
                    truncated = len(raw) != before.st_size
                    packet["artifacts"].append({"name": name, "bytes": before.st_size, "saved_bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(), "base64": base64.b64encode(raw).decode(), "truncated": truncated})
                    if truncated:
                        packet["export_errors"].append("export quota: " + name)
                    if name == "result/result.json" and not truncated:
                        packet["preparation"] = apt.validate_result(raw, self.nonce, self.manifest_sha256)
                finally:
                    os.close(fd)
            names = {a["name"] for a in packet["artifacts"]}
            apt.require(packet["preparation"] is not None, "preparation summary missing")
            required = {"result/result.json", "result/worker.stdout", "result/worker.stderr"}
            required.update("result/" + step["label"] + "." + stream for step in packet["preparation"]["steps"]
                            for stream in ("stdout", "stderr"))
            apt.require(required <= names, "completed step diagnostics missing")
        except (OSError, ValueError, RuntimeError) as exc:
            packet["export_errors"].append(str(exc)[:2048])
        packet["passed"] = bool(report["passed"] and packet["preparation"] and packet["preparation"]["passed"] and
                                not packet["export_errors"])
        apt.require(len(encode(packet)) <= EXPORT_LIMIT, "serialized export limit")
        return packet


def validate_export(raw, nonce, manifest_sha256):
    packet = apt.decode(raw, EXPORT_LIMIT)
    if type(packet) is dict and packet.get("scope") == "i5-preparation-native-lifecycle-export":
        return validate_native_export(raw, nonce, manifest_sha256)
    apt.fields(packet, "schema_version scope nonce uuid manifest_sha256 evidence_kind i5_ready passed supervision "
               "preparation artifacts export_errors")
    apt.require(type(packet["schema_version"]) is int and packet["schema_version"] == 1 and packet["scope"] == EXPORT_SCOPE and
                packet["nonce"] == nonce and packet["uuid"] == apt.UUID and packet["manifest_sha256"] == manifest_sha256 and
                packet["evidence_kind"] == "synthetic" and packet["i5_ready"] is False and type(packet["passed"]) is bool,
                "export binding")
    validate_supervision(packet["supervision"], nonce, manifest_sha256)
    apt.require(type(packet["artifacts"]) is list and len(packet["artifacts"]) <= len(ARTIFACTS) and
                type(packet["export_errors"]) is list and len(packet["export_errors"]) <= len(ARTIFACTS) + 1 and
                all(type(e) is str and 0 < len(e) <= 2048 for e in packet["export_errors"]), "export lists")
    names, used, summary = set(), 0, None
    for entry in packet["artifacts"]:
        apt.fields(entry, "name bytes saved_bytes sha256 base64 truncated")
        name = entry["name"]
        apt.require(name in ARTIFACTS and name not in names and type(entry["bytes"]) is int and entry["bytes"] >= 0 and
                    type(entry["saved_bytes"]) is int and 0 <= entry["saved_bytes"] <= entry["bytes"] and
                    entry["saved_bytes"] <= (SUMMARY_LIMIT if name == "result/result.json" else FILE_LIMIT) and
                    type(entry["truncated"]) is bool and entry["truncated"] == (entry["saved_bytes"] < entry["bytes"]) and
                    type(entry["base64"]) is str, "export artifact fields")
        data = base64.b64decode(entry["base64"], validate=True)
        apt.require(base64.b64encode(data).decode() == entry["base64"] and len(data) == entry["saved_bytes"] and
                    hashlib.sha256(data).hexdigest() == entry["sha256"], "artifact bytes/digest")
        names.add(name)
        used += len(data)
        apt.require(used <= DATA_LIMIT and (not entry["truncated"] or packet["export_errors"]), "artifact total/truncation")
        if name == "result/result.json" and not entry["truncated"]:
            try:
                summary = apt.validate_result(data, nonce, manifest_sha256)
            except ValueError:
                apt.require(packet["export_errors"], "invalid summary without export failure")
    apt.require(packet["preparation"] == summary, "export summary mismatch")
    if packet["passed"]:
        required = {"result/result.json", "result/worker.stdout", "result/worker.stderr"}
        apt.require(summary is not None, "passing export requires summary")
        required.update("result/" + s["label"] + "." + stream for s in summary["steps"] for stream in ("stdout", "stderr"))
        apt.require(required <= names and summary["passed"] and packet["supervision"]["passed"] and
                    not packet["export_errors"], "incomplete export cannot pass")
    else:
        apt.require(packet["export_errors"] or not packet["supervision"]["passed"] or
                    (summary is not None and not summary["passed"]), "unexplained export failure")
    return packet


def serve_preparation(control_fd, output_fd, ack_fd, *, work, boundary, guard, nonce, manifest_sha256,
                      prepare, exporter, total=apt.GUEST_SECONDS, silence=supervision.LEASE_SECONDS,
                      subreaper=supervision.enable_subreaper, keep_fds=()):
    """Guest transport endpoint; control is a read FD, never an autorenew timer.

    Live guest-agent transport is deliberately not wired to the public CLI.
    The supervisor retains mount directory FDs through reclamation and export.
    """
    pid, writer, reader = supervision.fork_supervisor(work, boundary, guard, nonce, manifest_sha256,
        prepare=prepare, exporter=exporter, control_fd=control_fd, total=total, silence=silence,
        subreaper=subreaper, keep_fds=keep_fds, ack_fd=ack_fd)
    apt.require(writer is None, "transport must not own guest renewal writer")
    # Close this duplicate reader; the independent supervisor consumes control.
    os.close(control_fd)
    os.close(ack_fd)
    deadline, size, status = time.monotonic() + total + supervision.CLEANUP_SECONDS + 3, 0, None
    try:
        while True:
            apt.require(time.monotonic() < deadline, "guest report deadline")
            ready, _, _ = select.select([reader], [], [], 0.05)
            if reader not in ready:
                continue
            raw = os.read(reader, min(65536, EXPORT_LIMIT - size + 1))
            if not raw:
                break
            size += len(raw)
            apt.require(size <= EXPORT_LIMIT, "guest report overflow")
            write_bounded(output_fd, raw, deadline=deadline)
        status = wait_child(pid, deadline)
        apt.require(status is not None, "guest supervisor reap deadline")
        return status
    finally:
        os.close(reader)
        # Do not kill a supervisor responsible for its worker cleanup. Its own
        # absolute lease remains active if this transport disappears.
        if status is None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            status = wait_child(pid, time.monotonic() + supervision.CLEANUP_SECONDS + 3)
            apt.require(status is not None, "supervisor cleanup unconfirmed; host recovery required")


def fork_watchdog(transport, recover, nonce, manifest_sha256, *, total=apt.HOST_SECONDS,
                  silence=supervision.LEASE_SECONDS, cleanup_seconds=25, recovery_seconds=120,
                  registration_fd=None, admission_fd=None, absolute_deadline=None, reap_seconds=2, defer_recovery=False,
                  transport_fds=()):
    """Return PID, caller lease writer, report reader and renewal ACK reader.

    transport(guest_control_read_fd, result_write_fd, guest_ack_write_fd) runs
    in its own child. Caller receives an ACK only after guest acceptance.
    recover() is the separately authorized, bound recovery adapter; offline
    callers inject a recorder. Neither callable can renew the host lease.
    Controller waits for the matching ACK before sending another frame; it
    cannot queue future renewals while the watchdog is starting or stalled.
    """
    # Internal lifecycle attachment only; standalone callers keep the original
    # four returned descriptors and recovery ownership. Supplied child-side
    # registration/admission descriptors must be closed by the caller after fork.
    attached = registration_fd is not None or admission_fd is not None
    apt.require(not attached or (type(registration_fd) is int and registration_fd >= 3 and
                type(admission_fd) is int and admission_fd >= 3 and registration_fd != admission_fd), "owner admission descriptors")
    apt.require(absolute_deadline is None or (type(absolute_deadline) in (int, float) and
                math.isfinite(absolute_deadline) and absolute_deadline > time.monotonic()), "watchdog absolute deadline")
    apt.require(type(reap_seconds) in (int, float) and math.isfinite(reap_seconds) and 0 < reap_seconds <= 2,
                "watchdog reap deadline")
    def until(seconds):
        return min(time.monotonic() + seconds, absolute_deadline if absolute_deadline is not None else float("inf"))
    apt.require(type(defer_recovery) is bool and (not defer_recovery or (attached and recover is None)),
                "deferred recovery requires attached lifecycle owner and no callback")
    extra_fds = (registration_fd, admission_fd) if attached else ()
    apt.require(type(transport_fds) is tuple and len(transport_fds) <= 1 and
                all(type(fd) is int and fd >= 3 and fd not in extra_fds for fd in transport_fds), "explicit staging descriptor whitelist")
    apt.require(0 < cleanup_seconds <= 25, "transport cleanup deadline")
    apt.require(0 < recovery_seconds <= 120, "recovery deadline")
    supervision.Lease(nonce, manifest_sha256, started=0, total=total, silence=silence, side="host")
    control_read, control_write = os.pipe()
    report_read, report_write = os.pipe()
    ack_read, ack_write = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        for fd in (control_read, control_write, report_read, report_write, ack_read, ack_write): os.close(fd)
        raise
    if pid == 0:
        close_except((control_read, report_write, ack_write) + extra_fds + transport_fds)
        os.setsid()
        child, guest_write, stream_read, guest_ack_read = None, None, None, None
        interrupted = []
        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda number, frame: interrupted.append(number))
        def checkpoint():
            apt.require(not interrupted, "host watchdog cancelled")
        packet = {"schema_version": 1, "scope": "i5-preparation-host-report", "nonce": nonce, "uuid": apt.UUID,
                  "manifest_sha256": manifest_sha256, "evidence_kind": "synthetic", "i5_ready": False,
                  "passed": False, "export": None, "watchdog": None, "transport_exit": None, "cleanup_errors": []}
        recovered = False
        def recover_once():
            nonlocal recovered
            apt.require(not recovered, "recovery already attempted")
            recovered = True
            if defer_recovery:
                return {"stopped": False, "passed": False, "i5_ready": False, "deferred": True}
            seconds = min(recovery_seconds, until(recovery_seconds) - time.monotonic())
            apt.require(seconds > 0, "watchdog recovery absolute deadline")
            return bounded_recovery(recover, seconds)
        try:
            lease = supervision.Lease(nonce, manifest_sha256, started=time.monotonic(), total=total,
                                      silence=silence, side="host")
            initial_lease(control_read, lease, checkpoint)
            guest_read, guest_write = os.pipe()
            stream_read, stream_write = os.pipe()
            guest_ack_read, guest_ack_write = os.pipe()
            child = os.fork()
            if child == 0:
                try:
                    close_except((guest_read, stream_write, guest_ack_write) + extra_fds + transport_fds)
                    watchdog_parent = os.getppid()
                    os.setsid()
                    signal.signal(signal.SIGTERM, signal.SIG_DFL)
                    signal.signal(signal.SIGINT, signal.SIG_DFL)
                    if attached:
                        write_frame(registration_fd, encode({"schema_version": 1, "scope": "i5-preparation-transport-admission",
                            "uuid": apt.UUID, "nonce": nonce, "manifest_sha256": manifest_sha256,
                            "pid": os.getpid(), "watchdog_pid": watchdog_parent}))
                        os.close(registration_fd)
                        admission_until = until(2)
                        while True:
                            apt.require(time.monotonic() < admission_until, "transport admission deadline")
                            ready, _, _ = select.select([admission_fd], [], [], 0.01)
                            if ready:
                                permit = os.read(admission_fd, 2)
                                apt.require(permit == b"1" and os.getppid() == watchdog_parent, "transport owner admission lost")
                                break
                        os.close(admission_fd)
                    code = transport(guest_read, stream_write, guest_ack_write)
                    os._exit(code if type(code) is int and 0 <= code <= 255 else 2)
                except BaseException as exc:
                    try:
                        write_bounded(stream_write, encode({"schema_version": 1, "scope": "i5-preparation-transport-error",
                            "uuid": apt.UUID, "nonce": nonce, "manifest_sha256": manifest_sha256,
                            "failure": (type(exc).__name__ + ": " + str(exc))[:2048], "i5_ready": False}),
                            deadline=until(1))
                    except BaseException:
                        pass  # Closed result pipe remains a transport failure.
                    os._exit(2)
            os.close(guest_read)
            os.close(stream_write)
            os.close(guest_ack_write)
            for fd in extra_fds: os.close(fd)
            for fd in transport_fds: os.close(fd)
            guest_lease = supervision.Lease(nonce, manifest_sha256, started=time.monotonic())
            guest_closed = False
            def relay():
                nonlocal guest_closed
                apt.require(not guest_closed, "renewal after guest control ended")
                try:
                    write_frame(guest_write, guest_lease.frame(lease.sequence))
                except BrokenPipeError:
                    # Completion can close control just before the last result
                    # bytes arrive. Do not ACK or extend the guest lease; drain
                    # the bounded result under the existing host deadline.
                    guest_closed = True
                    return
                while True:
                    checkpoint()
                    lease.check(time.monotonic())
                    ready, _, _ = select.select([guest_ack_read, control_read], [], [], 0.01)
                    if control_read in ready:
                        apt.require(not supervision.drain_lease(control_read, lease, time.monotonic()),
                                    "renewal before guest acknowledgement")
                    if guest_ack_read in ready:
                        raw_receipt = os.read(guest_ack_read, supervision.MAX_FRAME)
                        if not raw_receipt:
                            guest_closed = True
                            return
                        receipt = apt.decode(raw_receipt, supervision.MAX_FRAME)
                        apt.require(receipt == {"schema_version": 1, "scope": "i5-preparation-guest-ack",
                            "uuid": apt.UUID, "nonce": nonce, "manifest_sha256": manifest_sha256,
                            "sequence": lease.sequence} and type(receipt["sequence"]) is int and
                            type(receipt["schema_version"]) is int, "guest acknowledgement binding")
                        break
                write_frame(ack_write, encode({"schema_version": 1, "scope": "i5-preparation-host-ack",
                    "uuid": apt.UUID, "nonce": nonce, "manifest_sha256": manifest_sha256, "sequence": lease.sequence}))
            relay()
            def validate(raw):
                value = apt.decode(raw, 6 * apt.MIB)
                if type(value) is dict and value.get("scope") == "i5-preparation-transport-error":
                    apt.fields(value, "schema_version scope uuid nonce manifest_sha256 failure i5_ready")
                    apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                                value["uuid"] == apt.UUID and value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256 and
                                value["i5_ready"] is False and type(value["failure"]) is str and 0 < len(value["failure"]) <= 2048,
                                "transport failure binding")
                    raise ValueError(value["failure"])
                packet["export"] = validate_export(raw, nonce, manifest_sha256)
                apt.require(packet["export"]["passed"], "guest preparation/export failed")
            packet["watchdog"] = supervision.watch_transport(control_read, stream_read, lease,
                validate=validate, recover=recover_once, renewed=relay, manage_signals=False,
                cancelled=lambda: bool(interrupted))
        except (OSError, ValueError, RuntimeError) as exc:
            packet["watchdog"] = {"transport_complete": False, "failure": str(exc), "recovery": None, "i5_ready": False}
            if not recovered:
                try:
                    packet["watchdog"]["recovery"] = recover_once()
                except (OSError, ValueError, RuntimeError) as failure:
                    packet["cleanup_errors"].append("recovery: " + str(failure))
        finally:
            if guest_write is not None: os.close(guest_write)
            if stream_read is not None: os.close(stream_read)
            if guest_ack_read is not None: os.close(guest_ack_read)
            if child is not None:
                packet["transport_exit"] = wait_child(child, until(cleanup_seconds))
                if packet["transport_exit"] is None:
                    packet["cleanup_errors"].append("transport reap deadline")
                    # Exact newly created session only; never pgrep or VM PID.
                    try:
                        os.killpg(child, signal.SIGKILL)
                    except ProcessLookupError:
                        try:
                            os.kill(child, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    packet["transport_exit"] = wait_child(child, until(reap_seconds))
                    if packet["transport_exit"] is None:
                        packet["cleanup_errors"].append("transport kill/reap unconfirmed")
        packet["passed"] = bool(packet["watchdog"] and packet["watchdog"]["transport_complete"] and
                                packet["transport_exit"] == 0 and not packet["cleanup_errors"] and not interrupted)
        if interrupted and packet["watchdog"] and packet["watchdog"]["failure"] is None:
            packet["watchdog"]["failure"] = "host watchdog cancelled during transport cleanup"
        if not packet["passed"] and not recovered:
            try:
                packet["watchdog"]["recovery"] = recover_once()
            except (OSError, ValueError, RuntimeError) as failure:
                packet["cleanup_errors"].append("recovery: " + str(failure))
        try:
            write_bounded(report_write, encode(packet), deadline=until(2),
                          checkpoint=checkpoint if packet["passed"] else lambda: None)
        except (OSError, ValueError, RuntimeError):
            if not recovered:
                try:
                    recover_once()
                except (OSError, ValueError, RuntimeError):
                    pass  # Exit failure remains observable; consumer is gone.
            os._exit(2)
        os._exit(0 if packet["passed"] else 2)
    os.close(control_read)
    os.close(report_write)
    os.close(ack_write)
    return pid, control_write, report_read, ack_read


NATIVE_EXPORT_SCOPE = "i5-preparation-native-lifecycle-export"
NATIVE_FACT_SCOPE = "i5-preparation-native-lifecycle-facts"
NATIVE_FACT_LIMIT = 128 * 1024
NATIVE_LIFECYCLE_FLAGS = ("execution_authorized", "install_authorized", "physical_verified", "i5_ready")


def _register_object(registry, events, value):
    apt.fields(value, "role state identity bytes sequence")
    role, state, ident = value["role"], value["state"], value["identity"]
    apt.require(role in isolation.NATIVE_CREATE_ORDER and state in ("intent", "bound", "cleaned") and value["sequence"] is None and
                type(value["bytes"]) is int and value["bytes"] == (1024 if role in ("lease", "ack") else 0), "native object registration fields")
    if state == "intent":
        intended = [item["role"] for item in events if item["state"] == "intent"]
        apt.require(ident is None and role not in registry and role not in intended and
                    all(row["state"] == "bound" for row in registry.values()) and
                    not any(item["state"] == "cleaned" for item in events) and
                    intended + [role] == list(isolation.NATIVE_CREATE_ORDER[:len(intended) + 1]),
                    "native duplicate/out-of-order intent")
    else:
        apt.require(type(ident) is list and len(ident) == 2 and all(type(n) is int and n > 0 for n in ident), "native registration identity")
        apt.require(role in registry and (registry[role]["state"] == "intent" if state == "bound" else
                    registry[role]["state"] == "bound" and registry[role]["identity"] == ident), "native registration order")
    apt.require(len(events) < 27, "native registration count")
    if state == "cleaned":
        cleaned = [item["role"] for item in events if item["state"] == "cleaned"] + [role]
        apt.require(cleaned == [item for item in isolation.NATIVE_CLEAN_ORDER if item in cleaned],
                    "native cleanup registration order")
    events.append(dict(value))
    if state == "cleaned": registry.pop(role)
    else: registry[role] = dict(value)


def _validate_observations(value, nonce, digest):
    for key in ("initialization", "independent_readback"):
        record = value[key]
        apt.fields(record, "schema_version scope uuid nonce manifest_sha256 backend_kind cgroup_snapshots "
                   "prerequisite_observations objects input_bytes input_files_sha256 " + " ".join(isolation.NATIVE_FALSE_FLAGS))
        apt.require(record.get("scope") == "i5-preparation-native-initialization" and
                    type(record.get("schema_version")) is int and record["schema_version"] == 1 and record.get("uuid") == apt.UUID and
                    record.get("nonce") == nonce and record.get("manifest_sha256") == digest and
                    record.get("backend_kind") == "injected-offline" and
                    all(record.get(flag) is False for flag in isolation.NATIVE_FALSE_FLAGS) and
                    set(record.get("objects", {})) == {*isolation.NATIVE_CREATE_ORDER, "readonly_input"}, "native lifecycle initialization facts")
        apt.require(type(record["input_bytes"]) is int and 0 < record["input_bytes"] <= isolation.STORAGE["input"] and
                    apt.digest(record["input_files_sha256"]), "native input projection")
        prerequisites = record["prerequisite_observations"]
        apt.fields(prerequisites, "root_parent cgroup_root readonly_input")
        for role, item in prerequisites.items():
            apt.fields(item, "dev ino mount_id path device filesystem filesystem_magic mount_options super_options capacity_bytes inodes")
            apt.require(all(type(item[k]) is int and item[k] > 0 for k in ("dev", "ino", "mount_id", "filesystem_magic")) and
                        type(item["device"]) is str and type(item["path"]) is str and item["path"].startswith("/") and
                        all(type(item[k]) is list and item[k] == sorted(set(item[k])) and all(type(v) is str for v in item[k])
                            for k in ("mount_options", "super_options")), "native prerequisite fields")
            if role == "cgroup_root":
                apt.require(item["path"] == "/sys/fs/cgroup/radishlink-i5-preparation" and item["filesystem"] == "cgroup2" and
                            item["filesystem_magic"] == isolation.NATIVE_CGROUP2 and item["capacity_bytes"] is None and
                            item["inodes"] is None and "rw" in item["mount_options"] and "rw" in item["super_options"],
                            "native cgroup prerequisite")
            else:
                maximum = isolation.NATIVE_ROOT_BYTES if role == "root_parent" else isolation.STORAGE["input"]
                apt.require(type(item["capacity_bytes"]) is int and 0 < item["capacity_bytes"] <= maximum and
                            type(item["inodes"]) is int and item["inodes"] > 0, "native prerequisite capacity")
                if role == "root_parent":
                    apt.require(item["path"] == "/run/radishlink-i5-preparation" and item["filesystem"] == "tmpfs" and
                                item["filesystem_magic"] == isolation.NATIVE_TMPFS and
                                item["inodes"] <= isolation.NATIVE_ROOT_INODES and
                                {"rw", "nosuid", "nodev", "noexec"} <= set(item["mount_options"]) and
                                {"rw", "noswap"} <= set(item["super_options"]) and
                                "ro" not in item["mount_options"] + item["super_options"], "native root prerequisite")
                else:
                    apt.require(item["filesystem"] in isolation.NATIVE_INPUT_FS and
                                item["filesystem_magic"] == isolation.NATIVE_INPUT_FS[item["filesystem"]] and
                                "ro" in item["mount_options"] and "ro" in item["super_options"] and
                                "rw" not in item["mount_options"] + item["super_options"] and
                                record["input_bytes"] <= item["capacity_bytes"], "native input prerequisite")
        for key_name in ("dev", "mount_id", "device"):
            apt.require(len({item[key_name] for item in prerequisites.values()}) == 3, "native prerequisite domain alias")
        groups = record["cgroup_snapshots"]
        apt.fields(groups, "parent supervisor worker")
        for role, item in groups.items():
            apt.fields(item, "path identity type procs subtree children limits events memory_events pids_events")
            apt.require(type(item["identity"]) is list and all(type(n) is int and n > 0 for n in item["identity"]),
                        "native cgroup identity types")
            converted = dict(item, identity=tuple(item["identity"]))
            isolation.verify_cgroup(converted, role)
            apt.require(item["procs"] == [] and item["events"]["populated"] == 0, "native initial cgroup must be empty")
            for name in ("events", "memory_events", "pids_events"):
                apt.require(type(item[name]) is dict and all(type(n) is int and n == 0 for n in item[name].values()),
                            "native cgroup strict zero counters")
        objects, identities = record["objects"], []
        apt.fields(objects, " ".join((*isolation.NATIVE_CREATE_ORDER, "readonly_input")))
        root = "/run/radishlink-i5-preparation/" + nonce
        cgroup = "/sys/fs/cgroup/radishlink-i5-preparation/" + nonce
        input_path = prerequisites["readonly_input"]["path"]
        parsed_input = Path(input_path)
        apt.require(str(parsed_input) == input_path and parsed_input.is_absolute() and ".." not in parsed_input.parts and
                    parsed_input != Path("/") and parsed_input != Path(root) and Path(root) not in parsed_input.parents and
                    parsed_input not in Path(root).parents and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./-" for c in input_path),
                    "native readonly input lexical/disjoint path")
        paths = dict(guest_root=root, work=root + "/work", result=root + "/result", control=root + "/control",
                     lease=root + "/control/lease.slot", ack=root + "/control/ack.slot", cgroup_parent=cgroup,
                     cgroup_supervisor=cgroup + "/supervisor", cgroup_worker=cgroup + "/worker", readonly_input=input_path)
        for role, row in objects.items():
            apt.fields(row, "before after independent_readback")
            apt.require((row["before"] is not None) == (role == "readonly_input"), "native object creation baseline")
            observer_values = {"before": "preexisting-observer", "after": "creator", "independent_readback": "independent-reader"}
            after = row["after"]
            for observation, item in row.items():
                if item is None: continue
                apt.fields(item, "observer realm role path nonce manifest_sha256 dev ino uid gid mode kind nlink bytes sha256 symlink limits")
                apt.require(item["observer"] == observer_values[observation] and item["realm"] == "guest" and item["role"] == role and
                            item["path"] == paths[role] and item["nonce"] == nonce and item["manifest_sha256"] == digest and
                            all(type(item[k]) is int and item[k] > 0 for k in ("dev", "ino", "nlink")) and
                            all(type(item[k]) is int and item[k] == 0 for k in ("uid", "gid")) and
                            type(item["mode"]) is int and type(item["bytes"]) is int and item["symlink"] is False,
                            "native object observation identity/types")
                slot, readonly = role in ("lease", "ack"), role == "readonly_input"
                apt.require(item["mode"] == (0o600 if slot else 0o555 if readonly else 0o700) and
                            item["kind"] == ("regular" if slot else "readonly-tree" if readonly else "directory") and
                            item["bytes"] == (1024 if slot else record["input_bytes"] if readonly else 0) and
                            item["sha256"] == (hashlib.sha256(bytes(1024)).hexdigest() if slot else digest if readonly else None) and
                            (not slot or item["nlink"] == 1), "native object observation content")
                expected_limits = isolation.LIMITS[role.removeprefix("cgroup_")] if role.startswith("cgroup_") else None
                apt.require(item["limits"] == expected_limits, "native object limits")
                apt.require({k: v for k, v in item.items() if k != "observer"} ==
                            {k: v for k, v in after.items() if k != "observer"}, "native object independent readback mismatch")
            identities.append((after["dev"], after["ino"]))
            domain = "readonly_input" if role == "readonly_input" else "cgroup_root" if role.startswith("cgroup_") else "root_parent"
            apt.require(after["dev"] == prerequisites[domain]["dev"], "native object backing domain")
            if role == "readonly_input":
                apt.require(after["ino"] == prerequisites[domain]["ino"], "native input prerequisite identity")
            if role.startswith("cgroup_"):
                snapshot = groups[role.removeprefix("cgroup_")]
                apt.require(snapshot["identity"] == [after["dev"], after["ino"]] and snapshot["path"] == after["path"],
                            "native cgroup object/snapshot binding")
        apt.require(len(set(identities)) == 10, "native object identity alias")
    apt.require(value["initialization"] == value["independent_readback"], "native independent readback changed")


def validate_native_export(raw, nonce, manifest_sha256):
    value = apt.decode(raw, EXPORT_LIMIT)
    apt.fields(value, "schema_version scope uuid nonce manifest_sha256 evidence_kind i5_ready passed task_export native_lifecycle")
    apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["scope"] == NATIVE_EXPORT_SCOPE and
                value["uuid"] == apt.UUID and value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256 and
                value["evidence_kind"] == "synthetic" and value["i5_ready"] is False and type(value["passed"]) is bool,
                "native export scope/binding")
    facts = value["native_lifecycle"]
    apt.fields(facts, "schema_version scope uuid nonce manifest_sha256 delivery_sha256 backend_kind execution_authorized "
               "install_authorized physical_verified i5_ready initialization independent_readback cleanup registered pending "
               "processes owner_exit owner_reaped fd_closed task_supervisor_reaped task_worker_reaped first_failure cleanup_errors")
    apt.require(type(facts["schema_version"]) is int and facts["schema_version"] == 1 and facts["scope"] == NATIVE_FACT_SCOPE and
                facts["uuid"] == apt.UUID and facts["nonce"] == nonce and facts["manifest_sha256"] == manifest_sha256 and
                apt.digest(facts["delivery_sha256"]) and facts["backend_kind"] == "injected-offline" and
                all(facts[flag] is False for flag in NATIVE_LIFECYCLE_FLAGS), "native facts binding/STOP flags")
    apt.require(len(encode(facts)) <= NATIVE_FACT_LIMIT and type(facts["registered"]) is list and
                type(facts["pending"]) is dict and type(facts["cleanup_errors"]) is list and len(facts["cleanup_errors"]) <= 12 and
                all(type(item) is str and 0 < len(item) <= 1000 for item in facts["cleanup_errors"]) and
                (facts["first_failure"] is None or type(facts["first_failure"]) is str and 0 < len(facts["first_failure"]) <= 1000),
                "native facts limits/types")
    for flag in ("owner_reaped", "fd_closed", "task_supervisor_reaped", "task_worker_reaped"):
        apt.require(type(facts[flag]) is bool, "native lifecycle boolean state")
    apt.require((facts["owner_exit"] is None or type(facts["owner_exit"]) is int) and
                facts["owner_reaped"] == (facts["owner_exit"] is not None), "native owner reap/exit contradiction")
    apt.fields(facts["processes"], "owner supervisor worker")
    processes = facts["processes"]
    apt.require(type(processes["owner"]) is int and processes["owner"] > 1 and
                all(pid is None or type(pid) is int and pid > 1 for pid in processes.values()) and
                len({pid for pid in processes.values() if pid is not None}) == sum(pid is not None for pid in processes.values()) and
                (not facts["task_supervisor_reaped"] or processes["supervisor"] is not None) and
                (not facts["task_worker_reaped"] or processes["worker"] is not None), "native process tickets/reap binding")
    registry, events = {}, []
    for event in facts["registered"]: _register_object(registry, events, event)
    apt.require(encode(registry) == encode(facts["pending"]), "native registration/pending mismatch")
    init, readback, cleanup = facts["initialization"], facts["independent_readback"], facts["cleanup"]
    apt.require((init is None) == (readback is None), "native initialization readback pair")
    if init is not None:
        _validate_observations(dict(initialization=init, independent_readback=readback), nonce, manifest_sha256)
        bound = {e["role"]: e["identity"] for e in events if e["state"] == "bound"}
        apt.require(set(bound) == set(isolation.NATIVE_CREATE_ORDER), "native initialization registry incomplete")
        for role, ident in bound.items():
            observations = init["objects"][role]
            for key in ("after", "independent_readback"):
                item = observations[key]
                apt.require([item["dev"], item["ino"]] == ident and item["role"] == role and
                            item["nonce"] == nonce and item["manifest_sha256"] == manifest_sha256,
                            "native initialization/registration identity mismatch")
    if cleanup is not None:
        apt.fields(cleanup, "schema_version scope uuid nonce manifest_sha256 backend_kind errors cleaned pending " + " ".join(isolation.NATIVE_FALSE_FLAGS))
        apt.require(type(cleanup["schema_version"]) is int and cleanup["schema_version"] == 1 and
                    cleanup["scope"] == "i5-preparation-native-cleanup" and cleanup["uuid"] == apt.UUID and
                    cleanup["nonce"] == nonce and cleanup["manifest_sha256"] == manifest_sha256 and
                    cleanup["backend_kind"] == "injected-offline" and all(cleanup[f] is False for f in isolation.NATIVE_FALSE_FLAGS),
                    "native cleanup scope/binding")
        apt.require(type(cleanup["errors"]) is list and type(cleanup["cleaned"]) is list and type(cleanup["pending"]) is dict and
                    len(cleanup["errors"]) <= 12 and all(type(e) is str and 0 < len(e) <= 1000 for e in cleanup["errors"]) and
                    all(error in facts["cleanup_errors"] for error in cleanup["errors"]) and
                    cleanup["cleaned"] == [e["role"] for e in events if e["state"] == "cleaned"] and
                    encode(cleanup["pending"]) == encode({key: {field: row[field] for field in ("state", "identity")} for key, row in registry.items()}),
                    "native cleanup/registry mismatch")
    task = value["task_export"]
    if task is not None:
        apt.require(type(task) is dict and task.get("scope") == EXPORT_SCOPE, "native recursive task export rejected")
        validate_export(encode(task), nonce, manifest_sha256)
        apt.require(not facts["task_worker_reaped"] or task["supervision"]["reaped"], "native task reap contradiction")
    expected = bool(facts["first_failure"] is None and facts["owner_exit"] == 0 and facts["owner_reaped"] and
                    facts["fd_closed"] and facts["task_supervisor_reaped"] and facts["task_worker_reaped"] and
                    init is not None and cleanup is not None and not registry and not cleanup["errors"] and
                    not facts["cleanup_errors"] and task and task["passed"])
    apt.require(value["passed"] == expected and (expected or facts["first_failure"] or facts["cleanup_errors"] or
                facts["owner_exit"] != 0), "native lifecycle completion contradiction")
    return value
