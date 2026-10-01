package synthetic

import (
	"fmt"
	"testing"

	"radishlink.local/t0/internal/delivery"
)

func TestRetryLedgerRestoresConsumedBudget(t *testing.T) {
	m := messageFrom(fixtureData(1))
	q := newQueue(m, "data", "B", 0, 1, false)
	q.InitialLink = "down"
	for _, now := range []int64{0, 250, 750, 1750, 3750} {
		d, err := q.advance(retryBatch{now, "unchanged", "continue", "admit"})
		if err != nil || d.Send || d.TimedSlotsConsumed != 1 {
			t.Fatalf("blocked slot: %+v %v", d, err)
		}
	}
	d, err := q.advance(retryBatch{5000, "became_up", "continue", "admit"})
	if err != nil || !d.Send || !d.RecoveryConsumed {
		t.Fatalf("recovery: %+v %v", d, err)
	}
	if _, err := q.replay(); err != nil {
		t.Fatal(err)
	}
	d, err = q.advance(retryBatch{5000, "became_up", "continue", "admit"})
	if err != nil || d.Send || d.Reason != delivery.RetryDuplicateBatch || len(q.Batches) != 6 {
		t.Fatal("duplicate replay consumed budget")
	}
	if _, err := q.advance(retryBatch{5000, "became_down", "continue", "admit"}); err == nil {
		t.Fatal("same-time conflict accepted")
	}
	for _, b := range []retryBatch{{5001, "became_down", "continue", "admit"}, {5002, "became_up", "continue", "admit"}} {
		d, err := q.advance(b)
		if err != nil || d.Send {
			t.Fatal("recovery budget reset")
		}
	}
	wait := newQueue(m, "data", "B", 1000, 1, false)
	for i := int64(0); i < 64; i++ {
		if _, err := wait.advance(retryBatch{i, "unchanged", "continue", "admit"}); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := wait.advance(retryBatch{64, "unchanged", "continue", "admit"}); Code(err) != "SCHEDULE_LIMIT" || len(wait.Batches) != 64 || wait.Status != "schedule_limit" {
		t.Fatal("ledger overflow did not stop")
	}
}
func TestStateRejectsBrokenInvariants(t *testing.T) {
	n, _ := testNode(t, "A")
	mustSubmit(t, n, "one", testID, 1)
	for name, mutate := range map[string]func(*state){
		"version": func(s *state) { s.Version = 2 }, "null": func(s *state) { s.Actions = nil },
		"reference": func(s *state) { s.Queues[0].Key.ID = "44444444444444444444444444444444" },
		"counter":   func(s *state) { s.SendSteps = 0 }, "duplicate": func(s *state) { s.Messages = append(s.Messages, s.Messages[0]) },
		"body": func(s *state) { s.Messages[0].Body = "eQ==" }, "retention": func(s *state) { s.Messages[0].Transport = false },
		"deadline": func(s *state) { s.Queues[0].Deadline++ }, "tokens": func(s *state) { s.Buckets[0].Credit = -1 },
		"paused": func(s *state) { s.Messages[0].CustodySeen = true }, "missing-queue": func(s *state) { s.Queues = []queue{} },
	} {
		t.Run(name, func(t *testing.T) {
			s := n.storage.current.clone()
			mutate(&s)
			if _, err := encodeState(s); err == nil {
				t.Fatal("invalid state encoded")
			}
		})
	}
	if _, err := decodeState(make([]byte, maxStateBytes+1)); err == nil {
		t.Fatal("oversized state accepted")
	}
	buffer := cappedBuffer{limit: 2}
	if _, err := buffer.Write([]byte{1, 2, 3}); Code(err) != "REJECT_QUOTA" || buffer.Len() != 0 {
		t.Fatal("bounded buffer exceeded")
	}
}
func TestControlReservationsAndHistoryQuota(t *testing.T) {
	b, o := testNode(t, "B")
	rejected := false
	for i := 1; i <= 12; i++ {
		e := fixtureData(1)
		e.ID = fmt.Sprintf("%032x", i)
		e.Fingerprint = e.fingerprint()
		before := b.Generation()
		out, err := b.Step(Batch{Now: int64(2*i - 1), Inputs: []Input{permit(t, o, b, "A", e)}})
		if Code(err) == "REJECT_QUOTA" {
			if before != b.Generation() || len(out) != 0 {
				t.Fatal("quota rejection committed")
			}
			rejected = true
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		m := *b.storage.current.find(e.Key())
		mustStep(t, b, Batch{Now: int64(2 * i), Inputs: []Input{permit(t, o, b, "C", m.envelope("delivery", 0))}})
	}
	if !rejected {
		t.Fatal("control reservation limit not enforced")
	}
	c, oracle := testNode(t, "C")
	for i := 1; i <= 5; i++ {
		e := fixtureData(16384)
		e.ID = fmt.Sprintf("%032x", i)
		e.RemainingHops = 0
		e.Fingerprint = e.fingerprint()
		before := c.Generation()
		_, err := c.Step(Batch{Now: int64(i), Inputs: []Input{permit(t, oracle, c, "B", e)}})
		if i < 5 && err != nil {
			t.Fatal(err)
		}
		if i == 5 && (Code(err) != "REJECT_QUOTA" || c.Generation() != before) {
			t.Fatalf("history quota: %v", err)
		}
	}
}
func TestBucketBounds(t *testing.T) {
	b := bucket{Class: "control"}
	if err := b.refill(250); err != nil || b.Credit != 1024000 {
		t.Fatal("fractional accrual")
	}
	if err := b.refill(100000); err != nil || b.Credit != 4096000 {
		t.Fatal("burst saturation")
	}
	if err := b.refill(99999); Code(err) != "TIME_UNCERTAIN" {
		t.Fatal("rollback accepted")
	}
}
