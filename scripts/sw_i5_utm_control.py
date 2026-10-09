"""One authorized preparation-details lifecycle; never an I5 runtime entry."""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
UUID = "B86E1A47-9A67-4ECF-A51F-2B2F29CDB726"
SCRIPT = REPO / "scripts/inspect-sw-i5-guest.py"
UTMCTL = Path("/Applications/UTM.app/Contents/MacOS/utmctl")
SOURCES = (
    "scripts/sw_i5_utm_control.py", "scripts/test_sw_i5_utm_control.py",
    "scripts/inspect-sw-i5-guest.py", "scripts/test_sw_i5_guest.py",
    "scripts/sw_i5_utm_result.js",
)


def read_operation(nonce):
    if re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
        raise ValueError("invalid nonce")
    root = REPO / ".tmp" / ("i5-guest-return-" + nonce)
    if root.resolve() != root or (root / "operation.json").is_symlink():
        raise ValueError("canonical local operation path required")
    record = json.loads((root / "operation.json").read_text())
    expected = {"schema_version", "scope", "authorized", "nonce", "uuid", "base_revision",
                "hashes", "config_sha256", "utmctl_sha256"}
    if set(record) != expected or type(record["schema_version"]) is not int or \
            record["schema_version"] != 1 or record["scope"] != "i5-preparation-lifecycle-operation" or \
            record["authorized"] is not True or record["nonce"] != nonce or record["uuid"] != UUID:
        raise ValueError("current-task authorization and exact operation binding required")
    if not isinstance(record["base_revision"], str) or re.fullmatch(r"[0-9a-f]{40}", record["base_revision"]) is None:
        raise ValueError("invalid base revision")
    if not isinstance(record["hashes"], dict) or set(record["hashes"]) != set(SOURCES):
        raise ValueError("complete reviewed source manifest required")
    for path, digest in record["hashes"].items():
        if hashlib.sha256((REPO / path).read_bytes()).hexdigest() != digest:
            raise ValueError("reviewed source changed: " + path)
    if hashlib.sha256(UTMCTL.read_bytes()).hexdigest() != record["utmctl_sha256"]:
        raise ValueError("reviewed utmctl changed")
    return root, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized-once", action="store_true", required=True)
    parser.add_argument("--nonce", required=True)
    args = parser.parse_args()
    root, record = read_operation(args.nonce)
    spec = importlib.util.spec_from_file_location("i5_inventory", SCRIPT)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    collector.check_utm_config()
    config = Path.home() / "VirtualMachines/RadishLink-I5-Debian13-ARM64.utm/config.plist"
    config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    if config_hash != record["config_sha256"]:
        raise ValueError("reviewed config changed")
    if any(path.name != "operation.json" for path in root.iterdir()):
        raise FileExistsError("operation directory already contains an attempt or evidence")
    # A failed attempt is consumed too. Never overwrite or resume an old run.
    with (root / "attempt.json").open("x") as stream:
        json.dump({"nonce": record["nonce"], "uuid": UUID}, stream)
    result = {"schema_version": 1, "scope": "i5-preparation-lifecycle-result", "uuid": UUID, "nonce": record["nonce"], "passed": False,
              "start_attempted": False, "forced_stop": False, "guest_details_verified": False,
              "stopped": None, "status_before": None, "all_vm_states_unchanged": None,
              "failure_phase": None, "events": [], "errors": []}
    origin = time.monotonic()

    def event(stage):
        result["events"].append({"stage": stage, "elapsed_seconds": round(time.monotonic() - origin, 3)})

    def command(label, argv, timeout=15, limit=65536):
        code, out, err = None, b"", b""
        try:
            process = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=REPO)
            code, out, err = process.returncode, process.stdout, process.stderr
        except subprocess.TimeoutExpired as exc:
            out, err = exc.stdout or b"", exc.stderr or b""
            result["errors"].append(label + ": timeout")
        except OSError as exc:
            result["errors"].append(label + ": " + str(exc))
        evidence_ok = True
        try:
            (root / (label + ".stdout")).write_bytes(out[:limit])
            (root / (label + ".stderr")).write_bytes(err[:limit])
            (root / (label + ".json")).write_text(json.dumps({"exit_code": code,
                "stdout_bytes": len(out), "stderr_bytes": len(err)}) + "\n")
        except OSError as exc:
            evidence_ok = False
            result["errors"].append(label + ": evidence write: " + str(exc))
        if not evidence_ok or code != 0 or err or len(out) > limit or len(err) > limit:
            result["failure_phase"] = result["failure_phase"] or phase
            result["errors"].append(label + ": exit/stderr/size rejection")
            return None
        print(label + ": exit=0", flush=True)
        return out

    result["config_before_sha256"] = config_hash
    before, start_finished = None, None
    phase = "pre-boot-baseline"
    try:
        event("baseline-attempt")
        before = command("list-before", [str(UTMCTL), "list"])
        status = command("status-before", [str(UTMCTL), "status", UUID])
        if status is not None and status.strip() in {b"stopped", b"started"}:
            result["status_before"] = status.strip().decode("ascii")
            result["stopped"] = status.strip() == b"stopped"
        if before is None or UUID.encode() not in before or status is None or status.strip() != b"stopped" or result["errors"]:
            raise RuntimeError("pre-boot baseline failed; no VM start attempted; preserve evidence")
        event("baseline-verified")
        phase = "start"
        result["start_attempted"] = True
        event("start-attempt")
        try:
            started = command("start", [str(UTMCTL), "start", UUID], timeout=60)
        finally:
            start_finished = time.monotonic()
            event("start-returned")
        if started is None or result["errors"]:
            raise RuntimeError("start failed; outcome requires shutdown check")
        phase = "post-start-state"
        output = command("status-after-start", [str(UTMCTL), "status", UUID])
        if output is None or output.strip() != b"started" or result["errors"]:
            raise RuntimeError("VM started state unconfirmed; no guest collection")
        event("vm-started-observed")
        phase = "boot-grace"
        # Retain the prior 30-second grace; it is NOT a guest readiness probe.
        time.sleep(max(0, 30 - (time.monotonic() - start_finished)))
        event("boot-grace-complete")
        collector.check_utm_config()
        phase = "details"
        event("details-attempt")
        output = command("details-cli", [sys.executable, "-B", str(SCRIPT), "--collect-utm", "details",
                          "--nonce", record["nonce"]], timeout=65, limit=2 * 1024 * 1024)
        if output is None or result["errors"]:
            raise RuntimeError("details execution/evidence failed")
        execution, stdout, stderr = collector.parse_execution(output, record["nonce"], "details")
        evidence = root / "details"
        if execution != json.loads((evidence / "execution.json").read_text()) or \
                stdout != (evidence / "guest.stdout").read_bytes() or stderr != (evidence / "guest.stderr").read_bytes():
            raise RuntimeError("saved details evidence mismatch")
        collector.verify_case(execution, stdout, stderr, record["nonce"], "details")
        result["guest_details_verified"] = True
        event("guest-details-verified")
    except Exception as exc:
        result["failure_phase"] = phase
        result["errors"].append(str(exc))
    finally:
        # A failed baseline never authorizes stopping a VM or querying it again.
        if result["start_attempted"]:
            phase = "shutdown"
            # command() records launch/timeout/write failures and returns, so one
            # failed shutdown/log step cannot prevent the remaining cleanup steps.
            # Even a rejected start may have booted the VM. Apply the same bounded
            # grace before a power request, without executing guest work after failure.
            if start_finished is not None:
                time.sleep(max(0, 30 - (time.monotonic() - start_finished)))
            event("shutdown-request")
            command("shutdown-request", [str(UTMCTL), "stop", UUID, "--request"])
            deadline = time.monotonic() + 120
            stopped = False
            for attempt in range(6):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                output = command("shutdown-status-" + str(attempt), [str(UTMCTL), "status", UUID],
                                 timeout=min(15, remaining))
                if output is not None and output.strip() == b"stopped":
                    stopped = True
                    break
                time.sleep(max(0, min(30, deadline - time.monotonic())))
            if not stopped:
                result["forced_stop"] = True
                result["failure_phase"] = result["failure_phase"] or phase
                event("shutdown-force")
                command("shutdown-force", [str(UTMCTL), "stop", UUID, "--force"])
                output = command("status-after-force", [str(UTMCTL), "status", UUID])
                stopped = output is not None and output.strip() == b"stopped"
            result["stopped"] = stopped
            event("shutdown-observed" if stopped else "shutdown-unconfirmed")
            phase = "postflight"
            result["all_vm_states_unchanged"] = command("list-after", [str(UTMCTL), "list"]) == before
        else:
            event("baseline-rejected")
        try:
            collector.check_utm_config()
            result["config_after_sha256"] = hashlib.sha256(config.read_bytes()).hexdigest()
            result["config_unchanged"] = result["config_after_sha256"] == config_hash
        except Exception as exc:
            result["config_unchanged"] = False
            result["errors"].append("post-config: " + str(exc))
        if result["failure_phase"] is None and (result["errors"] or result["forced_stop"] or
                result["all_vm_states_unchanged"] is not True or not result["config_unchanged"]):
            result["failure_phase"] = "postflight" if result["config_unchanged"] is False else phase
        result["passed"] = result["guest_details_verified"] and result["stopped"] is True and \
            result["all_vm_states_unchanged"] and result["config_unchanged"] and \
            not result["errors"] and not result["forced_stop"]
        try:
            (root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        except OSError as exc:
            result["passed"] = False
            result["failure_phase"] = result["failure_phase"] or "result-write"
            result["errors"].append("result evidence write: " + str(exc))
        print(json.dumps(result, indent=2), flush=True)
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
