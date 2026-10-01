package main

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func assertResourceStop(t *testing.T, err error) {
	t.Helper()
	var classified *networkExit
	if !errors.Is(err, errNetworkResourceIsolation) || !errors.As(err, &classified) || classified.code != 2 {
		t.Fatalf("expected resource isolation INVALID, got %v", err)
	}
}

func TestNetworkEntrypointsStopBeforeEnvironmentAccess(t *testing.T) {
	root := filepath.Join(t.TempDir(), "absent-repository")
	for _, args := range [][]string{
		{"synthetic-run", "--repo-root", root, "--preflight"},
		{"synthetic-run", "--repo-root", root, "--matrix", "i5-seven-v1", "--repeats", "3"},
	} {
		assertResourceStop(t, run(args))
	}
	r := &preflightRunner{}
	assertResourceStop(t, runNetworkMatrix(context.Background(), r, root))
	if len(r.calls) != 0 {
		t.Fatalf("resource stop ran external commands: %v", r.calls)
	}
	if _, err := os.Stat(root); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("resource stop created repository: %v", err)
	}
}

func TestI5ShellStopsBeforeBootstrap(t *testing.T) {
	// The copied real entrypoint runs in an empty repository with an empty PATH.
	// Only shell builtins can run; no git, Python, Go or Docker is available.
	bash, err := exec.LookPath("bash")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../../../scripts/run-sw-i5-harness.sh")
	if err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"preflight"}, {"run", "--matrix", "i5-seven-v1", "--repeats", "3"}} {
		t.Run(args[0], func(t *testing.T) {
			root := t.TempDir()
			script := filepath.Join(root, "run-sw-i5-harness.sh")
			if err := os.WriteFile(script, raw, 0700); err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(context.Background(), operationTimeout)
			defer cancel()
			cmd := exec.CommandContext(ctx, bash, append([]string{script}, args...)...)
			cmd.Dir = root
			cmd.Env = []string{"PATH=" + filepath.Join(root, "no-tools")}
			out, err := cmd.CombinedOutput()
			var exit *exec.ExitError
			if !errors.As(err, &exit) || exit.ExitCode() != 2 || strings.TrimSpace(string(out)) != errNetworkResourceIsolation.Error() {
				t.Fatalf("shell did not stop before bootstrap: %v %s", err, out)
			}
			entries, err := os.ReadDir(root)
			if err != nil || len(entries) != 1 || entries[0].Name() != filepath.Base(script) {
				t.Fatalf("shell created bootstrap/cache/artifacts: %v %v", entries, err)
			}
		})
	}
}
