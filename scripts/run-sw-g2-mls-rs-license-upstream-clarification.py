#!/usr/bin/env python3
"""Create or read bounded debug_tree upstream-clarification evidence."""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, Request, build_opener
from unittest.mock import patch
SCHEMA_VERSION = 1
MANIFEST_CONTRACT = "sw-g2-mls-rs-license-upstream-clarification-v1"
EVIDENCE_ID = "SW-EXP-003"
PLAN_REVISION = "2879dfb32f21107914073fc820cd2450ca3951dc"
PLAN_PATH = "docs/testing/sw-g2-mls-rs-debug-tree-upstream-clarification-plan.md"
PLAN_SHA256 = "eaa3550927a44b910bc798563217d86146a77a66fd54bda00f708c0a26c4920d"
R1C_RUN_ID = "20260903-124253-90340.y7_6lakz"
R1C_MANIFEST_SHA256 = "f523347df20de4c654976f7b16107ad8e86227db90853327d36e225ce6270203"
PACKAGE = "debug_tree"
VERSION = "0.4.0"
REGISTRY_CHECKSUM = "2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57"
REPOSITORY = "martypapa/debug-tree"
REPOSITORY_URL = f"https://github.com/{REPOSITORY}"
COMMIT = "5b709de2d8872102b20b566c408d31d0662d7a9f"
TREE = "edc1ea9120f5d4070eb0fa60c77ab0da4c8a3e92"
API_HOST = "api.github.com"
ARTIFACT_RELATIVE = "artifacts/sw-g2-mls-rs-license-upstream-clarification"
ISSUE_TITLE = "License notice clarification for debug_tree 0.4.0"
ISSUE_BODY = """Hello, we are reviewing `debug_tree 0.4.0` for possible redistribution.

The published crate metadata declares `license = "MIT"`. We are looking specifically at:

- crate: `debug_tree 0.4.0`
- crates.io checksum: `2d1ec383f2d844902d3c34e4253ba11ae48513cdaddc565cf1a6518db09a8e57`
- repository: `https://github.com/martypapa/debug-tree`
- commit: `5b709de2d8872102b20b566c408d31d0662d7a9f`

We could not locate a complete MIT copyright and permission notice that states it applies to the published crate contents and that commit.

Could a maintainer please clarify:

1. Is all source distributed in this exact crate release and commit, except any explicitly identified third-party portions, offered under the MIT License?
2. What complete copyright and permission notice, including the applicable copyright holder name(s) and year(s), should redistributors preserve?
3. Are there any third-party code exceptions, additional attribution, or NOTICE requirements for this release?
4. Does this clarification apply retrospectively to the published `debug_tree 0.4.0` crate and the exact commit above?

If practical, could this clarification be recorded in an immutable commit in the official repository, for example by adding the applicable license notice and a note that identifies `0.4.0` and the commit above? A repository commit would give downstream redistributors a stable provenance reference.

This is a license-provenance and redistribution-documentation question, not a security report. Thank you.
"""
TITLE_SHA256 = "aa627aa1f8c9da8cac0805c5a28744bb76a1b8e123e3fbefdac296648ab3f01a"
BODY_SHA256 = "38fd3a3115c216ec5455a7b0abd550e92676dc1345b20870b1006305c8a1bdb8"
CREATE_REQUEST_LIMIT = 20
READ_REQUEST_LIMIT = 10
POST_LIMIT = 1
DOWNLOAD_LIMIT_BYTES = 5 * 1024 * 1024
EVIDENCE_LIMIT_BYTES = 20 * 1024 * 1024
DEADLINE_SECONDS = 300
RESPONSE_LIMIT_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "RadishLink-upstream-clarification/1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9]+\.[A-Za-z0-9_-]{6,}$")
FORBIDDEN_EVIDENCE = re.compile(rb"(?i)(authorization\s*:|cookie\s*:|bearer\s+[A-Za-z0-9._-]{8,}|gh[pousr]_[A-Za-z0-9]{8,})")
SAFE_RESPONSE_HEADERS = set("content-type date etag last-modified link x-github-api-version-selected x-github-media-type x-github-request-id x-ratelimit-limit x-ratelimit-remaining x-ratelimit-reset x-ratelimit-resource x-ratelimit-used".split())
class ClarificationError(RuntimeError):
    """Base class for bounded clarification failures."""
class StopClarification(ClarificationError):
    """A valid stop that must not be converted to success."""
class InvalidClarification(ClarificationError):
    """An input, identity, schema, or evidence failure."""
class AmbiguousExternalWrite(InvalidClarification):
    """A POST may have changed external state without a trustworthy response."""

@dataclass(frozen=True)
class HttpResult:
    method: str
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
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
def canonical_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8") + b"\n"
def validate_revision(value: str) -> str:
    if not HEX40.fullmatch(value):
        raise argparse.ArgumentTypeError("revision must be exactly 40 lowercase hexadecimal characters")
    return value
def validate_login(value: str) -> str:
    if not LOGIN.fullmatch(value):
        raise argparse.ArgumentTypeError("expected login is not a valid public GitHub login")
    return value
def validate_run_id(value: str) -> str:
    if not RUN_ID.fullmatch(value):
        raise argparse.ArgumentTypeError("source run id is malformed")
    return value
def require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise InvalidClarification(f"{label} must be a regular non-symlink file: {path}")
def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise InvalidClarification(f"refusing to overwrite evidence path: {path}")
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
    atomic_write_bytes(path, canonical_json(payload))
def run_git(repo_root: Path, *arguments: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise InvalidClarification(f"git {' '.join(arguments)} failed with {result.returncode}")
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8").rstrip("\n")
def fixed_object() -> dict[str, str]:
    return {"package": PACKAGE, "version": VERSION, "registry_checksum": REGISTRY_CHECKSUM,
            "repository": REPOSITORY, "repository_url": REPOSITORY_URL, "commit": COMMIT,
            "tree": TREE, "declared_license": "MIT", "r1c_run_id": R1C_RUN_ID,
            "r1c_manifest_sha256": R1C_MANIFEST_SHA256}
def message_contract() -> dict[str, str]:
    return {"title_path": "message/issue-title.txt", "title_sha256": TITLE_SHA256,
            "body_path": "message/issue-body.md", "body_sha256": BODY_SHA256}
def validate_plan_inputs(repo_root: Path) -> dict[str, Any]:
    plan_path = repo_root / PLAN_PATH
    require_regular_file(plan_path, "R1d-U-P plan")
    plan_bytes = plan_path.read_bytes()
    if sha256_bytes(plan_bytes) != PLAN_SHA256:
        raise InvalidClarification("R1d-U-P plan bytes drifted")
    committed = run_git(repo_root, "show", f"{PLAN_REVISION}:{PLAN_PATH}", binary=True)
    if committed != plan_bytes:
        raise InvalidClarification("R1d-U-P plan no longer matches its clean revision")
    if sha256_bytes(ISSUE_TITLE.encode("utf-8")) != TITLE_SHA256:
        raise InvalidClarification("fixed Issue title digest drifted")
    if sha256_bytes(ISSUE_BODY.encode("utf-8")) != BODY_SHA256:
        raise InvalidClarification("fixed Issue body digest drifted")
    manifest_path = (
        repo_root
        / "artifacts"
        / "sw-g2-mls-rs-license-review"
        / R1C_RUN_ID
        / "manifest.json"
    )
    require_regular_file(manifest_path, "R1c manifest")
    if sha256_file(manifest_path) != R1C_MANIFEST_SHA256:
        raise InvalidClarification("R1c manifest digest drifted")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2 or manifest.get("outcome") != "STOP":
        raise InvalidClarification("R1c manifest schema or outcome drifted")
    mappings = [
        item
        for item in manifest.get("package_license_mapping", [])
        if item.get("package") == PACKAGE and item.get("version") == VERSION
    ]
    if len(mappings) != 1:
        raise InvalidClarification("R1c debug_tree mapping is missing or duplicated")
    mapping = mappings[0]
    expected = {
        "registry_checksum": REGISTRY_CHECKSUM,
        "repository": REPOSITORY,
        "commit": COMMIT,
        "declared_license": "MIT",
        "missing_license_texts": ["MIT"],
        "copyright_paths": [],
        "notice_paths": [],
    }
    for key, value in expected.items():
        if mapping.get(key) != value:
            raise InvalidClarification(f"R1c debug_tree mapping drifted: {key}")
    commits = [item for item in manifest.get("commits", []) if item.get("repository") == REPOSITORY]
    if len(commits) != 1 or commits[0].get("commit") != COMMIT or commits[0].get("tree_sha") != TREE:
        raise InvalidClarification("R1c debug_tree commit/tree identity drifted")
    return {
        "plan_revision": PLAN_REVISION,
        "plan_sha256": PLAN_SHA256,
        "fixed_object": fixed_object(),
        "message": message_contract(),
    }
def local_preflight(repo_root: Path, expected_revision: str) -> dict[str, Any]:
    if run_git(repo_root, "rev-parse", "HEAD") != expected_revision:
        raise InvalidClarification("HEAD does not match the explicitly authorized clean revision")
    if run_git(repo_root, "status", "--porcelain=v1"):
        raise InvalidClarification("R1d-U network action requires a clean worktree")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", PLAN_REVISION, expected_revision],
        cwd=repo_root,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ancestor.returncode != 0:
        raise InvalidClarification("R1d-U-P clean revision is not an ancestor of HEAD")
    return validate_plan_inputs(repo_root)
def safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or "." in path.parts
        or path.as_posix() != value
        or any(not part for part in path.parts)
    ):
        raise InvalidClarification(f"unsafe evidence path: {value}")
    return path
