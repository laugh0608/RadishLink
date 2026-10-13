"""Independent preparation supervision and bounded lease protocol.

No guest/UTM launcher is enabled. A separately forked supervisor admits a
blocked child to its cgroup before releasing it. Only the supervisor owns the
lease read end; worker code cannot renew its own lease. Kernel and VM actions
are injected in offline tests, while pipes/process lifetimes are real.
"""

import ctypes
import json
import math
import os
import select
import signal
import time

from sw_i5_apt import GUEST_SECONDS, HOST_SECONDS, UUID, decode, digest, fields, require

MAX_FRAME = 512
MAX_REPORT = 16384
LEASE_SECONDS = 15
CLEANUP_SECONDS = 20


class Lease:
    def __init__(self, nonce, manifest_sha256, *, started, total=GUEST_SECONDS, silence=LEASE_SECONDS, side="guest"):
        import re
        require(type(nonce) is str and re.fullmatch(r"[0-9a-f]{32}", nonce) and digest(manifest_sha256), "lease binding")
        require(side in {"guest", "host"}, "lease side")
        maximum = GUEST_SECONDS if side == "guest" else HOST_SECONDS
        require(all(type(v) in (int, float) and math.isfinite(v) for v in (started, total, silence)) and
                0 < silence <= LEASE_SECONDS and silence <= total <= maximum, "lease deadlines")
        self.side = side
        self.scope = "i5-preparation-lease" if side == "guest" else "i5-preparation-host-lease"
        self.nonce, self.manifest_sha256 = nonce, manifest_sha256
        self.deadline, self.last, self.silence = started + total, started, silence
        self.sequence, self.buffer, self.cancelled = -1, b"", False
        self.acknowledge = lambda sequence: None

    def feed(self, raw, now):
        self.check(now, require_started=False)
        require(type(raw) is bytes and 0 < len(raw) <= MAX_FRAME, "invalid lease read")
        self.buffer += raw
        require(len(self.buffer) <= MAX_FRAME, "lease frame limit")
        if b"\n" not in self.buffer:
            return
        # One message per observation prevents a buffered burst from extending
        # a lease long after its real sender has disappeared.
        line, remaining = self.buffer.split(b"\n", 1)
        require(not remaining, "multiple buffered lease frames")
        self.buffer = b""
        value = decode(line, MAX_FRAME)
        fields(value, "schema_version scope uuid nonce manifest_sha256 sequence action")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["scope"] == self.scope and value["uuid"] == UUID and
                value["nonce"] == self.nonce and value["manifest_sha256"] == self.manifest_sha256 and
                type(value["sequence"]) is int and value["sequence"] == self.sequence + 1 and
                value["action"] in {"renew", "cancel"}, "stale/invalid lease message")
        self.sequence, self.last = value["sequence"], now
        self.cancelled = value["action"] == "cancel"
        self.check(now)
        self.acknowledge(self.sequence)

    def check(self, now, require_started=True):
        require(type(now) in (int, float) and math.isfinite(now) and now >= self.last, "monotonic clock moved backwards")
        require(not self.cancelled, "lease cancelled")
        require(now < self.deadline, "absolute preparation deadline")
        require(now - self.last < self.silence, "lease expired")
        require(not require_started or self.sequence >= 0, "initial lease required")

    def frame(self, sequence, action="renew"):
        return (json.dumps({"schema_version": 1, "scope": self.scope, "uuid": UUID,
                "nonce": self.nonce, "manifest_sha256": self.manifest_sha256,
                "sequence": sequence, "action": action}, separators=(",", ":")) + "\n").encode()


def drain_lease(fd, lease, now):
    sequence = lease.sequence
    readable, _, _ = select.select([fd], [], [], 0)
    if readable:
        raw = os.read(fd, MAX_FRAME)
        require(raw, "lease channel closed")
        lease.feed(raw, now)
    lease.check(now)
    return lease.sequence != sequence


def enable_subreaper():
    require(os.uname().sysname == "Linux", "Linux subreaper required")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "preparation subreaper")


