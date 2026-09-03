#!/usr/bin/env python3
"""Collect immutable upstream license evidence for the fixed mls-rs graph."""

from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPSHandler,
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from unittest.mock import patch


SCHEMA_VERSION = 2
MANIFEST_CONTRACT = "sw-g2-mls-rs-license-review-v2"
LEGACY_SCHEMA_VERSION = 1
LEGACY_MANIFEST_CONTRACT = "sw-g2-mls-rs-license-review-v1"
EVIDENCE_ID = "SW-EXP-003"
R0_REVISION = "147462a2d91c5bb3eae4a0985aa8ddf1fc658199"
D2_RUN_ID = "20260902-130415-49997.8P5Td6"
D2_REVISION = "64cf079a7b14a3ce90be92b93e56e2ad80555d80"
D2_MANIFEST_SHA256 = "b42b4bd34142e71f44c020ec3c84ab0c329b2865b0e822efbf0adb53f0440a5f"
D2_CHECKSUMS_SHA256 = "922ce41492cd7911a7be8c2c4f3aedf70e42116bce1b5fb0b03b6bdbdbbb4baa"
LOCK_SHA256 = "c6dfaaf0e89a580cbe7ae613fd3f05f2fc1f1b53eee1aff8b615ee50f9ca50c7"
RUSTSEC_REVISION = "5a0ebedfe8bdd2e295b171f4162f8c977bcad9a5"
REQUEST_LIMIT = 40
DOWNLOAD_LIMIT_BYTES = 50 * 1024 * 1024
EVIDENCE_LIMIT_BYTES = 100 * 1024 * 1024
DEADLINE_SECONDS = 600
SINGLE_RESPONSE_LIMIT_BYTES = 20 * 1024 * 1024
API_HOST = "api.github.com"
LEGACY_RAW_HOST = "raw.githubusercontent.com"
USER_AGENT = "RadishLink-license-review/2"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
LICENSE_NAME = re.compile(
    r"^(?:license|licence|notice|copying|copyright|authors)(?:[._-].*)?$",
    re.IGNORECASE,
)
ALLOWED_BLOB_MODES = {"100644"}
HISTORICAL_SCHEMA1_RUNS = {
    "20260903-120514-82051.tt412fp1": {
        "manifest_sha256": "9fc406d7411c491dfaec6c1c171441bee7fb17f39b81d621fe3df4c760173fc9",
        "checksums_sha256": "e6722f2e374faae491f2c610ff1bf7220013107cf59bdcd053c2362e461848fe",
        "request_count": 5,
        "downloaded_bytes": 142464,
    },
    "20260903-121508-84631.nx_b_jte": {
        "manifest_sha256": "b0ed5c9e1c523d39f1e98e4d92accc1983f2cf27045323697221c5f66788f530",
        "checksums_sha256": "465e3b7eb937397fa93c52c0451eba25780c39541484e5f6465a4117ca23c523",
        "request_count": 3,
        "downloaded_bytes": 131504,
    },
}


class ReviewError(RuntimeError):
    """Base class for bounded review failures."""


class StopReview(ReviewError):
    """A substantive upstream or license evidence stop."""


class InvalidReview(ReviewError):
    """An invalid input, runtime, or evidence contract."""


@dataclass(frozen=True)
class PackageSpec:
    name: str
    version: str
    checksum: str
    license: str
    repository: str
    commit: str
    path_in_vcs: str


@dataclass(frozen=True)
class CommitSpec:
    repository: str
    commit: str

    @property
    def owner(self) -> str:
        return self.repository.split("/", 1)[0]

    @property
    def repo(self) -> str:
        return self.repository.split("/", 1)[1]

    @property
    def commit_url(self) -> str:
        return f"https://{API_HOST}/repos/{self.repository}/git/commits/{self.commit}"

    def tree_url(self, tree_sha: str) -> str:
        query = urlencode({"recursive": "1"})
        return f"https://{API_HOST}/repos/{self.repository}/git/trees/{tree_sha}?{query}"

    def blob_url(self, blob_sha: str) -> str:
        if not HEX40.fullmatch(blob_sha):
            raise InvalidReview("GitHub blob SHA is invalid")
        return f"https://{API_HOST}/repos/{self.repository}/git/blobs/{blob_sha}"


@dataclass(frozen=True)
class HttpPayload:
    url: str
    status: int
    content_type: str
    headers: dict[str, str]
    body: bytes


PACKAGES = (
    PackageSpec(
        "debug_tree",
        "0.4.0",
        "2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57",
        "MIT",
        "martypapa/debug-tree",
        "5b709de2d8872102b20b566c408d31d0662d7a9f",
        ".",
    ),
    PackageSpec(
        "mls-rs",
        "0.56.0",
        "4392c3b3ed7d835ca8f318f85ca65d3f0d3e879538d6e70679827a2f3af72029",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "8f1b43f447a792ff9307f1c2c7f54da63914870e",
        "mls-rs",
    ),
    PackageSpec(
        "mls-rs-codec",
        "0.7.0",
        "45bd834f164dc06c1fed805540ae307a460b7ed7c2769a35a376f1de577a0dc1",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "3a185cd2cf4c89c3cd30adf294d7c18d2735725e",
        "mls-rs-codec",
    ),
    PackageSpec(
        "mls-rs-codec-derive",
        "0.2.0",
        "c8b31fb579767147e96686889f1e7459d6bd41a131b11d7cd130776cffadb1c3",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "5224ee3afd6f9f026d579f3ed17a8fdda121946e",
        "mls-rs-codec-derive",
    ),
    PackageSpec(
        "mls-rs-core",
        "0.27.0",
        "e282079e5bd2fe95a009ac8af6a8e510924d876234ee494cd97f15f52de53cb0",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "a0eb41def0cf227034bde19b7c11e62ab2a74a03",
        "mls-rs-core",
    ),
    PackageSpec(
        "mls-rs-crypto-awslc",
        "0.25.0",
        "858ba8df345ebbda20868b503fda4fb46a921ca0e035025cbbaed0c8b5245da0",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "a0eb41def0cf227034bde19b7c11e62ab2a74a03",
        "mls-rs-crypto-awslc",
    ),
    PackageSpec(
        "mls-rs-crypto-hpke",
        "0.21.0",
        "b53db9a20568dec53e4f280ec8152c862b98efe105894e378d996be3305f32f2",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "a0eb41def0cf227034bde19b7c11e62ab2a74a03",
        "mls-rs-crypto-hpke",
    ),
    PackageSpec(
        "mls-rs-crypto-traits",
        "0.22.0",
        "49171fd5c7c77cd29ec452dcc6f537b8c568084b97023dcc5c0d41140da8ceb4",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "a0eb41def0cf227034bde19b7c11e62ab2a74a03",
        "mls-rs-crypto-traits",
    ),
    PackageSpec(
        "mls-rs-identity-x509",
        "0.21.0",
        "ec1ecb6a61a296b8240cea19171477293663dcc6540353dc8cbcda2d9f61039b",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "a0eb41def0cf227034bde19b7c11e62ab2a74a03",
        "mls-rs-identity-x509",
    ),
    PackageSpec(
        "mls-rs-provider-sqlite",
        "0.23.0",
        "e8e52c2b3b9c3421fe4bd96266016306595a66c1f4830ee2f1a19d50b209895e",
        "Apache-2.0 OR MIT",
        "awslabs/mls-rs",
        "a0eb41def0cf227034bde19b7c11e62ab2a74a03",
        "mls-rs-provider-sqlite",
    ),
    PackageSpec(
        "r-efi",
        "6.0.0",
        "f8dcc9c7d52a811697d2151c701e0d08956f92b0e24136cf4cf27b57a6a0d9bf",
        "MIT OR Apache-2.0 OR LGPL-2.1-or-later",
        "r-efi/r-efi",
        "7e1b0322d31d625f81a5656096330934f9cd835d",
        ".",
    ),
)


COMMITS = tuple(
    CommitSpec(repository, commit)
    for repository, commit in sorted({(item.repository, item.commit) for item in PACKAGES})
)

EXPECTED_ARCHIVE_LICENSE_LIKE = {
    ("debug_tree", "0.4.0"): ("doc/build/LICENSE.adoc",),
    ("r-efi", "6.0.0"): ("AUTHORS",),
}
ARCHIVE_LICENSE_LIKE_SCOPE = {
    ("debug_tree", "0.4.0", "doc/build/LICENSE.adoc"): {
        "applicable_to_package": False,
        "covers_declared_expression": False,
        "scope_note": "Asciidoctor documentation-build asset, not debug_tree package licensing",
    },
    ("r-efi", "6.0.0", "AUTHORS"): {
        "applicable_to_package": True,
        "covers_declared_expression": False,
        "scope_note": "project attribution and MIT text with Apache/LGPL notices, not both full texts",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise InvalidReview(f"{label} must be a regular non-symlink file: {path}")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise InvalidReview(f"refusing to overwrite evidence path: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_json(path: Path, payload: Any) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    atomic_write_bytes(path, encoded)


def directory_usage_bytes(root: Path) -> int:
    total = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in [*directory_names, *file_names]:
            try:
                total += (directory_path / name).lstat().st_size
            except FileNotFoundError:
                continue
    return total


def validate_revision(value: str) -> str:
    if not HEX40.fullmatch(value):
        raise argparse.ArgumentTypeError("revision must be exactly 40 lowercase hexadecimal characters")
    return value


def run_git(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise InvalidReview(f"git {' '.join(arguments)} failed with {result.returncode}")
    return result.stdout.rstrip("\n")


def normalized_repository(value: str) -> str:
    if not isinstance(value, str):
        raise InvalidReview("repository value must be a string")
    normalized = value.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.lower()


def parse_checksum_file(repo_root: Path, checksum_path: Path) -> list[dict[str, str]]:
    lines = checksum_path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 32:
        raise InvalidReview("D2 checksum file must contain exactly 32 entries")
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\x00\r\n]+)", line)
        if not match:
            raise InvalidReview("D2 checksum line is malformed")
        expected, relative = match.groups()
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or relative in seen:
            raise InvalidReview("D2 checksum path is unsafe or duplicated")
        seen.add(relative)
        target = repo_root.joinpath(*pure.parts)
        require_regular_file(target, "D2 checksum target")
        actual = sha256_file(target)
        if actual != expected:
            raise InvalidReview(f"D2 checksum mismatch: {relative}")
        results.append({"path": relative, "sha256": actual})
    return results


def validate_d2_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version": 2,
        "manifest_contract": "sw-g2-candidate-phase-a-v2",
        "run_id": D2_RUN_ID,
        "outcome": "PASS",
        "stage": "phase-a-prepared",
        "resolved_package_count": 94,
        "cargo_lock_sha256": LOCK_SHA256,
        "advisory_db_revision": RUSTSEC_REVISION,
        "lockfile_preexisting": False,
        "lockfile_seeded": True,
        "lockfile_written": True,
        "mutable_cache_reused": False,
        "container_residual_count": 0,
        "exit_code": 0,
    }
    for key, value in required.items():
        if manifest.get(key) != value:
            raise InvalidReview(f"D2 manifest field drifted: {key}")
    repository = manifest.get("repository", {})
    if repository.get("git_revision") != D2_REVISION or repository.get("git_dirty_before") is not False:
        raise InvalidReview("D2 repository identity drifted")
    if repository.get("git_status_before") != "":
        raise InvalidReview("D2 git status before must be empty")
    if repository.get("git_status_after") != "?? tools/spikes/sw-g2-mls-rs/Cargo.lock":
        raise InvalidReview("D2 git status after drifted")
    if manifest.get("gate_exit_codes") != {"source": 0, "audit": 0, "deny": 0, "feature": 0}:
        raise InvalidReview("D2 gate exit codes drifted")
    runtime = manifest.get("runtime_controls", {})
    if runtime.get("termination_reason") != "completed" or runtime.get("monitor_status") != "stopped":
        raise InvalidReview("D2 runtime completion drifted")
    if runtime.get("elapsed_milliseconds") != 40525 or runtime.get("disk_peak_kib") != 229278:
        raise InvalidReview("D2 runtime values drifted")
    seed = manifest.get("dependency_graph_seed", {})
    seed_required = {
        "contract": "sw-g2-mls-rs-d-final-v1",
        "run_id": "20260901-135918-13430.mvBCS2",
        "repository_revision": "36765755154dc88f8bd21605cbc25f5abf6bb828",
        "source_outcome": "STOP",
        "source_stage": "feature-gate",
        "cargo_lock_sha256": LOCK_SHA256,
        "resolved_package_count": 94,
    }
    for key, value in seed_required.items():
        if seed.get(key) != value:
            raise InvalidReview(f"D2 seed field drifted: {key}")
    return manifest


def safe_tar_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    for member in members:
        pure = PurePosixPath(member.name)
        normalized_name = member.name.rstrip("/") if member.isdir() else member.name
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or "" in pure.parts
            or pure.as_posix() != normalized_name
            or any(ord(character) < 32 or ord(character) == 127 for character in member.name)
        ):
            raise InvalidReview("crate archive contains an unsafe path")
    return members