def directory_files(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise InvalidClarification("evidence run must be a regular directory")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise InvalidClarification(f"evidence contains a symlink: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise InvalidClarification(f"evidence contains a non-regular entry: {path}")
        files.append(path)
    return files
def directory_usage_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in directory_files(root))
def checksum_text(repo_root: Path, run_dir: Path, final_dir: Path | None = None) -> bytes:
    lines = []
    checksum_root = run_dir if final_dir is None else final_dir
    for path in directory_files(run_dir):
        if path.name == "checksums.sha256":
            continue
        target_path = checksum_root / path.relative_to(run_dir)
        relative = target_path.relative_to(repo_root).as_posix()
        lines.append(f"{sha256_file(path)}  {relative}\n")
    return "".join(lines).encode("utf-8")
def verify_checksums(repo_root: Path, run_dir: Path) -> None:
    checksum_path = run_dir / "checksums.sha256"
    require_regular_file(checksum_path, "evidence checksum file")
    lines = checksum_path.read_text(encoding="utf-8").splitlines()
    expected_paths: set[str] = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\x00\r\n]+)", line)
        if not match:
            raise InvalidClarification("malformed evidence checksum line")
        expected, relative = match.groups()
        pure = safe_relative_path(relative)
        target = repo_root.joinpath(*pure.parts)
        if relative in expected_paths:
            raise InvalidClarification("duplicated evidence checksum path")
        expected_paths.add(relative)
        require_regular_file(target, "evidence checksum target")
        if sha256_file(target) != expected:
            raise InvalidClarification(f"evidence checksum mismatch: {relative}")
    actual_paths = {
        path.relative_to(repo_root).as_posix()
        for path in directory_files(run_dir)
        if path.name != "checksums.sha256"
    }
    if expected_paths != actual_paths:
        raise InvalidClarification("evidence checksum coverage is incomplete")
def scan_for_credentials(run_dir: Path) -> None:
    for path in directory_files(run_dir):
        if path.name == "checksums.sha256":
            continue
        payload = path.read_bytes()
        if FORBIDDEN_EVIDENCE.search(payload):
            raise InvalidClarification(f"possible credential material in evidence: {path.name}")
def strict_keys(payload: dict[str, Any], expected: set[str], label: str) -> None:
    if not isinstance(payload, dict) or set(payload) != expected:
        raise InvalidClarification(f"{label} fields are missing or unknown")
def validate_message_files(run_dir: Path, message: dict[str, Any]) -> None:
    strict_keys(message, {"title_path", "title_sha256", "body_path", "body_sha256"}, "message")
    if message != message_contract():
        raise InvalidClarification("message contract drifted")
    title = run_dir.joinpath(*safe_relative_path(message["title_path"]).parts)
    body = run_dir.joinpath(*safe_relative_path(message["body_path"]).parts)
    require_regular_file(title, "Issue title")
    require_regular_file(body, "Issue body")
    if title.read_bytes() != ISSUE_TITLE.encode("utf-8"):
        raise InvalidClarification("Issue title bytes drifted")
    if body.read_bytes() != ISSUE_BODY.encode("utf-8"):
        raise InvalidClarification("Issue body bytes drifted")
def validate_network(network: dict[str, Any], mode: str) -> None:
    strict_keys(
        network,
        {
            "mode",
            "allowed_hosts",
            "proxies_disabled",
            "redirects_disabled",
            "request_count",
            "request_limit",
            "get_count",
            "post_count",
            "post_limit",
            "downloaded_bytes",
            "download_limit_bytes",
            "request_timeout_seconds",
            "retry_count",
            "background_processes_started",
            "response_records",
        },
        "network",
    )
    request_limit = CREATE_REQUEST_LIMIT if mode == "issue-create" else READ_REQUEST_LIMIT
    if network["mode"] != mode or network["allowed_hosts"] != [API_HOST]:
        raise InvalidClarification("network mode or host drifted")
    fixed = {
        "proxies_disabled": True,
        "redirects_disabled": True,
        "request_limit": request_limit,
        "post_limit": POST_LIMIT if mode == "issue-create" else 0,
        "download_limit_bytes": DOWNLOAD_LIMIT_BYTES,
        "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        "retry_count": 0,
        "background_processes_started": 0,
    }
    for key, value in fixed.items():
        if network.get(key) != value:
            raise InvalidClarification(f"network contract drifted: {key}")
    integers = ["request_count", "get_count", "post_count", "downloaded_bytes", "response_records"]
    if any(not isinstance(network.get(key), int) or network[key] < 0 for key in integers):
        raise InvalidClarification("network counters are invalid")
    if network["request_count"] != network["get_count"] + network["post_count"]:
        raise InvalidClarification("network method counts do not sum")
    if network["request_count"] > request_limit or network["downloaded_bytes"] > DOWNLOAD_LIMIT_BYTES:
        raise InvalidClarification("network budget exceeded")
    if network["post_count"] > network["post_limit"]:
        raise InvalidClarification("network POST limit exceeded")
    if network["response_records"] > network["request_count"]:
        raise InvalidClarification("response records exceed requests")
