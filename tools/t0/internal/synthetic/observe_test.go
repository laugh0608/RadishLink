package synthetic

import (
	"bytes"
	"errors"
	"reflect"
	"testing"
)

func TestObservationDetachedAndNoReplay(t *testing.T) {
	n, _ := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 1)
	first, err := n.Snapshot()
	if err != nil {
		t.Fatal(err)
	}
	before := n.Generation()
	copy, err := n.Snapshot()
	if err != nil {
		t.Fatal(err)
	}
	copy.Messages[0].BodyBytes = 100
	copy.Queues[0].Timed = 4
	copy.Buckets[0].Credit = 999
	got, err := n.Snapshot()
	if err != nil || !reflect.DeepEqual(first, got) || n.Generation() != before {
		t.Fatalf("snapshot mutated state: %v", err)
	}
	_, report, err := n.StepWithReport(Batch{Now: 1})
	if err != nil || !report.Committed || report.Before != before || report.After != before+1 || len(report.Decisions) != 1 || report.Decisions[0].Send {
		t.Fatalf("first report: %+v %v", report, err)
	}
	out, report, err := n.StepWithReport(Batch{Now: 250})
	if err != nil || len(out) != 1 || !report.Decisions[0].Send {
		t.Fatalf("send report: %+v %v", report, err)
	}
	var wire bytes.Buffer
	if err := out[0].Write(&wire, 250); err != nil {
		t.Fatal(err)
	}
	report.Decisions[0].TimedAfter = 0
	restored, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 250, n.Generation()})
	if err != nil {
		t.Fatal(err)
	}
	s, err := restored.Snapshot()
	if err != nil || s.Queues[0].Timed != 2 {
		t.Fatalf("budget observation: %v", err)
	}
	out, report, err = restored.StepWithReport(Batch{Now: 251})
	if err != nil || len(out) != 0 || len(report.Decisions) != 1 || report.Decisions[0].Send {
		t.Fatal("replayed send")
	}
}
func TestObservationNeverPublishesFailedCandidate(t *testing.T) {
	for _, stage := range []string{"before_write", "after_rename"} {
		t.Run(stage, func(t *testing.T) {
			n, _ := testNode(t, "A")
			mustSubmit(t, n, "one", testID, 1)
			mustStep(t, n, Batch{Now: 1})
			g := n.Generation()
			fault := errors.New("observer fault")
			n.storage.ops.hook = func(at string) error {
				if at == stage {
					return fault
				}
				return nil
			}
			out, r, err := n.StepWithReport(Batch{Now: 250})
			if !errors.Is(err, fault) || r.Committed || r.Before != g || r.After != g || len(out) != 0 || len(r.Decisions) != 0 {
				t.Fatalf("candidate escaped: %+v %v", r, err)
			}
			if _, err := n.Snapshot(); Code(err) != "STORE_OUTCOME_UNKNOWN" {
				t.Fatal("uncertain snapshot")
			}
		})
	}
}
