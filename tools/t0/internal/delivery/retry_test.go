package delivery

import (
	"math"
	"strings"
	"testing"
)

func newRetry(t *testing.T, start, deadline int64, link LinkState) RetryState {
	t.Helper()
	state, err := NewRetryState(start, deadline, link)
	if err != nil {
		t.Fatal(err)
	}
	return state
}

func tick(now int64) RetryBatch {
	return RetryBatch{NowMS: now, Link: LinkUnchanged, Signal: RetryContinue, Admission: Admit}
}

func linkBatch(now int64, link LinkEvent) RetryBatch {
	batch := tick(now)
	batch.Link = link
	return batch
}

func expectAdvance(t *testing.T, state RetryState, batch RetryBatch, want RetryDecision) RetryState {
	t.Helper()
	before := state
	next, got, err := state.Advance(batch)
	if err != nil || got != want {
		t.Fatalf("batch %+v: got %+v, error %v; want %+v", batch, got, err, want)
	}
	if state != before {
		t.Fatal("advance mutated its input")
	}
	return next
}

func TestRetryFixedSchedule(t *testing.T) {
	state := newRetry(t, 0, 30000, LinkUp)
	send := RetryDecision{Attempt: true, Send: true, TimedSlotsConsumed: 1, Reason: RetrySending}
	for _, now := range []int64{0, 250, 750, 1750, 3750} {
		if now > 0 {
			state = expectAdvance(t, state, tick(now-1), RetryDecision{Reason: RetryWaiting})
		}
		state = expectAdvance(t, state, tick(now), send)
		state = expectAdvance(t, state, tick(now), RetryDecision{Reason: RetryDuplicateBatch})
	}
	state = expectAdvance(t, state, tick(5000), RetryDecision{Reason: RetryTimedExhausted})
	if state.nextSlot != 5 || state.recoveryUsed {
		t.Fatalf("wrong final budget: %+v", state)
	}
}

func TestRetryFiveSecondOutageAndSingleRecovery(t *testing.T) {
	state := newRetry(t, 0, 30000, LinkDown)
	for _, now := range []int64{0, 250, 750, 1750, 3750} {
		state = expectAdvance(t, state, tick(now), RetryDecision{
			Attempt: true, TimedSlotsConsumed: 1, Reason: RetryLinkBlocked,
		})
	}
	state = expectAdvance(t, state, linkBatch(5000, LinkBecameUp), RetryDecision{
		Attempt: true, Send: true, RecoveryConsumed: true, Reason: RetrySending,
	})
	state = expectAdvance(t, state, linkBatch(5001, LinkBecameUp), RetryDecision{Reason: RetryTimedExhausted})
	state = expectAdvance(t, state, linkBatch(5002, LinkBecameDown), RetryDecision{Reason: RetryTimedExhausted})
	expectAdvance(t, state, linkBatch(5003, LinkBecameUp), RetryDecision{Reason: RetryTimedExhausted})
}

func TestRetryLateDispatchDoesNotBurst(t *testing.T) {
	for _, test := range []struct {
		name     string
		link     LinkState
		batch    RetryBatch
		recovery bool
	}{
		{"late_up", LinkUp, tick(5000), false},
		{"late_recovery", LinkDown, linkBatch(5000, LinkBecameUp), true},
	} {
		t.Run(test.name, func(t *testing.T) {
			state := newRetry(t, 0, 30000, test.link)
			initialReason := RetrySending
			if test.link == LinkDown {
				initialReason = RetryLinkBlocked
			}
			state = expectAdvance(t, state, tick(0), RetryDecision{
				Attempt: true, Send: test.link == LinkUp, TimedSlotsConsumed: 1, Reason: initialReason,
			})
			state = expectAdvance(t, state, test.batch, RetryDecision{
				Attempt: true, Send: true, TimedSlotsConsumed: 4, MissedSlots: 3,
				RecoveryConsumed: test.recovery, Reason: RetrySending,
			})
			expectAdvance(t, state, test.batch, RetryDecision{Reason: RetryDuplicateBatch})
		})
	}
	// Even the first dispatch may be late: it consumes all five planned slots.
	expectAdvance(t, newRetry(t, 0, 30000, LinkUp), tick(5000), RetryDecision{
		Attempt: true, Send: true, TimedSlotsConsumed: 5, MissedSlots: 4, Reason: RetrySending,
	})
}

