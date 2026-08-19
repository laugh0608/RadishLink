#!/usr/bin/env python3
"""Dependency-free repository governance and text hygiene checks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


REPO_ROOT = Path(__file__).resolve().parents[1]
MAX_PATH_LENGTH = 180
MAX_FILE_BYTES = 10 * 1024 * 1024

REQUIRED_FILES = (
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".github/ISSUE_TEMPLATE/bug-report.yml",
    ".github/ISSUE_TEMPLATE/change-proposal.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/rulesets/README.md",
    ".github/rulesets/master-protection.json",
    ".github/workflows/pr-check.yml",
    "AGENTS.md",
    "CLAUDE.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "README.md",
    "SECURITY.md",
    "docs/README.md",
    "docs/adr/0001-radio-and-host-baseline.md",
    "docs/adr/0002-underlay-overlay-separation.md",
    "docs/adr/0003-branch-pr-and-ruleset-governance.md",
    "docs/adr/README.md",
    "docs/architecture/network-and-routing.md",
    "docs/architecture/system-architecture.md",
    "docs/governance/repository-governance.md",
    "docs/hardware/hardware-strategy.md",
    "docs/hardware/poc-purchase-list.md",
    "docs/mobile/companion-app.md",
    "docs/product-definition.md",
    "docs/protocol/media-and-qos.md",
    "docs/regulatory/radio-compliance.md",
    "docs/research/technology-evidence.md",
    "docs/roadmap.md",
    "docs/security/security-architecture.md",
    "docs/status/current.md",
    "docs/testing/field-validation-plan.md",
    "scripts/check-repo.ps1",
    "scripts/check-repo.py",
    "scripts/check-repo.sh",
)

TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".dart",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsonc",
    ".jsx",
    ".kt",
    ".kts",
    ".md",
    ".mjs",
    ".proto",
    ".ps1",
    ".py",
    ".rs",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

TEXT_NAMES = {
    ".dockerignore",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "Dockerfile",
    "LICENSE",
    "Makefile",
}

FORBIDDEN_DIRECTORY_NAMES = {
    "__pycache__",
    "node_modules",
}

CONVENTIONAL_COMMIT = re.compile(
    r"^(feat|fix|docs|refactor|test|chore|ci|build|perf|revert)"
    r"(\([a-z0-9._/-]+\))?!?: .+"
)
ALLOWED_MERGE_COMMIT = re.compile(
    r"^Merge (pull request|branch|remote-tracking branch)"
)
MARKDOWN_LINK = re.compile(
    r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+['\"][^'\"]*['\"])?\)"
)
WINDOWS_USER_PATH = re.compile(r"[A-Za-z]:\\Users\\")
FULL_ACTION_PIN = re.compile(
    r"(?P<action>[^@\s]+)@(?P<sha>[0-9a-f]{40})\s+#\s+"
    r"(?P<version>v\d+\.\d+\.\d+)"
)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def repository_files() -> list[Path]:
    result = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return sorted(
        (REPO_ROOT / item for item in result.stdout.split("\0") if item),
        key=lambda path: path.as_posix(),
    )


def relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def is_text_file(path: Path) -> bool:
    return path.name in TEXT_NAMES or path.suffix.lower() in TEXT_SUFFIXES


def check_required_files(errors: list[str]) -> None:
    for item in REQUIRED_FILES:
        if not (REPO_ROOT / item).is_file():
            errors.append(f"missing required file: {item}")


def check_paths_and_sizes(paths: list[Path], errors: list[str]) -> None:
    for path in paths:
        name = relative(path)
        parts = set(path.relative_to(REPO_ROOT).parts)
        if len(name) > MAX_PATH_LENGTH:
            errors.append(f"path exceeds {MAX_PATH_LENGTH} characters: {name}")
        if path.is_file() and path.stat().st_size > MAX_FILE_BYTES:
            errors.append(
                f"file exceeds 10 MiB; use an explicit artifact or LFS policy: {name}"
            )
        if path.name in {".DS_Store", "Thumbs.db", "Desktop.ini"}:
            errors.append(f"operating-system metadata must not be committed: {name}")
        if parts.intersection(FORBIDDEN_DIRECTORY_NAMES):
            errors.append(f"generated dependency or cache directory must not be committed: {name}")
        if path.name == ".env" or (
            path.name.startswith(".env.") and not path.name.endswith(".example")
        ):
            errors.append(f"environment file must not be committed: {name}")


def check_text_files(paths: list[Path], errors: list[str]) -> None:
    for path in paths:
        if not path.is_file() or not is_text_file(path):
            continue

        name = relative(path)
        data = path.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            errors.append(f"UTF-8 BOM is not allowed: {name}")
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"text file is not valid UTF-8: {name}: {exc}")
            continue

        if "\x00" in text:
            errors.append(f"NUL byte found in declared text file: {name}")
        if "\r" in text:
            errors.append(f"text file must use LF line endings: {name}")
        if text and not text.endswith("\n"):
            errors.append(f"text file is missing final newline: {name}")

        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.endswith((" ", "\t")):
                errors.append(f"trailing whitespace: {name}:{line_number}")


def check_json_files(paths: list[Path], errors: list[str]) -> None:
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".json":
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON: {relative(path)}: {exc}")


def check_markdown_links(paths: list[Path], errors: list[str]) -> None:
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = unquote(match.group(1))
            if target.startswith(("#", "/", "http://", "https://", "mailto:")):
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(REPO_ROOT)
            except ValueError:
                errors.append(
                    f"relative link escapes repository: {relative(path)} -> {target}"
                )
                continue
            if not resolved.exists():
                errors.append(f"broken relative link: {relative(path)} -> {target}")


def check_local_absolute_paths(paths: list[Path], errors: list[str]) -> None:
    for path in paths:
        if not path.is_file() or path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        if "/Users/" in text or WINDOWS_USER_PATH.search(text):
            errors.append(
                f"committed documentation contains a local user path: {relative(path)}"
            )


def check_agent_files(errors: list[str]) -> None:
    agents = REPO_ROOT / "AGENTS.md"
    claude = REPO_ROOT / "CLAUDE.md"
    if agents.is_file() and claude.is_file() and agents.read_bytes() != claude.read_bytes():
        errors.append("AGENTS.md and CLAUDE.md must remain identical")


def find_rule(rules: list[object], rule_type: str) -> dict[str, object] | None:
    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == rule_type:
            return rule
    return None


def check_ruleset_contract(errors: list[str]) -> None:
    path = REPO_ROOT / ".github/rulesets/master-protection.json"
    if not path.is_file():
        return
    try:
        ruleset = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return

    if ruleset.get("target") != "branch":
        errors.append("master ruleset target must be branch")
    if ruleset.get("enforcement") != "active":
        errors.append("master ruleset template must declare active enforcement")
    if ruleset.get("bypass_actors") != []:
        errors.append("portable master ruleset must not hard-code remote bypass actors")

    include = ruleset.get("conditions", {}).get("ref_name", {}).get("include", [])
    if include != ["refs/heads/master"]:
        errors.append("master ruleset must target only refs/heads/master")

    rules = ruleset.get("rules")
    if not isinstance(rules, list):
        errors.append("master ruleset must define a rules array")
        return

    required_types = (
        "deletion",
        "non_fast_forward",
        "pull_request",
        "required_status_checks",
    )
    for required_type in required_types:
        if find_rule(rules, required_type) is None:
            errors.append(f"master ruleset is missing rule: {required_type}")

    if find_rule(rules, "commit_message_pattern") is not None:
        errors.append("commit messages belong in PR range checks, not the master ruleset")

    pull_request = find_rule(rules, "pull_request")
    if pull_request is not None:
        parameters = pull_request.get("parameters", {})
        if parameters.get("allowed_merge_methods") != ["merge", "rebase"]:
            errors.append("master ruleset must allow merge and rebase, in that order")
        if parameters.get("dismiss_stale_reviews_on_push") is not True:
            errors.append("master ruleset must dismiss stale reviews on push")
        if parameters.get("require_code_owner_review") is not False:
            errors.append("single-maintainer baseline must not require code owners")
        if parameters.get("require_last_push_approval") is not False:
            errors.append("single-maintainer baseline must not require last-push approval")
        if parameters.get("required_review_thread_resolution") is not True:
            errors.append("master ruleset must require review thread resolution")
        if parameters.get("required_approving_review_count") != 0:
            errors.append("single-maintainer baseline must require zero approvals")

    checks = find_rule(rules, "required_status_checks")
    if checks is not None:
        parameters = checks.get("parameters", {})
        contexts = [
            item.get("context")
            for item in parameters.get("required_status_checks", [])
            if isinstance(item, dict)
        ]
        if contexts != ["Candidate Quality"]:
            errors.append("master ruleset must require only Candidate Quality")
        if parameters.get("strict_required_status_checks_policy") is not True:
            errors.append("master ruleset must require the branch to be up to date")
        if parameters.get("do_not_enforce_on_create") is not True:
            errors.append("master ruleset must allow initial branch creation")


def check_workflow_contract(errors: list[str]) -> None:
    path = REPO_ROOT / ".github/workflows/pr-check.yml"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    required_fragments = (
        "pull_request:",
        "      - dev",
        "      - master",
        "permissions:\n  contents: read",
        "name: Repo Hygiene",
        "name: Candidate Quality",
        "if: always()",
        "persist-credentials: false",
        "./scripts/check-repo.sh --base-ref",
    )
    for fragment in required_fragments:
        if fragment not in text:
            errors.append(f"PR workflow is missing contract fragment: {fragment.strip()}")

    for forbidden_trigger in ("pull_request_target:", "workflow_run:"):
        if forbidden_trigger in text:
            errors.append(f"PR workflow must not use privileged trigger: {forbidden_trigger}")

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("uses:"):
            continue
        value = stripped.removeprefix("uses:").strip()
        if value.startswith("./"):
            continue
        if FULL_ACTION_PIN.fullmatch(value) is None:
            errors.append(
                "external action must use a full commit SHA and version comment: "
                f"{relative(path)}:{line_number}"
            )


def check_pr_template_contract(errors: list[str]) -> None:
    path = REPO_ROOT / ".github/PULL_REQUEST_TEMPLATE.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    required_fragments = (
        "目标地区、SKU、频段、带宽、功率或天线",
        "端到端加密",
        "声明与证据",
        "master -> dev",
        "未验证、风险与回滚",
    )
    for fragment in required_fragments:
        if fragment not in text:
            errors.append(f"PR template is missing project boundary: {fragment}")


def check_diff(base_ref: str | None, errors: list[str]) -> None:
    commands: list[tuple[str, ...]] = []
    if base_ref:
        if git("rev-parse", "--verify", base_ref, check=False).returncode != 0:
            errors.append(f"base ref does not resolve: {base_ref}")
            return
        commands.append(("diff", "--check", f"{base_ref}...HEAD"))
    else:
        commands.extend((("diff", "--check"), ("diff", "--cached", "--check")))

    for command in commands:
        result = git(*command, check=False)
        if result.returncode != 0:
            detail = (result.stdout + result.stderr).strip()
            errors.append(f"git {' '.join(command)} failed: {detail}")


def check_commit_messages(base_ref: str | None, errors: list[str]) -> None:
    if not base_ref:
        return
    if git("rev-parse", "--verify", base_ref, check=False).returncode != 0:
        return
    result = git("log", "--format=%H%x09%s", f"{base_ref}...HEAD")
    for line in result.stdout.splitlines():
        commit, _, subject = line.partition("\t")
        if CONVENTIONAL_COMMIT.fullmatch(subject) or ALLOWED_MERGE_COMMIT.match(subject):
            continue
        errors.append(f"non-conventional commit subject: {commit[:12]} {subject}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        help="optional base commit/ref for PR diff and commit-message checks",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    paths = repository_files()

    check_required_files(errors)
    check_paths_and_sizes(paths, errors)
    check_text_files(paths, errors)
    check_json_files(paths, errors)
    check_markdown_links(paths, errors)
    check_local_absolute_paths(paths, errors)
    check_agent_files(errors)
    check_ruleset_contract(errors)
    check_workflow_contract(errors)
    check_pr_template_contract(errors)
    check_diff(args.base_ref, errors)
    check_commit_messages(args.base_ref, errors)

    if errors:
        print("RadishLink repository baseline failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"RadishLink repository baseline passed ({len(paths)} files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