def validate_observations(run_dir: Path, network: dict[str, Any]) -> None:
    observations = sorted((run_dir / "network").glob("*.observation.json"))
    if len(observations) != network["response_records"]:
        raise InvalidClarification("network observation count drifted")
    observed_posts = 0
    for path in observations:
        require_regular_file(path, "network observation")
        observation = json.loads(path.read_text(encoding="utf-8"))
        strict_keys(
            observation,
            {"method", "url", "status", "headers", "body_path", "body_sha256", "body_size"},
            "network observation",
        )
        if observation["method"] not in {"GET", "POST"}:
            raise InvalidClarification("network observation contains a prohibited method")
        if observation["method"] == "POST":
            observed_posts += 1
        validate_api_url(observation["url"])
        if not isinstance(observation["status"], int) or not 100 <= observation["status"] <= 599:
            raise InvalidClarification("network observation status is invalid")
        headers = observation["headers"]
        if not isinstance(headers, dict) or not set(headers) <= SAFE_RESPONSE_HEADERS:
            raise InvalidClarification("network observation headers are not allowlisted")
        body_path = safe_relative_path(observation["body_path"])
        if body_path.parts[0] != "network":
            raise InvalidClarification("network response body is outside its directory")
        body_file = run_dir.joinpath(*body_path.parts)
        require_regular_file(body_file, "network response body")
        if observation["body_sha256"] != sha256_file(body_file):
            raise InvalidClarification("network response body digest drifted")
        if observation["body_size"] != body_file.stat().st_size:
            raise InvalidClarification("network response body size drifted")
    if observed_posts > network["post_count"]:
        raise InvalidClarification("observed POST responses exceed attempted POST requests")
    if len(observations) - observed_posts > network["get_count"]:
        raise InvalidClarification("observed GET responses exceed attempted GET requests")
    if network["response_records"] == network["request_count"] and observed_posts != network["post_count"]:
        raise InvalidClarification("complete network evidence has inconsistent method counts")
    if network["post_count"] == 1 and not (run_dir / "network" / "post-intent.json").is_file():
        raise InvalidClarification("POST evidence lacks its durable intent record")
def validate_account(account: dict[str, Any], require_observed: bool) -> None:
    strict_keys(account, {"expected_login", "observed_login", "observed_id"}, "account")
    if not isinstance(account["expected_login"], str) or not LOGIN.fullmatch(account["expected_login"]):
        raise InvalidClarification("expected public account is invalid")
    if require_observed:
        if account["observed_login"].lower() != account["expected_login"].lower():
            raise InvalidClarification("authenticated public account does not match authorization")
        if not isinstance(account["observed_id"], int) or account["observed_id"] <= 0:
            raise InvalidClarification("authenticated public account id is invalid")
    elif account["observed_login"] is not None or account["observed_id"] is not None:
        if not isinstance(account["observed_login"], str) or not isinstance(account["observed_id"], int):
            raise InvalidClarification("partially observed account is invalid")
def validate_issue(issue: dict[str, Any], expected_account: str) -> None:
    strict_keys(
        issue,
        {
            "number",
            "node_id",
            "api_url",
            "html_url",
            "author_login",
            "author_id",
            "created_at",
            "updated_at",
            "title_sha256",
            "body_sha256",
        },
        "issue",
    )
    if not isinstance(issue["number"], int) or issue["number"] <= 0:
        raise InvalidClarification("Issue number is invalid")
    if issue["api_url"] != f"https://{API_HOST}/repos/{REPOSITORY}/issues/{issue['number']}":
        raise InvalidClarification("Issue API URL drifted")
    if issue["html_url"] != f"https://github.com/{REPOSITORY}/issues/{issue['number']}":
        raise InvalidClarification("Issue HTML URL drifted")
    if issue["author_login"].lower() != expected_account.lower():
        raise InvalidClarification("Issue author does not match authorized account")
    if not isinstance(issue["author_id"], int) or issue["author_id"] <= 0:
        raise InvalidClarification("Issue author id is invalid")
    if issue["title_sha256"] != TITLE_SHA256 or issue["body_sha256"] != BODY_SHA256:
        raise InvalidClarification("Issue message digest drifted")
    for key in ("node_id", "created_at", "updated_at"):
        if not isinstance(issue[key], str) or not issue[key]:
            raise InvalidClarification(f"Issue field is empty: {key}")
def validate_response_summary(summary: dict[str, Any]) -> None:
    strict_keys(
        summary,
        {"comment_count", "event_count", "commenters", "referenced_commits", "next_page_seen"},
        "response_summary",
    )
    if any(not isinstance(summary[key], int) or summary[key] < 0 for key in ("comment_count", "event_count")):
        raise InvalidClarification("response counts are invalid")
    if not isinstance(summary["commenters"], list) or not all(
        isinstance(item, dict)
        and set(item) == {"login", "id", "author_association"}
        and isinstance(item["login"], str)
        and isinstance(item["id"], int)
        and isinstance(item["author_association"], str)
        for item in summary["commenters"]
    ):
        raise InvalidClarification("response commenter identity is invalid")
    if not isinstance(summary["referenced_commits"], list) or not all(
        HEX40.fullmatch(item) for item in summary["referenced_commits"]
    ):
        raise InvalidClarification("response commit references are invalid")
    if not isinstance(summary["next_page_seen"], bool):
        raise InvalidClarification("response pagination flag is invalid")
def validate_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    strict_keys(
        manifest,
        {
            "schema_version",
            "manifest_contract",
            "evidence_id",
            "run_id",
            "outcome",
            "stage",
            "reason",
            "exit_code",
            "start_time",
            "end_time",
            "repository_revision",
            "plan_revision",
            "plan_sha256",
            "fixed_object",
            "message",
            "account",
            "network",
            "issue",
            "source_x_run",
            "response_summary",
            "runtime",
            "input_sha256",
        },
        "manifest",
    )
    fixed = {
        "schema_version": SCHEMA_VERSION,
        "manifest_contract": MANIFEST_CONTRACT,
        "evidence_id": EVIDENCE_ID,
        "plan_revision": PLAN_REVISION,
        "plan_sha256": PLAN_SHA256,
        "fixed_object": fixed_object(),
    }
    for key, value in fixed.items():
        if manifest.get(key) != value:
            raise InvalidClarification(f"manifest field drifted: {key}")
    if manifest.get("run_id") != run_dir.name or not RUN_ID.fullmatch(run_dir.name):
        raise InvalidClarification("manifest run identity drifted")
    if not HEX40.fullmatch(manifest.get("repository_revision", "")):
        raise InvalidClarification("manifest repository revision is invalid")
    if not isinstance(manifest.get("reason"), str) or not manifest["reason"]:
        raise InvalidClarification("manifest reason is empty")
    validate_message_files(run_dir, manifest["message"])
    runtime = manifest["runtime"]
    strict_keys(
        runtime,
        {"elapsed_milliseconds", "deadline_seconds", "evidence_limit_bytes", "evidence_bytes_before_manifest"},
        "runtime",
    )
    if runtime["deadline_seconds"] != DEADLINE_SECONDS or runtime["evidence_limit_bytes"] != EVIDENCE_LIMIT_BYTES:
        raise InvalidClarification("runtime limits drifted")
    if not isinstance(runtime["elapsed_milliseconds"], int) or runtime["elapsed_milliseconds"] < 0:
        raise InvalidClarification("runtime elapsed value is invalid")
    if runtime["elapsed_milliseconds"] > DEADLINE_SECONDS * 1000:
        raise InvalidClarification("runtime deadline exceeded")
    if (
        not isinstance(runtime["evidence_bytes_before_manifest"], int)
        or runtime["evidence_bytes_before_manifest"] < 0
        or runtime["evidence_bytes_before_manifest"] > EVIDENCE_LIMIT_BYTES
    ):
        raise InvalidClarification("pre-manifest evidence size is invalid")
    input_sha = manifest["input_sha256"]
    strict_keys(input_sha, {"helper", "offline_checker"}, "input_sha256")
    if not all(HEX64.fullmatch(input_sha.get(key, "")) for key in input_sha):
        raise InvalidClarification("input script digest is invalid")
    mode = manifest["network"].get("mode")
    if mode == "issue-create":
        validate_network(manifest["network"], mode)
        validate_observations(run_dir, manifest["network"])
        combination = (manifest["outcome"], manifest["stage"], manifest["exit_code"])
        require_observed = combination in {
            ("STOP", "issue-created", 20),
            ("STOP", "external-write-rejected", 20),
            ("INVALID", "ambiguous-external-write", 10),
        }
        validate_account(manifest["account"], require_observed)
        if manifest["source_x_run"] is not None or manifest["response_summary"] is not None:
            raise InvalidClarification("Issue-create manifest contains response-only fields")
        if combination == ("STOP", "issue-created", 20):
            if manifest["network"]["post_count"] != 1 or manifest["issue"] is None:
                raise InvalidClarification("successful Issue evidence lacks exactly one POST or Issue")
            if manifest["network"]["response_records"] != manifest["network"]["request_count"]:
                raise InvalidClarification("successful Issue evidence lacks a response record")
            validate_issue(manifest["issue"], manifest["account"]["expected_login"])
        elif combination == ("INVALID", "ambiguous-external-write", 10):
            if manifest["network"]["post_count"] != 1 or manifest["issue"] is not None:
                raise InvalidClarification("ambiguous write evidence has inconsistent POST/Issue state")
            if manifest["network"]["response_records"] >= manifest["network"]["request_count"]:
                raise InvalidClarification("ambiguous write unexpectedly has every response")
        elif combination == ("STOP", "external-write-rejected", 20):
            if manifest["network"]["post_count"] != 1 or manifest["issue"] is not None:
                raise InvalidClarification("rejected write evidence has inconsistent POST/Issue state")
            if manifest["network"]["response_records"] != manifest["network"]["request_count"]:
                raise InvalidClarification("rejected write evidence lacks the rejection response")
        elif combination in {
            ("STOP", "preflight", 20),
            ("INVALID", "evidence-contract", 10),
        }:
            if manifest["network"]["post_count"] != 0 or manifest["issue"] is not None:
                raise InvalidClarification("pre-POST failure evidence contains external write state")
        else:
            raise InvalidClarification("unsupported Issue-create outcome/stage/exit combination")
    elif mode == "response-read":
        validate_network(manifest["network"], mode)
        validate_observations(run_dir, manifest["network"])
        combination = (manifest["outcome"], manifest["stage"], manifest["exit_code"])
        require_observed = combination in {
            ("STOP", "awaiting-upstream", 20),
            ("STOP", "response-collected", 20),
        }
        validate_account(manifest["account"], require_observed)
        if manifest["network"]["post_count"] != 0:
            raise InvalidClarification("response-read evidence contains a write request")
        if not isinstance(manifest["source_x_run"], str) or not RUN_ID.fullmatch(manifest["source_x_run"]):
            raise InvalidClarification("response-read source X run is invalid")
        if manifest["issue"] is None or manifest["response_summary"] is None:
            raise InvalidClarification("response-read evidence lacks Issue or response summary")
        validate_issue(manifest["issue"], manifest["account"]["expected_login"])
        validate_response_summary(manifest["response_summary"])
        if manifest["response_summary"]["next_page_seen"] and combination != ("STOP", "evidence-limit", 20):
            raise InvalidClarification("paginated response evidence must stop at its limit")
        allowed = {
            ("STOP", "awaiting-upstream", 20),
            ("STOP", "response-collected", 20),
            ("STOP", "evidence-limit", 20),
            ("INVALID", "evidence-contract", 10),
        }
        if combination not in allowed:
            raise InvalidClarification("unsupported response-read outcome/stage/exit combination")
    else:
        raise InvalidClarification("unknown network evidence mode")