func TestRetryRecoveryCollisionAndAdmission(t *testing.T) {
	for _, test := range []struct {
		admission Admission
		send      bool
		reason    RetryReason
	}{
		{Admit, true, RetrySending},
		{RejectQuota, false, RetryQuotaRejected},
		{RejectHop, false, RetryHopRejected},
	} {
		t.Run(string(test.reason), func(t *testing.T) {
			state := newRetry(t, 0, 30000, LinkDown)
			state = expectAdvance(t, state, tick(0), RetryDecision{Attempt: true, TimedSlotsConsumed: 1, Reason: RetryLinkBlocked})
			batch := linkBatch(250, LinkBecameUp)
			batch.Admission = test.admission
			state = expectAdvance(t, state, batch, RetryDecision{
				Attempt: true, Send: test.send, TimedSlotsConsumed: 1,
				RecoveryConsumed: true, Reason: test.reason,
			})
			state = expectAdvance(t, state, linkBatch(251, LinkBecameDown), RetryDecision{Reason: RetryWaiting})
			expectAdvance(t, state, linkBatch(252, LinkBecameUp), RetryDecision{Reason: RetryWaiting})
		})
	}
	// Initial up is not recovery, and a rejected timer is not deferred.
	state := newRetry(t, 0, 30000, LinkUp)
	batch := linkBatch(0, LinkBecameUp)
	batch.Admission = RejectQuota
	state = expectAdvance(t, state, batch, RetryDecision{Attempt: true, TimedSlotsConsumed: 1, Reason: RetryQuotaRejected})
	expectAdvance(t, state, tick(1), RetryDecision{Reason: RetryWaiting})
}

func TestRetryDeadlineAndTerminalPriority(t *testing.T) {
	for _, now := range []int64{4999, 5000, 5001} {
		state := newRetry(t, 0, 5000, LinkDown)
		want := RetryDecision{Reason: RetryExpired}
		if now == 4999 {
			want = RetryDecision{Attempt: true, Send: true, TimedSlotsConsumed: 5, MissedSlots: 4, RecoveryConsumed: true, Reason: RetrySending}
		}
		state = expectAdvance(t, state, linkBatch(now, LinkBecameUp), want)
		expectAdvance(t, state, tick(now+2), RetryDecision{Reason: RetryExpired})
	}
	for _, test := range []struct {
		signal RetrySignal
		reason RetryReason
	}{
		{RetryStop, RetryStopped}, {RetryPause, RetryPaused},
	} {
		state := newRetry(t, 0, 30000, LinkDown)
		batch := linkBatch(0, LinkBecameUp)
		batch.Signal = test.signal
		state = expectAdvance(t, state, batch, RetryDecision{Reason: test.reason})
		expectAdvance(t, state, linkBatch(250, LinkBecameUp), RetryDecision{Reason: test.reason})
	}
	expectAdvance(t, newRetry(t, 0, 0, LinkUp), tick(0), RetryDecision{Reason: RetryExpired})
}

func TestRetryBeforeStartAndNonzeroTimeCoordinate(t *testing.T) {
	state := newRetry(t, 1000, 30000, LinkDown)
	state = expectAdvance(t, state, linkBatch(100, LinkBecameUp), RetryDecision{Reason: RetryWaiting})
	state = expectAdvance(t, state, tick(999), RetryDecision{Reason: RetryWaiting})
	state = expectAdvance(t, state, tick(1000), RetryDecision{Attempt: true, Send: true, TimedSlotsConsumed: 1, Reason: RetrySending})
	state = expectAdvance(t, state, linkBatch(1100, LinkBecameDown), RetryDecision{Reason: RetryWaiting})
	expectAdvance(t, state, linkBatch(1200, LinkBecameUp), RetryDecision{Attempt: true, Send: true, RecoveryConsumed: true, Reason: RetrySending})
	state = newRetry(t, math.MaxInt64-3750, math.MaxInt64, LinkUp)
	expectAdvance(t, state, tick(math.MaxInt64-1), RetryDecision{Attempt: true, Send: true, TimedSlotsConsumed: 4, MissedSlots: 3, Reason: RetrySending})
}

func TestRetryRejectsInvalidConstruction(t *testing.T) {
	for _, test := range []struct {
		start, deadline int64
		link            LinkState
	}{
		{-1, 30000, LinkUp}, {0, -1, LinkUp}, {math.MaxInt64 - 3749, math.MaxInt64, LinkUp},
		{0, 30000, 0}, {0, 30000, 99},
	} {
		state, err := NewRetryState(test.start, test.deadline, test.link)
		if err == nil || state != (RetryState{}) {
			t.Fatalf("invalid construction %+v returned %+v, %v", test, state, err)
		}
	}
}

