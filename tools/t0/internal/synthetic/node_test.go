package synthetic

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

type testOracle map[VerdictRequest]Verdict

func testConfig(node string, oracle testOracle) Config {
	return Config{Run: testRun, Node: node, Scope: "squad", Epoch: testEpoch, Verdicts: func(r VerdictRequest) Verdict { return oracle[r] }}
}
func testNode(t *testing.T, node string) (*Node, testOracle) {
	t.Helper()
	oracle := testOracle{}
	dir := filepath.Join(t.TempDir(), "node")
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	n, err := InitNode(dir, testConfig(node, oracle))
	if err != nil {
		t.Fatal(err)
	}
	return n, oracle
}
func permit(t *testing.T, o testOracle, n *Node, from string, e Envelope) Input {
	t.Helper()
	b := mustEncode(t, e)
	purpose := "admission"
	if n.config.Node == "C" {
		purpose = "destination"
	}
	if e.Kind == "custody" {
		purpose = "custody"
	}
	if e.Kind == "delivery" {
		purpose = "delivery"
		if n.config.Node == "B" {
			purpose = "relay-clear"
		}
	}
	o[VerdictRequest{n.config.Node, from, digest(b), purpose, e.Key()}] = VerdictAccept
	return Input{from, b}
}
func mustSubmit(t *testing.T, n *Node, ref, id string, size int) {
	t.Helper()
	if _, err := n.Submit(ref, id, bytes.Repeat([]byte{'x'}, size), 0, 30000); err != nil {
		t.Fatal(err)
	}
}
func mustStep(t *testing.T, n *Node, b Batch) []*Transmission {
	t.Helper()
	out, err := n.Step(b)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

func TestSubmitIdentityAndQuota(t *testing.T) {
	n, _ := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 16384)
	generation := n.Generation()
	if _, err := n.Submit("one", testID, bytes.Repeat([]byte{'x'}, 16384), 10, 30000); err != nil || n.Generation() != generation {
		t.Fatalf("duplicate action: %v", err)
	}
	if _, err := n.Submit("one", testID, []byte("different"), 10, 30000); Code(err) != "CONFLICT" {
		t.Fatal(err)
	}
	for i := 2; i <= 4; i++ {
		mustSubmit(t, n, fmt.Sprint(i), fmt.Sprintf("%032x", i), 16384)
	}
	before := n.Generation()
	if _, err := n.Submit("five", fmt.Sprintf("%032x", 5), []byte{'x'}, 0, 30000); Code(err) != "REJECT_QUOTA" || n.Generation() != before {
		t.Fatalf("quota: %v", err)
	}
	view, err := n.Query("one")
	if err != nil || len(view.Body) != 16384 || view.Mode != "synthetic" {
		t.Fatal(err)
	}
	view.Body[0] = 'z'
	again, _ := n.Query("one")
	if again.Body[0] != 'x' {
		t.Fatal("query aliased persisted body")
	}
	bad := n.config
	bad.Verdicts = nil
	if _, err := InitNode(t.TempDir(), bad); err == nil {
		t.Fatal("nil oracle accepted")
	}
}
func TestReceiveRejectionDoesNotCommit(t *testing.T) {
	n, o := testNode(t, "B")
	e := fixtureData(1)
	in := Input{"A", mustEncode(t, e)}
	if _, err := n.Step(Batch{Now: 1, Inputs: []Input{in}}); Code(err) != "REJECT_VERDICT" || n.Generation() != 0 {
		t.Fatalf("oracle: %v", err)
	}
	in = permit(t, o, n, "A", e)
	mustStep(t, n, Batch{Now: 1, Inputs: []Input{in}})
	for _, kind := range []string{"conflict", "scope", "hop", "neighbor", "future"} {
		t.Run(kind, func(t *testing.T) {
			bad := e
			from := "A"
			switch kind {
			case "conflict":
				bad.Body = "eQ=="
			case "scope":
				bad.Scope = "other"
			case "hop":
				bad.RemainingHops = 0
			case "neighbor":
				from = "C"
			case "future":
				bad.Originated = 3
			}
			bad.Fingerprint = bad.fingerprint()
			input := permit(t, o, n, from, bad)
			before := n.Generation()
			if _, err := n.Step(Batch{Now: 2, Inputs: []Input{input}}); err == nil || n.Generation() != before {
				t.Fatalf("invalid input committed: %v", err)
			}
		})
	}
	before := len(n.storage.current.Queues)
	mustStep(t, n, Batch{Now: 2, Inputs: []Input{in}})
	if len(n.storage.current.Messages) != 1 || len(n.storage.current.Queues) != before {
		t.Fatal("duplicate allocated responsibility")
	}
}
func TestDeadlinePauseAndTransmission(t *testing.T) {
	n, o := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 1)
	if out := mustStep(t, n, Batch{Now: 1}); len(out) != 0 {
		t.Fatal("zero credit ignored")
	}
	out := mustStep(t, n, Batch{Now: 250})
	if len(out) != 1 {
		t.Fatal("expected retry")
	}
	var wire bytes.Buffer
	if err := out[0].Write(&wire, 30000); Code(err) != "EXPIRED" || wire.Len() != 0 {
		t.Fatalf("late write: %v", err)
	}
	if err := out[0].Write(&wire, 250); err == nil {
		t.Fatal("opportunity reused")
	}
	m := n.storage.current.Messages[0]
	custody := m.envelope("custody", 0)
	mustStep(t, n, Batch{Now: 300, Inputs: []Input{permit(t, o, n, "B", custody)}})
	if n.storage.current.Queues[0].Status != "paused" {
		t.Fatal("custody did not pause")
	}
	mustStep(t, n, Batch{Now: 30000})
	v, _ := n.Query("one")
	if v.State != "expired" || len(v.Body) != 1 || n.storage.current.Messages[0].Transport {
		t.Fatal("paused expiry failed")
	}
	if _, err := n.Step(Batch{Now: 30000}); err == nil {
		t.Fatal("same node timestamp accepted")
	}
}