class ForkWorker:
    """A child blocked on a private pipe before any caller-provided work."""
    def __init__(self, work, prepare=lambda: None):
        self.work, self.prepare, self.pid, self.release_fd, self.ready_fd, self.code = work, prepare, None, None, None, None
        self.admission_fd = None

    def spawn(self):
        read_fd, write_fd = os.pipe()
        ready_read, ready_write = os.pipe()
        try:
            pid = os.fork()
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            os.close(ready_read)
            os.close(ready_write)
            raise
        if pid == 0:
            error_fd = ready_write
            try:
                os.close(write_fd)
                os.close(ready_read)
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                # This fork happens in a dedicated single-threaded supervisor.
                # Close lease, report and cgroup descriptors before admission.
                maximum = os.sysconf("SC_OPEN_MAX")
                keep = sorted((read_fd, ready_write))
                first = 3
                for fd in keep:
                    os.closerange(first, fd)
                    first = fd + 1
                os.closerange(first, maximum)
                require(os.read(read_fd, 1) == b"S", "worker setup admission cancelled")
                self.prepare()
                require(os.write(ready_write, b"P") == 1, "worker setup acknowledgement")
                os.close(ready_write)
                error_fd = None
                require(os.read(read_fd, 1) == b"G", "worker tool admission cancelled")
                os.close(read_fd)
                code = self.work()
                os._exit(code if type(code) is int and 0 <= code <= 255 else 2)
            except BaseException as exc:
                diagnostic = (type(exc).__name__ + ": " + str(exc)).encode("utf-8", errors="replace")[:480]
                try:
                    os.write(error_fd if error_fd is not None else 2, (b"E" if error_fd is not None else b"") + diagnostic)
                except OSError:
                    pass  # Nonzero exit remains observable even when evidence is full/lost.
                os._exit(2)
        os.close(read_fd)
        os.close(ready_write)
        self.pid, self.release_fd, self.ready_fd, self.admission_fd = pid, write_fd, ready_read, read_fd
        return pid

    def admit_setup(self):
        require(os.write(self.release_fd, b"S") == 1, "setup admission short write")

    def ready(self):
        ready, _, _ = select.select([self.ready_fd], [], [], 0)
        if not ready:
            return False
        response = os.read(self.ready_fd, MAX_FRAME)
        require(response == b"P", "worker setup failed: " + response.decode("utf-8", errors="replace"))
        os.close(self.ready_fd)
        self.ready_fd = None
        return True

    def release(self):
        require(self.release_fd is not None, "worker already released")
        try:
            require(os.write(self.release_fd, b"G") == 1, "admission short write")
        finally:
            os.close(self.release_fd)
            self.release_fd = None

    def poll(self):
        if self.code is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.code = os.waitstatus_to_exitcode(status)
        return self.code

    def cancel_admission(self):
        if self.release_fd is not None:
            os.close(self.release_fd)
            self.release_fd = None
        if self.ready_fd is not None:
            os.close(self.ready_fd)
            self.ready_fd = None


def supervise(worker, boundary, guard, lease_fd, lease, *, clock=time.monotonic,
              pause=time.sleep, cleanup_seconds=CLEANUP_SECONDS, reap=None, exporter=None):
    """Run in the independent supervisor, outside the worker cgroup.

    The injected boundary owns cgroup.kill/populated; the injected guard checks
    immutable domains. A production caller also installs Linux subreaping and
    supplies reap(). Neither process-group absence nor leader exit is enough.
    """
    require(0 < cleanup_seconds <= CLEANUP_SECONDS, "cleanup deadline")
    result = {"schema_version": 1, "scope": "i5-preparation-supervision", "uuid": UUID,
              "nonce": lease.nonce, "manifest_sha256": lease.manifest_sha256, "i5_ready": False,
              "passed": False, "failure": None, "cleanup_errors": [], "admitted": False,
              "worker_exit": None, "population_empty": False, "reaped": False}
    started, admitted, interrupted = False, False, []
    previous = {}
    def interrupt(number, _frame):
        if not interrupted:
            interrupted.append(number)
    try:
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, interrupt)
        drain_lease(lease_fd, lease, clock())
        guard.before_admission()
        require(not boundary.populated(), "worker cgroup not empty before admission")
        pid = worker.spawn()
        started = True
        boundary.attach(pid)
        admitted = True
        guard.bind_worker(pid, worker.admission_fd)
        worker.admit_setup()
        while not worker.ready():
            require(not interrupted, "supervisor cancelled during setup")
            drain_lease(lease_fd, lease, clock())
            guard.check_cgroups()
            pause(0.01)
        guard.check()
        if exporter is not None:
            exporter.pin(pid, guard)
        drain_lease(lease_fd, lease, clock())
        require(not interrupted, "supervisor cancelled before release")
        worker.release()
        result["admitted"] = True
        while True:
            require(not interrupted, "supervisor cancelled")
            drain_lease(lease_fd, lease, clock())
            guard.check_cgroups()
            code = worker.poll()
            if code is not None:
                result["worker_exit"] = code
                require(code == 0, "preparation worker failed: " + str(code))
                # cgroup.procs omits zombies. Reaping has a separate result.
                require(not boundary.populated(), "worker descendants remain")
                drain_lease(lease_fd, lease, clock())
                break
            pause(min(0.05, max(0, lease.deadline - clock())))
    except (OSError, ValueError, RuntimeError) as exc:
        result["failure"] = str(exc)
    finally:
        if started:
            worker.cancel_admission()
            # A write to cgroup.procs can succeed before the admission readback
            # fails. Always kill the pinned, previously empty owned group.
            try:
                boundary.kill()
            except (OSError, ValueError, RuntimeError) as exc:
                result["cleanup_errors"].append("cgroup kill: " + str(exc))
            until = clock() + cleanup_seconds
            while True:
                try:
                    code = worker.poll()
                    empty = not boundary.populated()
                    reaped = reap(worker) if reap is not None else code is not None
                    if reap is not None:
                        code = worker.poll()
                    if code is not None:
                        result["worker_exit"] = code
                    result["population_empty"], result["reaped"] = empty, reaped
                    if empty and reaped and code is not None:
                        break
                except (OSError, ValueError, RuntimeError) as exc:
                    result["cleanup_errors"].append("cleanup observation: " + str(exc))
                    break
                if clock() >= until:
                    result["cleanup_errors"].append("population/reaping deadline")
                    break
                pause(min(0.02, max(0, until - clock())))
            try:
                guard.check_cgroups()
            except (OSError, ValueError, RuntimeError) as exc:
                result["cleanup_errors"].append("postflight: " + str(exc))
        else:
            # A rejected initial lease/baseline never grants cleanup authority.
            result["population_empty"] = False
        for number, handler in previous.items():
            signal.signal(number, handler)
    result["passed"] = bool(admitted and result["worker_exit"] == 0 and result["population_empty"] and
                            result["reaped"] and not result["failure"] and not result["cleanup_errors"])
    return result


