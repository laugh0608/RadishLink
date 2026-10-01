package synthetic

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"strconv"
	"testing"
	"time"
)

func prepareTransaction(t *testing.T, kind string) (*Node, testOracle) {
	t.Helper()
	node := "A"
	if kind == "T-B" || kind == "T-D-B" {
		node = "B"
	}
	if kind == "T-C" {
		node = "C"
	}
	n, o := testNode(t, node)
	if kind == "T-D-A" || kind == "retry" {
		mustSubmit(t, n, "one", testID, 1)
	}
	if kind == "retry" {
		mustStep(t, n, Batch{Now: 1})
	}
	if kind == "T-D-B" {
		mustStep(t, n, Batch{Now: 1, Inputs: []Input{permit(t, o, n, "A", fixtureData(1))}})
	}
	return n, o
}
func executeTransaction(t *testing.T, n *Node, o testOracle, kind string) ([]*Transmission, error) {
	t.Helper()
	if kind == "T-A" {
		_, err := n.Submit("one", testID, []byte{'x'}, 0, 30000)
		return nil, err
	}
	if kind == "retry" {
		return n.Step(Batch{Now: 250})
	}
	e := fixtureData(1)
	from, now := "A", int64(1)
	if kind == "T-C" {
		e.RemainingHops = 0
		from = "B"
	}
	if kind == "T-D-A" || kind == "T-D-B" {
		m := n.storage.current.Messages[0]
		e = m.envelope("delivery", 0)
		from = "B"
		if kind == "T-D-B" {
			from, now = "C", 2
		}
	}
	return n.Step(Batch{Now: now, Inputs: []Input{permit(t, o, n, from, e)}})
}

func TestTransactionIOAtomicity(t *testing.T) {
	for _, kind := range []string{"T-A", "T-B", "T-C", "T-D-A", "T-D-B", "retry"} {
		for _, stage := range []string{"before_create", "before_write", "short_write", "file_sync", "file_close", "rename", "after_rename", "directory_sync", "directory_close", "committed"} {
			t.Run(kind+"/"+stage, func(t *testing.T) {
				n, o := prepareTransaction(t, kind)
				old, err := encodeState(n.storage.current)
				if err != nil {
					t.Fatal(err)
				}
				var injected error = errors.New("transaction fault")
				if stage == "short_write" {
					base := n.storage.ops.create
					n.storage.ops.create = func(p string) (syncedFile, error) {
						f, err := base(p)
						if err != nil {
							return nil, err
						}
						return shortStateFile{f}, nil
					}
					injected = io.ErrShortWrite
				}
				n.storage.ops.hook = func(at string) error {
					if at == stage {
						return injected
					}
					return nil
				}
				out, err := executeTransaction(t, n, o, kind)
				if !errors.Is(err, injected) || len(out) != 0 {
					t.Fatalf("side effect before commit: %v", err)
				}
				retained, _ := encodeState(n.storage.current)
				if string(old) != string(retained) {
					t.Fatal("failed transaction published candidate")
				}
				restored, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 250, n.Generation()})
				if err != nil {
					t.Fatal(err)
				}
				wantNew := stage == "after_rename" || stage == "directory_sync" || stage == "directory_close" || stage == "committed"
				if wantNew {
					if restored.Generation() != n.Generation()+1 {
						t.Fatal("new state incomplete")
					}
				} else {
					got, _ := encodeState(restored.storage.current)
					if string(got) != string(old) {
						t.Fatal("old state changed")
					}
				}
			})
		}
	}
}

type crashFile struct{ syncedFile }

func (f crashFile) Write(p []byte) (int, error) {
	if _, err := f.syncedFile.Write(p[:len(p)/2]); err != nil {
		return 0, err
	}
	os.Exit(73)
	return 0, nil
}