func TestTransmissionCopiesAndStaleHandles(t *testing.T) {
	n, _ := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 1)
	mustStep(t, n, Batch{Now: 1})
	old := mustStep(t, n, Batch{Now: 250})
	fresh := mustStep(t, n, Batch{Now: 750})
	if len(old) != 1 || len(fresh) != 1 {
		t.Fatal("missing opportunities")
	}
	copy := *fresh[0]
	var wire bytes.Buffer
	if err := old[0].Write(&wire, 750); Code(err) != "EXPIRED" || wire.Len() != 0 {
		t.Fatalf("stale transmission: %v", err)
	}
	if err := fresh[0].Write(&wire, 750); err != nil {
		t.Fatalf("stale handle consumed fresh opportunity: %v", err)
	}
	size := wire.Len()
	if err := copy.Write(&wire, 750); err == nil || wire.Len() != size {
		t.Fatal("copied handle sent twice")
	}
}

func TestRejectedInputsDoNotPreventExpiry(t *testing.T) {
	for _, kind := range []string{"malformed", "late", "oracle"} {
		t.Run(kind, func(t *testing.T) {
			n, o := testNode(t, "B")
			old := permit(t, o, n, "A", fixtureData(1))
			mustStep(t, n, Batch{Now: 1, Inputs: []Input{old}})
			before := n.Generation()
			inputs := []Input{{Neighbor: "A", Frame: []byte("bad")}}
			if kind == "late" {
				inputs = []Input{old}
			}
			if kind == "oracle" {
				good := fixtureData(1)
				good.ID, good.Originated = "44444444444444444444444444444444", 30000
				good.Fingerprint = good.fingerprint()
				inputs = []Input{permit(t, o, n, "A", good)}
				bad := good
				bad.ID = "55555555555555555555555555555555"
				bad.Fingerprint = bad.fingerprint()
				inputs = append(inputs, Input{"A", mustEncode(t, bad)})
			}
			out, err := n.Step(Batch{Now: 30000, Inputs: inputs})
			if err == nil || len(out) != 0 || n.Generation() != before+1 {
				t.Fatalf("expiry not settled: %v", err)
			}
			if len(n.storage.current.Messages) != 1 {
				t.Fatal("partial input batch committed")
			}
			m := n.storage.current.Messages[0]
			if m.State != "expired" || m.Body != "" || m.Transport {
				t.Fatal("relay expiry postponed")
			}
			restored, err := OpenNode(n.storage.directory, n.config, Recovery{testEpoch, 30000, n.Generation()})
			if err != nil || restored.storage.current.Messages[0] != m {
				t.Fatalf("expiry not durable: %v", err)
			}
		})
	}
}

func TestBatchReportForRejectedInputExpiry(t *testing.T) {
	n, _ := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 1)
	out, r, err := n.StepWithReport(Batch{Now: 30000, Inputs: []Input{{Neighbor: "B", Frame: []byte("bad")}}})
	if err == nil || len(out) != 0 || !r.Committed || r.After != r.Before+1 || len(r.Decisions) != 0 || len(r.Transactions) != 1 || r.Transactions[0] != "expiry" {
		t.Fatalf("expiry report: %+v %v", r, err)
	}
}

func TestScheduleLimitReportIsNotExpiry(t *testing.T) {
	n, _ := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 1)
	for now := int64(1); now <= 64; now++ {
		mustStep(t, n, Batch{Now: now})
	}
	out, r, err := n.StepWithReport(Batch{Now: 65})
	if Code(err) != "SCHEDULE_LIMIT" || len(out) != 0 || !r.Committed || len(r.Transactions) != 1 || r.Transactions[0] != "schedule" {
		t.Fatalf("schedule report: %+v %v", r, err)
	}
}