def validate_evidence(repo_root: Path, run_dir: Path) -> dict[str, Any]:
    require_regular_file(run_dir / "manifest.json", "clarification manifest")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    validate_manifest(run_dir, manifest)
    verify_checksums(repo_root, run_dir)
    scan_for_credentials(run_dir)
    if directory_usage_bytes(run_dir) > EVIDENCE_LIMIT_BYTES:
        raise InvalidClarification("final evidence size limit exceeded")
    if manifest["network"]["mode"] == "response-read":
        source_dir = run_dir.parent / manifest["source_x_run"]
        if source_dir == run_dir:
            raise InvalidClarification("response run cannot reference itself")
        source = validate_evidence(repo_root, source_dir)
        if (source["outcome"], source["stage"]) != ("STOP", "issue-created"):
            raise InvalidClarification("response run source is not a successful X run")
        if source["account"]["expected_login"].lower() != manifest["account"]["expected_login"].lower():
            raise InvalidClarification("response run account differs from its X source")
        stable_fields = set(source["issue"]) - {"updated_at"}
        if any(source["issue"][key] != manifest["issue"][key] for key in stable_fields):
            raise InvalidClarification("response run Issue identity differs from its X source")
    return manifest
def write_message_files(run_dir: Path) -> None:
    atomic_write_bytes(run_dir / "message" / "issue-title.txt", ISSUE_TITLE.encode("utf-8"))
    atomic_write_bytes(run_dir / "message" / "issue-body.md", ISSUE_BODY.encode("utf-8"))
def prepare_artifact_directories(repo_root: Path) -> tuple[Path, Path, str]:
    artifact_root = repo_root / ARTIFACT_RELATIVE
    if artifact_root.is_symlink() or (artifact_root.exists() and not artifact_root.is_dir()):
        raise InvalidClarification("clarification artifact root is unsafe")
    artifact_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    partial = Path(
        tempfile.mkdtemp(
            prefix=f".{timestamp}-{os.getpid()}.",
            suffix=".partial",
            dir=artifact_root,
        )
    )
    os.chmod(partial, 0o700)
    run_id = partial.name.removeprefix(".").removesuffix(".partial")
    if not RUN_ID.fullmatch(run_id):
        raise InvalidClarification("generated clarification run id is invalid")
    return partial, artifact_root / run_id, run_id
def finalization_input_sha(repo_root: Path) -> dict[str, str]:
    helper = Path(__file__).resolve()
    checker = repo_root / "scripts" / "check-sw-g2-mls-rs-license-upstream-clarification.sh"
    require_regular_file(helper, "R1d-U helper")
    require_regular_file(checker, "R1d-U checker")
    return {"helper": sha256_file(helper), "offline_checker": sha256_file(checker)}
def finalize_directory(repo_root: Path, partial: Path, final: Path, manifest: dict[str, Any]) -> None:
    if final.exists() or final.is_symlink():
        raise InvalidClarification("refusing to replace a finalized clarification run")
    atomic_write_json(partial / "manifest.json", manifest)
    scan_for_credentials(partial)
    if directory_usage_bytes(partial) > EVIDENCE_LIMIT_BYTES:
        raise InvalidClarification("evidence exceeded its limit before finalization")
    atomic_write_bytes(
        partial / "checksums.sha256",
        checksum_text(repo_root, partial, final),
    )
    os.replace(partial, final)
    validate_evidence(repo_root, final)
class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request: Any, file_pointer: Any, code: int, message: str, headers: Any, new_url: str) -> None:
        return None
class NetworkBudget:
    def __init__(self, mode: str, start_monotonic: float) -> None:
        self.mode = mode
        self.request_limit = CREATE_REQUEST_LIMIT if mode == "issue-create" else READ_REQUEST_LIMIT
        self.post_limit = POST_LIMIT if mode == "issue-create" else 0
        self.start_monotonic = start_monotonic
        self.request_count = 0
        self.get_count = 0
        self.post_count = 0
        self.downloaded_bytes = 0
        self.response_records = 0
    def begin(self, method: str) -> None:
        if time.monotonic() - self.start_monotonic > DEADLINE_SECONDS:
            raise StopClarification("network wall-clock deadline reached")
        if self.request_count >= self.request_limit:
            raise StopClarification("network request limit reached")
        if method not in {"GET", "POST"}:
            raise InvalidClarification("network method is prohibited")
        if method == "POST" and self.post_count >= self.post_limit:
            raise InvalidClarification("network POST limit reached")
        self.request_count += 1
        if method == "GET":
            self.get_count += 1
        else:
            self.post_count += 1
    def receive(self, byte_count: int) -> None:
        if byte_count < 0 or self.downloaded_bytes + byte_count > DOWNLOAD_LIMIT_BYTES:
            raise StopClarification("network download limit reached")
        self.downloaded_bytes += byte_count
        self.response_records += 1
    def as_manifest(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "allowed_hosts": [API_HOST],
            "proxies_disabled": True,
            "redirects_disabled": True,
            "request_count": self.request_count,
            "request_limit": self.request_limit,
            "get_count": self.get_count,
            "post_count": self.post_count,
            "post_limit": self.post_limit,
            "downloaded_bytes": self.downloaded_bytes,
            "download_limit_bytes": DOWNLOAD_LIMIT_BYTES,
            "request_timeout_seconds": REQUEST_TIMEOUT_SECONDS,
            "retry_count": 0,
            "background_processes_started": 0,
            "response_records": self.response_records,
        }
