"""Offline, explicitly injected preparation owner. No public/native launcher.

Controller EOF cancels an independent owner, even while RPC or filesystem
children block. The owner is the sole shutdown adapter caller. Its own SIGKILL,
unkillable kernel work and descendants escaping known process groups still need
external environment recovery; this internal chain is not that proof.
"""

import math
import os
from pathlib import Path
import select
import signal
import time

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels
import sw_i5_preparation_evidence as evidence
import sw_i5_preparation_transport as transport

CAPS = {"init": 6, "start": 60, "readiness": 60, "active": 600, "watchdog_cleanup": 25,
        "watchdog_report": 2, "shutdown": 120, "persist": 6, "output": 2, "reap": 2}
# Eight conservative, separately charged cleanup slots. The evidence worker is
# the same process in init/persist; charging both is deliberately conservative.
REAP_SLOTS = ("evidence_init_abort", "start", "readiness", "watchdog_transport_kill",
              "watchdog", "transport_group", "shutdown", "evidence_persist")


class Budget:
    def __init__(self, *, total=900, silence=15, **caps):
        apt.require(type(total) in (int, float) and math.isfinite(total) and 0 < total <= 900, "lifecycle total budget")
        apt.require(not set(caps) - set(CAPS), "unknown lifecycle budget")
        self.caps = dict(CAPS, **caps)
        apt.require(all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= CAPS[k]
                        for k, v in self.caps.items()), "lifecycle phase budget")
        # run_transport keeps its existing close<=4 and output<=2 limits. Its
        # work window is shortened instead of extending the active phase.
        apt.require(self.caps["active"] > 6 and type(silence) in (int, float) and math.isfinite(silence) and
                    0 < silence <= min(15, self.caps["active"]), "lifecycle lease/work budget")
        fixed = sum(v for k, v in self.caps.items() if k not in ("active", "reap")) + len(REAP_SLOTS) * self.caps["reap"]
        self.caps["active"] = min(self.caps["active"], total - fixed)
        apt.require(self.caps["active"] > 6, "insufficient lifecycle cleanup reserves")
        self.total, self.silence = total, min(silence, self.caps["active"])
        self.worst_seconds = fixed + self.caps["active"]

    def tail(self, stage):
        c = self.caps
        if stage == "init": return c["start"] + c["readiness"] + c["active"] + self.tail("active") + 3 * c["reap"]
        if stage == "start": return c["readiness"] + c["active"] + self.tail("active") + 2 * c["reap"]
        if stage == "readiness": return c["active"] + self.tail("active") + c["reap"]
        if stage == "active": return c["watchdog_cleanup"] + c["watchdog_report"] + self.tail("shutdown") + c["shutdown"] + 3 * c["reap"]
        if stage == "shutdown": return c["persist"] + c["output"] + 2 * c["reap"]
        if stage == "persist": return c["output"] + c["reap"]
        return 0

    def deadline(self, stage, now, absolute):
        return min(now + self.caps[stage], absolute - self.tail(stage))


def bounded_text(value, limit):
    text = str(value)
    if len(channels.encode(text)) <= limit: return text, False
    low, high, suffix = 0, len(text), " [truncated]"
    while low < high:
        middle = (low + high + 1) // 2
        if len(channels.encode(text[:middle] + suffix)) <= limit: low = middle
        else: high = middle - 1
    return text[:low] + suffix, True


def action_request(nonce, digest, action, mode="work"):
    return {"schema_version": 1, "scope": "i5-preparation-lifecycle-action", "uuid": apt.UUID,
            "nonce": nonce, "manifest_sha256": digest, "action": action, "mode": mode}


def _poll_child(pid, code):
    if code is not None: return code
    done, status = os.waitpid(pid, os.WNOHANG)
    return os.waitstatus_to_exitcode(status) if done else None


