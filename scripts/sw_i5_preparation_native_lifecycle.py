"""Explicit offline wiring for one persistent guest FD owner and its parent.

The invocation parent supervises processes, never reopens objects for cleanup.
Only its owner child constructs NativeGuestInitialization. Task code runs under
the existing independent supervisor, with no inherited initialization FDs.
There is no default syscall, task, launcher, CLI, or execution authorization.
"""

import hashlib
import json
import math
import os
import select
import signal
import socket
import time

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels
import sw_i5_preparation_isolation as isolation
import sw_i5_preparation_native as native
import sw_i5_preparation_supervisor as supervision

SCOPE = "i5-preparation-native-lifecycle-export"
FACT_SCOPE = "i5-preparation-native-lifecycle-facts"
READY_SCOPE = "i5-preparation-native-lifecycle-ready"
FACT_LIMIT = 128 * 1024
REG_LIMIT = FACT_LIMIT
FLAGS = ("execution_authorized", "install_authorized", "physical_verified", "i5_ready")


class NativeGuestConfig:
    def __init__(self, contract_raw, manifest_raw, *, expected, delivery_sha256):
        apt.require(type(contract_raw) is bytes and type(manifest_raw) is bytes and apt.digest(delivery_sha256),
                    "native lifecycle immutable bytes/delivery binding")
        value = apt.decode(contract_raw, 8192)
        contract = isolation.Contract.parse(contract_raw, value.get("nonce"), value.get("manifest_sha256"))
        apt.require(hashlib.sha256(manifest_raw).hexdigest() == contract.manifest_sha256, "native lifecycle manifest binding")
        apt.validate_manifest(manifest_raw, contract.nonce)
        apt.fields(expected, "root_parent cgroup_root readonly_input")
        for row in expected.values():
            apt.fields(row, "dev ino mount_id")
            apt.require(all(type(n) is int and n > 0 for n in row.values()), "native lifecycle expected identity")
        self.contract_raw, self.manifest_raw = contract_raw, manifest_raw
        self.expected = json.loads(json.dumps(expected))
        self.delivery_sha256, self.nonce, self.digest = delivery_sha256, contract.nonce, contract.manifest_sha256

    def snapshot(self):
        return NativeGuestConfig(self.contract_raw, self.manifest_raw, expected=self.expected, delivery_sha256=self.delivery_sha256)


class NativeTaskAdapters:
    def __init__(self, *, work, boundary, guard, prepare, subreaper, exporter=None):
        apt.require(all(callable(f) for f in (work, prepare, subreaper)), "explicit native task adapters")
        apt.require(all(callable(getattr(boundary, key, None)) for key in ("attach", "populated", "kill")) and
                    all(callable(getattr(guard, key, None)) for key in
                        ("admit_supervisor", "before_admission", "bind_worker", "check", "check_cgroups")),
                    "explicit native task boundary and guard")
        self.work, self.boundary, self.guard = work, boundary, guard
        self.prepare, self.subreaper, self.exporter = prepare, subreaper, exporter


class NativeBudget:
    """Subdivides the existing phase windows; never increases the 897/900 cap."""
    def __init__(self, *, init=6, active=528, cleanup=2, reap=2, output=2, silence=15):
        values = dict(init=init, active=active, cleanup=cleanup, reap=reap, output=output, silence=silence)
        caps = dict(init=6, active=528, cleanup=2, reap=2, output=2, silence=15)
        apt.require(all(type(v) in (int, float) and math.isfinite(v) and 0 < v <= caps[k]
                        for k, v in values.items()) and silence <= active,
                    "native lifecycle bounded phase budgets")
        self.__dict__.update(values)
        # The owner and task cleanup share cleanup, and both reaps share reap.
        self.total = init + active + cleanup + reap + output
        apt.require(self.total <= apt.GUEST_SECONDS, "native lifecycle guest window")


def _error(exc):
    return (type(exc).__name__ + ": " + str(exc)).encode("utf-8")[:1000].decode("utf-8", "ignore")


def _poll(pid, code):
    if code is not None: return code
    done, status = os.waitpid(pid, os.WNOHANG)
    return os.waitstatus_to_exitcode(status) if done else None


def _signal(pid, number):
    try: os.killpg(pid, number)
    except ProcessLookupError:
        try: os.kill(pid, number)
        except ProcessLookupError: pass