def reap_descendants(worker):
    """For a dedicated Linux subreaper only; no unrelated child processes."""
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return True
        if pid == 0:
            return False
        if pid == worker.pid:
            worker.code = os.waitstatus_to_exitcode(status)


def fork_supervisor(work, boundary, guard, nonce, manifest_sha256, *, total=GUEST_SECONDS,
                    silence=LEASE_SECONDS, subreaper=enable_subreaper, prepare=lambda: None,
                    control_fd=None, exporter=None, keep_fds=(), ack_fd=None):
    """Internal process wiring, not a preparation authorization API.

    Return the supervisor PID, caller's lease write FD and bounded report read
    FD. Caller must close the lease on failure and wait/reap the supervisor.
    No FD permitting renewal is inherited by worker or supervisor. The future
    host adapter must provide a separate recovery route if this process dies.
    """
    lease_read, lease_write = os.pipe() if control_fd is None else (os.dup(control_fd), None)
    report_read, report_write = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        for fd in (lease_read, lease_write, report_read, report_write):
            if fd is not None:
                os.close(fd)
        raise
    if pid == 0:
        try:
            # No inherited renewal writer or unrelated pipe may keep a lost
            # controller alive. Kernel directory FDs are explicitly retained.
            kernel_fds = []
            candidates = [boundary]
            probe = vars(guard).get("probe")
            groups = vars(probe).get("groups", {}) if probe is not None else {}
            if isinstance(groups, dict):
                candidates.extend(groups.values())
            for candidate in candidates:
                descriptor = vars(candidate).get("fd")
                if type(descriptor) is int and descriptor >= 3:
                    kernel_fds.append(descriptor)
            keep = sorted({lease_read, report_write, *keep_fds, *kernel_fds, *([] if ack_fd is None else [ack_fd])})
            first = 3
            for fd in keep:
                os.closerange(first, fd)
                first = fd + 1
            os.closerange(first, os.sysconf("SC_OPEN_MAX"))
            os.setsid()
            guard.admit_supervisor()
            subreaper()
            lease = Lease(nonce, manifest_sha256, started=time.monotonic(), total=total, silence=silence)
            if ack_fd is not None:
                from sw_i5_preparation_channels import encode, write_frame
                lease.acknowledge = lambda sequence: write_frame(ack_fd, encode({"schema_version": 1,
                    "scope": "i5-preparation-guest-ack", "uuid": UUID, "nonce": nonce,
                    "manifest_sha256": manifest_sha256, "sequence": sequence}))
            # Wait for the first complete lease without launching any child.
            until = time.monotonic() + silence
            while lease.sequence < 0:
                remaining = until - time.monotonic()
                require(remaining > 0, "initial lease timeout")
                ready, _, _ = select.select([lease_read], [], [], remaining)
                require(ready, "initial lease timeout")
                raw = os.read(lease_read, MAX_FRAME)
                require(raw, "initial lease channel closed")
                lease.feed(raw, time.monotonic())
            result = supervise(ForkWorker(work, prepare), boundary, guard, lease_read, lease,
                               reap=reap_descendants if subreaper is enable_subreaper else None, exporter=exporter)
            if exporter is not None:
                from sw_i5_preparation_channels import encode, write_bounded
                def checkpoint():
                    drain_lease(lease_read, lease, time.monotonic())
                try:
                    packet = exporter.collect(result, checkpoint)
                    write_bounded(report_write, encode(packet), deadline=min(lease.deadline, time.monotonic() + 2))
                finally:
                    exporter.close()
                os._exit(0 if packet["passed"] else 2)
            raw = (json.dumps(result, separators=(",", ":")) + "\n").encode()
            require(len(raw) <= MAX_REPORT, "supervisor report limit")
            # Nonblocking: a dead or stalled result consumer cannot hold the
            # supervisor forever after cleanup has completed.
            os.set_blocking(report_write, False)
            require(os.write(report_write, raw) == len(raw), "supervisor report short write")
            os._exit(0 if result["passed"] else 2)
        except BaseException as exc:
            if exporter is not None:
                try:
                    from sw_i5_preparation_channels import encode, write_bounded
                    failure = (type(exc).__name__ + ": " + str(exc))[:2048]
                    report = {"schema_version": 1, "scope": "i5-preparation-supervision", "uuid": UUID,
                              "nonce": nonce, "manifest_sha256": manifest_sha256, "i5_ready": False,
                              "passed": False, "failure": failure, "cleanup_errors": [], "admitted": False,
                              "worker_exit": None, "population_empty": False, "reaped": False}
                    packet = exporter.collect(report, lambda: None)
                    write_bounded(report_write, encode(packet), deadline=time.monotonic() + 2)
                    exporter.close()
                except BaseException:
                    pass  # Broken/full report channel still produces nonzero exit.
            os._exit(2)
    os.close(lease_read)
    os.close(report_write)
    return pid, lease_write, report_read


