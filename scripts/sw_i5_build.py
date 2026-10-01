"""Bounded I5 Go build stages for a separately prepared Linux namespace.

No public build command yet: environment acceptance and I5 evidence binding
must precede integration into run-sw-i5-harness.sh. Offline tests inject the
process launcher; they do not invoke Landlock, mount, Go builds or Docker.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import resource
import signal
import subprocess
import time

from sw_i5_resources import DomainGuard, LinuxProbe, MIB, ResourceError, below, covering, require


def confine_child(build: Path) -> None:
    """Called only in the single-threaded fork child, before Go's first write.

    Landlock covers content writes, renames, truncation and device ioctls;
    verified read-only mounts cover metadata operations it does not mediate.
    Linux UAPI syscall numbers 444/445/446 apply to x86_64 and aarch64.
    """
    require(os.uname().machine in {"x86_64", "aarch64"}, "unsupported Landlock architecture")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * MIB, 32 * MIB))
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                          ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int

    def call(number, *args):
        result = libc.syscall(ctypes.c_long(number), *args)
        if result < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return result

    abi = call(444, ctypes.c_void_p(), ctypes.c_size_t(0), ctypes.c_uint(1))
    require(abi >= 5, "Landlock ABI 5 or newer required; no fallback")
    handled = (1 << 1) | sum(1 << bit for bit in range(4, 16))
    allowed = handled & ~sum(1 << bit for bit in (6, 9, 11, 15))
    mask = ctypes.c_uint64(handled)

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    rules = call(444, ctypes.byref(mask), ctypes.c_size_t(ctypes.sizeof(mask)), ctypes.c_uint(0))
    try:
        directory = os.open(build, os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            rule = PathRule(allowed, directory)
            call(445, ctypes.c_int(rules), ctypes.c_int(1), ctypes.byref(rule), ctypes.c_uint(0))
        finally:
            os.close(directory)
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        call(446, ctypes.c_int(rules), ctypes.c_uint(0))
    finally:
        os.close(rules)


def build_environment(stage: Path, go: Path, arch: str) -> dict[str, str]:
    require(arch in {"amd64", "arm64"}, "unsupported Go build architecture")
    # No os.environ merge: GOFLAGS, GOENV, proxies, XDG paths, telemetry and
    # user cache settings must not silently redirect toolchain writes.
    return {"PATH": str(go.parent) + ":/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
            "HOME": str(stage / "home"), "GOCACHE": str(stage / "cache"),
            "GOMODCACHE": str(stage / "modules"), "GOPATH": str(stage / "gopath"),
            "GOTMPDIR": str(stage / "tmp"), "TMPDIR": str(stage / "tmp"),
            "TMP": str(stage / "tmp"), "TEMP": str(stage / "tmp"),
            "XDG_CACHE_HOME": str(stage / "cache"), "XDG_CONFIG_HOME": str(stage / "home"),
            "XDG_DATA_HOME": str(stage / "home"), "XDG_STATE_HOME": str(stage / "home"),
            "GOTOOLCHAIN": "local", "GOPROXY": "off", "GOSUMDB": "off",
            "GOENV": "off", "GOWORK": "off", "GOTELEMETRY": "off",
            "CGO_ENABLED": "0", "GOOS": "linux", "GOARCH": arch}


def check_build_inputs(guard: DomainGuard, source: Path, go: Path) -> None:
    require(guard.build_scope, "build namespace verification required")
    guard.check()
    require(os.getuid() == os.geteuid() != 0, "unprivileged build identity required")
    status = Path("/proc/self/status").read_text()
    fields = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    require(all(int(fields[key].strip(), 16) == 0
                for key in ("CapInh", "CapPrm", "CapEff", "CapAmb")), "build capabilities present")
    require(fields.get("Threads", "").strip() == "1", "single-threaded build launcher required")
    mounts = (guard.probe or LinuxProbe()).mounts()
    for path in (source, go):
        require(path.is_absolute() and path.resolve(strict=True) == path,
                "canonical build input required")
        require(not below(path, guard.config.root) and "ro" in covering(mounts, path).options,
                "build input must be outside writable domains on a read-only mount")
    require(source.is_dir() and go.is_file() and os.access(go, os.X_OK), "invalid source or Go executable")


class BuildProcess:
    def __init__(self, argv, env, stage: Path, log):
        def prepare():
            try:
                confine_child(stage.parent)
            except BaseException as exc:
                # Popen otherwise replaces the precise pre-exec error with a
                # generic message. stderr already points into the build domain.
                os.write(2, ("I5_BUILD_CONFINEMENT_FAILED: " + str(exc) + "\n").encode())
                raise

        try:
            self.process = subprocess.Popen(
                argv, cwd=stage, env=env, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, close_fds=True, start_new_session=True,
                preexec_fn=prepare)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ResourceError(f"build launch failed: {exc}; diagnostic: {log.name}") from exc

    def wait(self, timeout: float):
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def cleanup(self) -> None:
        errors = []
        deadline = time.monotonic() + 5
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Normal when Go and all its compiler children already exited.
        except OSError as exc:
            errors.append(str(exc))
        try:
            self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
        # Waiting for just the Go leader is not proof that its process group
        # disappeared. Refuse success if a descendant (including a zombie) is
        # still visible. No broad process-name-based cleanup is permitted.
        while not errors:
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                break
            except OSError as exc:
                errors.append(str(exc))
                break
            if time.monotonic() >= deadline:
                errors.append("build process group remains after SIGKILL and Wait")
                break
            time.sleep(0.01)
        require(not errors, "build process cleanup failed: " + "; ".join(errors))


def supervise_build(guard, launch, *, clock=time.monotonic, timeout=300.0, interval=0.25):
    """Probe before start, during blocked builds, and after exit. Always reap.

    The entire fixed build domain remains reserved, including partial outputs
    and logs. This function never refunds space or removes failed evidence.
    """
    require(0 < interval <= 1 and 0 < timeout <= 300, "invalid build supervision limits")
    guard.check()
    start = clock()
    process = launch()
    failure = None
    try:
        while True:
            guard.check()
            remaining = timeout - (clock() - start)
            require(remaining > 0, "build deadline exceeded")
            result = process.wait(min(interval, remaining))
            if result is not None:
                require(clock() - start <= timeout, "build deadline exceeded")
                require(result == 0, "Go build failed with exit code " + str(result))
                guard.check()
                break
    except BaseException as exc:
        failure = exc
    try:
        process.cleanup()
    except BaseException as exc:
        if failure is not None:
            raise ResourceError(f"{failure}; cleanup: {exc}") from failure
        raise
    if failure is not None:
        raise failure


def build_pair(guard: DomainGuard, source: Path, go: Path, arch: str) -> tuple[Path, Path]:
    """Build bootstrap and node with one domain/cache; no namespace creation.

    This implementation is not wired into the public entry until Linux
    acceptance, descendant cleanup validation and evidence binding are done.
    """
    require(arch in {"amd64", "arm64"}, "unsupported Go build architecture")
    check_build_inputs(guard, source, go)
    env_arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
    require(env_arch is not None, "unsupported bootstrap architecture")
    stage = guard.config.root / "build" / "go-stage"
    guard.check()
    stage.mkdir(mode=0o700)  # Exclusive; no implicit reuse or removal.
    for name in ("home", "cache", "modules", "gopath", "tmp"):
        guard.check()
        (stage / name).mkdir(mode=0o700)
    outputs = []
    for name, target in (("bootstrap", env_arch), ("node", arch)):
        env = build_environment(stage, go, target)
        output = stage / name
        argv = [str(go), "-C", str(source / "tools/t0"), "build", "-mod=readonly",
                "-buildvcs=false", "-trimpath", "-o", str(output), "./cmd/sw-v0-harness"]
        guard.check()
        with (stage / (name + ".log")).open("xb") as log:
            supervise_build(guard, lambda: BuildProcess(argv, env, stage, log))
            log.flush()
            os.fsync(log.fileno())
        guard.check()
        require(output.is_file() and not output.is_symlink() and output.stat().st_size > 0,
                "missing build output: " + name)
        outputs.append(output)
    return tuple(outputs)
