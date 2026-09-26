package synthetic

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func TestStoreCorruptionAndRecoveryContext(t *testing.T) {
	n, _ := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 1)
	path := filepath.Join(n.storage.directory, "state.json")
	original, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	for name, data := range map[string][]byte{
		"empty": {}, "truncated": original[:len(original)/2],
		"unknown-version": bytes.Replace(original, []byte(`"store_version":1`), []byte(`"store_version":9`), 1),
		"checksum":        bytes.Replace(original, []byte(`"generation":1`), []byte(`"generation":0`), 1),
		"unknown-field":   append([]byte(`{"extra":0,`), original[1:]...),
		"duplicate":       append([]byte(`{"store_version":1,`), original[1:]...),
	} {
		t.Run(name, func(t *testing.T) {
			if err := os.WriteFile(path, data, 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 10, 1}); err == nil {
				t.Fatal("invalid store accepted")
			}
		})
	}
	if err := os.WriteFile(path, original, 0600); err != nil {
		t.Fatal(err)
	}
	for _, r := range []Recovery{{"", 10, 1}, {strings.Repeat("a", 32), 10, 1}, {testEpoch, -1, 1}, {testEpoch, 10, 2}, {testEpoch, 100001, 1}} {
		if _, err := OpenNode(n.storage.directory, n.config, r); err == nil {
			t.Fatal("unsafe recovery accepted")
		}
	}
	next := filepath.Join(n.storage.directory, "state.next")
	if err := os.WriteFile(next, []byte("partial"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 10, 1}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(next); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("abandoned next retained")
	}
	if err := os.WriteFile(next, original, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 10, 1}); err == nil {
		t.Fatal("orphan next promoted")
	}
	if _, err := os.Stat(next); err != nil {
		t.Fatal("orphan evidence removed")
	}
}

type shortStateFile struct{ syncedFile }

func (f shortStateFile) Write(p []byte) (int, error) {
	n, err := f.syncedFile.Write(p[:len(p)/2])
	return n, err
}
func TestStoreIOFailures(t *testing.T) {
	for _, stage := range []string{"before_create", "before_write", "short_write", "file_sync", "file_close", "rename", "after_rename", "directory_sync", "directory_close", "committed"} {
		t.Run(stage, func(t *testing.T) {
			n, _ := testNode(t, "A")
			before := n.Generation()
			injected := error(syscall.ENOSPC)
			if stage == "before_create" {
				injected = syscall.EROFS
			}
			ops := realOps()
			if stage == "short_write" {
				base := ops.create
				ops.create = func(p string) (syncedFile, error) {
					f, e := base(p)
					if e != nil {
						return nil, e
					}
					return shortStateFile{f}, nil
				}
				injected = io.ErrShortWrite
			} else {
				ops.hook = func(at string) error {
					if at == stage {
						return injected
					}
					return nil
				}
			}
			n.storage.ops = ops
			_, err := n.Submit("one", testID, []byte{'x'}, 0, 30000)
			unknown := stage == "rename" || stage == "after_rename" || stage == "directory_sync" || stage == "directory_close" || stage == "committed"
			want := "STORE_NOT_COMMITTED"
			if unknown {
				want = "STORE_OUTCOME_UNKNOWN"
			}
			if Code(err) != want || !errors.Is(err, injected) || n.Generation() != before {
				t.Fatalf("stage=%s err=%v generation=%d", stage, err, n.Generation())
			}
			if _, err := n.Submit("two", "44444444444444444444444444444444", []byte{'x'}, 1, 30000); Code(err) != "STORE_OUTCOME_UNKNOWN" {
				t.Fatal("failed store continued")
			}
			if _, err := n.Query("one"); Code(err) != "STORE_OUTCOME_UNKNOWN" {
				t.Fatal("uncertain state displayed")
			}
			reopened, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 1, 0})
			if err != nil {
				t.Fatal(err)
			}
			newState := stage == "after_rename" || stage == "directory_sync" || stage == "directory_close" || stage == "committed"
			wantGeneration := int64(0)
			if newState {
				wantGeneration = 1
			}
			if reopened.Generation() != wantGeneration {
				t.Fatal("partial generation")
			}
		})
	}
}
func TestStoreRejectsLinksAndWrongInitialization(t *testing.T) {
	n, _ := testNode(t, "A")
	if _, err := InitNode(n.storage.directory, n.config); err == nil {
		t.Fatal("existing store overwritten")
	}
	target := filepath.Join(t.TempDir(), "target")
	if err := os.WriteFile(target, []byte("untouched"), 0600); err != nil {
		t.Fatal(err)
	}
	next := filepath.Join(n.storage.directory, "state.next")
	if err := os.Symlink(target, next); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 0, 0}); err == nil {
		t.Fatal("symlink accepted")
	}
	b, err := os.ReadFile(target)
	if err != nil || string(b) != "untouched" {
		t.Fatal("symlink target changed")
	}
}