def _read_stream(fd, limit, deadline, checkpoint=lambda: None):
    raw = bytearray()
    os.set_blocking(fd, False)
    while True:
        checkpoint()
        apt.require(time.monotonic() < deadline, "native task result deadline")
        ready, _, _ = select.select([fd], [], [], 0.01)
        if not ready: continue
        data = os.read(fd, min(65536, limit - len(raw) + 1))
        if not data: return bytes(raw)
        raw.extend(data)
        apt.require(len(raw) <= limit, "native result byte limit")


def _owner(config, control_fd, output_fd, ack_fd, registry_fd, adapters, syscall_factory, budgets, deadlines):
    owner, supervisor_pid, supervisor_code, reader = None, None, None, None
    task_retirement = False
    task_export, first_failure, cleanup_errors = None, None, []
    facts = dict(initialization=None, independent_readback=None, cleanup=None, fd_closed=False,
                 task_supervisor_exit=None, task_supervisor_reaped=False, task_worker_reaped=False)
    registry_deadline = deadlines["work"]
    def register(kind, value):
        request = dict(kind=kind, value=value)
        channels.send(registry_fd, channels.encode(request), registry_deadline)
        answer = apt.decode(channels.receive(registry_fd, registry_deadline, REG_LIMIT), REG_LIMIT)
        apt.require(answer == {"ack": request}, "native registration ACK lost/mismatched")
    def native_register(value): register("object", value)
    def retire_failed_supervisor(pid):
        nonlocal task_retirement
        register("supervisor-unconfirmed", pid)
        register("task-stop", pid)
        register("task-retiring", dict(pid=pid, worker_reaped=False, population_empty=False))
        task_retirement = True
    def cancelled(number, frame): raise InterruptedError("native owner cancelled by signal " + str(number))
    try:
        channels.close_except((control_fd, output_fd, ack_fd, registry_fd))
        os.setsid()
        for number in (signal.SIGTERM, signal.SIGINT): signal.signal(number, cancelled)
        # Never inherit an already constructed backend, including its pinned FDs.
        system = syscall_factory()
        apt.require(system is not None and type(system) is not native.LinuxNativeSyscalls,
                    "offline native lifecycle requires explicitly injected syscalls")
        owner = native.NativeGuestInitialization(config.contract_raw, config.manifest_raw,
                                                expected=config.expected, syscalls=system)
        apt.require(owner.backend_kind == "injected-offline", "offline lifecycle backend kind")
        facts["initialization"] = owner.initialize(deadline=deadlines["init"], register=native_register)
        facts["independent_readback"] = owner.readback(deadline=deadlines["init"])
        register("ready", dict(initialization=facts["initialization"], independent_readback=facts["independent_readback"]))
        # Only the audited supervisor's explicit FD whitelist survives this fork.
        supervisor_pid, writer, reader = supervision.fork_supervisor(
            adapters.work, adapters.boundary, adapters.guard, config.nonce, config.digest,
            total=budgets.active, silence=budgets.silence, subreaper=adapters.subreaper,
            prepare=adapters.prepare, exporter=adapters.exporter, control_fd=control_fd, ack_fd=ack_fd,
            keep_fds=(registry_fd,), register_supervisor=lambda pid: register("supervisor", pid),
            register_worker=lambda pid: register("worker", pid), absolute_deadline=deadlines["task"],
            cleanup_seconds=min(1, budgets.cleanup / 2), retire_supervisor=retire_failed_supervisor)
        apt.require(writer is None, "native owner must not hold renewal writer")
        os.close(control_fd); control_fd = None
        os.close(ack_fd); ack_fd = None
        raw = _read_stream(reader, channels.EXPORT_LIMIT, deadlines["task"])
        # Nested native envelopes cannot pass as task exports.
        value = apt.decode(raw, channels.EXPORT_LIMIT)
        apt.require(value.get("scope") == channels.EXPORT_SCOPE, "native task requires original export scope")
        task_export = channels.validate_export(raw, config.nonce, config.digest)
        if not (task_export["supervision"]["reaped"] and task_export["supervision"]["population_empty"]):
            # P finishes this group's stop ticket before N is allowed waitpid;
            # a failure report cannot retire a still populated task group.
            register("task-stop", supervisor_pid)
        register("task-retiring", dict(pid=supervisor_pid, worker_reaped=task_export["supervision"]["reaped"],
                                      population_empty=task_export["supervision"]["population_empty"]))
        task_retirement = True
        while supervisor_code is None and time.monotonic() < deadlines["task"]:
            supervisor_code = _poll(supervisor_pid, supervisor_code)
            if supervisor_code is None: time.sleep(0.005)
        apt.require(supervisor_code is not None, "native task supervisor reap unconfirmed")
        facts["task_supervisor_exit"], facts["task_supervisor_reaped"] = supervisor_code, True
        facts["task_worker_reaped"] = task_export["supervision"]["reaped"]
        register("task-reaped", dict(pid=supervisor_pid, code=supervisor_code,
                                    worker_reaped=facts["task_worker_reaped"]))
        apt.require(supervisor_code == (0 if task_export["passed"] else 2), "native task result/exit mismatch")
        apt.require(task_export["passed"], "native task failed")
    except BaseException as exc:
        if supervisor_pid is None and type(getattr(exc, "pid", None)) is int:
            # A fork can succeed before its registration/admission fails. Never
            # turn a lost return into "no task was created" cleanup authority.
            supervisor_pid = exc.pid
            try: register("supervisor-unconfirmed", supervisor_pid)
            except BaseException as error: cleanup_errors.append(_error(error))
            if getattr(exc, "reaped", False) is True:
                supervisor_code = getattr(exc, "exit_code", None)
                facts["task_supervisor_exit"] = supervisor_code
                facts["task_supervisor_reaped"] = supervisor_code is not None
                try: register("task-reaped", dict(pid=supervisor_pid, code=supervisor_code, worker_reaped=False))
                except BaseException as error: cleanup_errors.append(_error(error))
        first_failure = _error(exc)
    finally:
        # Cleanup has its own reserved window and ignores further task cancellation.
        for number in (signal.SIGTERM, signal.SIGINT): signal.signal(number, signal.SIG_IGN)
        if supervisor_pid is not None and not facts["task_supervisor_reaped"]:
            if not task_retirement:
                try:
                    register("task-stop", supervisor_pid)
                    register("task-retiring", dict(pid=supervisor_pid, worker_reaped=False, population_empty=False))
                    task_retirement = True
                except BaseException as exc:
                    cleanup_errors.append(_error(exc))
            # P retires its signal ticket BEFORE N can reap/recycle S's PID.
            # An unacknowledged retirement grants no local wait/reap authority.
            if task_retirement:
                until = min(deadlines["cleanup"], time.monotonic() + budgets.cleanup / 2)
                while supervisor_code is None and time.monotonic() < until:
                    supervisor_code = _poll(supervisor_pid, supervisor_code)
                    if supervisor_code is None: time.sleep(0.005)
            facts["task_supervisor_exit"] = supervisor_code
            facts["task_supervisor_reaped"] = supervisor_code is not None
            # Without its complete report, waitpid(S) does not prove W was reaped.
            if task_export is not None: facts["task_worker_reaped"] = task_export["supervision"]["reaped"]
        safe = supervisor_pid is None or (facts["task_supervisor_reaped"] and facts["task_worker_reaped"] and
                    task_export is not None and task_export["supervision"]["population_empty"])
        if owner is not None:
            try:
                if safe:
                    registry_deadline = min(deadlines["cleanup"], time.monotonic() + budgets.cleanup)
                    register("cleanup-start", None)
                    facts["cleanup"] = owner.cleanup(deadline=registry_deadline, register=native_register)
                    cleanup_errors.extend(facts["cleanup"]["errors"])
                else: cleanup_errors.append("task population/reaping unconfirmed; preserve initialized objects")
            except BaseException as exc: cleanup_errors.append(_error(exc))
            finally:
                try: owner.close(); facts["fd_closed"] = True
                except BaseException as exc: cleanup_errors.append(_error(exc))
        for fd in (control_fd, ack_fd, reader):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
        facts.update(task_export=task_export, first_failure=first_failure, cleanup_errors=cleanup_errors)
        try:
            raw = channels.encode(facts)
            apt.require(len(raw) <= channels.EXPORT_LIMIT, "native owner result byte limit")
            channels.write_bounded(output_fd, raw, deadline=deadlines["result"])
        except BaseException: os._exit(2)
        os._exit(0 if first_failure is None and not cleanup_errors else 2)


