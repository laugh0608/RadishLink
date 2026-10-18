"""Internal, single-call preparation RPC process bridge; no public launcher.

Children keep the transport's session AND process group so its independent
watchdog can kill them. This bridge reaps its direct child on normal cancellation
and closes bounded pipes on failure. It cannot prove absence of descendants that
close/escape those pipes, handle SIGKILL of its caller, interrupt kernel process
creation, or kill an uninterruptible process. Outer watchdog/recovery is required.
"""

import base64
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import threading
import time

import sw_i5_apt as apt
import sw_i5_preparation_supervisor as supervision

REQUEST_LIMIT = 96 * 1024
RESPONSE_LIMIT = 6 * apt.MIB
STDERR_LIMIT = 65536


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def validate_invocation_descriptor(value, nonce, manifest_sha256):
    """Fixed library identity only; caller paths, scripts and callbacks are absent."""
    supervision.Lease(nonce, manifest_sha256, started=0)
    apt.fields(value, "schema_version scope uuid nonce manifest_sha256 delivery_sha256")
    apt.require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["scope"] == "i5-preparation-native-library-invocation" and value["uuid"] == apt.UUID and
                value["nonce"] == nonce and value["manifest_sha256"] == manifest_sha256 and
                apt.digest(value["delivery_sha256"]), "native invocation descriptor binding")
    raw = encode(value)
    apt.require(len(raw) <= 48 * 1024, "native invocation descriptor limit")
    return apt.decode(raw, 48 * 1024)