func TestStoreCrashHelper(t *testing.T) {
	if os.Getenv("RADISHLINK_I3_CHILD") != "bounded-crash-test" {
		return
	}
	kind, stage := os.Getenv("RADISHLINK_I3_TRANSACTION"), os.Getenv("RADISHLINK_I3_STAGE")
	g, err := strconv.ParseInt(os.Getenv("RADISHLINK_I3_GENERATION"), 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	now, err := strconv.ParseInt(os.Getenv("RADISHLINK_I3_NOW"), 10, 64)
	if err != nil {
		t.Fatal(err)
	}
	oracle := testOracle{}
	cfg := testConfig(os.Getenv("RADISHLINK_I3_NODE"), oracle)
	n, err := OpenNode(os.Getenv("RADISHLINK_I3_DIRECTORY"), cfg, Recovery{testEpoch, now, g})
	if err != nil {
		t.Fatal(err)
	}
	if stage == "partial_write" {
		base := n.storage.ops.create
		n.storage.ops.create = func(p string) (syncedFile, error) {
			f, e := base(p)
			if e != nil {
				return nil, e
			}
			return crashFile{f}, nil
		}
	} else {
		n.storage.ops.hook = func(at string) error {
			if at == stage {
				os.Exit(73)
			}
			return nil
		}
	}
	if _, err := executeTransaction(t, n, oracle, kind); err != nil {
		t.Fatal(err)
	}
	t.Fatal("crash point not reached")
}
func TestTransactionsSurviveProcessExit(t *testing.T) {
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"T-A", "T-B", "T-C", "T-D-A", "T-D-B", "retry"} {
		for _, stage := range []string{"before_create", "partial_write", "file_sync", "file_close", "rename", "after_rename", "directory_sync", "committed"} {
			t.Run(kind+"/"+stage, func(t *testing.T) {
				n, _ := prepareTransaction(t, kind)
				before := n.storage.current.clone()
				old, _ := encodeState(before)
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				defer cancel()
				cmd := exec.CommandContext(ctx, executable, "-test.run=^TestStoreCrashHelper$", "-test.timeout=4s")
				cmd.Env = append(os.Environ(), "RADISHLINK_I3_CHILD=bounded-crash-test", "RADISHLINK_I3_TRANSACTION="+kind, "RADISHLINK_I3_STAGE="+stage, "RADISHLINK_I3_NODE="+n.config.Node, "RADISHLINK_I3_DIRECTORY="+n.storage.directory, "RADISHLINK_I3_GENERATION="+strconv.FormatInt(before.Generation, 10), "RADISHLINK_I3_NOW="+strconv.FormatInt(before.Now, 10))
				output, err := cmd.CombinedOutput()
				var exitErr *exec.ExitError
				if ctx.Err() != nil || !errors.As(err, &exitErr) || exitErr.ExitCode() != 73 {
					t.Fatalf("child exit: %v / %s", err, output)
				}
				restored, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 250, before.Generation})
				if err != nil {
					t.Fatal(err)
				}
				wantNew := stage == "after_rename" || stage == "directory_sync" || stage == "committed"
				if !wantNew {
					got, _ := encodeState(restored.storage.current)
					if string(got) != string(old) {
						t.Fatal("partial old state")
					}
					return
				}
				if restored.Generation() != before.Generation+1 {
					t.Fatal("incomplete committed generation")
				}
				if kind == "retry" {
					q := restored.storage.current.Queues[0]
					if len(q.Batches) != 2 {
						t.Fatal("consumed retry not restored")
					}
					if out := mustStep(t, restored, Batch{Now: 251}); len(out) != 0 {
						t.Fatal("replayed committed Send")
					}
				}
				if kind == "T-C" {
					if restored.storage.current.ReceiveSteps != 1 || len(restored.storage.current.Messages) != 1 {
						t.Fatal("partial destination commit")
					}
				}
				if kind == "T-D-B" {
					m := restored.storage.current.Messages[0]
					if m.Body != "" || restored.storage.current.findQueue(m.Key, "delivery").Status != "active" {
						t.Fatal("return responsibility lost")
					}
				}
			})
		}
	}
}
