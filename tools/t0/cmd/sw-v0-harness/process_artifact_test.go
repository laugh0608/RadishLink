package main

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"radishlink.local/t0/internal/harness"
)

func outputBudget(t *testing.T, limit int64, check func() error) *harness.NetworkWriteBudget {
	t.Helper()
	b, err := harness.NewNetworkWriteBudget(limit, check)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestNetworkBundleReservesAllFilesBeforeCreatingDirectory(t *testing.T) {
	fixture := memoryBundle(t, "SW-V1-BASE-001", "p1", 1)
	root := t.TempDir()
	baseline := filepath.Join(root, "baseline")
	if err := harness.WriteNetworkBundle(baseline, fixture); err != nil {
		t.Fatal(err)
	}
	size, err := pathBytes(baseline)
	if err != nil {
		t.Fatal(err)
	}
	checks := 0
	budget := outputBudget(t, 2*size, func() error { checks++; return nil })
	for _, name := range []string{"first", "second"} {
		dest := filepath.Join(root, name)
		if err := harness.WriteNetworkBundleBudgeted(dest, fixture, budget); err != nil {
			t.Fatal(err)
		}
		if err := harness.VerifyEvidence(dest); err != nil {
			t.Fatal(err)
		}
		entries, err := os.ReadDir(baseline)
		if err != nil {
			t.Fatal(err)
		}
		for _, entry := range entries {
			if entry.IsDir() {
				continue
			}
			want, wantErr := os.ReadFile(filepath.Join(baseline, entry.Name()))
			got, gotErr := os.ReadFile(filepath.Join(dest, entry.Name()))
			if wantErr != nil || gotErr != nil || string(got) != string(want) {
				t.Fatalf("budget changed schema 3 bytes: %s %v %v", entry.Name(), wantErr, gotErr)
			}
		}
	}
	// Eight evidence files plus checksum, and one initial reservation per bundle.
	if checks != 20 || budget.Charged() != 2*size {
		t.Fatalf("not all output/checksum bytes or write checks accounted: %d/%d", budget.Charged(), checks)
	}
	for name, b := range map[string]*harness.NetworkWriteBudget{
		"exhausted":      budget,
		"one-byte-short": outputBudget(t, size-1, func() error { return nil }),
		"missing-budget": nil,
	} {
		dest := filepath.Join(root, name)
		if err := harness.WriteNetworkBundleBudgeted(dest, fixture, b); err == nil {
			t.Fatal("unbudgeted output accepted", name)
		}
		if _, err := os.Stat(dest); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("rejected reservation created directory", name, err)
		}
	}
}

func TestNetworkBundleSpaceFailureRetainsPartialEvidenceAndCharge(t *testing.T) {
	fixture := memoryBundle(t, "SW-V1-BASE-001", "p1", 1)
	cause := errors.New("fixture disk pressure")
	checks := 0
	budget := outputBudget(t, 32<<20, func() error {
		checks++
		if checks == 3 {
			return cause
		}
		return nil
	})
	root := filepath.Join(t.TempDir(), "partial")
	if err := harness.WriteNetworkBundleBudgeted(root, fixture, budget); !errors.Is(err, cause) {
		t.Fatal("lost space error", err)
	}
	if budget.Charged() == 0 || budget.Check() == nil {
		t.Fatal("failed output refunded/resumed")
	}
	if _, err := os.Stat(filepath.Join(root, "assertions.json")); err != nil {
		t.Fatal("first file not retained", err)
	}
	if _, err := os.Stat(filepath.Join(root, "checksums.sha256")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("failed partial bundle was finalized", err)
	}
	// An independent, preallocated diagnostic budget survives ordinary failure.
	diagnostic := outputBudget(t, 64, func() error { return nil })
	if err := writeNewJSON(filepath.Join(root, "failure.json"), "fixture failure", diagnostic, 64); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, "assertions.json")); err != nil {
		t.Fatal("diagnostic write discarded partial evidence", err)
	}
}

func TestCleanupFailureCanRetainDiagnosticAfterEvidenceBudgetStops(t *testing.T) {
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	r := newMemoryRunner(t)
	s := newProcessSample(context.Background(), r, p, "p1", "batch", "sample", strings.Repeat("2", 32), "image")
	if err := s.prepare(); err != nil {
		t.Fatal(err)
	}
	r.failRemove = true
	residuals, cleanupErr := s.cleanup()
	if cleanupErr == nil || residuals.Clean {
		t.Fatal("cleanup fixture did not fail")
	}
	ordinary := outputBudget(t, 1, func() error { return nil })
	if ordinary.Reserve(2) == nil {
		t.Fatal("ordinary quota fixture did not stop")
	}
	diagnostic := outputBudget(t, 32<<20, func() error { return nil })
	path := filepath.Join(t.TempDir(), "incomplete.json")
	v := struct {
		Error     string
		Residuals harness.NetworkResiduals
	}{cleanupErr.Error(), residuals}
	if err := writeNewJSON(path, v, diagnostic, 32<<20); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil || !strings.Contains(string(raw), "cleanup_failed") || len(r.objects) == 0 {
		t.Fatalf("failed cleanup evidence/residual inventory lost: %v %s", err, raw)
	}
}

type failingArtifact struct {
	short                  bool
	writeErr, syncErr, end error
	synced, closed         bool
}

func (f *failingArtifact) Write(p []byte) (int, error) {
	if f.short || f.writeErr != nil {
		return len(p) - 1, f.writeErr
	}
	return len(p), nil
}
func (f *failingArtifact) Sync() error  { f.synced = true; return f.syncErr }
func (f *failingArtifact) Close() error { f.closed = true; return f.end }

