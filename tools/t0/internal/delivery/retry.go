// Package delivery contains offline message-delivery algorithms. It does not
// authenticate evidence, persist state, or send frames.
package delivery

import (
	"errors"
	"fmt"
	"math"
)

// LinkState must be supplied explicitly, including at queue creation.
type LinkState uint8

const (
	LinkUp LinkState = iota + 1
	LinkDown
)

// LinkEvent represents at most one observation in a logical-time batch.
type LinkEvent uint8

const (
	LinkUnchanged LinkEvent = iota + 1
	LinkBecameUp
	LinkBecameDown
)

// RetrySignal is a caller-verified fact, not authentication performed here.
type RetrySignal uint8

const (
	RetryContinue RetrySignal = iota + 1
	RetryPause
	RetryStop
)

// Admission is the caller's current resource/hop decision.
type Admission uint8

const (
	Admit Admission = iota + 1
	RejectQuota
	RejectHop
)

// RetryBatch contains all events at NowMS. A second, different batch at the
// same time is rejected; callers must collect same-time facts before advancing.
type RetryBatch struct {
	NowMS     int64
	Link      LinkEvent
	Signal    RetrySignal
	Admission Admission
}

type RetryReason string

// RetryTimedExhausted only exhausts scheduled slots. It is not a terminal
// delivery state: an unused recovery opportunity may still be consumed.
const (
	RetryWaiting        RetryReason = "waiting"
	RetryTimedExhausted RetryReason = "timed_slots_exhausted"
	RetrySending        RetryReason = "send"
	RetryLinkBlocked    RetryReason = "blocked_link_down"
	RetryQuotaRejected  RetryReason = "rejected_quota"
	RetryHopRejected    RetryReason = "rejected_hop"
	RetryPaused         RetryReason = "paused"
	RetryStopped        RetryReason = "stopped"
	RetryExpired        RetryReason = "expired"
	RetryDuplicateBatch RetryReason = "duplicate_batch"
)

// RetryDecision describes only this transition. Attempt includes blocked or
// rejected attempts. A decision never grants custody, delivery, or deletion.
type RetryDecision struct {
	Attempt            bool
	Send               bool
	TimedSlotsConsumed int
	MissedSlots        int
	RecoveryConsumed   bool
	Reason             RetryReason
}

type retryPhase uint8

const (
	retryActive retryPhase = iota + 1
	retryPaused
	retryStopped
	retryExpired
)

// RetryState is a queue-local value. Its zero value is invalid. It has no
// persistence format: copying it does not prove crash safety or clock recovery.
type RetryState struct {
	initialized  bool
	startMS      int64
	deadlineMS   int64
	nextSlot     int
	recoveryUsed bool
	link         LinkState
	phase        retryPhase
	hasBatch     bool
	lastBatch    RetryBatch
}

// NewRetryState fixes five planned slots at startMS + 0/250/750/1750/3750
// and one recovery opportunity. deadlineMS is an already-conservative cutoff
// in the same logical time coordinate; it is never recomputed from link events.
func NewRetryState(startMS, deadlineMS int64, link LinkState) (RetryState, error) {
	state := RetryState{
		initialized: true, startMS: startMS, deadlineMS: deadlineMS,
		link: link, phase: retryActive,
	}
	if err := state.validate(); err != nil {
		return RetryState{}, err
	}
	return state, nil
}

