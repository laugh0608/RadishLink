#!/usr/bin/env python3
"""Monitor bounded local state for one candidate-neutral dependency audit run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any


SNAPSHOT_NAME = "runtime-control.json"
TRIGGER_NAME = "runtime-control-trigger.json"


def directory_usage_kib(root: Path) -> int:
    """Return apparent size without following symbolic links."""
    total_bytes = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for entry_name in [*directory_names, *file_names]:
            try:
                total_bytes += (directory_path / entry_name).lstat().st_size
            except FileNotFoundError:
                continue
    return (total_bytes + 1023) // 1024


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace one JSON snapshot without following a pre-existing temp symlink."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=True, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def limit_reason(
    elapsed_seconds: float,
    disk_current_kib: int,
    timeout_seconds: int,
    disk_budget_kib: int,
) -> str | None:
    if elapsed_seconds >= timeout_seconds:
        return "deadline_exceeded"
    if disk_current_kib >= disk_budget_kib:
        return "disk_budget_exceeded"
    return None


def snapshot_payload(
    *,
    status: str,
    reason: str | None,
    elapsed_seconds: float,
    disk_current_kib: int,
    disk_peak_kib: int,
    timeout_seconds: int,
    disk_budget_kib: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "stop_reason": reason,
        "elapsed_milliseconds": round(elapsed_seconds * 1000),
        "timeout_seconds": timeout_seconds,
        "disk_current_kib": disk_current_kib,
        "disk_peak_kib": disk_peak_kib,
        "disk_budget_kib": disk_budget_kib,
        "disk_enforcement": "periodic-apparent-size-monitor",
        "poll_interval_milliseconds": round(poll_interval_seconds * 1000),
    }


def monitor(args: argparse.Namespace) -> int:
    requested_run_dir = Path(args.run_dir)
    if requested_run_dir.is_symlink():
        raise ValueError("run directory must not be a symbolic link")
    run_dir = requested_run_dir.resolve(strict=True)
    if not run_dir.is_dir():
        raise ValueError("run directory must be a real directory")
    if args.runner_pid <= 1 or os.getppid() != args.runner_pid:
        raise ValueError("runner PID must identify the monitor parent")
    if args.timeout_seconds <= 0 or args.disk_budget_kib <= 0:
        raise ValueError("runtime limits must be positive")
    if not 0.01 <= args.poll_interval_seconds <= 60:
        raise ValueError("poll interval must be between 0.01 and 60 seconds")
    if args.elapsed_offset_seconds < 0:
        raise ValueError("elapsed offset must not be negative")

    snapshot_path = run_dir / SNAPSHOT_NAME
    trigger_path = run_dir / TRIGGER_NAME
    stopped = False

    def request_stop(_signal_number: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    monotonic_start = time.monotonic()
    disk_peak_kib = 0
    last_elapsed = float(args.elapsed_offset_seconds)
    last_disk_kib = 0
    try:
        while True:
            last_elapsed = args.elapsed_offset_seconds + time.monotonic() - monotonic_start
            last_disk_kib = directory_usage_kib(run_dir)
            disk_peak_kib = max(disk_peak_kib, last_disk_kib)
            if stopped:
                atomic_write_json(
                    snapshot_path,
                    snapshot_payload(
                        status="stopped",
                        reason="runner_requested_stop",
                        elapsed_seconds=last_elapsed,
                        disk_current_kib=last_disk_kib,
                        disk_peak_kib=disk_peak_kib,
                        timeout_seconds=args.timeout_seconds,
                        disk_budget_kib=args.disk_budget_kib,
                        poll_interval_seconds=args.poll_interval_seconds,
                    ),
                )
                return 0

            reason = limit_reason(
                last_elapsed,
                last_disk_kib,
                args.timeout_seconds,
                args.disk_budget_kib,
            )
            payload = snapshot_payload(
                status="triggered" if reason else "monitoring",
                reason=reason,
                elapsed_seconds=last_elapsed,
                disk_current_kib=last_disk_kib,
                disk_peak_kib=disk_peak_kib,
                timeout_seconds=args.timeout_seconds,
                disk_budget_kib=args.disk_budget_kib,
                poll_interval_seconds=args.poll_interval_seconds,
            )
            atomic_write_json(snapshot_path, payload)
            if reason:
                atomic_write_json(trigger_path, payload)
                try:
                    os.kill(args.runner_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                return 124 if reason == "deadline_exceeded" else 125
            time.sleep(args.poll_interval_seconds)
    except Exception as error:  # pragma: no cover - exercised by integration behavior
        payload = snapshot_payload(
            status="triggered",
            reason="monitor_error",
            elapsed_seconds=last_elapsed,
            disk_current_kib=last_disk_kib,
            disk_peak_kib=disk_peak_kib,
            timeout_seconds=args.timeout_seconds,
            disk_budget_kib=args.disk_budget_kib,
            poll_interval_seconds=args.poll_interval_seconds,
        )
        payload["error_type"] = type(error).__name__
        try:
            atomic_write_json(trigger_path, payload)
            atomic_write_json(snapshot_path, payload)
        except OSError:
            pass
        try:
            os.kill(args.runner_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return 126


def wait_for_path(path: Path, timeout_seconds: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path.name}")


def run_parent_signal_case(run_dir: Path, expected_reason: str) -> None:
    marker = run_dir / "parent-signal.txt"
    driver = """