def watch_transport(lease_fd, result_fd, lease, *, validate, recover, clock=time.monotonic,
                    transport_limit=6 * 1024 * 1024, renewed=lambda: None,
                    cancelled=lambda: False, manage_signals=True):
    """Host watchdog loop, in a process independent of a blocking transport.

    Caller owns/reaps this process and the transport. recover() uses the fixed
    start-attempt ticket; this loop never starts a VM or retries collection.
    A completed frame is only transport evidence, not lifecycle acceptance.
    """
    require(0 < transport_limit <= 6 * 1024 * 1024, "host transport limit")
    require(lease.side == "host", "separate host lease required")
    data = bytearray()
    result = {"transport_complete": False, "failure": None, "recovery": None, "i5_ready": False}
    interrupted, previous = [], {}
    def interrupt(number, _frame):
        if not interrupted:
            interrupted.append(number)
    try:
        for number in ((signal.SIGTERM, signal.SIGINT) if manage_signals else ()):
            previous[number] = signal.signal(number, interrupt)
        while True:
            require(not interrupted and not cancelled(), "host watchdog cancelled")
            if drain_lease(lease_fd, lease, clock()):
                renewed()
            ready, _, _ = select.select([lease_fd, result_fd], [], [], min(0.05, max(0, lease.deadline - clock())))
            if result_fd not in ready:
                continue
            chunk = os.read(result_fd, min(65536, transport_limit - len(data) + 1))
            if chunk:
                require(len(data) + len(chunk) <= transport_limit, "host transport overflow")
                data.extend(chunk)
                continue
            require(data, "transport closed without result")
            validate(bytes(data))
            require(not interrupted and not cancelled(), "host watchdog cancelled")
            if drain_lease(lease_fd, lease, clock()):
                renewed()
            result["transport_complete"] = True
            return result
    except (OSError, ValueError, RuntimeError) as exc:
        result["failure"] = str(exc)
        # Keep the initiating failure even if recovery itself loses contact.
        try:
            result["recovery"] = recover()
        except (OSError, ValueError, RuntimeError) as cleanup:
            result["recovery"] = {"stopped": False, "failure": str(cleanup)}
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    return result