def validate_request(request, nonce, manifest_sha256):
    supervision.Lease(nonce, manifest_sha256, started=0)
    apt.fields(request, "schema_version scope uuid nonce manifest_sha256 sequence action args")
    apt.require(type(request["schema_version"]) is int and request["schema_version"] == 1 and
                request["scope"] == "i5-preparation-utm-rpc" and request["uuid"] == apt.UUID and
                request["nonce"] == nonce and request["manifest_sha256"] == manifest_sha256 and
                type(request["sequence"]) is int and 0 <= request["sequence"] < 2 ** 53, "RPC request binding")
    action, args = request["action"], request["args"]
    fields = {"identify": "", "open": "role", "read": "handle", "write": "handle data",
              "execute": "program_base64 program_sha256", "execute-native": "descriptor",
              "native-ready": "process", "result": "process", "close": "handle"}
    apt.require(type(action) is str and action in fields, "RPC action")
    apt.fields(args, fields[action])
    for key in ("handle", "process"):
        if key in args:
            apt.require(type(args[key]) is int and 0 < args[key] < 2 ** 53, "RPC handle")
    if action == "open": apt.require(args["role"] in ("lease", "ack"), "RPC mailbox role")
    if action == "execute-native":
        validate_invocation_descriptor(args["descriptor"], nonce, manifest_sha256)
    if action in ("write", "execute"):
        text = args["data" if action == "write" else "program_base64"]
        maximum = 1024 if action == "write" else 48 * 1024
        apt.require(type(text) is str and 0 < len(text) <= 4 * ((maximum + 2) // 3), "RPC input size")
        raw = base64.b64decode(text, validate=True)
        apt.require(0 < len(raw) <= maximum and base64.b64encode(raw).decode("ascii") == text, "RPC input base64")
        if action == "write": apt.require(len(raw) == 1024, "RPC slot size")
        else: apt.require(apt.digest(args["program_sha256"]) and
                          hashlib.sha256(raw).hexdigest() == args["program_sha256"], "RPC program digest")
    raw = encode(request)
    apt.require(len(raw) <= REQUEST_LIMIT, "RPC request limit")
    return raw


def validate_response(raw, request, limit):
    apt.require(type(raw) is bytes and 0 < len(raw) <= limit, "RPC response limit")
    # Decode explicitly: json.loads(bytes) otherwise also accepts UTF-16/32.
    value = apt.decode(raw.decode("utf-8", errors="strict"), limit)
    apt.fields(value, "schema_version scope uuid nonce manifest_sha256 sequence action value")
    apt.require(value["scope"] == "i5-preparation-utm-rpc-result" and all(
        type(value[k]) is type(request[k]) and value[k] == request[k]
        for k in ("schema_version", "uuid", "nonce", "manifest_sha256", "sequence", "action")), "RPC response binding")
    return value


class ProcessRPC:
    """Explicit internal command injection, never a shell or automatic retry.

    timeout includes launch, I/O, termination and direct-child reap. Up to 250 ms
    (one quarter of shorter calls) is reserved inside it for SIGKILL/reap. The
    launch syscall itself still needs the independent outer watchdog.
    """
    def __init__(self, argv, nonce, manifest_sha256, *, cancelled=lambda: False, launcher=subprocess.Popen):
        apt.require(type(argv) in (list, tuple) and argv and all(type(a) is str and a and "\0" not in a for a in argv),
                    "RPC explicit argv required")
        apt.require(Path(argv[0]).is_absolute(), "RPC executable must be absolute")
        supervision.Lease(nonce, manifest_sha256, started=0)
        self.argv, self.nonce, self.digest = tuple(argv), nonce, manifest_sha256
        self.cancelled, self.launcher = cancelled, launcher

    def __call__(self, request, timeout, limit):
        started = time.monotonic()
        apt.require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 2 and
                    type(limit) is int and 0 < limit <= RESPONSE_LIMIT, "RPC process budget")
        deadline = started + timeout
        raw = validate_request(request, self.nonce, self.digest)
        io_deadline = deadline - min(0.25, timeout / 4)
        process, failure, cleanup = None, None, []
        selector = selectors.DefaultSelector()
        buffers, sent, interrupted, handlers = {"stdout": bytearray(), "stderr": bytearray()}, 0, [], {}
        original = None
        try:
            if threading.current_thread() is threading.main_thread():
                for number in (signal.SIGTERM, signal.SIGINT):
                    handlers[number] = signal.signal(number, lambda number, frame: interrupted.append(number))
            apt.require(not self.cancelled() and not interrupted, "RPC cancelled")
            apt.require(time.monotonic() < io_deadline, "RPC process deadline before launch")
            process = self.launcher(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    shell=False, close_fds=True, start_new_session=False)
            for name, event in (("stdin", selectors.EVENT_WRITE), ("stdout", selectors.EVENT_READ), ("stderr", selectors.EVENT_READ)):
                stream = getattr(process, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, event, name)
            while selector.get_map() or process.poll() is None:
                apt.require(not interrupted and not self.cancelled(), "RPC cancelled")
                remaining = io_deadline - time.monotonic()
                if remaining <= 0 and process.poll() is not None and selector.get_map():
                    raise ValueError("RPC pipe still open after child exit; descendant cleanup unconfirmed")
                apt.require(remaining > 0, "RPC process deadline")
                ready = selector.select(min(remaining, 0.01))
                for key, _ in ready:
                    name = key.data
                    if name == "stdin":
                        try: count = os.write(key.fd, raw[sent:sent + 65536])
                        except (BlockingIOError, InterruptedError): continue
                        apt.require(count > 0, "RPC zero stdin write")
                        sent += count
                        if sent == len(raw):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                    else:
                        maximum = limit if name == "stdout" else STDERR_LIMIT
                        budget = maximum - len(buffers[name])
                        try: data = os.read(key.fd, min(65536, budget + 1))
                        except (BlockingIOError, InterruptedError): continue
                        if not data:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        else:
                            apt.require(len(data) <= budget, "RPC " + name + " limit")
                            buffers[name].extend(data)
                # A child can exit between an empty select and poll. Drain its
                # remaining bytes/EOF until the same I/O deadline; a single
                # empty readiness result cannot prove a descendant pipe leak.
            apt.require(sent == len(raw), "RPC incomplete stdin")
            apt.require(process.returncode == 0, "RPC child exit/signal: " + str(process.returncode))
            apt.require(not buffers["stderr"], "RPC child stderr is nonempty")
            result = bytes(buffers["stdout"])
            validate_response(result, request, limit)
            apt.require(time.monotonic() < io_deadline, "late RPC response")
        except BaseException as exc:
            original, failure = exc, type(exc).__name__ + ": " + str(exc)
        finally:
            if process is not None:
                try:
                    if process.poll() is None: process.kill()
                except OSError as exc:
                    cleanup.append("kill: " + str(exc))
                try:
                    process.wait(timeout=max(0, deadline - time.monotonic()))
                except (OSError, subprocess.TimeoutExpired) as exc:
                    cleanup.append("direct child reap unconfirmed: " + type(exc).__name__)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try: stream.close()
                        except OSError as exc: cleanup.append("close: " + str(exc))
            selector.close()
            for number, handler in handlers.items(): signal.signal(number, handler)
        if interrupted:
            failure = (failure + "; " if failure else "") + "RPC cancelled by signal " + str(interrupted[0])
        if failure or cleanup:
            message = "preparation RPC process: " + (failure or "cleanup failed") + "; cleanup=" + repr(cleanup)
            if original is not None and not isinstance(original, Exception):
                original.add_note(message) if hasattr(original, "add_note") else None
                raise original
            raise ValueError(message) from original
        apt.require(time.monotonic() < deadline, "RPC completion deadline")
        return result


def assemble_jxa(source, source_sha256, request):
    """Bind reviewed source bytes AND exact stdin JSON without changing run().

    The original public run lives inside a closure. Only this internal generated
    wrapper calls the byte driver. Request/program bytes go in stdin and this
    private source file, never argv. The caller must separately authorize any
    future real Application use; this function merely builds bytes.
    """
    apt.require(type(source) is bytes and 0 < len(source) <= 128 * 1024 and apt.digest(source_sha256) and
                hashlib.sha256(source).hexdigest() == source_sha256, "JXA source digest")
    raw = validate_request(request, request["nonce"], request["manifest_sha256"])
    suffix = "\nreturn function () { preparationRPCStream(preparationFoundationIO(), " + json.dumps(raw.decode()) + \
             ", function () { return preparationNativeAPI(Application('com.utmapp.UTM')); }); };\n}());\n" + \
             "function run(argv) { if (argv.length !== 0) { throw new Error('internal RPC arguments'); } i5InternalRPC(); }\n"
    return ("var i5InternalRPC = (function () {\n" + source.decode("utf-8") + suffix).encode("utf-8")


class JXAProcessRPC:
    """Future internal native adapter, disabled unless a launcher is injected.

    No default launch, CLI, discovery or enable flag. Tests inject launchers that
    replace osascript with synthetic Python/Node; no real Application is called.
    """
    def __init__(self, source, source_sha256, nonce, manifest_sha256, *, launcher=None, cancelled=lambda: False, stager=None):
        apt.require(type(source) is bytes and 0 < len(source) <= 128 * 1024 and apt.digest(source_sha256) and
                    hashlib.sha256(source).hexdigest() == source_sha256, "JXA source digest")
        supervision.Lease(nonce, manifest_sha256, started=0)
        self.source, self.source_sha256, self.nonce, self.digest = source, source_sha256, nonce, manifest_sha256
        self.launcher, self.cancelled = launcher, cancelled
        self.stager = stager

    def with_stager(self, stager):
        return JXAProcessRPC(self.source, self.source_sha256, self.nonce, self.digest,
                             launcher=self.launcher, cancelled=self.cancelled, stager=stager)

    def __call__(self, request, timeout, limit):
        started = time.monotonic()
        apt.require(self.launcher is not None, "I5_NATIVE_RPC_INTERNAL_ONLY")
        apt.require(self.stager is not None, "I5_BOUND_STAGING_REQUIRED")
        apt.require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 2, "RPC process budget")
        validate_request(request, self.nonce, self.digest)
        apt.require(request["action"] not in ("execute-native", "native-ready"),
                    "I5_NATIVE_LIFECYCLE_REAL_ADAPTER_STOP: use an explicitly injected offline RPC")
        source = assemble_jxa(self.source, self.source_sha256, request)
        deadline = started + timeout
        failure, cleanup = None, None
        path = None
        try:
            path = self.stager.stage(request["sequence"], source, deadline)
            # Keep source cleanup INSIDE the same call deadline. ProcessRPC's
            # kill/reap reserve also remains inside its shortened work window.
            remaining = deadline - time.monotonic() - min(0.25, timeout / 4)
            apt.require(remaining > 0, "RPC source staging deadline")
            result = ProcessRPC(("/usr/bin/osascript", "-l", "JavaScript", str(path)), self.nonce, self.digest,
                                launcher=self.launcher, cancelled=self.cancelled)(request, remaining, limit)
        except BaseException as exc:
            failure = exc
        finally:
            try:
                if path is not None: self.stager.clean(request["sequence"], deadline)
            except BaseException as exc:
                cleanup = exc
        if failure is not None:
            if cleanup is not None:
                message = "JXA RPC: " + str(failure) + "; source cleanup: " + str(cleanup)
                if not isinstance(failure, Exception):
                    if hasattr(failure, "add_note"): failure.add_note(message)
                    raise failure from cleanup
                raise ValueError(message) from failure
            raise failure
        if cleanup is not None:
            raise ValueError("JXA RPC source cleanup: " + str(cleanup)) from cleanup
        apt.require(time.monotonic() < deadline, "RPC source cleanup deadline")
        return result


if __name__ == "__main__":
    raise SystemExit("I5_NATIVE_RPC_INTERNAL_ONLY")