import os
from pathlib import Path
import signal
import subprocess
import sys

marker = Path(os.environ["CONTROL_TEST_MARKER"])

def stop(_signal_number, _frame):
    marker.write_text("TERM\\n", encoding="utf-8")
    raise SystemExit(143)

signal.signal(signal.SIGTERM, stop)
subprocess.run([
    sys.executable,
    os.environ["CONTROL_HELPER"],
    "monitor",
    "--run-dir", os.environ["CONTROL_RUN_DIR"],
    "--runner-pid", str(os.getpid()),
    "--timeout-seconds", os.environ["CONTROL_TIMEOUT"],
    "--disk-budget-kib", os.environ["CONTROL_DISK_BUDGET"],
    "--poll-interval-seconds", "0.02",
    "--elapsed-offset-seconds", os.environ["CONTROL_ELAPSED_OFFSET"],
], check=False)
"""
    environment = os.environ.copy()
    environment.update(
        {
            "CONTROL_TEST_MARKER": str(marker),
            "CONTROL_HELPER": str(Path(__file__).resolve()),
            "CONTROL_RUN_DIR": str(run_dir),
            "CONTROL_TIMEOUT": "1" if expected_reason == "deadline_exceeded" else "30",
            "CONTROL_DISK_BUDGET": "1"
            if expected_reason == "disk_budget_exceeded"
            else "1048576",
            "CONTROL_ELAPSED_OFFSET": "1"
            if expected_reason == "deadline_exceeded"
            else "0",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", driver],
        env=environment,
        check=False,
        timeout=8,
    )
    if completed.returncode != 143:
        raise AssertionError(
            f"parent signal probe returned {completed.returncode}, expected 143"
        )
    if marker.read_text(encoding="utf-8") != "TERM\n":
        raise AssertionError("monitor did not signal its exact parent")
    trigger = json.loads((run_dir / TRIGGER_NAME).read_text(encoding="utf-8"))
    if trigger["stop_reason"] != expected_reason:
        raise AssertionError("monitor recorded the wrong trigger reason")


def run_requested_stop_case(run_dir: Path) -> None:
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "monitor",
            "--run-dir",
            str(run_dir),
            "--runner-pid",
            str(os.getpid()),
            "--timeout-seconds",
            "30",
            "--disk-budget-kib",
            "1048576",
            "--poll-interval-seconds",
            "0.02",
            "--elapsed-offset-seconds",
            "0",
        ]
    )
    wait_for_path(run_dir / SNAPSHOT_NAME)
    process.send_signal(signal.SIGTERM)
    if process.wait(timeout=5) != 0:
        raise AssertionError("requested-stop monitor did not exit cleanly")
    snapshot = json.loads((run_dir / SNAPSHOT_NAME).read_text(encoding="utf-8"))
    if snapshot["status"] != "stopped" or snapshot["stop_reason"] != "runner_requested_stop":
        raise AssertionError("requested-stop snapshot is invalid")


def self_test() -> int:
    if limit_reason(10, 0, 10, 100) != "deadline_exceeded":
        raise AssertionError("deadline boundary is not enforced")
    if limit_reason(0, 100, 10, 100) != "disk_budget_exceeded":
        raise AssertionError("disk boundary is not enforced")
    if limit_reason(0, 0, 10, 100) is not None:
        raise AssertionError("safe state unexpectedly triggered")

    with tempfile.TemporaryDirectory(prefix="radishlink-runtime-control-") as temp:
        root = Path(temp)
        size_root = root / "size"
        size_root.mkdir()
        (size_root / "payload").write_bytes(b"x" * 2048)
        external = root / "external"
        external.write_bytes(b"y" * 8192)
        (size_root / "external-link").symlink_to(external)
        if directory_usage_kib(size_root) >= 10:
            raise AssertionError("directory usage followed a symbolic link")

        atomic_target = root / "atomic.json"
        atomic_write_json(atomic_target, {"ok": True})
        if json.loads(atomic_target.read_text(encoding="utf-8")) != {"ok": True}:
            raise AssertionError("atomic JSON output is invalid")

        deadline_dir = root / "deadline"
        deadline_dir.mkdir()
        run_parent_signal_case(deadline_dir, "deadline_exceeded")
        disk_dir = root / "disk"
        disk_dir.mkdir()
        run_parent_signal_case(disk_dir, "disk_budget_exceeded")
        stop_dir = root / "stop"
        stop_dir.mkdir()
        run_requested_stop_case(stop_dir)

    print("SW-G2 dependency audit runtime control self-test: PASS")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)
    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--run-dir", required=True)
    monitor_parser.add_argument("--runner-pid", required=True, type=int)
    monitor_parser.add_argument("--timeout-seconds", required=True, type=int)
    monitor_parser.add_argument("--disk-budget-kib", required=True, type=int)
    monitor_parser.add_argument("--poll-interval-seconds", required=True, type=float)
    monitor_parser.add_argument("--elapsed-offset-seconds", required=True, type=float)
    subparsers.add_parser("self-test")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return self_test() if args.action == "self-test" else monitor(args)
    except (AssertionError, OSError, ValueError) as error:
        print(f"runtime control error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