def _evidence_worker(parent, nonce, digest, command_fd, result_fd, absolute):
    """One store owner; initialize/read back before start, consume report once."""
    store, initialized = None, False
    try:
        channels.close_except((command_fd, result_fd))
        os.setsid()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        store = evidence.EvidenceStore(parent, nonce, digest)
        store.verify_attempt()
        initialized = True
        channels.write_frame(result_fd, channels.encode({"ready": {"schema_version": 1,
            "scope": "i5-preparation-evidence-ready", "uuid": apt.UUID, "nonce": nonce, "manifest_sha256": digest}, "error": None}))
        header = bytearray()
        while b"\n" not in header:
            apt.require(time.monotonic() < absolute, "evidence command absolute deadline")
            ready, _, _ = select.select([command_fd], [], [], 0.05)
            if not ready: continue
            data = os.read(command_fd, 1)
            apt.require(data, "evidence owner closed before commit")
            header.extend(data)
            apt.require(len(header) <= evidence.RECEIPT_LIMIT, "evidence command header limit")
        message = apt.decode(bytes(header), evidence.RECEIPT_LIMIT)
        apt.fields(message, "report_bytes process_exit lifecycle")
        apt.require(type(message["report_bytes"]) is int and 0 <= message["report_bytes"] <= channels.HOST_REPORT_LIMIT,
                    "evidence report byte limit")
        raw = bytearray()
        while len(raw) < message["report_bytes"]:
            apt.require(time.monotonic() < absolute, "evidence input absolute deadline")
            ready, _, _ = select.select([command_fd], [], [], 0.05)
            if not ready: continue
            data = os.read(command_fd, min(65536, message["report_bytes"] - len(raw)))
            apt.require(data, "evidence report incomplete")
            raw.extend(data)
        apt.require(os.read(command_fd, 1) == b"", "evidence accepts only one report")
        receipt = store.persist(bytes(raw), message["process_exit"], lifecycle=message["lifecycle"])
        channels.write_bounded(result_fd, channels.encode({"receipt": receipt, "error": None}), deadline=absolute)
        store.close()
        os._exit(0)
    except BaseException as exc:
        try:
            result = {"receipt" if initialized else "ready": None, "error": bounded_text(type(exc).__name__ + ": " + str(exc), evidence.FIRST_ERROR_BYTES)[0]}
            channels.write_bounded(result_fd, channels.encode(result), deadline=absolute)
        except BaseException:
            pass
        if store is not None: store.close()
        os._exit(2)