def _header(config):
    return dict(schema_version=1, scope=FACT_SCOPE, uuid=apt.UUID, nonce=config.nonce,
                manifest_sha256=config.digest, delivery_sha256=config.delivery_sha256,
                backend_kind="injected-offline", **dict.fromkeys(FLAGS, False))


def run_native_guest(config, control_fd, output_fd, ack_fd, *, syscalls_factory, task_adapters,
                     budget=None, ready_fd=None):
    """One guest invocation parent; all real Linux/VM defaults remain disabled.

    `ready_fd` is an optional explicit offline adapter pipe, never a new guest
    filesystem object. Closing control cancels; no internally generated lease
    grants work. The parent only keeps registration facts after losing N.
    """
    started = time.monotonic()
    apt.require(type(config) is NativeGuestConfig and type(task_adapters) is NativeTaskAdapters and callable(syscalls_factory),
                "explicit native guest configuration and offline adapters")
    config = config.snapshot()
    budget = NativeBudget() if budget is None else budget
    apt.require(type(budget) is NativeBudget, "native lifecycle exact budget")
    budget = NativeBudget(**{key: getattr(budget, key) for key in ("init", "active", "cleanup", "reap", "output", "silence")})
    fds = (control_fd, output_fd, ack_fd) + (() if ready_fd is None else (ready_fd,))
    apt.require(all(type(fd) is int and fd >= 3 for fd in fds) and len(set(fds)) == len(fds), "native lifecycle private FDs")
    channels.close_except(fds)
    deadlines = dict(init=started + budget.init, task=started + budget.init + budget.active,
                     cleanup=started + budget.init + budget.active + budget.cleanup,
                     work=started + budget.init + budget.active + budget.cleanup,
                     result=started + budget.total - budget.output)
    absolute = started + budget.total
    child_read, child_write = os.pipe()
    result_read, result_write = os.pipe()
    left, right = socket.socketpair()
    reg_parent, reg_child = left.detach(), right.detach()
    try: pid = os.fork()
    except BaseException:
        for fd in (child_read, child_write, result_read, result_write, reg_parent, reg_child): os.close(fd)
        raise
    if pid == 0:
        _owner(config, child_read, result_write, ack_fd, reg_child, task_adapters, syscalls_factory, budget, deadlines)
        os._exit(2)
    for fd in (child_read, result_write, reg_child, ack_fd): os.close(fd)
    registry, events, roles, groups = {}, [], {}, {}
    raw, reg_buffer, code, message, first_failure = bytearray(), bytearray(), None, None, None
    is_ready, task_retired, task_stopped, task_reaped, worker_reaped, interrupted = False, False, False, False, False, []
    previous = {}
    settlement_errors = []
    def signal_owned(ticket, number):
        try: _signal(ticket, number)
        except OSError as exc: settlement_errors.append(_error(exc))
    failure_until, result_eof, control_open, cleanup_until = None, False, True, None
    for number in (signal.SIGTERM, signal.SIGINT):
        previous[number] = signal.signal(number, lambda number, frame: interrupted.append(number))
    def fail(reason):
        nonlocal first_failure, failure_until, child_write
        if first_failure is None:
            first_failure = str(reason)[:1000]
            failure_until = min(deadlines["result"], time.monotonic() + budget.cleanup + budget.reap)
            if child_write is not None: os.close(child_write); child_write = None
            # S gets an opportunity to reclaim W before N's cleanup barrier.
            if "supervisor" in groups and not task_retired: signal_owned(groups["supervisor"], signal.SIGTERM)
            if code is None: signal_owned(pid, signal.SIGTERM)
    try:
        for fd in (control_fd, result_read, reg_parent): os.set_blocking(fd, False)
        while not result_eof or code is None:
            now = time.monotonic()
            code = _poll(pid, code)
            if interrupted: fail("native guest parent cancelled by signal " + str(interrupted[0]))
            if cleanup_until is not None and now >= cleanup_until:
                fail("native guest cleanup deadline")
                if code is None: signal_owned(pid, signal.SIGKILL)
                break
            if now >= (deadlines["task"] if is_ready else deadlines["init"]): fail("native guest phase deadline")
            if now >= deadlines["result"] or (failure_until is not None and now >= failure_until):
                if code is None: signal_owned(pid, signal.SIGKILL)
                if "supervisor" in groups and not task_retired: signal_owned(groups["supervisor"], signal.SIGKILL)
                break
            watched = [result_read, reg_parent] + ([control_fd] if control_open else [])
            ready, _, _ = select.select(watched, [], [], 0.01)
            for fd in ready:
                if fd == control_fd:
                    data = os.read(fd, supervision.MAX_FRAME)
                    if not data:
                        control_open = False
                        fail("native guest control EOF")
                    elif first_failure is None:
                        # Exact lease validation remains in the existing S; P
                        # only forwards bytes, never fabricates a renewal.
                        apt.require(child_write is not None, "native control closed")
                        try:
                            channels.write_bounded(child_write, data, deadline=min(deadlines["task"], now + 0.2))
                        except BrokenPipeError:
                            # S may finish between a renewal and N's result.
                            # This grants no ACK/lease; accept only its complete
                            # independently validated terminal report below.
                            os.close(child_write); child_write = None
                elif fd == reg_parent:
                    chunk = os.read(fd, REG_LIMIT - len(reg_buffer) + 1)
                    if not chunk: continue
                    reg_buffer.extend(chunk)
                    apt.require(len(reg_buffer) <= REG_LIMIT, "native registration limit")
                    if b"\n" not in reg_buffer: continue
                    line, extra = bytes(reg_buffer).split(b"\n", 1)
                    apt.require(not extra, "native registration one outstanding frame")
                    reg_buffer.clear()
                    event = apt.decode(line, REG_LIMIT)
                    apt.fields(event, "kind value")
                    kind, value = event["kind"], event["value"]
                    if kind == "object":
                        _register_object(registry, events, value)
                    elif kind == "ready":
                        apt.require(not is_ready and set(registry) == set(native.CREATE_ORDER) and
                                    all(row["state"] == "bound" for row in registry.values()), "native ready registration barrier")
                        apt.fields(value, "initialization independent_readback")
                        roles.update(value)
                        _validate_observations(value, config.nonce, config.digest)
                        is_ready = True
                        if ready_fd is not None:
                            packet = dict(schema_version=1, scope=READY_SCOPE, uuid=apt.UUID, nonce=config.nonce,
                                          manifest_sha256=config.digest, ready=True, delivery_sha256=config.delivery_sha256)
                            channels.write_bounded(ready_fd, channels.encode(packet), deadline=deadlines["init"])
                            os.close(ready_fd); ready_fd = None
                    elif kind in ("supervisor", "worker"):
                        apt.require(is_ready and kind not in groups and type(value) is int and value > 1 and
                                    value != pid and value not in groups.values(), "native task PID registration")
                        groups[kind] = value
                    elif kind == "supervisor-unconfirmed":
                        apt.require(type(value) is int and value > 1 and value != pid and
                                    groups.get("supervisor", value) == value, "native unconfirmed supervisor ticket")
                        groups["supervisor"] = value
                    elif kind == "task-reaped":
                        apt.fields(value, "pid code worker_reaped")
                        apt.require(value["pid"] == groups.get("supervisor") and type(value["code"]) is int and
                                    type(value["worker_reaped"]) is bool, "native task reap binding")
                        task_reaped, worker_reaped = True, value["worker_reaped"]
                    elif kind == "task-retiring":
                        apt.fields(value, "pid worker_reaped population_empty")
                        apt.require(value["pid"] == groups.get("supervisor") and
                                    type(value["worker_reaped"]) is bool and type(value["population_empty"]) is bool and
                                    ((value["worker_reaped"] and value["population_empty"]) or task_stopped),
                                    "native task retirement binding")
                        # N may waitpid immediately after this ACK. P must no
                        # longer signal that PID/group ticket after retirement.
                        task_retired = True
                    elif kind == "task-stop":
                        apt.require(type(value) is int and value == groups.get("supervisor") and not task_retired and not task_stopped,
                                    "native failed task stop ticket")
                        signal_owned(value, signal.SIGTERM)
                        # N cannot reap S before receiving this ACK, so this
                        # ticket cannot be recycled while P signals its group.
                        signal_owned(value, signal.SIGKILL)
                        task_stopped = True
                    elif kind == "cleanup-start":
                        apt.require(value is None and cleanup_until is None, "native duplicate cleanup phase")
                        cleanup_until = min(deadlines["cleanup"], now + budget.cleanup)
                    else: raise ValueError("native registration unknown kind")
                    channels.send(reg_parent, channels.encode({"ack": event}), min(deadlines["work"], now + 0.5))
                else:
                    data = os.read(fd, min(65536, channels.EXPORT_LIMIT - len(raw) + 1))
                    if not data: result_eof = True
                    else:
                        raw.extend(data)
                        apt.require(len(raw) <= channels.EXPORT_LIMIT, "native parent result limit")
        until = min(absolute - budget.output, time.monotonic() + budget.reap)
        while code is None and time.monotonic() < until:
            code = _poll(pid, code)
            if code is None: time.sleep(0.005)
        if result_eof and raw:
            message = apt.decode(bytes(raw), channels.EXPORT_LIMIT)
            apt.fields(message, "initialization independent_readback cleanup fd_closed task_supervisor_exit "
                       "task_supervisor_reaped task_worker_reaped task_export first_failure cleanup_errors")
            if message["first_failure"] is not None: fail(message["first_failure"])
        else: fail("native owner result lost; registered objects remain pending")
    except BaseException as exc:
        fail(_error(exc))
        if code is None: signal_owned(pid, signal.SIGKILL)
        if "supervisor" in groups and not task_retired: signal_owned(groups["supervisor"], signal.SIGKILL)
        until = min(absolute - budget.output, time.monotonic() + budget.reap)
        while code is None and time.monotonic() < until:
            code = _poll(pid, code)
            if code is None: time.sleep(0.005)
    finally:
        if "supervisor" in groups and not task_retired:
            # N can disappear before sending any terminal frame. Its EOF must
            # not skip the independent parent's stop route for admitted S/W.
            target = groups["supervisor"]
            until = min(absolute - budget.output, time.monotonic() + budget.reap)
            signal_owned(target, signal.SIGTERM)
            graceful_until = min(until, time.monotonic() + budget.reap / 2)
            present = True
            while time.monotonic() < graceful_until:
                try: os.killpg(target, 0)
                except ProcessLookupError:
                    present = False
                    break
                except OSError as exc:
                    settlement_errors.append(_error(exc))
                    break
                time.sleep(0.005)
            if present:
                try: os.killpg(target, signal.SIGKILL)
                except ProcessLookupError: present = False
                except OSError as exc: settlement_errors.append(_error(exc))
            # P is not S's waitpid owner. Even absence here never sets reaped.
            while present and time.monotonic() < until:
                try: os.killpg(target, 0)
                except ProcessLookupError: break
                except OSError as exc:
                    settlement_errors.append(_error(exc))
                    break
                time.sleep(0.005)
        for number, handler in previous.items(): signal.signal(number, handler)
        for fd in (control_fd, child_write, result_read, reg_parent, ready_fd):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
    facts = _header(config)
    facts.update(initialization=roles.get("initialization"), independent_readback=roles.get("independent_readback"),
        cleanup=message["cleanup"] if message else None, registered=events, pending=registry, owner_exit=code,
        processes=dict(owner=pid, supervisor=groups.get("supervisor"), worker=groups.get("worker")),
        owner_reaped=code is not None, fd_closed=bool(message and message["fd_closed"]),
        task_supervisor_reaped=bool(message and message["task_supervisor_reaped"] and task_reaped),
        task_worker_reaped=bool(message and message["task_worker_reaped"] and worker_reaped),
        first_failure=first_failure, cleanup_errors=(message["cleanup_errors"] if message else ["owner result unavailable"]) + settlement_errors)
    task_export = message["task_export"] if message else None
    passed = bool(first_failure is None and code == 0 and not registry and facts["cleanup"] and
                  not facts["cleanup_errors"] and facts["task_supervisor_reaped"] and facts["task_worker_reaped"] and
                  facts["fd_closed"] and task_export and task_export["passed"])
    packet = dict(schema_version=1, scope=SCOPE, uuid=apt.UUID, nonce=config.nonce, manifest_sha256=config.digest,
                  evidence_kind="synthetic", i5_ready=False, passed=passed, task_export=task_export, native_lifecycle=facts)
    raw = channels.encode(packet)
    validate_native_export(raw, config.nonce, config.digest)
    channels.write_bounded(output_fd, raw, deadline=min(absolute, time.monotonic() + budget.output))
    return 0 if passed else 2


_register_object = channels._register_object
_validate_observations = channels._validate_observations
validate_native_export = channels.validate_native_export
