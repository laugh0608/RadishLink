#!/usr/bin/env python3
"""Materialize and verify offline inputs; never run Cargo or grant execution."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tomllib
from typing import Iterator


CONTRACT = "node-security-graph-inputs-v1"
DESIGN_REVISION = "fdefa3bbf4f8936935f747b8e5f1f79345283f19"
DOCUMENT = "docs/testing/node-security-graph-review-package.md"
BUNDLE_PARENT = "artifacts/node-security-graph-inputs"
MAX_INPUT_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 256 * 1024
BUNDLE_ID = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
BASELINES = {
    "node/Cargo.toml": "53e49bb950e8749a8b0c3a662ffdf279294a83e9fc391d566daf43878ca8ce5e",
    "node/Cargo.lock": "b5bb6b889765b5005bb20645ad5b1bf1b09573451dbad966cfa12d0ec68fbd24",
    "tools/spikes/sw-g2-mls-rs/Cargo.toml": "82fa10b4985273e4edcd54451432144711981f599be0ec090496a898cfdc7fe0",
    "tools/spikes/sw-g2-mls-rs/Cargo.lock": "c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7",
    "LICENSE": "74cc49765a69e5bef2f533b59a39e3d29dea30f4bb2d7e7693846f3867709e01",
}
MANIFEST_SHA256 = "afdea8deee4fa0cd4fbe8e5a0740e02384ce6e8d60135f791e4765cb9459ac22"
CONFIG_SHA256 = "1e707d3933bf964411852e125ebfa28c0dfee5137c0cf2dc28df803f2f8360d3"
SOURCE_STUB = b"// Metadata-only review input; no runtime implementation.\n"
REQUIRED_EXECUTION_EVIDENCE = [
    "hard-write-domain-and-path-confinement",
    "network-domain-enforcement-and-offline-transition",
    "process-group-memory-pids-fds-cpu-and-deadline-enforcement",
    "credential-free-environment-and-fixed-toolchain-binding",
    "supervisor-failure-and-parent-exit-validation",
    "clean-execution-revision-and-current-single-run-authorization",
]


class InputError(Exception):
    """A bounded, non-sensitive diagnostic for input preparation."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + "\n").encode()


def completion_bytes(checksums: bytes) -> bytes:
    return json_bytes({
        "schema_version": 1,
        "contract": CONTRACT,
        "status": "INPUTS_PREPARED",
        "checksums_sha256": digest(checksums),
    })


def total_bytes(files: dict[str, bytes]) -> int:
    return sum(map(len, files.values())) + len(completion_bytes(files["checksums.json"]))


def parts(relative: str) -> tuple[str, ...]:
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or not path.parts
        or "\\" in relative
        or any(part in {".", ".."} for part in relative.split("/"))
        or str(path) != relative
    ):
        raise InputError("invalid relative input path")
    return path.parts