class _Owner:
    def __init__(self, cancel_fd, report_fd, parent, request, rpc, start, readiness, shutdown, budget, started):
        self.cancel_fd, self.report_fd, self.parent, self.request, self.rpc = cancel_fd, report_fd, parent, request, rpc
        self.adapters, self.budget, self.absolute = {"start": start, "readiness": readiness, "shutdown": shutdown}, budget, started + budget.total
        self.nonce, self.digest = request["nonce"], request["manifest_sha256"]
        self.interrupted, self.frozen, self.host_raw, self.host_exit, self.host_passed = [], False, b"", None, False
        self.delivery_errors = []
        self.facts = {"schema_version": 1, "scope": "i5-preparation-lifecycle", "uuid": apt.UUID,
            "nonce": self.nonce, "manifest_sha256": self.digest, "evidence_kind": "synthetic", "i5_ready": False,
            "total_seconds": budget.total, "attempt_ready": False, "start_attempted": False, "start": None,
            "readiness": None, "shutdown_attempted": False, "shutdown": None, "transport_registered": False,
            "sessions_reaped": True, "frozen": False, "first_failure": None, "failure_truncated": False,
            "cleanup_errors": [], "cleanup_truncated": False, "passed": False}

    def fail(self, reason):
        if self.facts["first_failure"] is None:
            text, truncated = bounded_text(reason, evidence.FIRST_ERROR_BYTES)
            self.facts["first_failure"], self.facts["failure_truncated"] = text or "lifecycle failed", truncated or text.endswith(" [truncated]")

    def cleanup_error(self, reason):
        if self.frozen:
            if len(channels.encode(self.delivery_errors)) < evidence.CLEANUP_BYTES // 2:
                self.delivery_errors.append(bounded_text(reason, evidence.CLEANUP_BYTES // 2)[0])
            return
        self.fail(reason)
        self.facts["sessions_reaped"] = False
        errors = self.facts["cleanup_errors"]
        text, truncated = bounded_text(reason, evidence.CLEANUP_BYTES // 2)
        if len(errors) < 16 and len(channels.encode(errors + [text])) <= evidence.CLEANUP_BYTES:
            errors.append(text)
        else: truncated = True
        self.facts["cleanup_truncated"] = self.facts["cleanup_truncated"] or truncated or text.endswith(" [truncated]")

    def checkpoint(self, *, abort=True):
        if not self.frozen:
            ready, _, _ = select.select([self.cancel_fd], [], [], 0)
            if ready:
                data = os.read(self.cancel_fd, 1)
                self.fail("controller cancelled" if data else "controller liveness EOF")
            if self.interrupted: self.fail("lifecycle owner cancelled by signal " + str(self.interrupted[0]))
        apt.require(time.monotonic() < self.absolute, "lifecycle absolute deadline")
        if abort: apt.require(self.facts["first_failure"] is None, self.facts["first_failure"] or "lifecycle failed")

    def until(self, stage):
        deadline = self.budget.deadline(stage, time.monotonic(), self.absolute)
        apt.require(deadline > time.monotonic(), stage + " has no reserved work window")
        return deadline

    def finish(self, pid, code, label, *, kill=False):
        deadline = min(self.absolute, time.monotonic() + self.budget.caps["reap"])
        try:
            return self._finish(pid, code, label, kill, deadline)
        except Exception as exc:
            # Cleanup failures remain diagnostics; never replace an earlier
            # callback/RPC failure or fall back into the fork caller.
            self.cleanup_error(label + " cleanup exception: " + type(exc).__name__ + ": " + str(exc))
            if not self.frozen: self.fail(label + " cleanup exception: " + str(exc))
            try: os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                if code is None:
                    try: os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            except OSError as error: self.cleanup_error(label + " emergency kill: " + str(error))
            while code is None and time.monotonic() < deadline:
                try: code = _poll_child(pid, code)
                except (ChildProcessError, OSError): break
                if code is None: time.sleep(0.005)
            return code

    def _finish(self, pid, code, label, kill, deadline):
        code = _poll_child(pid, code)
        normal_exit_until = min(deadline, time.monotonic() + min(0.25, self.budget.caps["reap"] / 2))
        if not kill and code is None:
            while code is None and time.monotonic() < normal_exit_until:
                code = _poll_child(pid, code)
                if code is None: time.sleep(0.005)
            if code is None:
                self.cleanup_error(label + " did not exit after response")
                kill = True
        if kill and code is None:
            try: os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                if code is None:
                    try: os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            except OSError as exc: self.cleanup_error(label + " kill: " + str(exc))
        while code is None and time.monotonic() < deadline:
            code = _poll_child(pid, code)
            if code is None: time.sleep(0.005)
        if code is None:
            self.cleanup_error(label + " reap unconfirmed")
            return None
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return code
        except OSError as exc:
            self.cleanup_error(label + " group check: " + str(exc))
            return code
        self.cleanup_error(label + " descendants remained after leader exit")
        try: os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError: pass
        while time.monotonic() < deadline:
            try: os.killpg(pid, 0)
            except ProcessLookupError: return code
            time.sleep(0.005)
        self.cleanup_error(label + " group cleanup unconfirmed")
        return code

    def message(self, fd, deadline, *, abort=True):
        raw = bytearray()
        os.set_blocking(fd, False)
        while True:
            self.checkpoint(abort=abort)
            apt.require(time.monotonic() < deadline, "lifecycle response deadline")
            ready, _, _ = select.select([fd], [], [], 0.01)
            if not ready: continue
            data = os.read(fd, min(4096, evidence.RECEIPT_LIMIT - len(raw) + 1))
            apt.require(data, "lifecycle response EOF")
            raw.extend(data)
            apt.require(len(raw) <= evidence.RECEIPT_LIMIT, "lifecycle response byte limit")
            if b"\n" in raw:
                line, extra = bytes(raw).split(b"\n", 1)
                apt.require(not extra, "multiple lifecycle responses")
                return apt.decode(line, evidence.RECEIPT_LIMIT)

    def action(self, action, mode="work"):
        request, deadline = action_request(self.nonce, self.digest, action, mode), self.until(action)
        reader, writer = os.pipe()
        pid, code = None, None
        try:
            pid = os.fork()
            if pid == 0:
                try:
                    channels.close_except((writer,))
                    os.setsid()
                    signal.signal(signal.SIGTERM, signal.SIG_DFL)
                    signal.signal(signal.SIGINT, signal.SIG_DFL)
                    result = self.adapters[action](request)
                    raw = channels.encode({"result": result, "error": None})
                    apt.require(len(raw) <= evidence.RECEIPT_LIMIT, "action reply limit")
                    channels.write_bounded(writer, raw, deadline=deadline)
                    os._exit(0)
                except BaseException as exc:
                    try: channels.write_bounded(writer, channels.encode({"result": None,
                        "error": bounded_text(type(exc).__name__ + ": " + str(exc), evidence.FIRST_ERROR_BYTES)[0]}), deadline=deadline)
                    except BaseException: pass
                    os._exit(2)
            os.close(writer); writer = None
            message = self.message(reader, deadline, abort=action != "shutdown")
            apt.fields(message, "result error")
            apt.require(message["error"] is None, action + " callback: " + str(message["error"]))
            result = evidence.validate_action_result(message["result"], self.nonce, self.digest, action, mode)
            while code is None:
                self.checkpoint(abort=action != "shutdown")
                apt.require(time.monotonic() < deadline, action + " child exit deadline")
                code = _poll_child(pid, code)
                if code is None: time.sleep(0.005)
            apt.require(code == 0, action + " process failed: " + str(code))
            return result
        except Exception as exc:
            self.fail(action + ": " + type(exc).__name__ + ": " + str(exc))
            raise
        finally:
            os.close(reader)
            if writer is not None: os.close(writer)
            if pid not in (None, 0): self.finish(pid, code, action, kill=code is None)

    def evidence_start(self):
        command_read, command_write = os.pipe()
        result_read, result_write = os.pipe()
        try:
            pid = os.fork()
        except BaseException:
            for fd in (command_read, command_write, result_read, result_write): os.close(fd)
            raise
        if pid == 0:
            try: _evidence_worker(self.parent, self.nonce, self.digest, command_read, result_write, self.absolute)
            finally: os._exit(2)
        os.close(command_read); os.close(result_write)
        self.evidence_pid, self.command_fd, self.result_fd = pid, command_write, result_read
        message = self.message(result_read, self.until("init"))
        apt.fields(message, "ready error")
        apt.require(message["error"] is None and message["ready"] == {"schema_version": 1,
            "scope": "i5-preparation-evidence-ready", "uuid": apt.UUID, "nonce": self.nonce, "manifest_sha256": self.digest} and
            type(message["ready"]["schema_version"]) is int, "evidence initialization: " + str(message["error"]))
        self.facts["attempt_ready"] = True

    def host(self):
        active_until = self.until("active")
        phase_until = min(self.absolute - self.budget.tail("shutdown") - self.budget.caps["shutdown"] -
                          2 * self.budget.caps["reap"], active_until + self.budget.caps["watchdog_cleanup"] +
                          self.budget.caps["reap"] + self.budget.caps["watchdog_report"])
        reg_read, reg_write = os.pipe()
        admit_read, admit_write = os.pipe()
        watchdog, watch_code, child_pid = None, None, None
        lease_write, report_read, ack_read = None, None, None
        registration, report, ack = bytearray(), bytearray(), bytearray()
        reg_eof, report_eof, cancelled = False, False, False
        pending, sequence, next_renew = None, 0, time.monotonic()
        def adapter(reader, writer, ack_writer):
            work = min(594, active_until - time.monotonic() - 6)
            apt.require(work > 0, "transport work window exhausted")
            return transport.run_transport(reader, writer, ack_writer, self.request, rpc=self.rpc, total=work)
        try:
            watchdog, lease_write, report_read, ack_read = channels.fork_watchdog(adapter, None, self.nonce, self.digest,
                total=min(self.budget.caps["active"], active_until - time.monotonic()), silence=self.budget.silence,
                cleanup_seconds=self.budget.caps["watchdog_cleanup"], recovery_seconds=min(120, self.budget.caps["shutdown"]),
                registration_fd=reg_write, admission_fd=admit_read, absolute_deadline=phase_until,
                reap_seconds=self.budget.caps["reap"], defer_recovery=True)
            os.close(reg_write); reg_write = None
            os.close(admit_read); admit_read = None
            for fd in (reg_read, report_read, ack_read): os.set_blocking(fd, False)
            lease = channels.supervision.Lease(self.nonce, self.digest, started=time.monotonic(),
                total=self.budget.caps["active"], silence=self.budget.silence, side="host")
            while not report_eof or watch_code is None or not reg_eof:
                self.checkpoint(abort=False)
                if time.monotonic() >= active_until: self.fail("lifecycle active deadline")
                watch_code = _poll_child(watchdog, watch_code)
                if watch_code not in (None, 0, 2): self.fail("watchdog exit/signal: " + str(watch_code))
                if self.facts["first_failure"] and not cancelled:
                    cancelled = True
                    if admit_write is not None: os.close(admit_write); admit_write = None
                    if lease_write is not None: os.close(lease_write); lease_write = None
                    if watch_code is None:
                        try: os.kill(watchdog, signal.SIGTERM)
                        except ProcessLookupError: pass
                    if child_pid is not None:
                        try: os.killpg(child_pid, signal.SIGKILL)
                        except ProcessLookupError: pass
                apt.require(time.monotonic() < phase_until, "watchdog report/cleanup deadline")
                if not cancelled and watch_code is None and pending is None and time.monotonic() >= next_renew:
                    channels.write_frame(lease_write, lease.frame(sequence))
                    pending = sequence
                    next_renew = time.monotonic() + min(5, self.budget.silence / 3)
                fds = ([] if reg_eof else [reg_read]) + ([] if report_eof else [report_read])
                if ack_read is not None: fds.append(ack_read)
                ready, _, _ = select.select(fds, [], [], 0.01)
                for fd in ready:
                    if fd == reg_read:
                        data = os.read(fd, channels.supervision.MAX_FRAME - len(registration) + 1)
                        if not data:
                            reg_eof = True
                            continue
                        registration.extend(data)
                        apt.require(len(registration) <= channels.supervision.MAX_FRAME, "transport registration limit")
                        if b"\n" in registration:
                            line, extra = bytes(registration).split(b"\n", 1)
                            apt.require(not extra and child_pid is None, "duplicate transport registration")
                            value = apt.decode(line, channels.supervision.MAX_FRAME)
                            apt.fields(value, "schema_version scope uuid nonce manifest_sha256 pid watchdog_pid")
                            apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                                value["scope"] == "i5-preparation-transport-admission" and value["uuid"] == apt.UUID and
                                value["nonce"] == self.nonce and value["manifest_sha256"] == self.digest and
                                type(value["pid"]) is int and value["pid"] > 0 and value["watchdog_pid"] == watchdog and
                                type(value["watchdog_pid"]) is int, "transport registration binding")
                            child_pid = value["pid"]  # Record before any admission or liveness query.
                            self.facts["transport_registered"] = True
                            apt.require(os.getpgid(child_pid) == child_pid, "transport session not established")
                            watch_code = _poll_child(watchdog, watch_code)
                            self.checkpoint(abort=False)
                            if watch_code is None and self.facts["first_failure"] is None:
                                channels.write_frame(admit_write, b"1")
                            if admit_write is not None: os.close(admit_write); admit_write = None
                    elif fd == ack_read:
                        data = os.read(fd, channels.supervision.MAX_FRAME - len(ack) + 1)
                        if not data:
                            os.close(ack_read); ack_read = None
                            continue
                        ack.extend(data)
                        apt.require(len(ack) <= channels.supervision.MAX_FRAME, "host ACK limit")
                        if b"\n" in ack:
                            line, extra = bytes(ack).split(b"\n", 1)
                            value = apt.decode(line, channels.supervision.MAX_FRAME)
                            apt.require(not extra and pending is not None and value == {"schema_version": 1,
                                "scope": "i5-preparation-host-ack", "uuid": apt.UUID, "nonce": self.nonce,
                                "manifest_sha256": self.digest, "sequence": pending} and type(value["sequence"]) is int and
                                type(value["schema_version"]) is int, "host ACK binding")
                            sequence, pending, ack = pending + 1, None, bytearray()
                    else:
                        data = os.read(fd, min(65536, channels.HOST_REPORT_LIMIT - len(report) + 1))
                        if not data: report_eof = True
                        else:
                            available = channels.HOST_REPORT_LIMIT - len(report)
                            report.extend(data[:available])
                            apt.require(len(data) <= available, "host report byte limit")
            self.host_raw, self.host_exit = bytes(report), watch_code
            value = evidence.validate_host_report(self.host_raw, self.nonce, self.digest)
            apt.require(watch_code == (0 if value["passed"] else 2), "watchdog report/exit mismatch")
            self.host_passed = value["passed"]
            if not self.host_passed: self.fail(value["watchdog"]["failure"] or "host preparation failed")
        except Exception as exc:
            self.fail("host: " + type(exc).__name__ + ": " + str(exc))
            raise
        finally:
            self.host_raw = bytes(report)
            self.host_exit = watch_code
            for fd in (reg_read, reg_write, admit_read, admit_write, lease_write, report_read, ack_read):
                if fd is not None: os.close(fd)
            if watchdog is not None: self.finish(watchdog, watch_code, "watchdog", kill=watch_code is None)
            if child_pid is not None:
                # The watchdog is the direct reaper. We can check/kill only its
                # exact registered group, including leader-exit pipe-free leaks.
                deadline = min(self.absolute, time.monotonic() + self.budget.caps["reap"])
                try:
                    os.killpg(child_pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    self.cleanup_error("transport group remained after watchdog exit")
                    os.killpg(child_pid, signal.SIGKILL)
                    while time.monotonic() < deadline:
                        try: os.killpg(child_pid, 0)
                        except ProcessLookupError: break
                        time.sleep(0.005)
                    else: self.cleanup_error("transport group cleanup unconfirmed")
            elif registration or not reg_eof or (watchdog is not None and watch_code != 0):
                self.cleanup_error("transport registration/cleanup unconfirmed")

    def commit(self):
        deadline = self.until("persist")
        raw = channels.encode({"report_bytes": len(self.host_raw), "process_exit": self.host_exit,
                               "lifecycle": self.facts}) + self.host_raw
        os.set_blocking(self.command_fd, False)
        offset = 0
        while offset < len(raw):
            self.checkpoint(abort=False)
            apt.require(time.monotonic() < deadline, "lifecycle persistence input deadline")
            _, ready, _ = select.select([], [self.command_fd], [], 0.01)
            if not ready: continue
            try: count = os.write(self.command_fd, memoryview(raw)[offset:offset + 65536])
            except BlockingIOError: continue
            apt.require(count > 0, "evidence command zero write")
            offset += count
        os.close(self.command_fd); self.command_fd = None
        message = self.message(self.result_fd, deadline, abort=False)
        apt.fields(message, "receipt error")
        apt.require(message["error"] is None and type(message["receipt"]) is dict, "lifecycle persistence: " + str(message["error"]))
        return message["receipt"]

    def run(self):
        self.evidence_pid, self.command_fd, self.result_fd = None, None, None
        receipt, persistence_error, evidence_code, evidence_finished = None, None, None, False
        try:
            self.checkpoint()
            self.evidence_start()
            self.checkpoint()
            self.facts["start_attempted"] = True  # Includes fork failure/lost return; never restart.
            self.facts["start"] = self.action("start")
            self.checkpoint()
            self.facts["readiness"] = self.action("readiness")
            self.checkpoint()
            self.host()
        except Exception as exc:
            self.fail(type(exc).__name__ + ": " + str(exc))
        finally:
            if self.facts["start_attempted"]:
                self.facts["shutdown_attempted"] = True
                mode = "normal" if self.host_passed and self.facts["first_failure"] is None and not self.facts["cleanup_errors"] else "recovery"
                try:
                    self.facts["shutdown"] = self.action("shutdown", mode)
                    if self.facts["shutdown"]["forced_stop"]: self.fail("forced shutdown cannot pass")
                except Exception as exc:
                    self.fail("shutdown: " + str(exc))
                    self.cleanup_error("shutdown: " + str(exc))
            # This is the cancellation cut: stop has finished, final facts are
            # checked once more, then frozen. Delivery failure cannot redo work.
            try: self.checkpoint(abort=False)
            except ValueError as exc: self.fail(exc)
            if not self.host_passed and self.facts["first_failure"] is None: self.fail("host result not accepted")
            self.facts["frozen"], self.frozen = True, True
            self.facts["passed"] = bool(self.host_passed and self.facts["first_failure"] is None and
                not self.facts["cleanup_errors"] and self.facts["sessions_reaped"])
            if self.facts["attempt_ready"]:
                try:
                    receipt = self.commit()
                    evidence_code = self.finish(self.evidence_pid, None, "evidence persist")
                    evidence_finished = True
                    apt.require(evidence_code == 0 and not self.delivery_errors, "evidence process exit/reap failed: " + repr(self.delivery_errors))
                    apt.require(receipt.get("schema_version") == 2 and receipt.get("lifecycle") == self.facts and
                                receipt.get("passed") == self.facts["passed"], "persisted lifecycle receipt mismatch")
                except Exception as exc:
                    persistence_error = bounded_text(exc, evidence.FIRST_ERROR_BYTES)[0]
            if self.evidence_pid is not None and not evidence_finished:
                evidence_code = self.finish(self.evidence_pid, evidence_code, "evidence aborted", kill=True)
            for fd in (self.command_fd, self.result_fd):
                if fd is not None: os.close(fd)
            packet = {"schema_version": 1, "scope": "i5-preparation-lifecycle-result", "uuid": apt.UUID,
                "nonce": self.nonce, "manifest_sha256": self.digest, "evidence_kind": "synthetic", "i5_ready": False,
                "passed": bool(receipt and receipt["passed"] and persistence_error is None and evidence_code == 0),
                "lifecycle": self.facts, "receipt": receipt, "persistence_error": persistence_error, "delivery_errors": self.delivery_errors}
            try:
                raw = channels.encode(packet)
                apt.require(len(raw) <= 2 * evidence.RECEIPT_LIMIT, "lifecycle result byte limit")
                channels.write_bounded(self.report_fd, raw, deadline=min(self.absolute, time.monotonic() + self.budget.caps["output"]))
            except (OSError, ValueError, RuntimeError):
                os._exit(2)
            os._exit(0 if packet["passed"] else 2)


def fork_lifecycle(evidence_parent, request, *, rpc, start, readiness, shutdown, budget=None):
    """Return owner PID, exclusive caller liveness/cancel writer, result reader.

    Keeping the writer open grants liveness, not a timer or queued lease. Any
    byte cancels; EOF also cancels before the stop-complete freeze. No callback
    or native adapter is inferred. The global clock starts before validation/fork.
    """
    started = time.monotonic()
    budget = Budget() if budget is None else budget
    apt.require(type(budget) is Budget and type(budget.caps) is dict and set(budget.caps) == set(CAPS), "lifecycle budget snapshot")
    budget = Budget(total=budget.total, silence=budget.silence, **dict(budget.caps))
    apt.require(type(budget) is Budget and all(callable(f) for f in (rpc, start, readiness, shutdown)), "explicit lifecycle adapters/budget")
    # Pure binding validation; canonical path/ownership/file I/O is exclusively
    # performed by the evidence worker, never in the owner controller loop.
    apt.require(type(evidence_parent) in (str, Path) or isinstance(evidence_parent, Path), "explicit evidence parent")
    apt.require(type(request) is dict, "lifecycle transport request")
    program = transport.unbase64(request.get("program_base64"), 48 * 1024)
    apt.require(type(request.get("schema_version")) is int and request == transport.transport_request(request["nonce"], request["manifest_sha256"], program), "lifecycle request binding")
    cancel_read, cancel_write = os.pipe()
    report_read, report_write = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        for fd in (cancel_read, cancel_write, report_read, report_write): os.close(fd)
        raise
    if pid == 0:
        owner = None
        try:
            channels.close_except((cancel_read, report_write))
            os.setsid()
            owner = _Owner(cancel_read, report_write, evidence_parent, request, rpc, start, readiness, shutdown, budget, started)
            for number in (signal.SIGTERM, signal.SIGINT):
                signal.signal(number, lambda number, frame: owner.interrupted.append(number))
            owner.run()
        finally:
            os._exit(2)
    os.close(cancel_read); os.close(report_write)
    return pid, cancel_write, report_read


if __name__ == "__main__":
    raise SystemExit("I5_PREPARATION_ISOLATION_REQUIRED")
