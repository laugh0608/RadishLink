package harness

import (
	"testing"
	"time"
)

func TestClockObservesWallRollbackWithoutMonotonicRollback(t *testing.T) {
	initial := time.Unix(1_800_000_000, 0)
	clock, err := NewTestClock(initial)
	if err != nil {
		t.Fatal(err)
	}
	advance, err := clock.Advance(1500 * time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	rollback, err := clock.ObserveWall(initial.Add(-time.Hour))
	if err != nil {
		t.Fatal(err)
	}
	if rollback.Kind != "wall_clock_rollback_observed" {
		t.Fatalf("rollback kind: got %q", rollback.Kind)
	}
	if rollback.MonotonicMS != advance.MonotonicMS || rollback.MonotonicMS != 1500 {
		t.Fatalf("monotonic time changed during rollback: advance=%d rollback=%d", advance.MonotonicMS, rollback.MonotonicMS)
	}
	monotonic, _, sequence := clock.Snapshot()
	if monotonic != 1500 || sequence != 2 {
		t.Fatalf("clock snapshot: monotonic=%d sequence=%d", monotonic, sequence)
	}
}

func TestClockRejectsNegativeAdvance(t *testing.T) {
	clock, err := NewTestClock(time.Unix(1_800_000_000, 0))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := clock.Advance(-time.Millisecond); err == nil {
		t.Fatal("negative monotonic advance was accepted")
	}
	monotonic, _, sequence := clock.Snapshot()
	if monotonic != 0 || sequence != 0 {
		t.Fatalf("negative advance mutated clock: monotonic=%d sequence=%d", monotonic, sequence)
	}
}