def safe_headers(headers: Any) -> dict[str, str]:
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() in SAFE_RESPONSE_HEADERS
    }
def validate_api_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != API_HOST or parsed.port not in {None, 443}:
        raise InvalidClarification("GitHub API URL is outside the frozen host")
    if parsed.username or parsed.password or parsed.fragment or not parsed.path.startswith("/"):
        raise InvalidClarification("GitHub API URL contains prohibited components")
    if ".." in PurePosixPath(parsed.path).parts or "//" in parsed.path:
        raise InvalidClarification("GitHub API URL path is unsafe")
def validate_api_result(result: HttpResult, expected_status: set[int]) -> dict[str, Any]:
    validate_api_url(result.url)
    if 300 <= result.status < 400:
        raise StopClarification("GitHub API redirect is prohibited")
    if result.status not in expected_status:
        raise StopClarification(f"GitHub API returned HTTP {result.status}")
    content_type = result.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in {"application/json", "application/vnd.github+json"}:
        raise StopClarification("GitHub API response is not JSON")
    if not result.body or result.body.lstrip().lower().startswith((b"{", b"[")):
        raise StopClarification("GitHub API response is empty or HTML-like")
    try:
        parsed = json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StopClarification("GitHub API response JSON is invalid") from error
    if not isinstance(parsed, (dict, list)):
        raise StopClarification("GitHub API response has an unsupported JSON root")
    return parsed
def load_github_token() -> str:
    if shutil.which("gh") is None:
        raise InvalidClarification("gh is required to use the project owner's existing GitHub session")
    result = subprocess.run(
        ["gh", "auth", "token", "--hostname", "github.com"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise InvalidClarification("existing GitHub session is unavailable")
    token = result.stdout.decode("utf-8").strip()
    if not token or "\n" in token or "\r" in token:
        raise InvalidClarification("existing GitHub session returned an invalid token")
    return token
class GitHubClient:
    def __init__(
        self,
        budget: NetworkBudget,
        recorder: Callable[[HttpResult, bytes | None], None],
    ) -> None:
        self.budget = budget
        self.recorder = recorder
        self.token = load_github_token()
        self.opener = build_opener(ProxyHandler({}), NoRedirectHandler(), HTTPSHandler())

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        filter_account: bool = False,
        post_intent: Callable[[], None] | None = None,
    ) -> HttpResult:
        if not path.startswith("/"):
            raise InvalidClarification("GitHub API request path must be absolute")
        url = f"https://{API_HOST}{path}"
        validate_api_url(url)
        encoded = canonical_json(payload) if payload is not None else None
        if method == "POST" and post_intent is not None:
            post_intent()
        self.budget.begin(method)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=encoded, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS)
            status = response.status
            response_headers = safe_headers(response.headers)
            body = response.read(RESPONSE_LIMIT_BYTES + 1)
        except HTTPError as error:
            status = error.code
            response_headers = safe_headers(error.headers)
            body = error.read(RESPONSE_LIMIT_BYTES + 1)
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            if method == "POST":
                raise AmbiguousExternalWrite(f"POST response is unavailable: {type(error).__name__}") from error
            raise StopClarification(f"GET response is unavailable: {type(error).__name__}") from error
        if len(body) > RESPONSE_LIMIT_BYTES:
            if method == "POST":
                raise AmbiguousExternalWrite("POST response exceeded the single-response limit")
            raise StopClarification("GET response exceeded the single-response limit")
        try:
            self.budget.receive(len(body))
        except StopClarification as error:
            if method == "POST":
                raise AmbiguousExternalWrite("POST response exceeded the cumulative download limit") from error
            raise
        result = HttpResult(method, url, status, response_headers, body)
        recorded = body
        if filter_account:
            parsed = validate_api_result(result, {200})
            if not isinstance(parsed, dict):
                raise InvalidClarification("authenticated account response is not an object")
            recorded = canonical_json({"login": parsed.get("login"), "id": parsed.get("id")})
        try:
            self.recorder(result, recorded)
        except (InvalidClarification, OSError) as error:
            self.budget.response_records -= 1
            if method == "POST":
                raise AmbiguousExternalWrite("POST response could not be durably recorded") from error
            raise InvalidClarification("GET response could not be durably recorded") from error
        return result
class EvidenceRecorder:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.index = 0

    def post_intent(self) -> None:
        atomic_write_json(
            self.run_dir / "network" / "post-intent.json",
            {
                "method": "POST",
                "url": f"https://{API_HOST}/repos/{REPOSITORY}/issues",
                "title_sha256": TITLE_SHA256,
                "body_sha256": BODY_SHA256,
                "recorded_at": utc_now(),
            },
        )

    def record(self, result: HttpResult, recorded_body: bytes | None) -> None:
        self.index += 1
        stem = f"{self.index:02d}"
        body = result.body if recorded_body is None else recorded_body
        body_path = f"network/{stem}.response.json"
        atomic_write_bytes(self.run_dir / body_path, body)
        atomic_write_json(
            self.run_dir / "network" / f"{stem}.observation.json",
            {
                "method": result.method,
                "url": result.url,
                "status": result.status,
                "headers": result.headers,
                "body_path": body_path,
                "body_sha256": sha256_bytes(body),
                "body_size": len(body),
            },
        )