func TestArtifactWriteFailuresKeepReservationAndCauses(t *testing.T) {
	cause := errors.New("fixture I/O failure")
	for _, stage := range []string{"create", "short", "write", "sync", "close"} {
		t.Run(stage, func(t *testing.T) {
			budget := outputBudget(t, 4, func() error { return nil })
			f := &failingArtifact{}
			want := cause
			switch stage {
			case "short":
				f.short, f.end = true, cause
				want = io.ErrShortWrite
			case "write":
				f.writeErr = cause
			case "sync":
				f.syncErr = cause
			case "close":
				f.end = cause
			}
			err := writeNewJSONWithCreate("fixture.json", "x", budget, 4, func(string) (artifactFile, error) {
				if budget.Charged() != 4 {
					t.Fatal("create before reservation")
				}
				if stage == "create" {
					return nil, cause
				}
				return f, nil
			})
			if !errors.Is(err, want) || budget.Charged() != 4 || (stage != "create" && !f.closed) {
				t.Fatalf("failure lost/refunded: %v %+v", err, f)
			}
			if stage == "short" && (!errors.Is(err, cause) || f.synced) {
				t.Fatal("short write lost close error or synced incomplete file")
			}
		})
	}
}

func TestArtifactIncludesLFAndRefusesBeforeCreate(t *testing.T) {
	root := t.TempDir()
	budget := outputBudget(t, 4, func() error { return nil })
	path := filepath.Join(root, "exact.json")
	if err := writeNewJSON(path, "x", budget, 4); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil || string(raw) != "\"x\"\n" || budget.Charged() != 4 {
		t.Fatal("exact LF boundary", err, string(raw))
	}
	for _, mode := range []string{"file-cap", "budget-cap", "space", "encode", "no-budget"} {
		t.Run(mode, func(t *testing.T) {
			limit := 4
			var value any = "x"
			b := outputBudget(t, 4, func() error { return nil })
			switch mode {
			case "file-cap":
				limit = 3
			case "budget-cap":
				b = outputBudget(t, 3, func() error { return nil })
			case "space":
				b = outputBudget(t, 4, func() error { return errors.New("fixture space failure") })
			case "encode":
				value = make(chan int)
			case "no-budget":
				b = nil
			}
			err := writeNewJSONWithCreate("never.json", value, b, limit, func(string) (artifactFile, error) {
				t.Fatal("rejected write created file")
				return nil, nil
			})
			if err == nil || (b != nil && b.Charged() != 0) {
				t.Fatal("rejected write charged/accepted", err)
			}
		})
	}
}

type diskRunner struct {
	raw string
	err error
}

func (r diskRunner) Start(context.Context, string, ...string) (controlPeer, error) {
	panic("disk checker must not start a process")
}
func (r diskRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	if name != "df" || len(args) != 2 || args[0] != "-Pk" {
		return nil, errors.New("unexpected disk check command")
	}
	return []byte(r.raw), r.err
}

func TestHostDiskRejectsMissingMalformedAndLowInventory(t *testing.T) {
	const header = "Filesystem 1024-blocks Used Available Capacity Mounted\n"
	const row = "fixture 2000000 100 1048576 1% /fixture\n"
	if err := checkHostDisk(context.Background(), diskRunner{raw: header + row}, "/fixture"); err != nil {
		t.Fatal("exact 1 GiB boundary", err)
	}
	for _, raw := range []string{"", header, header + "fixture 1 2\n", header + row + row, header + strings.Replace(row, "1048576", "1048575", 1), header + strings.Replace(row, "1048576", "NaN", 1), header + strings.Replace(row, "1048576", "9223372036854775808", 1)} {
		if err := checkHostDisk(context.Background(), diskRunner{raw: raw}, "/fixture"); err == nil {
			t.Fatal("invalid disk inventory accepted", raw)
		}
	}
	cause := errors.New("fixture df failure")
	if err := checkHostDisk(context.Background(), diskRunner{err: cause}, "/fixture"); !errors.Is(err, cause) {
		t.Fatal("lost disk command cause", err)
	}
}

func TestNetworkRejectsUnbudgetedContainerTemporaryStorage(t *testing.T) {
	for name, mutate := range map[string]func(*dockerInspect){
		"default-shm":     func(v *dockerInspect) { v.HostConfig.IpcMode = "private" },
		"missing-tmpfs":   func(v *dockerInspect) { v.HostConfig.Tmpfs = nil },
		"oversized-tmpfs": func(v *dockerInspect) { v.HostConfig.Tmpfs = map[string]string{"/tmp": "rw,noexec,nosuid,size=32m"} },
		"extra-tmpfs": func(v *dockerInspect) {
			v.HostConfig.Tmpfs = map[string]string{"/tmp": "rw,noexec,nosuid,size=16m", "/extra": "size=16m"}
		},
	} {
		t.Run(name, func(t *testing.T) {
			p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
			r := newMemoryRunner(t)
			r.inspectMutation = mutate
			s := newProcessSample(context.Background(), r, p, "p1", "batch", "sample", strings.Repeat("2", 32), "image")
			err := s.prepare()
			_, cleanupErr := s.cleanup()
			if err == nil || !strings.Contains(err.Error(), "container temporary storage mismatch") || cleanupErr != nil {
				t.Fatalf("unbudgeted tmp storage accepted or cleanup lost: %v / %v", err, cleanupErr)
			}
		})
	}
}
