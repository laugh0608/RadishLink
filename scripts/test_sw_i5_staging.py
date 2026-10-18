"""Bounded real socket IPC and strict identity checks; no native launcher."""

import json
import os
import signal
import socket
import time
import unittest

import sw_i5_preparation_channels as channels
import sw_i5_preparation_staging as staging


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.children, self.sockets = [], []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for fd in self.sockets:
            try: os.close(fd)
            except OSError: pass
        for pid in self.children:
            try:
                if channels.wait_child(pid, time.monotonic() + 0.2) is None:
                    os.kill(pid, signal.SIGKILL); os.waitpid(pid, 0)
            except (ChildProcessError, ProcessLookupError): pass

    def client(self, mode="ok"):
        left, right = socket.socketpair()
        client_fd, server_fd = left.detach(), right.detach()
        pid = os.fork()
        if pid == 0:
            channels.close_except((server_fd,))
            try:
                if mode == "upload-hang": time.sleep(10)
                for _ in range(2):
                    deadline = time.monotonic() + 2
                    header = json.loads(staging.receive(server_fd, deadline))
                    if header["bytes"]: staging.receive(server_fd, deadline, header["bytes"], line=False)
                    value = {key: header[key] for key in ("schema_version", "scope", "uuid", "nonce", "manifest_sha256", "root_identity", "operation", "sequence")}
                    value.update(path="/synthetic/" + "a" * 32 + "/rpc-" + str(header["sequence"]) + ".js", error=None)
                    if mode == "late": time.sleep(0.3)
                    if mode == "lost": os._exit(0)
                    if mode == "nonce": value["nonce"] = "f" * 32
                    if mode == "root": value["root_identity"] = [1, 3]
                    if mode == "scope": value["scope"] = "wrong"
                    if mode == "sequence": value["sequence"] += 1
                    if mode == "extra": value["unknown"] = True
                    if mode == "error": value["error"] = "synthetic staging failure"
                    staging.send(server_fd, channels.encode(value), deadline)
                os._exit(0)
            except BaseException: os._exit(2)
        self.children.append(pid)
        os.close(server_fd); self.sockets.append(client_fd)
        return staging.StagingClient(client_fd, "/synthetic/" + "a" * 32, [1, 2], 700000, "a" * 32, "b" * 64)

    def test_bound_source_create_clean_and_monotonic_sequence(self):
        client = self.client()
        self.assertTrue(client.stage(0, b"synthetic", time.monotonic() + 1).endswith("rpc-0.js"))
        client.clean(0, time.monotonic() + 1)
        with self.assertRaisesRegex(ValueError, "sequence"): client.stage(0, b"duplicate", time.monotonic() + 1)

    def test_wrong_scope_nonce_root_sequence_extra_error_and_lost_reply_poison(self):
        for mode in ("nonce", "root", "scope", "sequence", "extra", "error", "lost"):
            with self.subTest(mode=mode):
                client = self.client(mode)
                with self.assertRaises(ValueError): client.stage(0, b"source", time.monotonic() + 1)
                with self.assertRaisesRegex(ValueError, "previously failed"): client.stage(1, b"source", time.monotonic() + 1)

    def test_late_reply_and_upload_stall_stop_inside_single_deadline(self):
        for mode, raw in (("late", b"source"), ("upload-hang", b"x" * 700000)):
            client = self.client(mode)
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "deadline"): client.stage(0, raw, started + 0.15)
            self.assertLess(time.monotonic() - started, 0.5)
            with self.assertRaisesRegex(ValueError, "previously failed"): client.clean(0, started + 1)

    def test_source_quota_is_reserved_before_upload(self):
        client = self.client("upload-hang")
        with self.assertRaisesRegex(ValueError, "reservation"): client.stage(0, b"x" * 700001, time.monotonic() + 1)
        self.assertEqual(client.sequence, -1)
        self.assertFalse(client.failed)


if __name__ == "__main__": unittest.main()
