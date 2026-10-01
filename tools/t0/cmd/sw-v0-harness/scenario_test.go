package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"radishlink.local/t0/internal/harness"
)

func scenarioTestMetadata(t *testing.T, repeat int) harness.ScenarioManifest {
	t.Helper()
	repo, err := filepath.Abs("../../../..")
	if err != nil {
		t.Fatal(err)
	}
	gitDir := filepath.Join(repo, ".git")
	info, err := os.Stat(gitDir)
	if err != nil {
		t.Fatal(err)
	}
	if !info.IsDir() {
		raw, err := os.ReadFile(gitDir)
		if err != nil {
			t.Fatal(err)
		}
		gitDir = strings.TrimSpace(strings.TrimPrefix(string(raw), "gitdir: "))
		if !filepath.IsAbs(gitDir) {
			gitDir = filepath.Join(repo, gitDir)
		}
	}
	head, err := os.ReadFile(filepath.Join(gitDir, "HEAD"))
	if err != nil {
		t.Fatal(err)
	}
	revision := strings.TrimSpace(string(head))
	if strings.HasPrefix(revision, "ref: ") {
		ref := strings.TrimPrefix(revision, "ref: ")
		raw, err := os.ReadFile(filepath.Join(gitDir, ref))
		if err != nil {
			common, readErr := os.ReadFile(filepath.Join(gitDir, "commondir"))
			if readErr != nil {
				t.Fatal(err)
			}
			raw, err = os.ReadFile(filepath.Join(gitDir, strings.TrimSpace(string(common)), ref))
			if err != nil {
				t.Fatal(err)
			}
		}
		revision = strings.TrimSpace(string(raw))
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	f, err := os.Open(executable)
	if err != nil {
		t.Fatal(err)
	}
	h := sha256.New()
	_, readErr := io.Copy(h, f)
	closeErr := f.Close()
	if readErr != nil || closeErr != nil {
		t.Fatalf("binary hash: %v %v", readErr, closeErr)
	}
	return harness.ScenarioManifest{Batch: "i4-test", Run: fmt.Sprintf("repeat-%d", repeat), Repeat: int64(repeat), GitRevision: revision, Dirty: true, Binary: hex.EncodeToString(h.Sum(nil)), GoVersion: runtime.Version(), OS: runtime.GOOS, Arch: runtime.GOARCH, Started: time.Now().UTC().Format(time.RFC3339Nano)}
}
func executeScenarioTest(t *testing.T, p harness.ScenarioProfile, sub string, repeat int) harness.ScenarioBundle {
	t.Helper()
	meta := scenarioTestMetadata(t, repeat)
	meta.Evidence = fmt.Sprintf("%s/%s/%s/%d", meta.Batch, p.ID, sub, repeat)
	b, err := runScenario(t.TempDir(), p, sub, meta)
	if err != nil {
		t.Fatal(err)
	}
	b.Manifest.Ended = time.Now().UTC().Format(time.RFC3339Nano)
	return b
}
func TestScenarioRepeatedEvidence(t *testing.T) {
	names := []string{"base", "loss-evidence", "loss-evidence-ba", "down-bc", "down-ab"}
	for _, name := range names {
		p, _, err := harness.LoadScenarioProfile("../../profiles/i4", "sw-v1-"+name+"-001.json")
		if err != nil {
			t.Fatal(err)
		}
		for _, sub := range p.Subcases {
			t.Run(name+"/"+sub.ID, func(t *testing.T) {
				root := t.TempDir()
				for repeat := 1; repeat <= 3; repeat++ {
					b := executeScenarioTest(t, p, sub.ID, repeat)
					m, _, result, err := harness.AssessScenario(p, sub.ID, b.Events, b.Residuals)
					if err != nil || result != "PASS" {
						t.Fatalf("assessment %s: %v metrics=%+v", result, err, m)
					}
					path := filepath.Join(root, fmt.Sprint(repeat))
					if err := harness.WriteScenarioBundle(path, b); err != nil {
						t.Fatal(err)
					}
					if err := harness.VerifyEvidence(path); err != nil {
						t.Fatal(err)
					}
				}
				if _, err := harness.CompareEvidenceRuns(root); err != nil {
					t.Fatal(err)
				}
			})
		}
	}
}
func copyEvents(t *testing.T, events []harness.ScenarioEvent) []harness.ScenarioEvent {
	t.Helper()
	raw, err := json.Marshal(events)
	if err != nil {
		t.Fatal(err)
	}
	var out []harness.ScenarioEvent
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return out
}
func setDetail(t *testing.T, e *harness.ScenarioEvent, v any) {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	e.Detail = raw
}
func TestScenarioRejectsInconsistentFacts(t *testing.T) {
	p, err := harness.CanonicalScenario("SW-V1-BASE-001")
	if err != nil {
		t.Fatal(err)
	}
	b := executeScenarioTest(t, p, "p1024", 1)
	for _, change := range []string{"send-source", "budget", "generation", "release", "counter", "missing-commit", "missing-send", "verdict", "metrics", "transaction-kind", "queue-status", "hop"} {
		t.Run(change, func(t *testing.T) {
			events := copyEvents(t, b.Events)
			changed := false
			for i := range events {
				e := &events[i]
				switch {
				case change == "transaction-kind" && e.Kind == "submit_result":
					var d harness.OperationDetail
					if err := json.Unmarshal(e.Detail, &d); err != nil {
						t.Fatal(err)
					}
					d.Transactions = []string{"T-C"}
					setDetail(t, e, d)
					changed = true
				case (change == "queue-status" || change == "hop") && e.Kind == "state_observed":
					var d harness.ObservedState
					if err := json.Unmarshal(e.Detail, &d); err != nil {
						t.Fatal(err)
					}
					if len(d.Queues) > 0 {
						if change == "hop" {
							d.Queues[0].Hops = 2
						} else {
							d.Queues[0].Status = "unknown"
						}
						setDetail(t, e, d)
						changed = true
					}
				case change == "send-source" && e.Kind == "frame_received":
					var f harness.FrameDetail
					json.Unmarshal(e.Detail, &f)
					f.SendSequence = 1
					setDetail(t, e, f)
					changed = true
				case change == "budget" && e.Kind == "retry_decision":
					var r harness.ObservedRetry
					json.Unmarshal(e.Detail, &r)
					r.TimedAfter++
					setDetail(t, e, r)
					changed = true
				case change == "generation" && e.Kind == "batch_result":
					e.After++
					changed = true
				case change == "release" && e.Kind == "state_observed" && e.Node == "B":
					var s harness.ObservedState
					json.Unmarshal(e.Detail, &s)
					if len(s.Messages) > 0 && s.Messages[0].BodyBytes > 0 {
						s.Messages[0].BodyBytes = 0
						setDetail(t, e, s)
						changed = true
					}
				case change == "counter" && e.Kind == "state_observed" && e.Node == "C":
					var s harness.ObservedState
					json.Unmarshal(e.Detail, &s)
					if len(s.Messages) > 0 {
						s.ReceiveSteps = 0
						setDetail(t, e, s)
						changed = true
					}
				case change == "missing-commit" && e.Kind == "batch_result", change == "missing-send" && e.Kind == "frame_written":
					events = append(events[:i], events[i+1:]...)
					changed = true
				case change == "verdict" && e.Kind == "verdict_decision":
					var v harness.VerdictDetail
					json.Unmarshal(e.Detail, &v)
					v.Purpose = "wrong-purpose"
					setDetail(t, e, v)
					changed = true
				}
				if changed {
					break
				}
			}
			if change == "metrics" {
				root := filepath.Join(t.TempDir(), "bundle")
				if err := harness.WriteScenarioBundle(root, b); err != nil {
					t.Fatal(err)
				}
				path := filepath.Join(root, "metrics.json")
				raw, err := os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				raw = bytes.Replace(raw, []byte(`"destination_commits":1`), []byte(`"destination_commits":2`), 1)
				if err := os.WriteFile(path, raw, 0600); err != nil {
					t.Fatal(err)
				}
				if err := harness.FinalizeEvidence(root); err == nil {
					t.Fatal("forged metric accepted after rechecksum")
				}
				return
			}
			if !changed {
				t.Fatal("mutation missed")
			}
			_, _, result, err := harness.AssessScenario(p, "p1024", events, b.Residuals)
			if err == nil && result == "PASS" {
				t.Fatal("inconsistent facts accepted")
			}
		})
	}
}

// Rehash all files as an attacker could. This must not repair semantic forgeries.
func rehashScenarioTest(t *testing.T, root string) {
	t.Helper()
	files := []string{"assertions.json", "events.ndjson", "manifest.json", "metrics.json", "profile.json", "residuals.json", "topology.json"}
	var checks strings.Builder
	for _, name := range files {
		raw, err := os.ReadFile(filepath.Join(root, name))
		if err != nil {
			t.Fatal(err)
		}
		fmt.Fprintf(&checks, "%s  %s\n", scenarioHash(raw), name)
	}
	if err := os.WriteFile(filepath.Join(root, "checksums.sha256"), []byte(checks.String()), 0600); err != nil {
		t.Fatal(err)
	}
}
func TestScenarioCompleteFailureAndInvalidBundles(t *testing.T) {
	p, err := harness.CanonicalScenario("SW-V1-BASE-001")
	if err != nil {
		t.Fatal(err)
	}
	base := executeScenarioTest(t, p, "p1", 1)
	for _, outcome := range []string{"FAIL", "INVALID"} {
		t.Run(outcome, func(t *testing.T) {
			b := base
			b.Events = copyEvents(t, base.Events)
			for i := range b.Events {
				e := &b.Events[i]
				if outcome == "INVALID" && e.Kind == "environment_check" {
					var d harness.EnvironmentDetail
					if err := json.Unmarshal(e.Detail, &d); err != nil {
						t.Fatal(err)
					}
					d.Passed = false
					d.Reason = "injected_self_check_failure"
					setDetail(t, e, d)
					break
				}
				if outcome == "FAIL" && e.Kind == "state_observed" && e.Node == "C" {
					var s harness.ObservedState
					if err := json.Unmarshal(e.Detail, &s); err != nil {
						t.Fatal(err)
					}
					if len(s.Messages) > 0 {
						s.ReceiveSteps = 2
						setDetail(t, e, s)
					}
				}
			}
			_, a, result, err := harness.AssessScenario(p, "p1", b.Events, b.Residuals)
			if err != nil || result != outcome {
				t.Fatalf("wanted %s got %s %v %+v", outcome, result, err, a)
			}
			root := filepath.Join(t.TempDir(), "bundle")
			if err := harness.WriteScenarioBundle(root, b); err != nil {
				t.Fatal(err)
			}
			if err := harness.VerifyEvidence(root); err != nil {
				t.Fatal(err)
			}
			raw, err := os.ReadFile(filepath.Join(root, "manifest.json"))
			if err != nil {
				t.Fatal(err)
			}
			var m harness.ScenarioManifest
			if err := json.Unmarshal(raw, &m); err != nil {
				t.Fatal(err)
			}
			if m.Result != outcome {
				t.Fatal("failed result hidden")
			}
		})
	}
}
func TestScenarioRehashCannotForgeFacts(t *testing.T) {
	p, err := harness.CanonicalScenario("SW-V1-BASE-001")
	if err != nil {
		t.Fatal(err)
	}
	b := executeScenarioTest(t, p, "p1", 1)
	for _, kind := range []string{"metrics", "events", "assertions"} {
		t.Run(kind, func(t *testing.T) {
			root := filepath.Join(t.TempDir(), "bundle")
			if err := harness.WriteScenarioBundle(root, b); err != nil {
				t.Fatal(err)
			}
			name := kind + ".json"
			if kind == "events" {
				name = "events.ndjson"
			}
			path := filepath.Join(root, name)
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "metrics":
				raw = bytes.Replace(raw, []byte(`"destination_commits":1`), []byte(`"destination_commits":2`), 1)
			case "assertions":
				raw = bytes.Replace(raw, []byte(`"passed":true`), []byte(`"passed":false`), 1)
			case "events":
				raw = bytes.Replace(raw, []byte(`"timed_after":1`), []byte(`"timed_after":2`), 1)
			}
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			if kind == "events" {
				mp := filepath.Join(root, "manifest.json")
				mr, err := os.ReadFile(mp)
				if err != nil {
					t.Fatal(err)
				}
				var m harness.ScenarioManifest
				if err := json.Unmarshal(mr, &m); err != nil {
					t.Fatal(err)
				}
				m.EventsHash = scenarioHash(raw)
				encoded, err := json.Marshal(m)
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(mp, append(encoded, '\n'), 0600); err != nil {
					t.Fatal(err)
				}
			}
			rehashScenarioTest(t, root)
			if err := harness.VerifyEvidence(root); err == nil {
				t.Fatal("forged evidence accepted with recomputed hashes")
			}
		})
	}
}
func TestScenarioComparisonBindings(t *testing.T) {
	p, err := harness.CanonicalScenario("SW-V1-BASE-001")
	if err != nil {
		t.Fatal(err)
	}
	b := executeScenarioTest(t, p, "p1", 1)
	root := t.TempDir()
	for i := 1; i <= 3; i++ {
		copy := b
		copy.Manifest.Repeat = int64(i)
		copy.Manifest.Run = fmt.Sprintf("repeat-%d", i)
		copy.Manifest.Evidence = fmt.Sprintf("%s/%s/p1/%d", b.Manifest.Batch, p.ID, i)
		if i == 3 {
			copy.Manifest.Binary = strings.Repeat("f", 64)
		}
		if err := harness.WriteScenarioBundle(filepath.Join(root, fmt.Sprint(i)), copy); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := harness.CompareEvidenceRuns(root); err == nil {
		t.Fatal("different binary compared equal")
	}
	for _, name := range []string{"manifest.json", "events.ndjson"} {
		path := filepath.Join(root, "3", name)
		if err := os.Remove(path); err != nil {
			t.Fatal(err)
		}
		if _, err := harness.CompareEvidenceRuns(root); err == nil {
			t.Fatal("partial repeat accepted")
		}
	}
}

func TestScenarioResourceAndVersionRejection(t *testing.T) {
	p, err := harness.CanonicalScenario("SW-V1-BASE-001")
	if err != nil {
		t.Fatal(err)
	}
	b := executeScenarioTest(t, p, "p1", 1)
	for _, kind := range []string{"unknown-file", "symlink", "missing-checksum", "wrong-subcase", "v0-manifest", "fourth-repeat"} {
		t.Run(kind, func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, "1")
			if err := harness.WriteScenarioBundle(path, b); err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "unknown-file":
				if err := os.WriteFile(filepath.Join(path, "extra.json"), []byte("{}\n"), 0600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Remove(filepath.Join(path, "metrics.json")); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(filepath.Join(path, "profile.json"), filepath.Join(path, "metrics.json")); err != nil {
					t.Fatal(err)
				}
			case "missing-checksum":
				if err := os.Remove(filepath.Join(path, "checksums.sha256")); err != nil {
					t.Fatal(err)
				}
			case "wrong-subcase", "v0-manifest":
				file := filepath.Join(path, "manifest.json")
				raw, err := os.ReadFile(file)
				if err != nil {
					t.Fatal(err)
				}
				if kind == "wrong-subcase" {
					raw = bytes.Replace(raw, []byte(`"subcase_id":"p1"`), []byte(`"subcase_id":"p1024"`), 1)
				} else {
					raw = bytes.Replace(raw, []byte(`"schema_version":2`), []byte(`"schema_version":1`), 1)
				}
				if err := os.WriteFile(file, raw, 0600); err != nil {
					t.Fatal(err)
				}
				rehashScenarioTest(t, path)
			case "fourth-repeat":
				for i := 2; i <= 4; i++ {
					if err := os.Mkdir(filepath.Join(root, fmt.Sprint(i)), 0700); err != nil {
						t.Fatal(err)
					}
				}
				if _, err := harness.CompareEvidenceRuns(root); err == nil {
					t.Fatal("four repeats accepted")
				}
				return
			}
			if err := harness.VerifyEvidence(path); err == nil {
				t.Fatal("invalid artifact accepted")
			}
		})
	}
	r := &scenarioRecorder{}
	r.bytes = 4 * 1024 * 1024
	r.add(0, "driver", "environment_check", nil, 0, 0, 0, harness.EnvironmentDetail{ID: "recorder", Passed: true, Reason: "test"})
	if r.err == nil || len(r.events) != 0 {
		t.Fatal("recorder silently truncated")
	}
}
