"""Internal bounded staging IPC. Filesystem work belongs to the evidence worker.

No default directory, launcher or retry. A lost reply poisons this client; the
independent lifecycle owner must settle the worker's registered residue.
"""

import hashlib
import os
import select
import time

import sw_i5_apt as apt
import sw_i5_preparation_channels as channels

HEADER_LIMIT = 2048


from sw_i5_preparation_channels import send, receive


class StagingClient:
    def __init__(self, fd, root, identity, source_limit, nonce, digest):
        from sw_i5_preparation_plan import assembled_source_bound
        apt.require(type(fd) is int and fd >= 3 and type(source_limit) is int and 0 < source_limit <= assembled_source_bound(128 * 1024),
                    "explicit bound staging descriptor/limit")
        self.fd, self.root, self.identity, self.source_limit = fd, root, identity, source_limit
        self.binding = dict(schema_version=1, scope="i5-synthetic-staging", uuid=apt.UUID, nonce=nonce,
                            manifest_sha256=digest, root_identity=identity)
        self.failed, self.sequence = False, -1

    def exchange(self, operation, sequence, deadline, source=b""):
        apt.require(not self.failed, "staging IPC previously failed; no retry")
        apt.require(type(sequence) is int and 0 <= sequence < 2 ** 53 and operation in ("stage", "clean"), "staging sequence/action")
        if operation == "stage":
            apt.require(sequence > self.sequence and type(source) is bytes and 0 < len(source) <= self.source_limit,
                        "staging source reservation/sequence")
            self.sequence = sequence
        try:
            header = dict(self.binding, operation=operation, sequence=sequence, deadline=deadline,
                          bytes=len(source), sha256=hashlib.sha256(source).hexdigest())
            send(self.fd, channels.encode(header) + source, deadline)
            reply = apt.decode(receive(self.fd, deadline), HEADER_LIMIT)
            apt.fields(reply, "schema_version scope uuid nonce manifest_sha256 root_identity operation sequence path error")
            apt.require(all(type(reply[key]) is type(value) and reply[key] == value for key, value in self.binding.items()),
                        "staging response identity binding")
            apt.require(reply["operation"] == operation and type(reply["sequence"]) is int and reply["sequence"] == sequence,
                        "staging response binding")
            apt.require(reply["error"] is None, "staging worker: " + str(reply["error"]))
            expected = self.root + "/rpc-" + str(sequence) + ".js"
            apt.require(reply["path"] == expected, "staging bound source path")
            apt.require(time.monotonic() < deadline, "late staging response")
            return expected
        except BaseException:
            self.failed = True
            raise

    def stage(self, sequence, source, deadline):
        return self.exchange("stage", sequence, deadline, source)

    def clean(self, sequence, deadline):
        return self.exchange("clean", sequence, deadline)