func TestRetryErrorsPreserveStateAndNeverSend(t *testing.T) {
	state := newRetry(t, 0, 30000, LinkUp)
	state = expectAdvance(t, state, tick(100), RetryDecision{Attempt: true, Send: true, TimedSlotsConsumed: 1, Reason: RetrySending})
	for _, test := range []struct {
		name   string
		change func(*RetryBatch)
	}{
		{"negative_time", func(b *RetryBatch) { b.NowMS = -1 }},
		{"rollback", func(b *RetryBatch) { b.NowMS = 99 }},
		{"same_time_new_fact", func(b *RetryBatch) { b.NowMS = 100; b.Signal = RetryStop }},
		{"missing_link", func(b *RetryBatch) { b.Link = 0 }},
		{"unknown_link", func(b *RetryBatch) { b.Link = 99 }},
		{"missing_signal", func(b *RetryBatch) { b.Signal = 0 }},
		{"unknown_signal", func(b *RetryBatch) { b.Signal = 99 }},
		{"missing_admission", func(b *RetryBatch) { b.Admission = 0 }},
		{"unknown_admission", func(b *RetryBatch) { b.Admission = 99 }},
	} {
		t.Run(test.name, func(t *testing.T) {
			batch := tick(250)
			test.change(&batch)
			next, decision, err := state.Advance(batch)
			if err == nil || next != state || decision != (RetryDecision{}) {
				t.Fatalf("invalid batch changed state or produced a decision: %+v, %+v, %v", next, decision, err)
			}
		})
	}
	for _, badSlot := range []int{-1, 6} {
		invalid := state
		invalid.nextSlot = badSlot
		next, decision, err := invalid.Advance(tick(250))
		if err == nil || !strings.Contains(err.Error(), "slot index") || next != invalid || decision != (RetryDecision{}) {
			t.Fatalf("corrupt budget accepted: %+v, %v", decision, err)
		}
	}
	var zero RetryState
	next, decision, err := zero.Advance(tick(0))
	if err == nil || next != zero || decision != (RetryDecision{}) {
		t.Fatal("zero-value state was usable")
	}
	// Failed inputs did not consume the next valid opportunity.
	expectAdvance(t, state, tick(250), RetryDecision{Attempt: true, Send: true, TimedSlotsConsumed: 1, Reason: RetrySending})
}

func TestRetryQueuesAreIndependent(t *testing.T) {
	first := newRetry(t, 0, 30000, LinkDown)
	second := newRetry(t, 0, 30000, LinkDown)
	first = expectAdvance(t, first, linkBatch(0, LinkBecameUp), RetryDecision{Attempt: true, Send: true, TimedSlotsConsumed: 1, RecoveryConsumed: true, Reason: RetrySending})
	second = expectAdvance(t, second, tick(0), RetryDecision{Attempt: true, TimedSlotsConsumed: 1, Reason: RetryLinkBlocked})
	if !first.recoveryUsed || second.recoveryUsed || second.link != LinkDown {
		t.Fatal("queue-local state leaked between instances")
	}
	expectAdvance(t, second, linkBatch(100, LinkBecameUp), RetryDecision{Attempt: true, Send: true, RecoveryConsumed: true, Reason: RetrySending})
}

func TestRetryBudgetRemainsBoundedDuringLinkFlapping(t *testing.T) {
	state := newRetry(t, 0, 30000, LinkDown)
	var attempts, timedSlots, recoveries int
	for now := int64(0); now <= 6000; now += 50 {
		link := LinkBecameDown
		if now%100 == 50 {
			link = LinkBecameUp
		}
		next, decision, err := state.Advance(linkBatch(now, link))
		if err != nil {
			t.Fatal(err)
		}
		state = next
		if decision.Attempt {
			attempts++
		}
		timedSlots += decision.TimedSlotsConsumed
		if decision.RecoveryConsumed {
			recoveries++
		}
		if attempts > 6 || timedSlots > 5 || recoveries > 1 {
			t.Fatalf("flapping replenished budget at %d: attempts=%d slots=%d recoveries=%d", now, attempts, timedSlots, recoveries)
		}
	}
	if attempts != 6 || timedSlots != 5 || recoveries != 1 {
		t.Fatalf("expected five scheduled attempts and one recovery, got %d/%d/%d", attempts, timedSlots, recoveries)
	}
}
