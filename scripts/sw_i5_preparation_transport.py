"""UTM preparation transport and fixed guest mailbox, offline adapters only.

RPC is injected: no Application, osascript, VM start, file provisioning or CLI.
UTM exposes guest file access and one-shot exec input, not streaming exec stdin.
"""

import base64
import hashlib
import os
from pathlib import Path
import select
import stat
import time

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels
import sw_i5_preparation_rpc as process_rpc
import sw_i5_preparation_supervisor as supervision

SLOT_BYTES = 1024
SLOT_MAGIC = b"I5M1"
RPC_LIMIT = 6 * apt.MIB


def pack_slot(frame):
    apt.require(type(frame) is bytes and 0 < len(frame) <= supervision.MAX_FRAME, "mailbox frame size")
    prefix = SLOT_MAGIC + len(frame).to_bytes(4, "big") + hashlib.sha256(frame).digest() + frame
    return prefix + b"\0" * (SLOT_BYTES - len(prefix))


def unpack_slot(raw):
    apt.require(type(raw) is bytes and len(raw) == SLOT_BYTES, "mailbox size")
    if raw == b"\0" * SLOT_BYTES: return None
    size = int.from_bytes(raw[4:8], "big")
    # A QEMU file write is not assumed atomic. Incomplete/torn updates grant no
    # renewal; existing monotonic silence/absolute deadlines continue unchanged.
    if raw[:4] != SLOT_MAGIC or not 0 < size <= supervision.MAX_FRAME: return None
    frame = raw[40:40 + size]
    if raw[8:40] != hashlib.sha256(frame).digest() or any(raw[40 + size:]): return None
    return frame


