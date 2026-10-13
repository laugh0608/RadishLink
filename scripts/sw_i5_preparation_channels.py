"""Offline preparation channel wiring; no public launcher or VM authorization.

Control -> independent host watchdog -> guest supervisor uses separate pipes.
The transport never owns a lease writer. Export uses directory FDs pinned while
worker admission is blocked, and reads only after complete worker reclamation.
All external transport/recovery and privileged setup are explicitly injected.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import stat
import time

import sw_i5_apt as apt
import sw_i5_preparation_supervisor as supervision

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
                  silence=supervision.LEASE_SECONDS, cleanup_seconds=25, recovery_seconds=120):
    """Return PID, caller lease writer, report reader and renewal ACK reader.

    transport(guest_control_read_fd, result_write_fd, guest_ack_write_fd) runs
    in its own child. Caller receives an ACK only after guest acceptance.
    recover() is the separately authorized, bound recovery adapter; offline
    callers inject a recorder. Neither callable can renew the host lease.
    Controller waits for the matching ACK before sending another frame; it
    cannot queue future renewals while the watchdog is starting or stalled.
    """
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
        close_except((control_read, report_write, ack_write))
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
            return bounded_recovery(recover, recovery_seconds)
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
                    close_except((guest_read, stream_write, guest_ack_write))
                    os.setsid()
                    signal.signal(signal.SIGTERM, signal.SIG_DFL)
                    signal.signal(signal.SIGINT, signal.SIG_DFL)
                    code = transport(guest_read, stream_write, guest_ack_write)
                    os._exit(code if type(code) is int and 0 <= code <= 255 else 2)
                except BaseException:
                    os._exit(2)
            os.close(guest_read)
            os.close(stream_write)
            os.close(guest_ack_write)
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
                packet["transport_exit"] = wait_child(child, time.monotonic() + cleanup_seconds)
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
                    packet["transport_exit"] = wait_child(child, time.monotonic() + 2)
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
            write_bounded(report_write, encode(packet), deadline=time.monotonic() + 2,
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