def validate_repository_response(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise InvalidClarification("repository response is not an object")
    if payload.get("full_name") != REPOSITORY or payload.get("html_url") != REPOSITORY_URL:
        raise InvalidClarification("repository identity drifted")
    if payload.get("has_issues") is not True or payload.get("disabled") is True:
        raise StopClarification("official repository Issues are unavailable")
def validate_commit_response(payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("sha") != COMMIT:
        raise InvalidClarification("fixed upstream commit identity drifted")
    tree = payload.get("tree")
    if not isinstance(tree, dict) or tree.get("sha") != TREE:
        raise InvalidClarification("fixed upstream tree identity drifted")
def validate_duplicate_search(payload: Any) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("total_count"), int):
        raise InvalidClarification("duplicate Issue search response is malformed")
    if payload["total_count"] != 0:
        raise StopClarification("an equivalent open or closed Issue already exists")
def issue_from_response(payload: Any, expected_login: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AmbiguousExternalWrite("Issue creation response is not an object")
    user = payload.get("user")
    number = payload.get("number")
    if not isinstance(user, dict) or not isinstance(number, int):
        raise AmbiguousExternalWrite("Issue creation response lacks identity")
    if payload.get("title") != ISSUE_TITLE or payload.get("body") != ISSUE_BODY:
        raise AmbiguousExternalWrite("created Issue message differs from the frozen bytes")
    issue = {
        "number": number,
        "node_id": payload.get("node_id"),
        "api_url": payload.get("url"),
        "html_url": payload.get("html_url"),
        "author_login": user.get("login"),
        "author_id": user.get("id"),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
        "title_sha256": TITLE_SHA256,
        "body_sha256": BODY_SHA256,
    }
    validate_issue(issue, expected_login)
    return issue
def parse_created_issue(result: HttpResult, expected_login: str) -> dict[str, Any]:
    if result.status != 201:
        if result.status in {400, 401, 403, 404, 422}:
            validate_api_result(result, {201})
        raise AmbiguousExternalWrite(f"POST returned uncertain HTTP {result.status}")
    try:
        payload = validate_api_result(result, {201})
    except StopClarification as error:
        raise AmbiguousExternalWrite("POST succeeded but its response cannot be validated") from error
    return issue_from_response(payload, expected_login)
def extract_referenced_commits(comments: list[Any]) -> list[str]:
    pattern = re.compile(
        rf"https://github\.com/{re.escape(REPOSITORY)}/commit/([0-9a-f]{{40}})(?:\b|/)"
    )
    found = {
        match.group(1)
        for comment in comments
        if isinstance(comment, dict) and isinstance(comment.get("body"), str)
        for match in pattern.finditer(comment["body"])
        if match.group(1) != COMMIT
    }
    if len(found) > 3:
        raise StopClarification("response references exceed the bounded commit limit")
    return sorted(found)
def response_summary(comments: Any, events: Any, next_page_seen: bool) -> dict[str, Any]:
    if not isinstance(comments, list) or not isinstance(events, list):
        raise InvalidClarification("Issue comments or events response is not an array")
    commenters: dict[tuple[str, int, str], dict[str, Any]] = {}
    for comment in comments:
        if not isinstance(comment, dict) or not isinstance(comment.get("user"), dict):
            raise InvalidClarification("Issue comment identity is malformed")
        user = comment["user"]
        login = user.get("login")
        identifier = user.get("id")
        association = comment.get("author_association")
        if not isinstance(login, str) or not isinstance(identifier, int) or not isinstance(association, str):
            raise InvalidClarification("Issue commenter identity is malformed")
        key = (login, identifier, association)
        commenters[key] = {"login": login, "id": identifier, "author_association": association}
    return {
        "comment_count": len(comments),
        "event_count": len(events),
        "commenters": [commenters[key] for key in sorted(commenters)],
        "referenced_commits": extract_referenced_commits(comments),
        "next_page_seen": next_page_seen,
    }
def validate_response_assessment(assessment: dict[str, Any]) -> None:
    strict_keys(
        assessment,
        {
            "package_identity_bound",
            "authorized_maintainer",
            "complete_notice_and_holder",
            "third_party_and_notice_answered",
            "retrospective_application",
            "immutable_official_commit",
        },
        "response_assessment",
    )
    for key, value in assessment.items():
        if value is not True:
            raise StopClarification(f"upstream response acceptance is not closed: {key}")
def base_manifest(
    run_id: str,
    revision: str,
    start_time: str,
    elapsed_ms: int,
    account: dict[str, Any],
    network: dict[str, Any],
    outcome: str,
    stage: str,
    reason: str,
    exit_code: int,
    issue: dict[str, Any] | None,
    source_x_run: str | None,
    summary: dict[str, Any] | None,
    input_sha: dict[str, str],
    evidence_bytes: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_contract": MANIFEST_CONTRACT,
        "evidence_id": EVIDENCE_ID,
        "run_id": run_id,
        "outcome": outcome,
        "stage": stage,
        "reason": reason,
        "exit_code": exit_code,
        "start_time": start_time,
        "end_time": utc_now(),
        "repository_revision": revision,
        "plan_revision": PLAN_REVISION,
        "plan_sha256": PLAN_SHA256,
        "fixed_object": fixed_object(),
        "message": message_contract(),
        "account": account,
        "network": network,
        "issue": issue,
        "source_x_run": source_x_run,
        "response_summary": summary,
        "runtime": {
            "elapsed_milliseconds": elapsed_ms,
            "deadline_seconds": DEADLINE_SECONDS,
            "evidence_limit_bytes": EVIDENCE_LIMIT_BYTES,
            "evidence_bytes_before_manifest": evidence_bytes,
        },
        "input_sha256": input_sha,
    }
def create_issue(repo_root: Path, revision: str, expected_login: str) -> int:
    preflight = local_preflight(repo_root, revision)
    start_time = utc_now()
    start_monotonic = time.monotonic()
    partial, final, run_id = prepare_artifact_directories(repo_root)
    write_message_files(partial)
    atomic_write_json(partial / "preflight.json", preflight)
    recorder = EvidenceRecorder(partial)
    budget = NetworkBudget("issue-create", start_monotonic)
    account = {"expected_login": expected_login, "observed_login": None, "observed_id": None}
    issue: dict[str, Any] | None = None
    outcome, stage, reason, exit_code = "INVALID", "evidence-contract", "unhandled failure", 10
    try:
        client = GitHubClient(budget, recorder.record)
        user_result = client.request("GET", "/user", filter_account=True)
        user = validate_api_result(user_result, {200})
        if not isinstance(user, dict):
            raise InvalidClarification("authenticated account response is malformed")
        account = {
            "expected_login": expected_login,
            "observed_login": user.get("login"),
            "observed_id": user.get("id"),
        }
        validate_account(account, True)

        repo_result = client.request("GET", f"/repos/{REPOSITORY}")
        validate_repository_response(validate_api_result(repo_result, {200}))
        commit_result = client.request("GET", f"/repos/{REPOSITORY}/git/commits/{COMMIT}")
        validate_commit_response(validate_api_result(commit_result, {200}))
        query = urlencode(
            {
                "q": (
                    f'repo:{REPOSITORY} is:issue in:body "{REGISTRY_CHECKSUM}" "{COMMIT}"'
                )
            }
        )
        duplicate_result = client.request("GET", f"/search/issues?{query}")
        validate_duplicate_search(validate_api_result(duplicate_result, {200}))
        created_result = client.request(
            "POST",
            f"/repos/{REPOSITORY}/issues",
            {"title": ISSUE_TITLE, "body": ISSUE_BODY},
            post_intent=recorder.post_intent,
        )
        issue = parse_created_issue(created_result, expected_login)
        outcome, stage, reason, exit_code = (
            "STOP",
            "issue-created",
            "public Issue created; awaiting a qualified upstream response",
            20,
        )
    except AmbiguousExternalWrite as error:
        outcome, stage, reason, exit_code = "INVALID", "ambiguous-external-write", str(error), 10
    except StopClarification as error:
        stage = "external-write-rejected" if budget.post_count == 1 else "preflight"
        outcome, reason, exit_code = "STOP", str(error), 20
    except InvalidClarification as error:
        outcome, stage, reason, exit_code = "INVALID", "evidence-contract", str(error), 10

    elapsed_ms = round((time.monotonic() - start_monotonic) * 1000)
    manifest = base_manifest(
        run_id,
        revision,
        start_time,
        elapsed_ms,
        account,
        budget.as_manifest(),
        outcome,
        stage,
        reason,
        exit_code,
        issue,
        None,
        None,
        finalization_input_sha(repo_root),
        directory_usage_bytes(partial),
    )
    finalize_directory(repo_root, partial, final, manifest)
    print(f"SW-EXP-003 debug_tree R1d-U-X: {outcome} {final.relative_to(repo_root)}")
    return exit_code
def collect_response(repo_root: Path, revision: str, source_run_id: str, expected_login: str) -> int:
    local_preflight(repo_root, revision)
    artifact_root = repo_root / ARTIFACT_RELATIVE
    source_dir = artifact_root / source_run_id
    source = validate_evidence(repo_root, source_dir)
    if (source["outcome"], source["stage"]) != ("STOP", "issue-created"):
        raise InvalidClarification("R1d-U-R source is not a finalized successful X run")
    if source["account"]["expected_login"].lower() != expected_login.lower():
        raise InvalidClarification("R1d-U-R expected account differs from X evidence")
    source_issue = source["issue"]

    start_time = utc_now()
    start_monotonic = time.monotonic()
    partial, final, run_id = prepare_artifact_directories(repo_root)
    write_message_files(partial)
    recorder = EvidenceRecorder(partial)
    budget = NetworkBudget("response-read", start_monotonic)
    account = {"expected_login": expected_login, "observed_login": None, "observed_id": None}
    summary: dict[str, Any] | None = None
    outcome, stage, reason, exit_code = "INVALID", "evidence-contract", "unhandled failure", 10
    try:
        client = GitHubClient(budget, recorder.record)
        user_result = client.request("GET", "/user", filter_account=True)
        user = validate_api_result(user_result, {200})
        if not isinstance(user, dict):
            raise InvalidClarification("authenticated account response is malformed")
        account = {
            "expected_login": expected_login,
            "observed_login": user.get("login"),
            "observed_id": user.get("id"),
        }
        validate_account(account, True)
        number = source_issue["number"]
        issue_result = client.request("GET", f"/repos/{REPOSITORY}/issues/{number}")
        issue_payload = validate_api_result(issue_result, {200})
        issue = issue_from_response(issue_payload, expected_login)
        stable_issue_fields = set(source_issue) - {"updated_at"}
        if any(issue[key] != source_issue[key] for key in stable_issue_fields):
            raise InvalidClarification("public Issue identity or frozen message changed after X")
        comments_result = client.request(
            "GET", f"/repos/{REPOSITORY}/issues/{number}/comments?per_page=100"
        )
        comments = validate_api_result(comments_result, {200})
        events_result = client.request(
            "GET", f"/repos/{REPOSITORY}/issues/{number}/events?per_page=100"
        )
        events = validate_api_result(events_result, {200})
        next_page = any(
            'rel="next"' in result.headers.get("link", "")
            for result in (comments_result, events_result)
        )
        summary = response_summary(comments, events, next_page)
        for commit_sha in summary["referenced_commits"]:
            commit_result = client.request(
                "GET", f"/repos/{REPOSITORY}/git/commits/{commit_sha}"
            )
            payload = validate_api_result(commit_result, {200})
            if not isinstance(payload, dict) or payload.get("sha") != commit_sha:
                raise InvalidClarification("response-referenced commit identity drifted")
        if next_page:
            outcome, stage, reason, exit_code = (
                "STOP",
                "evidence-limit",
                "Issue response pagination exceeded the frozen single-page evidence bound",
                20,
            )
        elif summary["comment_count"] == 0:
            outcome, stage, reason, exit_code = (
                "STOP",
                "awaiting-upstream",
                "no upstream comment is present",
                20,
            )
        else:
            outcome, stage, reason, exit_code = (
                "STOP",
                "response-collected",
                "upstream activity collected; acceptance requires separate review",
                20,
            )
    except StopClarification as error:
        outcome, stage, reason, exit_code = "STOP", "evidence-limit", str(error), 20
        if summary is None:
            summary = {
                "comment_count": 0,
                "event_count": 0,
                "commenters": [],
                "referenced_commits": [],
                "next_page_seen": False,
            }
    except InvalidClarification as error:
        outcome, stage, reason, exit_code = "INVALID", "evidence-contract", str(error), 10
        if summary is None:
            summary = {
                "comment_count": 0,
                "event_count": 0,
                "commenters": [],
                "referenced_commits": [],
                "next_page_seen": False,
            }

    elapsed_ms = round((time.monotonic() - start_monotonic) * 1000)
    manifest = base_manifest(
        run_id,
        revision,
        start_time,
        elapsed_ms,
        account,
        budget.as_manifest(),
        outcome,
        stage,
        reason,
        exit_code,
        source_issue,
        source_run_id,
        summary,
        finalization_input_sha(repo_root),
        directory_usage_bytes(partial),
    )
    finalize_directory(repo_root, partial, final, manifest)
    print(f"SW-EXP-003 debug_tree R1d-U-R: {outcome} {final.relative_to(repo_root)}")
    return exit_code
def expect_error(error_type: type[Exception], callback: Callable[[], Any]) -> None:
    try:
        callback()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")
def synthetic_record(run_dir: Path, index: int, method: str, status: int, payload: Any) -> None:
    body = canonical_json(payload)
    body_path = f"network/{index:02d}.response.json"
    atomic_write_bytes(run_dir / body_path, body)
    atomic_write_json(
        run_dir / "network" / f"{index:02d}.observation.json",
        {
            "method": method,
            "url": f"https://{API_HOST}/synthetic/{index}",
            "status": status,
            "headers": {"content-type": "application/json"},
            "body_path": body_path,
            "body_sha256": sha256_bytes(body),
            "body_size": len(body),
        },
    )
def synthetic_manifest(
    run_dir: Path,
    mode: str,
    source_x_run: str | None = None,
) -> dict[str, Any]:
    write_message_files(run_dir)
    account = {"expected_login": "radish-test", "observed_login": "radish-test", "observed_id": 42}
    issue = {
        "number": 7,
        "node_id": "I_synthetic",
        "api_url": f"https://{API_HOST}/repos/{REPOSITORY}/issues/7",
        "html_url": f"https://github.com/{REPOSITORY}/issues/7",
        "author_login": "radish-test",
        "author_id": 42,
        "created_at": "2026-09-03T00:00:00Z",
        "updated_at": "2026-09-03T00:00:00Z",
        "title_sha256": TITLE_SHA256,
        "body_sha256": BODY_SHA256,
    }
    if mode == "issue-create":
        atomic_write_json(run_dir / "network" / "post-intent.json", {"synthetic": True})
        synthetic_record(run_dir, 1, "POST", 201, {"number": 7})
        network = NetworkBudget(mode, time.monotonic())
        network.request_count = 1
        network.post_count = 1
        network.downloaded_bytes = len(canonical_json({"number": 7}))
        network.response_records = 1
        outcome, stage, reason, exit_code = "STOP", "issue-created", "synthetic awaiting", 20
        summary = None
    else:
        synthetic_record(run_dir, 1, "GET", 200, [])
        network = NetworkBudget(mode, time.monotonic())
        network.request_count = 1
        network.get_count = 1
        network.downloaded_bytes = len(canonical_json([]))
        network.response_records = 1
        outcome, stage, reason, exit_code = "STOP", "awaiting-upstream", "synthetic wait", 20
        summary = {
            "comment_count": 0,
            "event_count": 0,
            "commenters": [],
            "referenced_commits": [],
            "next_page_seen": False,
        }
    return base_manifest(
        run_dir.name,
        "a" * 40,
        "2026-09-03T00:00:00Z",
        1,
        account,
        network.as_manifest(),
        outcome,
        stage,
        reason,
        exit_code,
        issue,
        source_x_run,
        summary,
        {"helper": "b" * 64, "offline_checker": "c" * 64},
        directory_usage_bytes(run_dir),
    )
def rewrite_manifest_and_checksums(repo_root: Path, run_dir: Path, manifest: dict[str, Any]) -> None:
    (run_dir / "manifest.json").write_bytes(canonical_json(manifest))
    (run_dir / "checksums.sha256").write_bytes(checksum_text(repo_root, run_dir))
def self_test() -> int:
    with patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")):
        assert sha256_bytes(ISSUE_TITLE.encode("utf-8")) == TITLE_SHA256
        assert sha256_bytes(ISSUE_BODY.encode("utf-8")) == BODY_SHA256
        assert validate_revision("a" * 40) == "a" * 40
        expect_error(argparse.ArgumentTypeError, lambda: validate_revision("A" * 40))
        expect_error(argparse.ArgumentTypeError, lambda: validate_login("-bad"))
        expect_error(InvalidClarification, lambda: validate_api_url("http://api.github.com/x"))
        expect_error(InvalidClarification, lambda: validate_api_url("https://example.com/x"))
        expect_error(InvalidClarification, lambda: validate_api_url("https://api.github.com/a/../b"))
        expect_error(StopClarification, lambda: validate_duplicate_search({"total_count": 1}))
        validate_duplicate_search({"total_count": 0})
        expect_error(
            StopClarification,
            lambda: validate_api_result(
                HttpResult("GET", f"https://{API_HOST}/x", 302, {"content-type": "application/json"}, b"{}"),
                {200},
            ),
        )
        expect_error(
            StopClarification,
            lambda: validate_api_result(
                HttpResult("GET", f"https://{API_HOST}/x", 200, {"content-type": "text/html"}, b"<html>"),
                {200},
            ),
        )
        create_budget = NetworkBudget("issue-create", time.monotonic())
        create_budget.begin("POST")
        expect_error(InvalidClarification, lambda: create_budget.begin("POST"))
        read_budget = NetworkBudget("response-read", time.monotonic())
        expect_error(InvalidClarification, lambda: read_budget.begin("POST"))
        read_budget.downloaded_bytes = DOWNLOAD_LIMIT_BYTES
        expect_error(StopClarification, lambda: read_budget.receive(1))
        expired_budget = NetworkBudget("response-read", time.monotonic() - DEADLINE_SECONDS - 1)
        expect_error(StopClarification, lambda: expired_budget.begin("GET"))
        assessment = {
            "package_identity_bound": True,
            "authorized_maintainer": True,
            "complete_notice_and_holder": True,
            "third_party_and_notice_answered": True,
            "retrospective_application": True,
            "immutable_official_commit": True,
        }
        validate_response_assessment(assessment)
        for key in assessment:
            invalid = dict(assessment)
            invalid[key] = False
            expect_error(StopClarification, lambda invalid=invalid: validate_response_assessment(invalid))

        with tempfile.TemporaryDirectory(prefix="radishlink-r1d-u-self-test.") as temporary:
            root = Path(temporary)
            x_partial = root / ".20260903-000000-1.abcdef.partial"
            x_final = root / "20260903-000000-1.abcdef"
            x_partial.mkdir(mode=0o700)
            x_manifest = synthetic_manifest(x_partial, "issue-create")
            x_manifest["run_id"] = x_final.name
            finalize_directory(root, x_partial, x_final, x_manifest)
            validate_evidence(root, x_final)

            r_partial = root / ".20260903-000001-1.ghijkl.partial"
            r_final = root / "20260903-000001-1.ghijkl"
            r_partial.mkdir(mode=0o700)
            r_manifest = synthetic_manifest(r_partial, "response-read", x_final.name)
            r_manifest["run_id"] = r_final.name
            finalize_directory(root, r_partial, r_final, r_manifest)
            validate_evidence(root, r_final)
            paginated = root / "20260903-000002-1.pagexx"
            shutil.copytree(r_final, paginated)
            manifest = json.loads((paginated / "manifest.json").read_text(encoding="utf-8"))
            manifest["run_id"] = paginated.name
            manifest["response_summary"]["next_page_seen"] = True
            rewrite_manifest_and_checksums(root, paginated, manifest)
            expect_error(InvalidClarification, lambda: validate_evidence(root, paginated))
            cases: list[Callable[[dict[str, Any]], None]] = [
                lambda item: item.update(schema_version=99),
                lambda item: item.update(unknown_field=True),
                lambda item: item["fixed_object"].update(commit="d" * 40),
                lambda item: item["fixed_object"].update(repository="other/repo"),
                lambda item: item["fixed_object"].update(registry_checksum="d" * 64),
                lambda item: item["account"].update(observed_login="other"),
                lambda item: item["network"].update(post_count=0),
                lambda item: item["network"].update(post_count=2, request_count=2),
            ]
            for index, mutate in enumerate(cases):
                candidate = root / f"20260903-0100{index:02d}-1.case{index:02d}x"
                shutil.copytree(x_final, candidate)
                manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
                manifest["run_id"] = candidate.name
                mutate(manifest)
                rewrite_manifest_and_checksums(root, candidate, manifest)
                expect_error(InvalidClarification, lambda candidate=candidate: validate_evidence(root, candidate))
            for suffix, relative in (("bodyxx", "issue-body.md"), ("titlex", "issue-title.txt")):
                message_drift = root / f"20260903-020000-1.{suffix}"
                shutil.copytree(x_final, message_drift)
                manifest = json.loads((message_drift / "manifest.json").read_text(encoding="utf-8"))
                manifest["run_id"] = message_drift.name
                (message_drift / "message" / relative).write_text("drift\n", encoding="utf-8")
                rewrite_manifest_and_checksums(root, message_drift, manifest)
                expect_error(InvalidClarification, lambda message_drift=message_drift: validate_evidence(root, message_drift))
            tampered = root / "20260903-020001-1.tamper"
            shutil.copytree(x_final, tampered)
            manifest = json.loads((tampered / "manifest.json").read_text(encoding="utf-8"))
            manifest["run_id"] = tampered.name
            rewrite_manifest_and_checksums(root, tampered, manifest)
            (tampered / "message" / "issue-title.txt").write_text("tampered", encoding="utf-8")
            expect_error(InvalidClarification, lambda: validate_evidence(root, tampered))
            credential = root / "20260903-020002-1.secret"
            shutil.copytree(x_final, credential)
            manifest = json.loads((credential / "manifest.json").read_text(encoding="utf-8"))
            manifest["run_id"] = credential.name
            (credential / "leak.txt").write_text("Authorization: Bearer synthetic-secret", encoding="utf-8")
            rewrite_manifest_and_checksums(root, credential, manifest)
            expect_error(InvalidClarification, lambda: validate_evidence(root, credential))
            ambiguous = root / "20260903-020003-1.ambiguo"
            shutil.copytree(x_final, ambiguous)
            manifest = json.loads((ambiguous / "manifest.json").read_text(encoding="utf-8"))
            manifest["run_id"] = ambiguous.name
            manifest.update(
                outcome="INVALID",
                stage="ambiguous-external-write",
                reason="synthetic timeout after POST",
                exit_code=10,
                issue=None,
            )
            manifest["network"]["response_records"] = manifest["network"]["request_count"] - 1
            (ambiguous / "network" / "01.observation.json").unlink()
            (ambiguous / "network" / "01.response.json").unlink()
            rewrite_manifest_and_checksums(root, ambiguous, manifest)
            validate_evidence(root, ambiguous)
    print("SW-EXP-003 debug_tree upstream clarification offline self-test: PASS")
    return 0
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("self-test", help="run synthetic offline checks only")
    preflight = subparsers.add_parser("preflight", help="validate local frozen inputs only")
    preflight.add_argument("expected_revision", type=validate_revision)
    create = subparsers.add_parser("create-issue", help="perform one separately authorized R1d-U-X")
    create.add_argument("expected_revision", type=validate_revision)
    create.add_argument("expected_login", type=validate_login)
    create.add_argument("--authorized-r1d-u-x", action="store_true", required=True)
    read = subparsers.add_parser("collect-response", help="perform one separately authorized R1d-U-R")
    read.add_argument("expected_revision", type=validate_revision)
    read.add_argument("source_x_run", type=validate_run_id)
    read.add_argument("expected_login", type=validate_login)
    read.add_argument("--authorized-r1d-u-r", action="store_true", required=True)
    return parser
def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    if arguments.action == "self-test":
        return self_test()
    if arguments.action == "preflight":
        try:
            local_preflight(repo_root, arguments.expected_revision)
        except InvalidClarification as error:
            print(f"INVALID before R1d-U network/evidence: {error}", file=sys.stderr)
            return 10
        print("SW-EXP-003 debug_tree upstream clarification preflight: PASS")
        return 0
    if arguments.action == "create-issue":
        try:
            return create_issue(repo_root, arguments.expected_revision, arguments.expected_login)
        except InvalidClarification as error:
            print(f"INVALID before R1d-U-X network/evidence: {error}", file=sys.stderr)
            return 10
    if arguments.action == "collect-response":
        try:
            return collect_response(
                repo_root,
                arguments.expected_revision,
                arguments.source_x_run,
                arguments.expected_login,
            )
        except InvalidClarification as error:
            print(f"INVALID before R1d-U-R network/evidence: {error}", file=sys.stderr)
            return 10
    parser.error("unsupported action")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