def read_crate_member(archive: tarfile.TarFile, member_name: str) -> bytes:
    try:
        member = archive.getmember(member_name)
    except KeyError as error:
        raise InvalidReview(f"crate archive is missing {member_name}") from error
    if not member.isfile() or member.issym() or member.islnk():
        raise InvalidReview(f"crate archive member is not a regular file: {member_name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise InvalidReview(f"crate archive member cannot be read: {member_name}")
    return stream.read()


def find_crate_archive(cache_root: Path, package: PackageSpec) -> Path:
    matches = [path for path in cache_root.rglob(f"{package.name}-{package.version}.crate")]
    if len(matches) != 1:
        raise InvalidReview(f"expected one retained crate archive for {package.name} {package.version}")
    path = matches[0]
    require_regular_file(path, "crate archive")
    if sha256_file(path) != package.checksum:
        raise InvalidReview(f"crate archive checksum drifted: {package.name} {package.version}")
    return path


def validate_package_archive(
    repo_root: Path, cache_root: Path, package: PackageSpec
) -> dict[str, Any]:
    archive_path = find_crate_archive(cache_root, package)
    prefix = f"{package.name}-{package.version}"
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = safe_tar_members(archive)
        cargo_bytes = read_crate_member(archive, f"{prefix}/Cargo.toml")
        vcs_bytes = read_crate_member(archive, f"{prefix}/.cargo_vcs_info.json")
        license_like_members = [
            member
            for member in members
            if member.isfile() and LICENSE_NAME.fullmatch(PurePosixPath(member.name).name)
        ]
        license_like_files = []
        for member in license_like_members:
            relative = PurePosixPath(member.name).relative_to(prefix).as_posix()
            body = read_crate_member(archive, member.name)
            scope = ARCHIVE_LICENSE_LIKE_SCOPE.get((package.name, package.version, relative))
            if scope is None:
                raise InvalidReview(
                    f"fixed crate archive license-like inventory drifted: {package.name}"
                )
            license_like_files.append(
                {
                    "path": relative,
                    "sha256": sha256_bytes(body),
                    "detected_complete_license_texts": sorted(
                        classify_license_text(body.decode("utf-8"))
                    ),
                    **scope,
                }
            )
    actual_license_like = tuple(sorted(item["path"] for item in license_like_files))
    expected_license_like = EXPECTED_ARCHIVE_LICENSE_LIKE.get((package.name, package.version), ())
    if actual_license_like != expected_license_like:
        raise InvalidReview(f"fixed crate archive license-like inventory drifted: {package.name}")
    cargo = tomllib.loads(cargo_bytes.decode("utf-8"))
    package_table = cargo.get("package", {})
    expected_repository = f"https://github.com/{package.repository}"
    fields = {
        "name": package.name,
        "version": package.version,
        "license": package.license,
        "repository": expected_repository,
    }
    for key, value in fields.items():
        actual = package_table.get(key)
        if key == "repository":
            if not isinstance(actual, str) or normalized_repository(actual) != normalized_repository(value):
                raise InvalidReview(f"crate Cargo repository drifted: {package.name}")
        elif actual != value:
            raise InvalidReview(f"crate Cargo {key} drifted: {package.name}")
    vcs = json.loads(vcs_bytes.decode("utf-8"))
    if vcs.get("git", {}).get("sha1") != package.commit:
        raise InvalidReview(f"crate vcs commit drifted: {package.name}")
    path_in_vcs = vcs.get("path_in_vcs") or "."
    if path_in_vcs != package.path_in_vcs:
        raise InvalidReview(f"crate vcs path drifted: {package.name}")
    return {
        **asdict(package),
        "archive_relative_path": archive_path.relative_to(repo_root).as_posix(),
        "archive_sha256": sha256_file(archive_path),
        "cargo_toml_sha256": sha256_bytes(cargo_bytes),
        "cargo_vcs_info_sha256": sha256_bytes(vcs_bytes),
        "license_like_files_in_archive": license_like_files,
    }


def validate_lock_inventory(lock_path: Path) -> None:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    entries = lock.get("package", [])
    for package in PACKAGES:
        matches = [
            entry
            for entry in entries
            if entry.get("name") == package.name and entry.get("version") == package.version
        ]
        if len(matches) != 1:
            raise InvalidReview(f"lockfile package identity drifted: {package.name}")
        entry = matches[0]
        if entry.get("checksum") != package.checksum:
            raise InvalidReview(f"lockfile checksum drifted: {package.name}")
        if entry.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            raise InvalidReview(f"lockfile source drifted: {package.name}")


def validate_metadata_inventory(metadata_path: Path) -> None:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    entries = metadata.get("packages", [])
    for package in PACKAGES:
        matches = [
            entry
            for entry in entries
            if entry.get("name") == package.name and entry.get("version") == package.version
        ]
        if len(matches) != 1:
            raise InvalidReview(f"metadata package identity drifted: {package.name}")
        entry = matches[0]
        if entry.get("license") != package.license:
            raise InvalidReview(f"metadata license drifted: {package.name}")
        expected_repository = f"https://github.com/{package.repository}"
        if normalized_repository(entry.get("repository", "")) != normalized_repository(expected_repository):
            raise InvalidReview(f"metadata repository drifted: {package.name}")
        if entry.get("source") != "registry+https://github.com/rust-lang/crates.io-index":
            raise InvalidReview(f"metadata source drifted: {package.name}")


def validate_audit_summary(audit_path: Path) -> None:
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not isinstance(audit, dict):
        raise InvalidReview("D2 cargo-audit report is not an object")
    if audit.get("database") != {
        "advisory-count": 1239,
        "last-commit": RUSTSEC_REVISION,
        "last-updated": "2026-09-02T11:13:32+02:00",
    }:
        raise InvalidReview("D2 cargo-audit database summary drifted")
    if audit.get("lockfile") != {"dependency-count": 94}:
        raise InvalidReview("D2 cargo-audit dependency count drifted")
    if audit.get("vulnerabilities") != {"found": False, "count": 0, "list": []}:
        raise InvalidReview("D2 cargo-audit vulnerability summary drifted")
    if audit.get("warnings") != {}:
        raise InvalidReview("D2 cargo-audit warning summary drifted")
    settings = audit.get("settings", {})
    if not isinstance(settings, dict) or settings.get("ignore") != []:
        raise InvalidReview("D2 cargo-audit ignore settings drifted")


def local_preflight(repo_root: Path, expected_revision: str) -> dict[str, Any]:
    head = run_git(repo_root, "rev-parse", "HEAD")
    if head != expected_revision:
        raise InvalidReview("HEAD does not match the explicitly authorized clean revision")
    if run_git(repo_root, "status", "--porcelain=v1"):
        raise InvalidReview("R1c collection requires a clean worktree")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", R0_REVISION, head],
        cwd=repo_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ancestor.returncode != 0:
        raise InvalidReview("R0 clean revision is not an ancestor of HEAD")

    d2_dir = repo_root / "artifacts" / "sw-g2-mls-rs" / D2_RUN_ID
    manifest_path = d2_dir / "manifest.json"
    checksums_path = d2_dir / "checksums.sha256"
    require_regular_file(manifest_path, "D2 manifest")
    require_regular_file(checksums_path, "D2 checksums")
    if sha256_file(manifest_path) != D2_MANIFEST_SHA256:
        raise InvalidReview("D2 manifest checksum drifted")
    if sha256_file(checksums_path) != D2_CHECKSUMS_SHA256:
        raise InvalidReview("D2 checksum list checksum drifted")
    manifest = validate_d2_manifest(manifest_path)
    checksum_entries = parse_checksum_file(repo_root, checksums_path)

    lock_paths = (
        repo_root / "tools" / "spikes" / "sw-g2-mls-rs" / "Cargo.lock",
        repo_root / "artifacts" / "sw-g2-mls-rs" / "20260901-135918-13430.mvBCS2" / "Cargo.lock",
        d2_dir / "Cargo.lock",
    )
    lock_payloads: list[bytes] = []
    for lock_path in lock_paths:
        require_regular_file(lock_path, "fixed lockfile")
        if sha256_file(lock_path) != LOCK_SHA256:
            raise InvalidReview(f"fixed lockfile checksum drifted: {lock_path}")
        lock_payloads.append(lock_path.read_bytes())
    if len(set(lock_payloads)) != 1:
        raise InvalidReview("repository, D seed, and D2 lockfiles differ")
    validate_lock_inventory(lock_paths[0])
    metadata_path = d2_dir / "cargo-metadata.json"
    require_regular_file(metadata_path, "D2 metadata")
    validate_metadata_inventory(metadata_path)
    audit_path = d2_dir / "cargo-audit.json"
    require_regular_file(audit_path, "D2 cargo-audit report")
    validate_audit_summary(audit_path)

    cache_root = d2_dir / ".work" / "cargo-home" / "registry" / "cache"
    if cache_root.is_symlink() or not cache_root.is_dir():
        raise InvalidReview("retained D2 registry cache is unavailable or a symlink")
    package_inventory = [validate_package_archive(repo_root, cache_root, item) for item in PACKAGES]

    return {
        "repository_revision": head,
        "r0_revision": R0_REVISION,
        "d2": {
            "run_id": D2_RUN_ID,
            "revision": D2_REVISION,
            "manifest_sha256": D2_MANIFEST_SHA256,
            "checksums_sha256": D2_CHECKSUMS_SHA256,
            "checksum_entry_count": len(checksum_entries),
            "lock_sha256": LOCK_SHA256,
            "resolved_package_count": manifest["resolved_package_count"],
            "gate_exit_codes": manifest["gate_exit_codes"],
            "advisory_db_revision": manifest["advisory_db_revision"],
        },
        "packages": package_inventory,
    }


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


class HttpSession:
    def __init__(self, start_monotonic: float) -> None:
        self.start_monotonic = start_monotonic
        self.allowed_urls = {item.commit_url for item in COMMITS}
        self.request_count = 0
        self.downloaded_bytes = 0
        self.observations: list[dict[str, Any]] = []
        self.opener = build_opener(ProxyHandler({}), NoRedirectHandler(), HTTPSHandler())

    def allow(self, url: str) -> None:
        validate_url_shape(url)
        self.allowed_urls.add(url)

    def get(self, url: str, kind: str) -> HttpPayload:
        if kind != "api":
            raise InvalidReview("R1c transport only permits GitHub API responses")
        if url not in self.allowed_urls:
            raise InvalidReview(f"request URL is outside the derived allowlist: {url}")
        validate_url_shape(url)
        if self.request_count >= REQUEST_LIMIT:
            raise StopReview("HTTP request limit reached")
        elapsed = time.monotonic() - self.start_monotonic
        if elapsed >= DEADLINE_SECONDS:
            raise StopReview("R1c deadline reached")
        self.request_count += 1
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with self.opener.open(request, timeout=min(30.0, DEADLINE_SECONDS - elapsed)) as response:
                status = response.status
                headers = {key.lower(): value for key, value in response.headers.items()}
                body = response.read(SINGLE_RESPONSE_LIMIT_BYTES + 1)
        except HTTPError as error:
            headers = {
                key.lower(): value
                for key, value in (error.headers.items() if error.headers is not None else [])
            }
            body = error.read(SINGLE_RESPONSE_LIMIT_BYTES + 1)
            content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            selected_headers = {
                key: headers[key]
                for key in ("content-type", "content-length", "etag", "last-modified", "location")
                if key in headers
            }
            self.downloaded_bytes += len(body)
            self.observations.append(
                make_http_observation(
                    url,
                    error.code,
                    content_type,
                    body,
                    selected_headers,
                    f"HTTPError: {error.code}",
                )
            )
            if len(body) > SINGLE_RESPONSE_LIMIT_BYTES:
                raise StopReview("single HTTP error response exceeded its byte limit") from error
            if self.downloaded_bytes > DOWNLOAD_LIMIT_BYTES:
                raise StopReview("total HTTP download limit reached") from error
            raise StopReview(f"HTTP request returned {error.code}: {url}") from error
        except (URLError, TimeoutError, OSError) as error:
            self.observations.append(
                make_http_observation(url, None, "", b"", {}, type(error).__name__)
            )
            raise StopReview(f"HTTP request failed without retry: {url}") from error
        if status != 200:
            raise StopReview(f"HTTP status is not 200: {status}")
        if len(body) > SINGLE_RESPONSE_LIMIT_BYTES:
            raise StopReview("single HTTP response exceeded its byte limit")
        self.downloaded_bytes += len(body)
        if self.downloaded_bytes > DOWNLOAD_LIMIT_BYTES:
            raise StopReview("total HTTP download limit reached")
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        validate_http_body(kind, content_type, body)
        selected_headers = {
            key: headers[key]
            for key in ("content-type", "content-length", "etag", "last-modified")
            if key in headers
        }
        self.observations.append(
            make_http_observation(url, status, content_type, body, selected_headers)
        )
        return HttpPayload(url, status, content_type, selected_headers, body)


class FakeSession:
    def __init__(self, responses: dict[str, HttpPayload]) -> None:
        self.responses = responses
        self.allowed_urls: set[str] = set()
        self.request_count = 0
        self.downloaded_bytes = 0
        self.observations: list[dict[str, Any]] = []

    def allow(self, url: str) -> None:
        validate_url_shape(url)
        self.allowed_urls.add(url)

    def get(self, url: str, kind: str) -> HttpPayload:
        if kind != "api":
            raise InvalidReview("R1c fake transport only permits GitHub API responses")
        if url not in self.allowed_urls:
            raise InvalidReview("fake request escaped the derived allowlist")
        validate_url_shape(url)
        self.request_count += 1
        try:
            response = self.responses[url]
        except KeyError as error:
            raise AssertionError(f"missing fake response: {url}") from error
        self.observations.append(
            make_http_observation(
                url,
                response.status,
                response.content_type,
                response.body,
                response.headers,
            )
        )
        self.downloaded_bytes += len(response.body)
        if response.status != 200:
            raise StopReview(f"unexpected HTTP status: {response.status}")
        validate_http_body(kind, response.content_type, response.body)
        return response


def make_http_observation(
    url: str,
    status: int | None,
    content_type: str,
    body: bytes,
    headers: dict[str, str],
    error: str | None = None,
) -> dict[str, Any]:
    parsed = urlsplit(url)
    observation = {
        "method": "GET",
        "host": parsed.hostname,
        "path": parsed.path,
        "query": parsed.query,
        "url": url,
        "status": status,
        "content_type": content_type,
        "byte_count": len(body),
        "sha256": sha256_bytes(body),
        "headers": headers,
    }
    if error is not None:
        observation["error"] = error
    return observation


def validate_url_shape(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise InvalidReview("request URL must be anonymous HTTPS without a fragment")
    if parsed.hostname != API_HOST:
        raise InvalidReview("request URL host is not allowed")
    if parsed.port not in {None, 443}:
        raise InvalidReview("request URL port is not allowed")
    pure = PurePosixPath(parsed.path)
    if (
        not parsed.path.startswith("/")
        or "//" in parsed.path
        or ".." in pure.parts
        or "" in pure.parts[1:]
    ):
        raise InvalidReview("request URL path is unsafe")
    if parsed.query not in {"", "recursive=1"}:
        raise InvalidReview("API request URL query is not allowed")


def validate_http_body(kind: str, content_type: str, body: bytes) -> None:
    if not body:
        raise StopReview("HTTP response is empty")
    lowered = content_type.lower()
    if kind != "api":
        raise InvalidReview("R1c HTTP validation only permits GitHub API responses")
    if lowered not in {"application/json", "application/vnd.github+json"}:
        raise StopReview("GitHub API response is not JSON")
    try:
        json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StopReview("GitHub API response is invalid JSON") from error


def validate_decoded_text(body: bytes) -> str:
    if not body:
        raise StopReview("decoded Git blob is empty")
    if b"\x00" in body:
        raise StopReview("decoded Git blob contains binary NUL bytes")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        raise StopReview("decoded Git blob is not UTF-8 text") from error
    if text.startswith("version https://git-lfs.github.com/spec/v1"):
        raise StopReview("decoded Git blob is a Git LFS pointer")
    if text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise StopReview("decoded Git blob is HTML")
    return text


def validate_commit_payload(payload: HttpPayload, spec: CommitSpec) -> str:
    data = json.loads(payload.body.decode("utf-8"))
    if not isinstance(data, dict):
        raise InvalidReview(f"GitHub commit response is not an object: {spec.repository}")
    if data.get("sha") != spec.commit:
        raise InvalidReview(f"GitHub commit identity drifted: {spec.repository}")
    tree = data.get("tree")
    if not isinstance(tree, dict):
        raise InvalidReview(f"GitHub commit tree object is missing: {spec.repository}")
    tree_sha = tree.get("sha")
    if not isinstance(tree_sha, str) or not HEX40.fullmatch(tree_sha):
        raise InvalidReview(f"GitHub commit tree SHA is invalid: {spec.repository}")
    return tree_sha


def safe_tree_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise InvalidReview("GitHub tree path is empty or absolute")
    pure = PurePosixPath(value)
    if ".." in pure.parts or "" in pure.parts or pure.as_posix() != value:
        raise InvalidReview("GitHub tree path is unsafe")
    return pure.as_posix()


def validate_tree_payload(payload: HttpPayload, tree_sha: str) -> dict[str, dict[str, Any]]:
    data = json.loads(payload.body.decode("utf-8"))
    if not isinstance(data, dict):
        raise InvalidReview("GitHub tree response is not an object")
    if data.get("sha") != tree_sha:
        raise InvalidReview("GitHub tree identity drifted")
    if data.get("truncated") is not False:
        raise InvalidReview("GitHub tree is truncated or lacks a non-truncated assertion")
    entries = data.get("tree")
    if not isinstance(entries, list):
        raise InvalidReview("GitHub tree entries are missing")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise InvalidReview("GitHub tree entry is invalid")
        path = safe_tree_path(entry.get("path", ""))
        if path in result:
            raise InvalidReview("GitHub tree contains duplicate paths")
        result[path] = entry
    return result


def ancestor_directories(path_in_vcs: str) -> list[str]:
    if path_in_vcs in {"", "."}:
        return [""]
    pure = PurePosixPath(safe_tree_path(path_in_vcs))
    result = [""]
    current: list[str] = []
    for part in pure.parts:
        current.append(part)
        result.append("/".join(current))
    return result


def join_tree_path(directory: str, name: str) -> str:
    return f"{directory}/{name}" if directory else name


def is_regular_tree_blob(entry: dict[str, Any]) -> bool:
    return entry.get("type") == "blob" and entry.get("mode") in ALLOWED_BLOB_MODES


def validate_selected_blob_entry(
    spec: CommitSpec,
    path: str,
    entry: dict[str, Any],
) -> tuple[str, int, str]:
    safe_tree_path(path)
    if entry.get("type") != "blob" or entry.get("mode") != "100644":
        raise StopReview(f"selected tree entry is not a mode 100644 blob: {path}")
    blob_sha = entry.get("sha")
    if not isinstance(blob_sha, str) or not HEX40.fullmatch(blob_sha):
        raise InvalidReview(f"selected tree entry blob SHA is invalid: {path}")
    size = entry.get("size")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 <= size <= SINGLE_RESPONSE_LIMIT_BYTES
    ):
        raise InvalidReview(f"selected tree entry size is invalid: {path}")
    api_url = spec.blob_url(blob_sha)
    tree_url = entry.get("url")
    if tree_url is not None and tree_url != api_url:
        raise InvalidReview(f"selected tree entry URL differs from the derived blob URL: {path}")
    return blob_sha, size, api_url


def validate_blob_payload(
    payload: HttpPayload,
    spec: CommitSpec,
    path: str,
    entry: dict[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    blob_sha, tree_size, api_url = validate_selected_blob_entry(spec, path, entry)
    if payload.url != api_url:
        raise InvalidReview(f"GitHub blob response URL differs from the derived URL: {path}")
    data = json.loads(payload.body.decode("utf-8"))
    if not isinstance(data, dict):
        raise InvalidReview(f"GitHub blob response is not an object: {path}")
    if data.get("sha") != blob_sha:
        raise InvalidReview(f"GitHub blob response SHA differs from the tree entry: {path}")
    if data.get("encoding") != "base64":
        raise InvalidReview(f"GitHub blob response encoding is not base64: {path}")
    content = data.get("content")
    if not isinstance(content, str):
        raise InvalidReview(f"GitHub blob response content is not a string: {path}")
    response_size = data.get("size")
    if isinstance(response_size, bool) or not isinstance(response_size, int) or response_size < 0:
        raise InvalidReview(f"GitHub blob response size is invalid: {path}")
    compact_content = content.replace("\r", "").replace("\n", "")
    try:
        decoded = base64.b64decode(compact_content.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise InvalidReview(f"GitHub blob response contains invalid base64: {path}") from error
    if response_size != tree_size or len(decoded) != tree_size:
        raise InvalidReview(f"GitHub blob decoded size differs from the tree entry: {path}")
    if git_blob_sha1(decoded) != blob_sha:
        raise InvalidReview(f"decoded Git blob SHA-1 differs from the tree entry: {path}")
    validate_decoded_text(decoded)
    repository_path = f"{spec.repository}/{spec.commit}/{path}"
    return decoded, {
        "repository": spec.repository,
        "commit": spec.commit,
        "tree_path": path,
        "tree_entry_type": "blob",
        "tree_entry_mode": "100644",
        "tree_entry_size": tree_size,
        "tree_entry_url": entry.get("url"),
        "blob_sha": blob_sha,
        "api_url": api_url,
        "envelope_path": f"blobs/{repository_path}.json",
        "envelope_sha256": sha256_bytes(payload.body),
        "decoded_path": f"upstream/{repository_path}",
        "decoded_sha256": sha256_bytes(decoded),
        "decoded_size": len(decoded),
    }


def select_initial_paths(
    tree: dict[str, dict[str, Any]],
    packages: Iterable[PackageSpec],
) -> dict[str, set[str]]:
    selected: dict[str, set[str]] = {}
    for package in packages:
        package_paths: set[str] = set()
        ancestors = ancestor_directories(package.path_in_vcs)
        for directory in ancestors:
            manifest_path = join_tree_path(directory, "Cargo.toml")
            entry = tree.get(manifest_path)
            if entry is None or not is_regular_tree_blob(entry):
                raise StopReview(f"upstream manifest is missing or not a regular file: {manifest_path}")
            package_paths.add(manifest_path)
        for path, entry in tree.items():
            pure = PurePosixPath(path)
            parent = pure.parent.as_posix()
            if parent == ".":
                parent = ""
            for directory in ancestors:
                licenses_prefix = join_tree_path(directory, "LICENSES") + "/"
                lowercase_prefix = join_tree_path(directory, "licenses") + "/"
                candidate = (
                    parent == directory and LICENSE_NAME.fullmatch(pure.name) is not None
                ) or path.startswith(licenses_prefix) or path.startswith(lowercase_prefix)
                if candidate:
                    if not is_regular_tree_blob(entry):
                        raise StopReview(f"license/notice candidate is non-regular: {path}")
                    package_paths.add(path)
        selected[package.name] = package_paths
    return selected


def resolve_manifest_field(
    package_table: dict[str, Any],
    workspace_package: dict[str, Any],
    field: str,
    package_directory: str,
) -> tuple[Any, str]:
    value = package_table.get(field)
    if isinstance(value, dict) and value.get("workspace") is True:
        return workspace_package.get(field), ""
    return value, package_directory


def safe_relative_reference(base_directory: str, value: str) -> str:
    if not value or value.startswith("/"):
        raise StopReview("manifest-referenced path is empty or absolute")
    combined = PurePosixPath(base_directory) / PurePosixPath(value)
    if ".." in combined.parts or "" in combined.parts:
        raise StopReview("manifest-referenced path escapes its allowed directory")
    return combined.as_posix()


def manifest_identity_and_references(
    package: PackageSpec,
    raw_files: dict[str, bytes],
) -> list[dict[str, str]]:
    package_directory = "" if package.path_in_vcs == "." else package.path_in_vcs
    package_manifest_path = join_tree_path(package_directory, "Cargo.toml")
    try:
        root_manifest = tomllib.loads(raw_files["Cargo.toml"].decode("utf-8"))
        package_manifest = tomllib.loads(raw_files[package_manifest_path].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise StopReview(f"upstream Cargo manifest cannot be parsed: {package.name}") from error
    package_table = package_manifest.get("package", {})
    workspace = root_manifest.get("workspace", {})
    if not isinstance(workspace, dict):
        raise StopReview(f"upstream Cargo workspace table is invalid: {package.name}")
    workspace_package = workspace.get("package", {})
    if not isinstance(package_table, dict) or not isinstance(workspace_package, dict):
        raise StopReview(f"upstream Cargo manifest tables are invalid: {package.name}")
    name, _ = resolve_manifest_field(package_table, workspace_package, "name", package_directory)
    version, _ = resolve_manifest_field(package_table, workspace_package, "version", package_directory)
    license_value, _ = resolve_manifest_field(package_table, workspace_package, "license", package_directory)
    repository, _ = resolve_manifest_field(package_table, workspace_package, "repository", package_directory)
    if name != package.name or version != package.version or license_value != package.license:
        raise StopReview(f"upstream manifest identity or license differs: {package.name}")
    expected_repository = f"https://github.com/{package.repository}"
    if not isinstance(repository, str) or normalized_repository(repository) != normalized_repository(expected_repository):
        raise StopReview(f"upstream manifest repository differs: {package.name}")
    references: list[dict[str, str]] = []
    for field in ("license-file", "readme"):
        value, base = resolve_manifest_field(package_table, workspace_package, field, package_directory)
        if value is None or value is False:
            continue
        if not isinstance(value, str):
            raise StopReview(f"upstream manifest {field} is not a path string: {package.name}")
        direct_value = package_table.get(field)
        source_manifest = (
            "Cargo.toml"
            if isinstance(direct_value, dict) and direct_value.get("workspace") is True
            else package_manifest_path
        )
        references.append(
            {
                "field": field,
                "source_manifest": source_manifest,
                "path": safe_relative_reference(base, value),
            }
        )
    return references


def classify_license_text(text: str) -> set[str]:
    lowered = text.lower()
    found: set[str] = set()
    if "permission is hereby granted, free of charge" in lowered and "the software is provided \"as is\"" in lowered:
        found.add("MIT")
    if "apache license" in lowered and "version 2.0, january 2004" in lowered:
        found.add("Apache-2.0")
    if (
        "gnu lesser general public license" in lowered
        and "version 2.1, february 1999" in lowered
        and "terms and conditions for copying, distribution and modification" in lowered
    ):
        found.add("LGPL-2.1-or-later")
    return found


def required_license_ids(expression: str) -> set[str]:
    values = {value.strip() for value in expression.split(" OR ")}
    allowed = {"MIT", "Apache-2.0", "LGPL-2.1-or-later"}
    if not values or not values.issubset(allowed):
        raise InvalidReview(f"unsupported fixed SPDX expression: {expression}")
    return values


def save_http_payload(run_dir: Path, relative: str, payload: HttpPayload) -> None:
    atomic_write_bytes(run_dir / relative, payload.body)
    if directory_usage_bytes(run_dir) > EVIDENCE_LIMIT_BYTES:
        raise StopReview("evidence budget exceeded")


def fetch_selected_blob(
    run_dir: Path,
    spec: CommitSpec,
    path: str,
    tree: dict[str, dict[str, Any]],
    session: HttpSession | FakeSession,
    decoded_payloads: dict[str, bytes],
    blob_records: dict[str, dict[str, Any]],
) -> None:
    if path in decoded_payloads:
        return
    entry = tree.get(path)
    if entry is None:
        raise StopReview(f"selected tree path is absent: {path}")
    _, _, api_url = validate_selected_blob_entry(spec, path, entry)
    session.allow(api_url)
    payload = session.get(api_url, "api")
    envelope_path = f"blobs/{spec.repository}/{spec.commit}/{path}.json"
    save_http_payload(run_dir, envelope_path, payload)
    decoded, record = validate_blob_payload(payload, spec, path, entry)
    if record["envelope_path"] != envelope_path:
        raise InvalidReview("derived blob envelope path drifted")
    atomic_write_bytes(run_dir / record["decoded_path"], decoded)
    if directory_usage_bytes(run_dir) > EVIDENCE_LIMIT_BYTES:
        raise StopReview("evidence budget exceeded")
    decoded_payloads[path] = decoded
    blob_records[path] = record


def collect_remote(
    run_dir: Path,
    packages: tuple[PackageSpec, ...],
    commits: tuple[CommitSpec, ...],
    session: HttpSession | FakeSession,
    all_mappings: list[dict[str, Any]] | None = None,
    commit_records: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    packages_by_commit: dict[tuple[str, str], list[PackageSpec]] = {}
    for package in packages:
        packages_by_commit.setdefault((package.repository, package.commit), []).append(package)

    if all_mappings is None:
        all_mappings = []
    if commit_records is None:
        commit_records = []
    for commit_spec in commits:
        session.allow(commit_spec.commit_url)
        commit_payload = session.get(commit_spec.commit_url, "api")
        commit_file = f"commits/{commit_spec.repository.replace('/', '_')}-{commit_spec.commit}.json"
        save_http_payload(run_dir, commit_file, commit_payload)
        tree_sha = validate_commit_payload(commit_payload, commit_spec)

        tree_url = commit_spec.tree_url(tree_sha)
        session.allow(tree_url)
        tree_payload = session.get(tree_url, "api")
        tree_file = f"trees/{commit_spec.repository.replace('/', '_')}-{commit_spec.commit}.json"
        save_http_payload(run_dir, tree_file, tree_payload)
        tree = validate_tree_payload(tree_payload, tree_sha)
        current_packages = packages_by_commit[(commit_spec.repository, commit_spec.commit)]
        selected = select_initial_paths(tree, current_packages)
        union_paths = set().union(*selected.values())

        decoded_payloads: dict[str, bytes] = {}
        blob_records: dict[str, dict[str, Any]] = {}
        commit_record = {
            "repository": commit_spec.repository,
            "commit": commit_spec.commit,
            "tree_sha": tree_sha,
            "tree_truncated": False,
            "commit_url": commit_spec.commit_url,
            "tree_url": tree_url,
            "commit_response_path": commit_file,
            "tree_response_path": tree_file,
            "commit_response_sha256": sha256_bytes(commit_payload.body),
            "tree_response_sha256": sha256_bytes(tree_payload.body),
            "transport": "git-blobs-api",
            "blobs": [],
            "notice_present": False,
            "notice_paths": [],
        }
        commit_records.append(commit_record)
        for path in sorted(union_paths):
            fetch_selected_blob(
                run_dir,
                commit_spec,
                path,
                tree,
                session,
                decoded_payloads,
                blob_records,
            )
            commit_record["blobs"] = [blob_records[item] for item in sorted(blob_records)]

        referenced_by_package: dict[str, list[dict[str, str]]] = {}
        for package in current_packages:
            references = manifest_identity_and_references(package, decoded_payloads)
            referenced_by_package[package.name] = references
            for reference in references:
                reference_path = reference["path"]
                entry = tree.get(reference_path)
                if entry is None or not is_regular_tree_blob(entry):
                    raise StopReview(
                        f"manifest-referenced file is absent or non-regular: {reference_path}"
                    )
                selected[package.name].add(reference_path)
                fetch_selected_blob(
                    run_dir,
                    commit_spec,
                    reference_path,
                    tree,
                    session,
                    decoded_payloads,
                    blob_records,
                )
                commit_record["blobs"] = [
                    blob_records[item] for item in sorted(blob_records)
                ]

        for package in current_packages:
            paths = sorted(selected[package.name])
            classifications: set[str] = set()
            notice_paths: list[str] = []
            copyright_paths: list[str] = []
            evidence_files: list[dict[str, Any]] = []
            for path in paths:
                body = decoded_payloads[path]
                text = body.decode("utf-8")
                classifications.update(classify_license_text(text))
                basename = PurePosixPath(path).name
                if basename.lower().startswith("notice"):
                    notice_paths.append(path)
                if basename.lower().startswith("copyright") or "copyright" in text.lower():
                    copyright_paths.append(path)
                evidence_files.append(dict(blob_records[path]))
            required = required_license_ids(package.license)
            missing = sorted(required - classifications)
            all_mappings.append(
                {
                    "package": package.name,
                    "version": package.version,
                    "registry_checksum": package.checksum,
                    "repository": package.repository,
                    "commit": package.commit,
                    "path_in_vcs": package.path_in_vcs,
                    "declared_license": package.license,
                    "required_license_texts": sorted(required),
                    "detected_license_texts": sorted(classifications),
                    "missing_license_texts": missing,
                    "notice_paths": sorted(set(notice_paths)),
                    "notice_present": bool(notice_paths),
                    "copyright_paths": sorted(set(copyright_paths)),
                    "manifest_references": referenced_by_package[package.name],
                    "evidence_files": evidence_files,
                }
            )
        commit_mapping = [
            item
            for item in all_mappings
            if item["repository"] == commit_spec.repository and item["commit"] == commit_spec.commit
        ]
        commit_notice_paths = sorted(
            {
                path
                for item in commit_mapping
                for path in item["notice_paths"]
            }
        )
        commit_record["notice_present"] = bool(commit_notice_paths)
        commit_record["notice_paths"] = commit_notice_paths

    return all_mappings, commit_records


def build_checksums(repo_root: Path, partial_dir: Path, final_dir: Path) -> str:
    paths = sorted(
        path
        for path in partial_dir.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name != "checksums.sha256"
    )
    lines: list[str] = []
    for path in paths:
        relative_inside = path.relative_to(partial_dir)
        final_path = final_dir / relative_inside
        relative_repo = final_path.relative_to(repo_root).as_posix()
        lines.append(f"{sha256_file(path)}  {relative_repo}")
    return "\n".join(lines) + "\n"


def verify_checksum_text(
    repo_root: Path,
    checksum_text: str,
    expected_root: Path | None = None,
    actual_root: Path | None = None,
) -> None:
    for line in checksum_text.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\x00\r\n]+)", line)
        if not match:
            raise InvalidReview("generated checksum line is malformed")
        expected, relative = match.groups()
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            raise InvalidReview("generated checksum path is unsafe")
        target = repo_root.joinpath(*pure.parts)
        if expected_root is not None or actual_root is not None:
            if expected_root is None or actual_root is None:
                raise InvalidReview("checksum root override is incomplete")
            try:
                target = actual_root / target.relative_to(expected_root)
            except ValueError as error:
                raise InvalidReview("generated checksum path escaped the final evidence root") from error
        require_regular_file(target, "generated checksum target")
        if sha256_file(target) != expected:
            raise InvalidReview(f"generated checksum mismatch: {relative}")


def manifest_schema(manifest: dict[str, Any]) -> int:
    identity = (manifest.get("schema_version"), manifest.get("manifest_contract"))
    if identity == (LEGACY_SCHEMA_VERSION, LEGACY_MANIFEST_CONTRACT):
        return LEGACY_SCHEMA_VERSION
    if identity == (SCHEMA_VERSION, MANIFEST_CONTRACT):
        return SCHEMA_VERSION
    raise InvalidReview("license review manifest schema or contract is unsupported")


def evidence_file(run_dir: Path, relative: str, label: str) -> Path:
    if not isinstance(relative, str):
        raise InvalidReview(f"{label} path is not a string")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "" in pure.parts or pure.as_posix() != relative:
        raise InvalidReview(f"{label} path is unsafe")
    target = run_dir.joinpath(*pure.parts)
    require_regular_file(target, label)
    return target


def validate_evidence_checksums(repo_root: Path, run_dir: Path) -> None:
    checksum_path = run_dir / "checksums.sha256"
    require_regular_file(checksum_path, "license review checksums")
    checksum_text = checksum_path.read_text(encoding="utf-8")
    verify_checksum_text(repo_root, checksum_text)
    expected_prefix = run_dir.relative_to(repo_root).as_posix() + "/"
    listed: set[str] = set()
    for line in checksum_text.splitlines():
        match = re.fullmatch(r"[0-9a-f]{64}  ([^\x00\r\n]+)", line)
        if match is None:
            raise InvalidReview("license review checksum line is malformed")
        relative = match.group(1)
        if not relative.startswith(expected_prefix) or relative in listed:
            raise InvalidReview("license review checksum path escaped or is duplicated")
        listed.add(relative)
    all_paths = list(run_dir.rglob("*"))
    if any(path.is_symlink() for path in all_paths):
        raise InvalidReview("license review evidence contains a symbolic link")
    actual = {
        path.relative_to(repo_root).as_posix()
        for path in all_paths
        if path.is_file() and path != checksum_path
    }
    if listed != actual:
        raise InvalidReview("license review checksum coverage differs from final files")


def validate_network_contract(manifest: dict[str, Any], allowed_hosts: list[str]) -> None:
    network = manifest.get("network")
    if not isinstance(network, dict):
        raise InvalidReview("license review network contract is missing")
    required = {
        "method": "GET",
        "allowed_hosts": allowed_hosts,
        "anonymous": True,
        "proxies_disabled": True,
        "redirects_disabled": True,
        "request_limit": REQUEST_LIMIT,
        "download_limit_bytes": DOWNLOAD_LIMIT_BYTES,
        "retry": False,
    }
    for key, value in required.items():
        if network.get(key) != value:
            raise InvalidReview(f"license review network field drifted: {key}")
    requests = network.get("requests")
    if not isinstance(requests, list) or network.get("request_count") != len(requests):
        raise InvalidReview("license review request count drifted")
    if len(requests) > REQUEST_LIMIT:
        raise InvalidReview("license review request limit was exceeded")
    downloaded = 0
    for observation in requests:
        if not isinstance(observation, dict):
            raise InvalidReview("license review HTTP observation is invalid")
        if observation.get("method") != "GET" or observation.get("host") not in allowed_hosts:
            raise InvalidReview("license review HTTP observation escaped the contract")
        byte_count = observation.get("byte_count")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise InvalidReview("license review HTTP byte count is invalid")
        downloaded += byte_count
        digest = observation.get("sha256")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise InvalidReview("license review HTTP digest is invalid")
    if network.get("downloaded_bytes") != downloaded or downloaded > DOWNLOAD_LIMIT_BYTES:
        raise InvalidReview("license review downloaded byte count drifted")
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        raise InvalidReview("license review runtime contract is missing")
    if runtime.get("deadline_seconds") != DEADLINE_SECONDS:
        raise InvalidReview("license review deadline drifted")
    if runtime.get("evidence_limit_bytes") != EVIDENCE_LIMIT_BYTES:
        raise InvalidReview("license review evidence limit drifted")
    if runtime.get("background_processes_started") != 0:
        raise InvalidReview("license review unexpectedly started a background process")
    elapsed = runtime.get("elapsed_milliseconds")
    evidence_bytes = runtime.get("evidence_bytes_before_manifest")
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, int)
        or not 0 <= elapsed <= DEADLINE_SECONDS * 1000
    ):
        raise InvalidReview("license review elapsed time is invalid")
    if (
        isinstance(evidence_bytes, bool)
        or not isinstance(evidence_bytes, int)
        or not 0 <= evidence_bytes <= EVIDENCE_LIMIT_BYTES
    ):
        raise InvalidReview("license review evidence byte count is invalid")


def validate_schema1_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    run_id = run_dir.name
    expected = HISTORICAL_SCHEMA1_RUNS.get(run_id)
    if expected is None:
        raise InvalidReview("schema 1 evidence is not one of the two frozen historical runs")
    required = {
        "run_id": run_id,
        "outcome": "STOP",
        "stage": "license-evidence",
        "exit_code": 20,
        "package_count": len(PACKAGES),
        "repository_count": 3,
        "commit_count": len(COMMITS),
        "commits": [],
        "package_license_mapping": [],
    }
    for key, value in required.items():
        if manifest.get(key) != value:
            raise InvalidReview(f"historical schema 1 manifest field drifted: {key}")
    validate_network_contract(manifest, [API_HOST, LEGACY_RAW_HOST])
    network = manifest["network"]
    if network.get("request_count") != expected["request_count"]:
        raise InvalidReview("historical schema 1 request count drifted")
    if network.get("downloaded_bytes") != expected["downloaded_bytes"]:
        raise InvalidReview("historical schema 1 downloaded byte count drifted")
    requests = network["requests"]
    if sum(item.get("error") == "TimeoutError" for item in requests) != 1:
        raise InvalidReview("historical schema 1 timeout evidence drifted")
    for observation in requests:
        parsed = urlsplit(observation.get("url", ""))
        if parsed.hostname != observation.get("host") or parsed.path != observation.get("path"):
            raise InvalidReview("historical schema 1 observation URL drifted")
        if parsed.hostname == API_HOST:
            validate_url_shape(observation["url"])
        elif parsed.hostname == LEGACY_RAW_HOST:
            parts = parsed.path.strip("/").split("/")
            if (
                parsed.scheme != "https"
                or parsed.query
                or len(parts) < 4
                or not HEX40.fullmatch(parts[2])
            ):
                raise InvalidReview("historical schema 1 raw URL is not immutable")
    observations = json.loads(
        evidence_file(run_dir, "http-observations.json", "HTTP observations").read_text(
            encoding="utf-8"
        )
    )
    mappings = json.loads(
        evidence_file(run_dir, "package-license-mapping.json", "package mapping").read_text(
            encoding="utf-8"
        )
    )
    if observations != requests or mappings != []:
        raise InvalidReview("historical schema 1 sidecar content drifted")


def validate_schema2_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    if manifest.get("network", {}).get("transport") != "git-blobs-api":
        raise InvalidReview("schema 2 transport is not Git Blobs API")
    validate_network_contract(manifest, [API_HOST])
    observations = manifest["network"]["requests"]
    for observation in observations:
        url = observation.get("url", "")
        validate_url_shape(url)
        parsed = urlsplit(url)
        if (
            observation.get("host") != parsed.hostname
            or observation.get("path") != parsed.path
            or observation.get("query") != parsed.query
        ):
            raise InvalidReview("schema 2 HTTP observation URL fields drifted")
        if observation.get("status") == 200:
            if observation.get("content_type") not in {
                "application/json",
                "application/vnd.github+json",
            }:
                raise InvalidReview("schema 2 successful response is not JSON")
            if observation.get("byte_count", 0) == 0 or "error" in observation:
                raise InvalidReview("schema 2 successful response observation is invalid")
    if (run_dir / "http-observations.json").exists():
        recorded = json.loads(
            evidence_file(run_dir, "http-observations.json", "HTTP observations").read_text(
                encoding="utf-8"
            )
        )
        if recorded != observations:
            raise InvalidReview("schema 2 HTTP observation sidecar drifted")
    mappings = manifest.get("package_license_mapping")
    commits = manifest.get("commits")
    if not isinstance(mappings, list) or not isinstance(commits, list):
        raise InvalidReview("schema 2 mappings or commit records are invalid")
    if (run_dir / "package-license-mapping.json").exists():
        recorded = json.loads(
            evidence_file(run_dir, "package-license-mapping.json", "package mapping").read_text(
                encoding="utf-8"
            )
        )
        if recorded != mappings:
            raise InvalidReview("schema 2 package mapping sidecar drifted")
    observation_digests = {
        (item.get("url"), item.get("sha256"))
        for item in observations
        if item.get("status") == 200
    }
    all_blob_records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in commits:
        if not isinstance(record, dict) or record.get("transport") != "git-blobs-api":
            raise InvalidReview("schema 2 commit transport record is invalid")
        spec = CommitSpec(record.get("repository", ""), record.get("commit", ""))
        if not HEX40.fullmatch(spec.commit):
            raise InvalidReview("schema 2 commit identity is invalid")
        commit_body = evidence_file(
            run_dir, record.get("commit_response_path"), "commit response"
        ).read_bytes()
        tree_body = evidence_file(
            run_dir, record.get("tree_response_path"), "tree response"
        ).read_bytes()
        if sha256_bytes(commit_body) != record.get("commit_response_sha256"):
            raise InvalidReview("schema 2 commit response digest drifted")
        if sha256_bytes(tree_body) != record.get("tree_response_sha256"):
            raise InvalidReview("schema 2 tree response digest drifted")
        commit_payload = make_payload(record.get("commit_url", ""), "api", commit_body)
        tree_sha = validate_commit_payload(commit_payload, spec)
        if tree_sha != record.get("tree_sha") or record.get("tree_truncated") is not False:
            raise InvalidReview("schema 2 tree identity drifted")
        tree_url = spec.tree_url(tree_sha)
        if record.get("tree_url") != tree_url:
            raise InvalidReview("schema 2 tree URL drifted")
        tree_payload = make_payload(tree_url, "api", tree_body)
        tree = validate_tree_payload(tree_payload, tree_sha)
        if (spec.commit_url, sha256_bytes(commit_body)) not in observation_digests:
            raise InvalidReview("schema 2 commit response lacks its HTTP observation")
        if (tree_url, sha256_bytes(tree_body)) not in observation_digests:
            raise InvalidReview("schema 2 tree response lacks its HTTP observation")
        blobs = record.get("blobs")
        if not isinstance(blobs, list):
            raise InvalidReview("schema 2 blob records are missing")
        for blob_record in blobs:
            if not isinstance(blob_record, dict):
                raise InvalidReview("schema 2 blob record is invalid")
            path = blob_record.get("tree_path")
            entry = tree.get(path)
            if entry is None:
                raise InvalidReview("schema 2 blob path is absent from its tree")
            envelope = evidence_file(
                run_dir, blob_record.get("envelope_path"), "blob envelope"
            ).read_bytes()
            decoded = evidence_file(
                run_dir, blob_record.get("decoded_path"), "decoded blob"
            ).read_bytes()
            api_url = blob_record.get("api_url")
            validate_http_body("api", "application/json", envelope)
            validated_decoded, validated_record = validate_blob_payload(
                make_payload(api_url, "api", envelope),
                spec,
                path,
                entry,
            )
            if validated_record != blob_record or validated_decoded != decoded:
                raise InvalidReview("schema 2 blob evidence chain drifted")
            if (api_url, sha256_bytes(envelope)) not in observation_digests:
                raise InvalidReview("schema 2 blob envelope lacks its HTTP observation")
            key = (spec.repository, spec.commit, path)
            if key in all_blob_records:
                raise InvalidReview("schema 2 blob path is duplicated")
            all_blob_records[key] = blob_record
    mapped_blob_records: set[tuple[str, str, str]] = set()
    for mapping in mappings:
        if not isinstance(mapping, dict) or not isinstance(mapping.get("evidence_files"), list):
            raise InvalidReview("schema 2 package evidence mapping is invalid")
        for blob_record in mapping["evidence_files"]:
            key = (
                blob_record.get("repository"),
                blob_record.get("commit"),
                blob_record.get("tree_path"),
            )
            if all_blob_records.get(key) != blob_record:
                raise InvalidReview("schema 2 package mapping differs from its blob chain")
            mapped_blob_records.add(key)
    if manifest.get("outcome") == "PASS" and mapped_blob_records != set(all_blob_records):
        raise InvalidReview("schema 2 blob chain is not fully represented in package mappings")


def validate_review_evidence(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise InvalidReview("license review run must be a regular directory")
    manifest_path = run_dir / "manifest.json"
    checksum_path = run_dir / "checksums.sha256"
    require_regular_file(manifest_path, "license review manifest")
    require_regular_file(checksum_path, "license review checksums")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise InvalidReview("license review manifest is not an object")
    schema = manifest_schema(manifest)
    if schema == LEGACY_SCHEMA_VERSION:
        expected = HISTORICAL_SCHEMA1_RUNS.get(run_dir.name)
        if expected is None:
            raise InvalidReview("unexpected historical schema 1 run")
        if sha256_file(manifest_path) != expected["manifest_sha256"]:
            raise InvalidReview("historical schema 1 manifest checksum drifted")
        if sha256_file(checksum_path) != expected["checksums_sha256"]:
            raise InvalidReview("historical schema 1 checksum-list checksum drifted")
        validate_schema1_manifest(run_dir, manifest)
    else:
        required = {
            "run_id": run_dir.name,
            "package_count": len(PACKAGES),
            "repository_count": len({item.repository for item in PACKAGES}),
            "commit_count": len(COMMITS),
            "r0_revision": R0_REVISION,
        }
        for key, value in required.items():
            if manifest.get(key) != value:
                raise InvalidReview(f"schema 2 manifest field drifted: {key}")
        if not isinstance(manifest.get("repository_revision"), str) or not HEX40.fullmatch(
            manifest["repository_revision"]
        ):
            raise InvalidReview("schema 2 repository revision is invalid")
        commit_items = manifest.get("commits", [])
        commit_identities = {
            (item.get("repository"), item.get("commit"))
            for item in commit_items
            if isinstance(item, dict)
        }
        expected_commits = {(item.repository, item.commit) for item in COMMITS}
        if len(commit_identities) != len(commit_items) or not commit_identities <= expected_commits:
            raise InvalidReview("schema 2 commit inventory escaped or is duplicated")
        mapping_items = manifest.get("package_license_mapping", [])
        mapping_identities = {
            (item.get("package"), item.get("version"), item.get("registry_checksum"))
            for item in mapping_items
            if isinstance(item, dict)
        }
        expected_mappings = {(item.name, item.version, item.checksum) for item in PACKAGES}
        if len(mapping_identities) != len(mapping_items) or not mapping_identities <= expected_mappings:
            raise InvalidReview("schema 2 package mapping inventory escaped or is duplicated")
        outcome_contracts = {
            "PASS": ({"license-evidence-collected"}, 0, type(None)),
            "STOP": ({"license-evidence", "resource-limit"}, 20, dict),
            "INVALID": ({"evidence-contract"}, 30, dict),
        }
        outcome = manifest.get("outcome")
        if outcome not in outcome_contracts:
            raise InvalidReview("schema 2 outcome is invalid")
        stages, exit_code, failure_type = outcome_contracts[outcome]
        if (
            manifest.get("stage") not in stages
            or manifest.get("exit_code") != exit_code
            or not isinstance(manifest.get("failure"), failure_type)
        ):
            raise InvalidReview("schema 2 outcome contract drifted")
        d2 = manifest.get("d2")
        if not isinstance(d2, dict) or d2.get("run_id") != D2_RUN_ID:
            raise InvalidReview("schema 2 D2 identity drifted")
        if d2.get("manifest_sha256") != D2_MANIFEST_SHA256:
            raise InvalidReview("schema 2 D2 manifest digest drifted")
        if d2.get("checksums_sha256") != D2_CHECKSUMS_SHA256:
            raise InvalidReview("schema 2 D2 checksum-list digest drifted")
        if d2.get("lock_sha256") != LOCK_SHA256:
            raise InvalidReview("schema 2 D2 lock digest drifted")
        if manifest.get("outcome") == "PASS":
            if commit_identities != expected_commits:
                raise InvalidReview("schema 2 PASS commit inventory drifted")
            if mapping_identities != expected_mappings:
                raise InvalidReview("schema 2 PASS package mapping inventory drifted")
        validate_schema2_manifest(run_dir, manifest)
    validate_evidence_checksums(repo_root, run_dir)
    return manifest


def finalize_run(
    repo_root: Path,
    partial_dir: Path,
    final_dir: Path,
    manifest: dict[str, Any],
    log_lines: list[str],
) -> None:
    atomic_write_bytes(partial_dir / "run.log", ("\n".join(log_lines) + "\n").encode("utf-8"))
    atomic_write_json(partial_dir / "manifest.json", manifest)
    checksum_text = build_checksums(repo_root, partial_dir, final_dir)
    atomic_write_bytes(partial_dir / "checksums.sha256", checksum_text.encode("utf-8"))
    verify_checksum_text(repo_root, checksum_text, final_dir, partial_dir)
    if final_dir.exists() or final_dir.is_symlink():
        raise InvalidReview("final evidence directory already exists")
    os.replace(partial_dir, final_dir)
    try:
        verify_checksum_text(repo_root, checksum_text)
    except InvalidReview:
        invalid_dir = final_dir.with_name(f".{final_dir.name}.invalid")
        if invalid_dir.exists() or invalid_dir.is_symlink():
            raise
        os.replace(final_dir, invalid_dir)
        raise


def prepare_artifact_directories(repo_root: Path) -> tuple[Path, Path, str]:
    artifact_parent = repo_root / "artifacts"
    artifact_root = artifact_parent / "sw-g2-mls-rs-license-review"
    for directory in (artifact_parent, artifact_root):
        if directory.is_symlink():
            raise InvalidReview(f"artifact directory must not be a symlink: {directory}")
        if directory.exists() and not directory.is_dir():
            raise InvalidReview(f"artifact path is not a directory: {directory}")
        directory.mkdir(mode=0o700, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    partial_dir = Path(tempfile.mkdtemp(prefix=f".{timestamp}-{os.getpid()}.", suffix=".partial", dir=artifact_root))
    os.chmod(partial_dir, 0o700)
    run_id = partial_dir.name.removeprefix(".").removesuffix(".partial")
    final_dir = artifact_root / run_id
    return partial_dir, final_dir, run_id


def collect(repo_root: Path, expected_revision: str) -> int:
    start_time = utc_now()
    start_monotonic = time.monotonic()
    preflight = local_preflight(repo_root, expected_revision)
    partial_dir, final_dir, run_id = prepare_artifact_directories(repo_root)
    log_lines = [
        f"{start_time} R1c collect start",
        f"revision={expected_revision}",
        "network=anonymous HTTPS GET; api.github.com Git commit/tree/blob APIs",
        "retry=disabled",
    ]
    session = HttpSession(start_monotonic)
    outcome = "INVALID"
    stage = "network"
    exit_code = 30
    failure: dict[str, str] | None = None
    mappings: list[dict[str, Any]] = []
    commit_records: list[dict[str, Any]] = []
    try:
        atomic_write_json(partial_dir / "inventory.json", preflight)
        collect_remote(
            partial_dir,
            PACKAGES,
            COMMITS,
            session,
            mappings,
            commit_records,
        )
        atomic_write_json(partial_dir / "package-license-mapping.json", mappings)
        atomic_write_json(partial_dir / "http-observations.json", session.observations)
        missing = [item["package"] for item in mappings if item["missing_license_texts"]]
        if missing:
            raise StopReview("upstream evidence does not cover every declared SPDX alternative")
        outcome = "PASS"
        stage = "license-evidence-collected"
        exit_code = 0
    except StopReview as error:
        outcome = "STOP"
        stage = "license-evidence"
        exit_code = 20
        failure = {"type": type(error).__name__, "message": str(error)}
        log_lines.append(f"STOP: {error}")
    except InvalidReview as error:
        outcome = "INVALID"
        stage = "evidence-contract"
        exit_code = 30
        failure = {"type": type(error).__name__, "message": str(error)}
        log_lines.append(f"INVALID: {error}")

    if not (partial_dir / "package-license-mapping.json").exists():
        atomic_write_json(partial_dir / "package-license-mapping.json", mappings)
    if not (partial_dir / "http-observations.json").exists():
        atomic_write_json(partial_dir / "http-observations.json", session.observations)
    elapsed_ms = round((time.monotonic() - start_monotonic) * 1000)
    evidence_bytes = directory_usage_bytes(partial_dir)
    if elapsed_ms > DEADLINE_SECONDS * 1000 or evidence_bytes > EVIDENCE_LIMIT_BYTES:
        outcome = "STOP"
        stage = "resource-limit"
        exit_code = 20
        failure = {"type": "StopReview", "message": "runtime or evidence budget exceeded"}
    helper_path = Path(__file__).resolve()
    checker_path = repo_root / "scripts" / "check-sw-g2-mls-rs-license-review.sh"
    require_regular_file(checker_path, "R1c offline checker")
    end_time = utc_now()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_contract": MANIFEST_CONTRACT,
        "evidence_id": EVIDENCE_ID,
        "run_id": run_id,
        "outcome": outcome,
        "stage": stage,
        "exit_code": exit_code,
        "failure": failure,
        "start_time": start_time,
        "end_time": end_time,
        "repository_revision": expected_revision,
        "r0_revision": R0_REVISION,
        "d2": preflight["d2"],
        "package_count": len(PACKAGES),
        "repository_count": len({item.repository for item in PACKAGES}),
        "commit_count": len(COMMITS),
        "commits": commit_records,
        "package_license_mapping": mappings,
        "network": {
            "method": "GET",
            "transport": "git-blobs-api",
            "allowed_hosts": [API_HOST],
            "anonymous": True,
            "proxies_disabled": True,
            "redirects_disabled": True,
            "request_count": session.request_count,
            "request_limit": REQUEST_LIMIT,
            "downloaded_bytes": session.downloaded_bytes,
            "download_limit_bytes": DOWNLOAD_LIMIT_BYTES,
            "retry": False,
            "requests": session.observations,
        },
        "runtime": {
            "elapsed_milliseconds": elapsed_ms,
            "deadline_seconds": DEADLINE_SECONDS,
            "evidence_bytes_before_manifest": evidence_bytes,
            "evidence_limit_bytes": EVIDENCE_LIMIT_BYTES,
            "background_processes_started": 0,
        },
        "input_sha256": {
            "helper": sha256_file(helper_path),
            "offline_checker": sha256_file(checker_path),
        },
    }
    log_lines.append(f"{end_time} outcome={outcome} stage={stage} exit_code={exit_code}")
    if manifest_schema(manifest) != SCHEMA_VERSION:
        raise InvalidReview("R1c final manifest schema drifted")
    validate_schema2_manifest(partial_dir, manifest)
    finalize_run(repo_root, partial_dir, final_dir, manifest, log_lines)
    print(f"SW-EXP-003 mls-rs license review R1c: {outcome} {final_dir.relative_to(repo_root)}")
    return exit_code


def make_payload(url: str, kind: str, body: bytes) -> HttpPayload:
    content_type = "application/json" if kind == "api" else "text/plain"
    return HttpPayload(url, 200, content_type, {"content-type": content_type}, body)


def expect_error(error_type: type[Exception], callback: Callable[[], Any]) -> None:
    try:
        callback()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


def self_test() -> int:
    with patch.object(
        socket,
        "create_connection",
        side_effect=AssertionError("network forbidden in self-test"),
    ):
        assert validate_revision("a" * 40) == "a" * 40
        expect_error(argparse.ArgumentTypeError, lambda: validate_revision("A" * 40))
        expect_error(InvalidReview, lambda: validate_url_shape("http://api.github.com/x"))
        expect_error(InvalidReview, lambda: validate_url_shape("https://example.com/x"))
        expect_error(
            InvalidReview,
            lambda: validate_url_shape(f"https://{LEGACY_RAW_HOST}/a/b/main/LICENSE"),
        )
        expect_error(InvalidReview, lambda: validate_url_shape("https://api.github.com/a/../b"))
        assert manifest_schema(
            {"schema_version": LEGACY_SCHEMA_VERSION, "manifest_contract": LEGACY_MANIFEST_CONTRACT}
        ) == LEGACY_SCHEMA_VERSION
        assert manifest_schema(
            {"schema_version": SCHEMA_VERSION, "manifest_contract": MANIFEST_CONTRACT}
        ) == SCHEMA_VERSION

        commit_sha = "b" * 40
        tree_sha = "c" * 40
        package = PackageSpec(
            "demo",
            "1.2.3",
            "d" * 64,
            "Apache-2.0 OR MIT",
            "owner/repo",
            commit_sha,
            "crate",
        )
        commit = CommitSpec(package.repository, package.commit)
        commit_body = json.dumps({"sha": commit_sha, "tree": {"sha": tree_sha}}).encode("utf-8")
        root_manifest = b'''[workspace]\nmembers = ["crate"]\n[workspace.package]\nlicense = "Apache-2.0 OR MIT"\nrepository = "https://github.com/owner/repo"\n'''
        package_manifest = b'''[package]\nname = "demo"\nversion = "1.2.3"\nlicense.workspace = true\nrepository.workspace = true\nreadme = "README.md"\n'''
        apache = b"Apache License\nVersion 2.0, January 2004\n"
        mit = b'''MIT License\nPermission is hereby granted, free of charge\nTHE SOFTWARE IS PROVIDED "AS IS"\n'''
        notice = b"Copyright Example\n"
        decoded_bodies = {
            "Cargo.toml": root_manifest,
            "LICENSE-APACHE": apache,
            "LICENSE-MIT": mit,
            "NOTICE": notice,
            "crate/Cargo.toml": package_manifest,
            "crate/src/lib.rs": b"pub fn demo() {}\n",
            "crate/README.md": b"Demo package\n",
        }

        def tree_entry(path: str, body: bytes, mode: str = "100644") -> dict[str, Any]:
            blob_sha = git_blob_sha1(body)
            return {
                "path": path,
                "type": "blob",
                "mode": mode,
                "sha": blob_sha,
                "size": len(body),
                "url": commit.blob_url(blob_sha),
            }

        def blob_envelope(
            entry: dict[str, Any],
            body: bytes,
            *,
            response_sha: str | None = None,
            encoding: str = "base64",
            content: str | None = None,
            size: int | None = None,
        ) -> bytes:
            return json.dumps(
                {
                    "sha": response_sha if response_sha is not None else entry["sha"],
                    "encoding": encoding,
                    "content": (
                        base64.encodebytes(body).decode("ascii")
                        if content is None
                        else content
                    ),
                    "size": len(body) if size is None else size,
                }
            ).encode("utf-8")

        tree_entries = [tree_entry(path, body) for path, body in decoded_bodies.items()]
        tree_entries.append(
            {
                "path": "crate/OTHER-LINK",
                "type": "blob",
                "mode": "120000",
                "sha": "7" * 40,
                "size": 8,
                "url": commit.blob_url("7" * 40),
            }
        )
        tree_body = json.dumps(
            {"sha": tree_sha, "truncated": False, "tree": tree_entries}
        ).encode("utf-8")
        responses: dict[str, HttpPayload] = {
            commit.commit_url: make_payload(commit.commit_url, "api", commit_body),
            commit.tree_url(tree_sha): make_payload(commit.tree_url(tree_sha), "api", tree_body),
        }
        for entry in tree_entries:
            if entry["mode"] != "100644":
                continue
            body = decoded_bodies[entry["path"]]
            url = commit.blob_url(entry["sha"])
            responses[url] = make_payload(url, "api", blob_envelope(entry, body))

        with tempfile.TemporaryDirectory(
            prefix="radishlink-mls-rs-license-review-self-test."
        ) as temporary:
            run_dir = Path(temporary) / "run"
            run_dir.mkdir(mode=0o700)
            session = FakeSession(responses)
            mappings, records = collect_remote(run_dir, (package,), (commit,), session)
            assert len(records) == 1
            assert mappings[0]["missing_license_texts"] == []
            assert mappings[0]["notice_present"] is True
            assert mappings[0]["manifest_references"] == [
                {
                    "field": "readme",
                    "source_manifest": "crate/Cargo.toml",
                    "path": "crate/README.md",
                }
            ]
            assert "crate/src/lib.rs" not in {
                item["tree_path"] for item in mappings[0]["evidence_files"]
            }
            assert "crate/OTHER-LINK" not in {
                item["tree_path"] for item in mappings[0]["evidence_files"]
            }
            assert all(item["host"] == API_HOST for item in session.observations)
            assert all(item["path"].startswith("/") for item in session.observations)
            assert all(
                item["api_url"].startswith(f"https://{API_HOST}/")
                for item in records[0]["blobs"]
            )
            assert all(
                item["blob_sha"] == git_blob_sha1(decoded_bodies[item["tree_path"]])
                for item in records[0]["blobs"]
            )

            manifest = {
                "schema_version": SCHEMA_VERSION,
                "manifest_contract": MANIFEST_CONTRACT,
                "outcome": "PASS",
                "commits": records,
                "package_license_mapping": mappings,
                "network": {
                    "transport": "git-blobs-api",
                    "method": "GET",
                    "allowed_hosts": [API_HOST],
                    "anonymous": True,
                    "proxies_disabled": True,
                    "redirects_disabled": True,
                    "request_count": session.request_count,
                    "request_limit": REQUEST_LIMIT,
                    "downloaded_bytes": session.downloaded_bytes,
                    "download_limit_bytes": DOWNLOAD_LIMIT_BYTES,
                    "retry": False,
                    "requests": session.observations,
                },
                "runtime": {
                    "elapsed_milliseconds": 1,
                    "deadline_seconds": DEADLINE_SECONDS,
                    "evidence_bytes_before_manifest": directory_usage_bytes(run_dir),
                    "evidence_limit_bytes": EVIDENCE_LIMIT_BYTES,
                    "background_processes_started": 0,
                },
            }
            validate_schema2_manifest(run_dir, manifest)

            final_dir = Path(temporary) / "final"
            finalize_run(Path(temporary), run_dir, final_dir, manifest, ["self-test"])
            checksum_text = (final_dir / "checksums.sha256").read_text(encoding="utf-8")
            verify_checksum_text(Path(temporary), checksum_text)
            (final_dir / "run.log").write_text("tampered\n", encoding="utf-8")
            expect_error(
                InvalidReview,
                lambda: verify_checksum_text(Path(temporary), checksum_text),
            )

        wrong_commit = make_payload(
            commit.commit_url,
            "api",
            json.dumps({"sha": "e" * 40, "tree": {"sha": tree_sha}}).encode("utf-8"),
        )
        expect_error(InvalidReview, lambda: validate_commit_payload(wrong_commit, commit))
        expect_error(InvalidReview, lambda: safe_tree_path("crate//LICENSE"))
        expect_error(InvalidReview, lambda: safe_tree_path("crate/../LICENSE"))
        valid_entry = tree_entries[0]
        invalid_tree_sha = dict(valid_entry, sha="A" * 40)
        expect_error(
            InvalidReview,
            lambda: validate_selected_blob_entry(commit, valid_entry["path"], invalid_tree_sha),
        )
        mismatched_tree_url = dict(valid_entry, url=commit.blob_url("f" * 40))
        expect_error(
            InvalidReview,
            lambda: validate_selected_blob_entry(commit, valid_entry["path"], mismatched_tree_url),
        )
        response_sha_drift = make_payload(
            valid_entry["url"],
            "api",
            blob_envelope(valid_entry, root_manifest, response_sha="f" * 40),
        )
        expect_error(
            InvalidReview,
            lambda: validate_blob_payload(
                response_sha_drift,
                commit,
                valid_entry["path"],
                valid_entry,
            ),
        )
        wrong_encoding = make_payload(
            valid_entry["url"],
            "api",
            blob_envelope(valid_entry, root_manifest, encoding="utf-8"),
        )
        expect_error(
            InvalidReview,
            lambda: validate_blob_payload(
                wrong_encoding,
                commit,
                valid_entry["path"],
                valid_entry,
            ),
        )
        invalid_base64 = make_payload(
            valid_entry["url"],
            "api",
            blob_envelope(valid_entry, root_manifest, content="not base64!"),
        )
        expect_error(
            InvalidReview,
            lambda: validate_blob_payload(
                invalid_base64,
                commit,
                valid_entry["path"],
                valid_entry,
            ),
        )
        size_drift = make_payload(
            valid_entry["url"],
            "api",
            blob_envelope(valid_entry, root_manifest, size=len(root_manifest) + 1),
        )
        expect_error(
            InvalidReview,
            lambda: validate_blob_payload(size_drift, commit, valid_entry["path"], valid_entry),
        )
        sha1_drift_entry = dict(
            valid_entry,
            sha="f" * 40,
            url=commit.blob_url("f" * 40),
        )
        sha1_drift = make_payload(
            sha1_drift_entry["url"],
            "api",
            blob_envelope(sha1_drift_entry, root_manifest),
        )
        expect_error(
            InvalidReview,
            lambda: validate_blob_payload(
                sha1_drift,
                commit,
                valid_entry["path"],
                sha1_drift_entry,
            ),
        )
        executable_license_tree = {
            "Cargo.toml": tree_entries[0],
            "crate/Cargo.toml": tree_entries[4],
            "crate/LICENSE": tree_entry("crate/LICENSE", mit, mode="100755"),
        }
        expect_error(
            StopReview,
            lambda: select_initial_paths(executable_license_tree, (package,)),
        )
        redirect = HttpPayload(
            commit.commit_url,
            302,
            "application/json",
            {"content-type": "application/json", "location": "https://example.com/redirect"},
            commit_body,
        )
        redirect_session = FakeSession({commit.commit_url: redirect})
        redirect_session.allow(commit.commit_url)
        expect_error(StopReview, lambda: redirect_session.get(commit.commit_url, "api"))
        assert redirect_session.observations[0]["status"] == 302
        truncated = make_payload(
            commit.tree_url(tree_sha),
            "api",
            json.dumps({"sha": tree_sha, "truncated": True, "tree": []}).encode("utf-8"),
        )
        expect_error(InvalidReview, lambda: validate_tree_payload(truncated, tree_sha))
        expect_error(StopReview, lambda: validate_http_body("api", "text/html", b"<html>x</html>"))
        expect_error(StopReview, lambda: validate_http_body("api", "application/json", b""))
        expect_error(StopReview, lambda: validate_decoded_text(b"x\x00y"))
        expect_error(StopReview, lambda: validate_decoded_text(b"<html>x</html>"))
        expect_error(
            StopReview,
            lambda: validate_decoded_text(b"version https://git-lfs.github.com/spec/v1\n"),
        )
        expect_error(StopReview, lambda: validate_decoded_text(b"\xff\xfe"))
        assert not is_regular_tree_blob({"path": "LICENSE", "type": "blob", "mode": "100755"})
        assert classify_license_text(mit.decode("utf-8")) == {"MIT"}
        assert classify_license_text(apache.decode("utf-8")) == {"Apache-2.0"}
        lgpl = (
            "GNU LESSER GENERAL PUBLIC LICENSE\n"
            "Version 2.1, February 1999\n"
            "TERMS AND CONDITIONS FOR COPYING, DISTRIBUTION AND MODIFICATION\n"
        )
        assert classify_license_text(lgpl) == {"LGPL-2.1-or-later"}

    print("SW-EXP-003 mls-rs license review offline self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("self-test", help="run synthetic offline checks only")
    collect_parser = subparsers.add_parser(
        "collect", help="perform one separately authorized R1c collection"
    )
    collect_parser.add_argument("expected_revision", type=validate_revision)
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if arguments.action == "self-test":
        return self_test()
    if arguments.action == "collect":
        repo_root = Path(__file__).resolve().parent.parent
        try:
            return collect(repo_root, arguments.expected_revision)
        except InvalidReview as error:
            print(f"INVALID before R1c network/evidence: {error}", file=sys.stderr)
            return 10
    parser.error("unsupported action")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
