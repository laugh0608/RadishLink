package harness

import (
	"errors"
	"sync"
	"time"
)

type ClockEvent struct {
	Sequence       uint64 `json:"sequence"`
	Kind           string `json:"kind"`
	MonotonicMS    int64  `json:"monotonic_ms"`
	ObservedUnixMS int64  `json:"observed_unix_ms"`
	PreviousUnixMS int64  `json:"previous_unix_ms"`
}

type TestClock struct {
	mu          sync.Mutex
	monotonicMS int64
	lastWallMS  int64
	sequence    uint64
}

func NewTestClock(initialWall time.Time) (*TestClock, error) {
	if initialWall.IsZero() {
		return nil, errors.New("initial wall time is required")
	}
	return &TestClock{lastWallMS: initialWall.UnixMilli()}, nil
}

func (clock *TestClock) Advance(delta time.Duration) (ClockEvent, error) {
	if delta < 0 {
		return ClockEvent{}, errors.New("monotonic test clock cannot advance by a negative duration")
	}
	clock.mu.Lock()
	defer clock.mu.Unlock()
	clock.monotonicMS += delta.Milliseconds()
	clock.sequence++
	return ClockEvent{
		Sequence:       clock.sequence,
		Kind:           "monotonic_advanced",
		MonotonicMS:    clock.monotonicMS,
		ObservedUnixMS: clock.lastWallMS,
		PreviousUnixMS: clock.lastWallMS,
	}, nil
}

func (clock *TestClock) ObserveWall(observed time.Time) (ClockEvent, error) {
	if observed.IsZero() {
		return ClockEvent{}, errors.New("observed wall time is required")
	}
	clock.mu.Lock()
	defer clock.mu.Unlock()
	previous := clock.lastWallMS
	observedMS := observed.UnixMilli()
	kind := "wall_clock_observed"
	if observedMS < previous {
		kind = "wall_clock_rollback_observed"
	}
	clock.lastWallMS = observedMS
	clock.sequence++
	return ClockEvent{
		Sequence:       clock.sequence,
		Kind:           kind,
		MonotonicMS:    clock.monotonicMS,
		ObservedUnixMS: observedMS,
		PreviousUnixMS: previous,
	}, nil
}

func (clock *TestClock) Snapshot() (monotonicMS, wallUnixMS int64, sequence uint64) {
	clock.mu.Lock()
	defer clock.mu.Unlock()
	return clock.monotonicMS, clock.lastWallMS, clock.sequence
}