// Advance computes a new value without changing the receiver. Errors return
// the original state and an empty decision. Before acting on Send, the caller
// must durably commit the returned state; replaying an older state is unsafe.
func (state RetryState) Advance(batch RetryBatch) (RetryState, RetryDecision, error) {
	if err := state.validate(); err != nil {
		return state, RetryDecision{}, err
	}
	if err := batch.validate(); err != nil {
		return state, RetryDecision{}, err
	}
	if state.hasBatch {
		if batch.NowMS < state.lastBatch.NowMS {
			return state, RetryDecision{}, fmt.Errorf("retry time moved backward: %d < %d", batch.NowMS, state.lastBatch.NowMS)
		}
		if batch.NowMS == state.lastBatch.NowMS {
			if batch != state.lastBatch {
				return state, RetryDecision{}, fmt.Errorf("conflicting retry batch at %d ms", batch.NowMS)
			}
			return state, RetryDecision{Reason: RetryDuplicateBatch}, nil
		}
	}

	next := state
	next.hasBatch, next.lastBatch = true, batch
	if next.phase == retryStopped || batch.Signal == RetryStop {
		next.phase = retryStopped
		return next, RetryDecision{Reason: RetryStopped}, nil
	}
	if next.phase == retryExpired {
		return next, RetryDecision{Reason: RetryExpired}, nil
	}
	if next.phase == retryPaused || batch.Signal == RetryPause {
		next.phase = retryPaused
		return next, RetryDecision{Reason: RetryPaused}, nil
	}
	if batch.NowMS >= next.deadlineMS {
		next.phase = retryExpired
		return next, RetryDecision{Reason: RetryExpired}, nil
	}

	recovered := next.link == LinkDown && batch.Link == LinkBecameUp
	switch batch.Link {
	case LinkBecameUp:
		next.link = LinkUp
	case LinkBecameDown:
		next.link = LinkDown
	}
	if batch.NowMS < next.startMS {
		return next, RetryDecision{Reason: RetryWaiting}, nil
	}

	decision := RetryDecision{}
	// A local fixed array avoids shared mutable policy or caller-selected budgets.
	offsets := [...]int64{0, 250, 750, 1750, 3750}
	for _, offset := range offsets[next.nextSlot:] {
		if batch.NowMS < next.startMS+offset {
			break
		}
		next.nextSlot++
		decision.TimedSlotsConsumed++
	}
	if decision.TimedSlotsConsumed > 0 {
		decision.MissedSlots = decision.TimedSlotsConsumed - 1
	}
	if recovered && !next.recoveryUsed {
		next.recoveryUsed = true
		decision.RecoveryConsumed = true
	}
	decision.Attempt = decision.TimedSlotsConsumed > 0 || decision.RecoveryConsumed
	if !decision.Attempt {
		decision.Reason = RetryWaiting
		if next.nextSlot == 5 {
			decision.Reason = RetryTimedExhausted
		}
		return next, decision, nil
	}
	switch {
	case next.link == LinkDown:
		decision.Reason = RetryLinkBlocked
	case batch.Admission == RejectQuota:
		decision.Reason = RetryQuotaRejected
	case batch.Admission == RejectHop:
		decision.Reason = RetryHopRejected
	default:
		decision.Send, decision.Reason = true, RetrySending
	}
	return next, decision, nil
}

func (state RetryState) validate() error {
	if !state.initialized {
		return errors.New("retry state must be constructed")
	}
	if state.startMS < 0 || state.startMS > math.MaxInt64-3750 {
		return fmt.Errorf("retry start must be within 0..%d ms: %d", int64(math.MaxInt64-3750), state.startMS)
	}
	if state.deadlineMS < 0 {
		return fmt.Errorf("retry deadline must be nonnegative: %d", state.deadlineMS)
	}
	if state.nextSlot < 0 || state.nextSlot > 5 {
		return fmt.Errorf("retry slot index must be within 0..5: %d", state.nextSlot)
	}
	if state.link != LinkUp && state.link != LinkDown {
		return fmt.Errorf("unknown retry link state: %d", state.link)
	}
	if state.phase < retryActive || state.phase > retryExpired {
		return fmt.Errorf("unknown retry phase: %d", state.phase)
	}
	if state.hasBatch {
		if err := state.lastBatch.validate(); err != nil {
			return fmt.Errorf("previous retry batch: %w", err)
		}
	} else if state.nextSlot != 0 || state.recoveryUsed || state.phase != retryActive {
		return errors.New("retry progress requires a previous batch")
	}
	return nil
}

func (batch RetryBatch) validate() error {
	if batch.NowMS < 0 {
		return fmt.Errorf("retry time must be nonnegative: %d", batch.NowMS)
	}
	if batch.Link < LinkUnchanged || batch.Link > LinkBecameDown {
		return fmt.Errorf("unknown retry link event: %d", batch.Link)
	}
	if batch.Signal < RetryContinue || batch.Signal > RetryStop {
		return fmt.Errorf("unknown retry signal: %d", batch.Signal)
	}
	if batch.Admission < Admit || batch.Admission > RejectHop {
		return fmt.Errorf("unknown retry admission: %d", batch.Admission)
	}
	return nil
}