def unbase64(text, limit):
    apt.require(type(text) is str and len(text) <= 4 * ((limit + 2) // 3), "RPC base64 limit")
    raw = base64.b64decode(text, validate=True)
    apt.require(len(raw) <= limit and base64.b64encode(raw).decode() == text, "noncanonical RPC base64")
    return raw


class SlotFile:
    def __init__(self, path, *, owner, writable):
        self.path = Path(path)
        apt.require(self.path.is_absolute() and self.path.resolve(strict=True) == self.path, "canonical mailbox path")
        self.fd = os.open(self.path, (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        self.owner = owner
        try:
            info = os.fstat(self.fd)
            self.identity = (info.st_dev, info.st_ino)
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    def check(self):
        for info in (os.fstat(self.fd), self.path.lstat()):
            apt.require(stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == self.identity and
                        info.st_uid == self.owner and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and
                        info.st_size == SLOT_BYTES, "mailbox identity/mode/size changed")
        apt.require(self.path.resolve(strict=True) == self.path, "mailbox ancestor changed")

    def read(self):
        self.check()
        raw = os.pread(self.fd, SLOT_BYTES + 1, 0)
        self.check()
        apt.require(len(raw) == SLOT_BYTES, "mailbox short/oversized read")
        return raw

    def write(self, frame):
        self.check()
        raw = pack_slot(frame)
        apt.require(os.pwrite(self.fd, raw, 0) == SLOT_BYTES, "mailbox short write")
        apt.require(self.read() == raw, "mailbox write readback mismatch")

    def close(self):
        os.close(self.fd)


class GuestMailbox:
    def __init__(self, lease_slot, ack_slot, nonce, manifest_sha256):
        supervision.Lease(nonce, manifest_sha256, started=0)
        self.lease_slot, self.ack_slot = lease_slot, ack_slot
        self.nonce, self.manifest_sha256 = nonce, manifest_sha256
        self.fds = (lease_slot.fd, ack_slot.fd)
        self.previous = b"\0" * SLOT_BYTES
        apt.require(lease_slot.identity != ack_slot.identity and ack_slot.read() == self.previous, "fresh distinct mailbox required")

    def read_pending(self):
        raw = self.lease_slot.read()
        if raw == self.previous: return None
        frame = unpack_slot(raw)
        if frame is None: return None
        self.previous = raw
        return frame

    def acknowledge(self, sequence):
        self.ack_slot.write(channels.encode({"schema_version": 1, "scope": "i5-preparation-guest-ack", "uuid": apt.UUID,
            "nonce": self.nonce, "manifest_sha256": self.manifest_sha256, "sequence": sequence}))


def transport_request(nonce, manifest_sha256, program):
    supervision.Lease(nonce, manifest_sha256, started=0)
    apt.require(type(program) is bytes and 0 < len(program) <= 48 * 1024, "reviewed guest program size")
    return {"schema_version": 1, "scope": "i5-preparation-utm-transport", "uuid": apt.UUID, "nonce": nonce,
            "manifest_sha256": manifest_sha256, "program_sha256": hashlib.sha256(program).hexdigest(),
            "program_base64": base64.b64encode(program).decode()}


def run_transport(control_fd, output_fd, ack_fd, request, *, rpc, clock=time.monotonic, total=600):
    """Adapt watchdog pipes to bounded UTM RPCs; execute is never retried.

    rpc(request, timeout, limit) returns encoded RPC JSON. Each invocation must
    itself be bounded externally (ProcessRPC provides the internal process
    bridge); the independent host watchdog also supervises a blocked adapter.
    Handles never escape this one transport attempt. No native adapter is
    selected implicitly, and a lost execute response is never retried.
    """
    apt.fields(request, "schema_version scope uuid nonce manifest_sha256 program_sha256 program_base64")
    program = unbase64(request["program_base64"], 48 * 1024)
    apt.require(request == transport_request(request["nonce"], request["manifest_sha256"], program) and
                type(request["schema_version"]) is int and 0 < total <= 600, "transport request binding")
    nonce, digest = request["nonce"], request["manifest_sha256"]
    deadline, call_id, handles = clock() + total, 0, {}
    lease = supervision.Lease(nonce, digest, started=clock())
    pending, previous_ack, executed = None, -1, False
    failure, cleanup = None, []
    result_raw, result_exit = None, None
    def call(action, args, *, cleanup_call=False):
        nonlocal call_id
        remaining = (cleanup_deadline if cleanup_call else deadline) - clock()
        apt.require(remaining > 0, "UTM transport deadline")
        envelope = {"schema_version": 1, "scope": "i5-preparation-utm-rpc", "uuid": apt.UUID,
                    "nonce": nonce, "manifest_sha256": digest, "sequence": call_id, "action": action, "args": args}
        call_id += 1
        raw = rpc(envelope, timeout=min(2, remaining), limit=RPC_LIMIT)
        apt.require(clock() < (cleanup_deadline if cleanup_call else deadline), "late UTM RPC response")
        value = process_rpc.validate_response(raw, envelope, RPC_LIMIT)
        return value["value"]
    def read_slot(role):
        return unbase64(call("read", {"handle": handles[role]}), SLOT_BYTES)
    try:
        identity = call("identify", {})
        apt.require(identity == {"uuid": apt.UUID, "status": "started"}, "UTM target not started")
        for role in ("lease", "ack"):
            handle = call("open", {"role": role})
            apt.require(type(handle) is int and handle > 0 and handle not in handles.values(), "invalid mailbox handle")
            handles[role] = handle
            apt.require(read_slot(role) == b"\0" * SLOT_BYTES, "UTM mailbox not fresh")
        # Initial control grants exactly one execute, not an automatic lease.
        channels.initial_lease(control_fd, lease)
        pending = lease.sequence
        frame = lease.frame(pending)
        slot = pack_slot(frame)
        apt.require(call("write", {"handle": handles["lease"], "data": base64.b64encode(slot).decode()}) is None,
                    "unexpected mailbox write response")
        apt.require(read_slot("lease") == slot, "UTM lease write readback")
        executed = True
        process = call("execute", {"program_base64": request["program_base64"], "program_sha256": request["program_sha256"]})
        apt.require(type(process) is int and process > 0, "missing UTM process handle")
        while True:
            lease.check(clock())
            readable, _, _ = select.select([control_fd], [], [], 0)
            if readable:
                raw = os.read(control_fd, supervision.MAX_FRAME)
                apt.require(raw, "UTM control channel closed")
                before = lease.sequence
                lease.feed(raw, clock())
                if lease.sequence != before:
                    apt.require(pending is None, "UTM renewal before acknowledgement")
                    pending = lease.sequence
                    slot = pack_slot(lease.frame(lease.sequence))
                    call("write", {"handle": handles["lease"], "data": base64.b64encode(slot).decode()})
                    apt.require(read_slot("lease") == slot, "UTM lease write readback")
            if pending is not None:
                frame = unpack_slot(read_slot("ack"))
                if frame is not None:
                    ack = apt.decode(frame, supervision.MAX_FRAME)
                    apt.require(type(ack) is dict, "UTM guest ACK type")
                    expected = {"schema_version": 1, "scope": "i5-preparation-guest-ack", "uuid": apt.UUID,
                                "nonce": nonce, "manifest_sha256": digest, "sequence": pending}
                    if ack.get("sequence") == previous_ack:
                        old = dict(expected, sequence=previous_ack)
                        apt.require(ack == old and type(ack["sequence"]) is int and type(ack["schema_version"]) is int,
                                    "UTM stale ACK binding")
                    else:
                        apt.require(ack == expected and type(ack["sequence"]) is int and type(ack["schema_version"]) is int,
                                    "UTM guest ACK binding")
                        channels.write_frame(ack_fd, frame)
                        previous_ack, pending = pending, None
            result = call("result", {"process": process})
            apt.require(type(result) is dict and type(result.get("exited")) is bool, "UTM result status")
            if result["exited"]:
                apt.fields(result, "exited exit_code signal_code stdout_base64 stderr_base64")
                apt.require(type(result["exit_code"]) is int and result["exit_code"] in {0, 2} and
                            type(result["signal_code"]) is int and result["signal_code"] == 0, "UTM guest exit/signal")
                result_raw = unbase64(result["stdout_base64"], channels.EXPORT_LIMIT)
                apt.require(unbase64(result["stderr_base64"], 65536) == b"", "UTM guest stderr")
                exported = channels.validate_export(result_raw, nonce, digest)
                result_exit = 0 if exported["passed"] else 2
                apt.require(result["exit_code"] == result_exit, "UTM guest result/exit mismatch")
                lease.check(clock())
                break
            select.select([control_fd], [], [], 0.02)
    except (OSError, ValueError, RuntimeError) as exc:
        failure = str(exc)
    finally:
        cleanup_deadline = clock() + 4
        for role, handle in handles.items():
            try:
                apt.require(call("close", {"handle": handle}, cleanup_call=True) is None, "unexpected close response")
            except (OSError, ValueError, RuntimeError) as exc:
                cleanup.append(role + ": " + str(exc))
    if failure or cleanup:
        raise ValueError("UTM preparation transport: " + (failure or "close failed") +
                         "; executed=" + str(executed) + "; cleanup=" + repr(cleanup))
    channels.write_bounded(output_fd, result_raw, deadline=time.monotonic() + 2)
    return result_exit