@contextmanager
def directory(root: Path, relative: str | None = None) -> Iterator[int]:
    """Traverse directories through no-follow descriptors, not symlink paths."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in parts(relative) if relative else ():
            child = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


def read_file(root: Path, relative: str, limit: int) -> bytes:
    components = parts(relative)
    parent = "/".join(components[:-1]) or None
    with directory(root, parent) as descriptor:
        file_fd = os.open(
            components[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise InputError("input must be a regular single-link file")
            if before.st_size > limit:
                raise InputError("input exceeds byte limit")
            data = bytearray()
            while len(data) <= limit:
                chunk = os.read(file_fd, min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            after = os.fstat(file_fd)
            if (
                len(data) > limit
                or len(data) != before.st_size
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise InputError("input changed or exceeded byte limit while reading")
            return bytes(data)
        finally:
            os.close(file_fd)


def execution_plan() -> dict:
    """Descriptive argv only. No code in this module executes this plan."""
    manifest = ["--manifest-path", "$review_root/input/Cargo.toml"]
    commands = [{"stage": "G1", "argv": ["$cargo_bin", "generate-lockfile", *manifest]}]
    commands.append({"stage": "G2", "argv": ["$cargo_bin", "fetch", "--locked", *manifest]})
    for target in [None, "aarch64-unknown-linux-gnu", "aarch64-apple-darwin"]:
        args = ["$cargo_bin", "metadata", "--frozen", "--format-version", "1"]
        if target:
            args += ["--filter-platform", target]
        commands.append({"stage": "G2", "argv": args + manifest})
    for target in ["all", "aarch64-unknown-linux-gnu", "aarch64-apple-darwin"]:
        commands.append({"stage": "G2", "argv": [
            "$cargo_bin", "tree", "--frozen", "--target", target,
            "--edges", "normal,build,dev,features", "--format", "{p} {f}", *manifest,
        ]})
    return {
        "schema_version": 1,
        "contract": CONTRACT,
        "scope": "offline-inputs-only",
        "design_revision": DESIGN_REVISION,
        "execution_authorized": False,
        "execution_ready": False,
        "missing_execution_evidence": REQUIRED_EXECUTION_EVIDENCE,
        "toolchain": {"rust": "1.97.1", "cargo": "1.97.1", "host": "aarch64-apple-darwin"},
        "baselines": BASELINES,
        "input_hashes": {"manifest": MANIFEST_SHA256, "cargo_config": CONFIG_SHA256},
        "stage_limits": {
            "G1": {"seconds": 300, "work_bytes": 64 * 1024 * 1024, "evidence_bytes": 8 * 1024 * 1024},
            "G2": {"seconds": 900, "work_bytes": 512 * 1024 * 1024, "evidence_bytes": 32 * 1024 * 1024},
        },
        "commands_for_review_only": commands,
    }


def expected_files(repo: Path) -> dict[str, bytes]:
    sources = {}
    for path, checksum in BASELINES.items():
        content = read_file(repo, path, MAX_SOURCE_BYTES)
        if digest(content) != checksum:
            raise InputError("baseline input hash mismatch")
        sources[path] = content
    document = read_file(repo, DOCUMENT, MAX_SOURCE_BYTES).decode("utf-8")
    blocks = re.findall(r"^```toml\n(.*?)^```$", document, re.MULTILINE | re.DOTALL)
    if len(blocks) != 2:
        raise InputError("expected exactly two TOML input blocks")
    manifest_bytes, config_bytes = (block.encode() for block in blocks)
    if digest(manifest_bytes) != MANIFEST_SHA256 or digest(config_bytes) != CONFIG_SHA256:
        raise InputError("reviewed TOML input hash mismatch")
    manifest = tomllib.loads(blocks[0])
    tomllib.loads(blocks[1])
    node = tomllib.loads(sources["node/Cargo.toml"].decode())
    if len(manifest.get("dependencies", {})) != 8:
        raise InputError("candidate dependency count mismatch")
    for name in ("rusqlite", "serde", "serde_json"):
        if manifest["dependencies"].get(name) != node["dependencies"].get(name):
            raise InputError("Node baseline dependency mismatch")
    files = {
        "input/Cargo.toml": manifest_bytes,
        "input/LICENSE": sources["LICENSE"],
        "input/input.rs": SOURCE_STUB,
        "cargo-home/config.toml": config_bytes,
        "review-plan.json": json_bytes(execution_plan()),
    }
    files["checksums.json"] = json_bytes({
        "schema_version": 1,
        "contract": CONTRACT,
        "files": {name: digest(data) for name, data in sorted(files.items())},
    })
    if total_bytes(files) > MAX_INPUT_BYTES:
        raise InputError("offline input bundle exceeds total byte limit")
    return files


def check_id(bundle_id: str) -> None:
    if not BUNDLE_ID.fullmatch(bundle_id):
        raise InputError("invalid bundle ID")


def write_exclusive(parent_fd: int, name: str, data: bytes) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd
    )
    try:
        remaining = memoryview(data)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise InputError("short input write")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare(repo: Path, bundle_id: str) -> Path:
    check_id(bundle_id)
    files = expected_files(repo)  # Complete validation before creating any output.
    # Create only this fixed parent chain; open every component without following links.
    with directory(repo) as root_fd:
        parent_fd = os.dup(root_fd)
        try:
            for component in parts(BUNDLE_PARENT):
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                )
                os.close(parent_fd)
                parent_fd = child_fd
            os.mkdir(bundle_id, 0o700, dir_fd=parent_fd)  # Existing output always rejects.
            bundle_fd = os.open(
                bundle_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            try:
                for name in ("input", "cargo-home"):
                    os.mkdir(name, 0o700, dir_fd=bundle_fd)
                for name, data in files.items():
                    components = parts(name)
                    if len(components) == 1:
                        write_exclusive(bundle_fd, name, data)
                    else:
                        child_fd = os.open(
                            components[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=bundle_fd,
                        )
                        try:
                            write_exclusive(child_fd, components[1], data)
                            os.fsync(child_fd)
                        finally:
                            os.close(child_fd)
                os.fsync(bundle_fd)
                # Published last: partial writes can never become a verified input bundle.
                write_exclusive(bundle_fd, "complete.json", completion_bytes(files["checksums.json"]))
                os.fsync(bundle_fd)
                os.fsync(parent_fd)
            finally:
                os.close(bundle_fd)
        finally:
            os.close(parent_fd)
    output = repo / BUNDLE_PARENT / bundle_id
    verify(repo, bundle_id)
    return output


def verify(repo: Path, bundle_id: str) -> dict:
    check_id(bundle_id)
    files = expected_files(repo)
    files["complete.json"] = completion_bytes(files["checksums.json"])
    found: set[str] = set()
    expected_dirs = {"input", "cargo-home"}
    entries = 0

    def inventory(descriptor: int, prefix: str) -> None:
        nonlocal entries
        with os.scandir(descriptor) as directory_entries:
            for entry in directory_entries:
                entries += 1
                if entries > len(files) + len(expected_dirs):
                    raise InputError("unexpected input bundle entry")
                name = f"{prefix}{entry.name}"
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode) and name in expected_dirs:
                    child = os.open(
                        entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                    try:
                        inventory(child, name + "/")
                    finally:
                        os.close(child)
                elif stat.S_ISREG(mode) and name in files:
                    found.add(name)
                else:
                    raise InputError("unexpected input bundle entry")

    with directory(repo, f"{BUNDLE_PARENT}/{bundle_id}") as descriptor:
        inventory(descriptor, "")
    if found != files.keys():
        raise InputError("incomplete input bundle")
    for name, expected in files.items():
        # Walk from the trusted root again, so swapped directory links cannot redirect reads.
        actual = read_file(repo, f"{BUNDLE_PARENT}/{bundle_id}/{name}", MAX_INPUT_BYTES)
        if actual != expected:
            raise InputError("prepared input content mismatch")
    return {"status": "INPUTS_VERIFIED", "execution_ready": False, "execution_authorized": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("check")
    for action in ("prepare", "verify"):
        actions.add_parser(action).add_argument("bundle_id")
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parent.parent
    try:
        if args.action == "check":
            files = expected_files(repo)
            result = {"status": "INPUTS_CHECKED", "bytes": total_bytes(files), "execution_ready": False}
        elif args.action == "prepare":
            prepare(repo, args.bundle_id)
            result = verify(repo, args.bundle_id)
            result["bundle"] = f"{BUNDLE_PARENT}/{args.bundle_id}"
        else:
            result = verify(repo, args.bundle_id)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (InputError, OSError, ValueError, UnicodeError) as error:
        # Do not echo file contents, arbitrary paths, environment values or raw OS messages.
        message = str(error) if isinstance(error, InputError) else type(error).__name__
        print(f"STOP/input-preparation: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
