"""Offline real subprocess bridge tests; no osascript/Application/UTM calls."""

import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import sw_i5_apt as apt
import sw_i5_preparation_rpc as rpc

NONCE, DIGEST = "a" * 32, "b" * 64
PREFIX = '''import json, os, signal, sys, time
r = json.loads(sys.stdin.buffer.read())
v = {k: r[k] for k in ("schema_version", "uuid", "nonce", "manifest_sha256", "sequence", "action")}
v.update(scope="i5-preparation-utm-rpc-result", value={"uuid": r["uuid"], "status": "started"})
'''
REPLY = 'sys.stdout.buffer.write(json.dumps(v).encode()); sys.stdout.buffer.flush()\n'


def request(action="identify", args=None, sequence=0):
    return {"schema_version": 1, "scope": "i5-preparation-utm-rpc", "uuid": apt.UUID,
            "nonce": NONCE, "manifest_sha256": DIGEST, "sequence": sequence, "action": action, "args": args or {}}


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="radishlink-rpc-test-")
        self.addCleanup(self.temp.cleanup)
        self.root, self.children = Path(self.temp.name), []
        self.index = 0

    def explicit_stager(self):
        root = self.root / "controlled-staging"
        root.mkdir(mode=0o700)
        class Fixture:
            def stage(self, sequence, source, deadline):
                path = root / (str(sequence) + ".js")
                with path.open("xb") as output: output.write(source)
                path.chmod(0o600)
                return str(path)
            def clean(self, sequence, deadline):
                (root / (str(sequence) + ".js")).unlink()
        return Fixture()

    def bridge(self, source, **options):
        path = self.root / (str(self.index) + ".py")
        self.index += 1
        path.write_text(source)
        def launch(argv, **kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertFalse(kwargs["start_new_session"])
            self.assertTrue(kwargs["close_fds"])
            child = subprocess.Popen(argv, **kwargs)
            self.children.append(child)
            return child
        return rpc.ProcessRPC((sys.executable, "-I", "-B", str(path)), NONCE, DIGEST, launcher=launch, **options)

    def assert_reaped(self):
        for child in self.children:
            self.assertIsNotNone(child.returncode)
            with self.assertRaises(ChildProcessError): os.waitpid(child.pid, os.WNOHANG)

    def test_real_process_response_and_group_fd_boundaries(self):
        reader, writer = os.pipe()
        os.set_inheritable(writer, True)
        source = PREFIX + '''
assert os.getpgrp() == int(os.environ["I5_TEST_PGID"])
try: os.fstat(int(os.environ["I5_TEST_FD"]))
except OSError: pass
else: raise RuntimeError("unrelated fd leaked")
''' + REPLY
        before = dict(os.environ)
        try:
            os.environ["I5_TEST_PGID"], os.environ["I5_TEST_FD"] = str(os.getpgrp()), str(writer)
            raw = self.bridge(source)(request(), 2, 2048)
            self.assertEqual(json.loads(raw)["value"]["status"], "started")
            self.assert_reaped()
        finally:
            os.environ.clear()
            os.environ.update(before)
            os.close(reader)
            os.close(writer)

    def test_invalid_utf8_utf16_partial_multi_duplicate_json_rejected(self):
        for payload in (b"\xff", b'{"half":', b'{}\n{}', b'{"a":1,"a":2}', '{"a":1}'.encode("utf-16")):
            with self.subTest(payload=repr(payload)):
                bridge = self.bridge('import sys\nsys.stdin.buffer.read()\nsys.stdout.buffer.write(' + repr(payload) + ')\n')
                with self.assertRaises(ValueError): bridge(request(), 2, 2048)
        self.assert_reaped()

    def test_stdin_stdout_stalls_deadline_and_late_reply(self):
        program = b"x" * (48 * 1024)
        args = {"program_base64": __import__("base64").b64encode(program).decode(),
                "program_sha256": hashlib.sha256(program).hexdigest()}
        cases = [('import time\ntime.sleep(30)\n', request("execute", args)),
                 (PREFIX + 'sys.stdout.buffer.write(b"{\\\"half\\\":"); sys.stdout.buffer.flush(); time.sleep(30)\n', request()),
                 (PREFIX + 'time.sleep(0.4)\n' + REPLY, request())]
        for source, value in cases:
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "deadline"):
                self.bridge(source)(value, 0.3, 2048)
            self.assertLess(time.monotonic() - started, 1)
        self.assert_reaped()

    def test_stream_overflow_nonempty_stderr_nonzero_exit_and_signal(self):
        cases = [(PREFIX + 'sys.stdout.buffer.write(b"x" * 10000)\n', "stdout limit"),
                 (PREFIX + 'sys.stderr.buffer.write(b"x" * 100000)\n', "stderr limit"),
                 (PREFIX + 'sys.stderr.write("synthetic error")\n' + REPLY, "stderr"),
                 (PREFIX + 'sys.exit(7)\n', "exit/signal: 7"),
                 (PREFIX + 'os.kill(os.getpid(), signal.SIGTERM)\n', "exit/signal: -15")]
        for source, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.bridge(source)(request(), 2, 2048)
        self.assert_reaped()

    def test_full_stderr_pipe_is_drained_without_deadlock(self):
        with self.assertRaisesRegex(ValueError, "stderr is nonempty"):
            self.bridge(PREFIX + 'sys.stderr.buffer.write(b"x" * 65536); sys.stderr.buffer.flush()\n' + REPLY)(request(), 2, 2048)
        self.assert_reaped()

    def test_child_exit_after_empty_select_still_drains_bytes_and_eof(self):
        original = rpc.selectors.DefaultSelector
        outer = self
        class ExitBetweenSelectAndPoll:
            def __init__(self): self.inner, self.delayed = original(), False
            def __getattr__(self, name): return getattr(self.inner, name)
            def select(self, timeout):
                ready = self.inner.select(timeout)
                if not self.delayed and any(key.data != "stdin" for key, _ in ready):
                    outer.children[-1].wait(timeout=1)
                    self.delayed = True
                    return []
                return ready
        with patch.object(rpc.selectors, "DefaultSelector", ExitBetweenSelectAndPoll):
            value = self.bridge(PREFIX + REPLY)(request(), 2, 2048)
        self.assertEqual(json.loads(value)["sequence"], 0)
        self.assert_reaped()

    def test_binding_errors_rejected_without_launch_and_response_binding_checked(self):
        bridge = self.bridge(PREFIX + REPLY)
        for modified in (dict(request(), uuid="other"), dict(request(), sequence=True), dict(request(), action="start"),
                         request("execute", {"program_base64": "eA==", "program_sha256": "c" * 64})):
            with self.assertRaises(ValueError): bridge(modified, 2, 2048)
        self.assertEqual(self.children, [])
        for field, value in (("nonce", "c" * 32), ("sequence", 9), ("action", "close"), ("schema_version", True)):
            with self.assertRaisesRegex(ValueError, "binding"):
                self.bridge(PREFIX + 'v[' + repr(field) + '] = ' + repr(value) + '\n' + REPLY)(request(), 2, 2048)
        self.assert_reaped()

    def test_native_fixed_descriptor_actions_and_old_program_limit(self):
        descriptor = {"schema_version": 1, "scope": "i5-preparation-native-library-invocation", "uuid": apt.UUID,
                      "nonce": NONCE, "manifest_sha256": DIGEST, "delivery_sha256": "d" * 64}
        for value in (request("execute-native", {"descriptor": descriptor}), request("native-ready", {"process": 777})):
            rpc.validate_request(value, NONCE, DIGEST)
            reply = self.bridge(PREFIX + REPLY)(value, 2, 2048)
            self.assertEqual(json.loads(reply)["action"], value["action"])
        for change in ({"schema_version": True}, {"extra": 1}, {"library_root": "/tmp/arbitrary"}, {"nonce": "e" * 32}):
            with self.assertRaises(ValueError):
                rpc.validate_request(request("execute-native", {"descriptor": dict(descriptor, **change)}), NONCE, DIGEST)
        for size in (48 * 1024, 48 * 1024 + 1):
            raw = b"x" * size
            value = request("execute", {"program_base64": __import__("base64").b64encode(raw).decode(),
                "program_sha256": hashlib.sha256(raw).hexdigest()})
            if size == 48 * 1024: rpc.validate_request(value, NONCE, DIGEST)
            else:
                with self.assertRaises(ValueError): rpc.validate_request(value, NONCE, DIGEST)
        source = b"function preparationRPCStream(){}"
        native = rpc.JXAProcessRPC(source, hashlib.sha256(source).hexdigest(), NONCE, DIGEST,
            launcher=lambda *a, **k: self.fail("native action launched"), stager=self.explicit_stager())
        for action, args in (("execute-native", {"descriptor": descriptor}), ("native-ready", {"process": 777})):
            with self.assertRaisesRegex(ValueError, "REAL_ADAPTER_STOP"): native(request(action, args), 2, 2048)
        self.assert_reaped()

    def test_cancellation_callback_and_baseexception_reap_child(self):
        called = []
        def cancelled():
            called.append(1)
            return len(called) > 2
        with self.assertRaisesRegex(ValueError, "cancelled"):
            self.bridge(PREFIX + 'time.sleep(30)\n', cancelled=cancelled)(request(), 2, 2048)
        def interrupt():
            if self.children and self.children[-1].poll() is None: raise KeyboardInterrupt("synthetic cancel")
            return False
        with self.assertRaises(KeyboardInterrupt):
            self.bridge(PREFIX + 'time.sleep(30)\n', cancelled=interrupt)(request(), 2, 2048)
        self.assert_reaped()

    def test_transport_group_sigterm_reaps_rpc_child_and_restores_handler(self):
        reader, writer = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(reader)
            os.setsid()
            try:
                def launch(argv, **kwargs):
                    process = subprocess.Popen(argv, **kwargs)
                    os.write(writer, (str(process.pid) + " " + str(os.getpgid(process.pid)) + "\n").encode())
                    return process
                source = self.root / "blocked.py"
                source.write_text('import time\ntime.sleep(30)\n')
                bridge = rpc.ProcessRPC((sys.executable, "-I", "-B", str(source)), NONCE, DIGEST, launcher=launch)
                handler = signal.getsignal(signal.SIGTERM)
                try: bridge(request(), 2, 2048)
                except ValueError as exc:
                    assert "cancelled" in str(exc)
                    assert signal.getsignal(signal.SIGTERM) == handler
                    os.write(writer, b"reaped\n")
                    os._exit(0)
            except BaseException:
                os._exit(2)
            os._exit(3)
        os.close(writer)
        try:
            self.assertTrue(select.select([reader], [], [], 3)[0])
            child, group = map(int, os.read(reader, 64).split())
            self.assertEqual(group, pid)
            os.killpg(pid, signal.SIGTERM)
            self.assertTrue(select.select([reader], [], [], 3)[0])
            self.assertEqual(os.read(reader, 64), b"reaped\n")
            self.assertEqual(os.waitpid(pid, 0)[1], 0)
            with self.assertRaises(ProcessLookupError): os.kill(child, 0)
        finally:
            os.close(reader)
            try:
                done, _ = os.waitpid(pid, os.WNOHANG)
                if not done:
                    try: os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    os.waitpid(pid, 0)
            except ChildProcessError:
                pass

    def test_descendant_retaining_pipe_fails_without_claiming_cleanup(self):
        descendant = self.root / "descendant"
        source = PREFIX + '''
pid = os.fork()
if pid == 0:
    time.sleep(30)
    os._exit(0)
open(''' + repr(str(descendant)) + ''', "w").write(str(pid))
''' + REPLY
        try:
            with self.assertRaisesRegex(ValueError, "descendant cleanup unconfirmed"):
                self.bridge(source)(request(), 2, 2048)
            self.assert_reaped()
        finally:
            if descendant.exists():
                try: os.kill(int(descendant.read_text()), signal.SIGKILL)
                except ProcessLookupError: pass

    def test_native_default_stop_source_exact_binding_and_injected_launcher(self):
        source = (Path(__file__).parent / "sw_i5_utm_result.js").read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        native = rpc.JXAProcessRPC(source, digest, NONCE, DIGEST)
        with self.assertRaisesRegex(ValueError, "I5_NATIVE_RPC_INTERNAL_ONLY"):
            native(request(), 2, 2048)
        with self.assertRaisesRegex(ValueError, "source digest"):
            rpc.assemble_jxa(source + b"x", digest, request())
        paths = []
        helper = self.root / "synthetic.js"
        helper.write_text(r'''const fs = require("node:fs"), vm = require("node:vm");
function data(buffer) { return {buffer, length: buffer.length,
    subdataWithRange: range => data(buffer.subarray(range[0], range[0] + range[1]))}; }
function $(text) { return {dataUsingEncoding: () => data(Buffer.from(text, "utf8"))}; }
$.NSUTF8StringEncoding = 4;
$.NSMakeRange = (offset, length) => [offset, length];
$.NSFileHandle = {fileHandleWithStandardInput: {readDataOfLength: length => {
    const buffer = Buffer.alloc(length); return data(buffer.subarray(0, fs.readSync(0, buffer, 0, length, null)));
}}, fileHandleWithStandardOutput: {writeData: part => fs.writeSync(1, part.buffer)}};
$.NSMutableData = {get data() { const parts = []; return {appendData: part => parts.push(part.buffer),
    get buffer() { return Buffer.concat(parts); }}; }};
$.NSString = {alloc: {initWithDataEncoding: part => {
    let value; try { value = new TextDecoder("utf-8", {fatal: true}).decode(part.buffer); } catch (_) { value = null; }
    return {isNil: () => value === null, js: value};
}}};
const machine = {id: () => "B86E1A47-9A67-4ECF-A51F-2B2F29CDB726", status: () => "started"};
const app = {virtualMachines: {byId: () => machine}};
const context = vm.createContext({$, ObjC: {import: () => {}}, Application: name => {
    if (name !== "com.utmapp.UTM") { throw new Error("wrong app"); } return app;
}});
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
context.run([]);
''')
        def launch(argv, **kwargs):
            self.assertEqual(tuple(argv[:3]), ("/usr/bin/osascript", "-l", "JavaScript"))
            path = Path(argv[3]); paths.append(path)
            content = path.read_text()
            self.assertIn("preparationRPCStream(preparationFoundationIO()", content)
            self.assertIn(json.dumps(rpc.encode(request()).decode()), content)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            child = subprocess.Popen((shutil.which("node"), str(helper), str(path)), **kwargs)
            self.children.append(child)
            return child
        with self.assertRaisesRegex(ValueError, "I5_BOUND_STAGING_REQUIRED"):
            rpc.JXAProcessRPC(source, digest, NONCE, DIGEST, launcher=launch)(request(), 2, 2048)
        native = rpc.JXAProcessRPC(source, digest, NONCE, DIGEST, launcher=launch, stager=self.explicit_stager())
        self.assertEqual(json.loads(native(request(), 2, 2048))["sequence"], 0)
        self.assertFalse(paths[0].exists())
        self.assert_reaped()

    def test_source_cleanup_error_preserves_rpc_failure(self):
        source = (Path(__file__).parent / "sw_i5_utm_result.js").read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        def launch(*args, **kwargs):
            raise OSError("synthetic launch failed")
        stager = self.explicit_stager()
        native = rpc.JXAProcessRPC(source, digest, NONCE, DIGEST, launcher=launch, stager=stager)
        original = stager.clean
        def cleanup(sequence, deadline):
            original(sequence, deadline)
            raise OSError("synthetic source cleanup failed")
        with patch.object(stager, "clean", cleanup):
            with self.assertRaisesRegex(ValueError, "launch failed.*source cleanup failed"):
                native(request(), 2, 2048)


if __name__ == "__main__":
    unittest.main()
