package harness

import (
	"errors"
	"reflect"
	"slices"
	"strings"
)

func queueID(node string, key ObservedKey, kind string) string {
	return node + "/" + key.ID + "/" + kind
}
func messageAt(s ObservedState) *ObservedMessage {
	if len(s.Messages) == 0 {
		return nil
	}
	return &s.Messages[0]
}
func queueAt(s ObservedState, kind string) *ObservedQueue {
	for i := range s.Queues {
		if s.Queues[i].Kind == kind {
			return &s.Queues[i]
		}
	}
	return nil
}
func peak(a, b ResourceUsage) ResourceUsage {
	return ResourceUsage{max(a.PayloadObjects, b.PayloadObjects), max(a.PayloadBytes, b.PayloadBytes), max(a.HistoryObjects, b.HistoryObjects), max(a.HistoryBytes, b.HistoryBytes), max(a.ControlObjects, b.ControlObjects), max(a.ControlBytes, b.ControlBytes)}
}
func keyFixture() ObservedKey {
	return ObservedKey{1, "A", "i4-small4", "33333333333333333333333333333333"}
}
func direction(from, to string) string { return strings.ToLower(from) + "-to-" + strings.ToLower(to) }
func frameFixture(frames []ScenarioFrame, dir, kind string) *ScenarioFrame {
	for i := range frames {
		if direction(frames[i].From, frames[i].To) == dir && frames[i].Kind == kind {
			return &frames[i]
		}
	}
	return nil
}

// AssessScenario re-derives outcomes from facts, not the submitted assertion booleans.
func AssessScenario(p ScenarioProfile, subcase string, events []ScenarioEvent, res ScenarioResiduals) (ScenarioMetrics, ScenarioAssertions, string, error) {
	if err := p.Validate(); err != nil {
		return ScenarioMetrics{}, ScenarioAssertions{}, "", err
	}
	sub, err := p.Subcase(subcase)
	if err != nil {
		return ScenarioMetrics{}, ScenarioAssertions{}, "", err
	}
	return assessSemantics(semanticContract{2, sub.Size, p.Fault}, events, res)
}

// The contract is internal and is only constructed after a version-specific profile check.
type semanticContract struct {
	schema, size int64
	fault        ScenarioFault
}

func assessSemantics(c semanticContract, events []ScenarioEvent, res ScenarioResiduals) (ScenarioMetrics, ScenarioAssertions, string, error) {
	m := ScenarioMetrics{Schema: c.schema, Events: int64(len(events)), Peaks: []NodePeak{{Node: "A"}, {Node: "B"}, {Node: "C"}}, Latencies: []int64{}}
	assertions := ScenarioAssertions{Schema: c.schema, Items: []ScenarioAssertion{}}
	invalid := func(msg string) (ScenarioMetrics, ScenarioAssertions, string, error) {
		return ScenarioMetrics{}, ScenarioAssertions{}, "", errors.New(msg)
	}
	if _, err := encodeSemanticEvents(events, c.schema); err != nil {
		return invalid(err.Error())
	}
	frames, err := ScenarioFrames(c.size)
	if err != nil {
		return invalid(err.Error())
	}
	states := map[string]ObservedState{}
	pending := map[string]ScenarioEvent{}
	received := map[string][]ScenarioEvent{}
	verdicts := map[string][]ScenarioEvent{}
	decisions := map[string]ScenarioEvent{}
	allDecisions := map[string][]ObservedRetry{}
	written := map[int64]ScenarioEvent{}
	consumed := map[int64]bool{}
	dropped := map[int64]bool{}
	checks := map[string]int64{}
	matchedVerdicts := map[int64]bool{}
	envOK, implOK := true, true
	ended, aborted := false, false
	var downAt, upAt int64 = -1, -1
	var triggerCount int64
	var endSequence int64
	implSources := []int64{}
	envSources := []int64{}
	seenStates := map[string]bool{}
	addImpl := func(ok bool, seq int64) {
		if !ok {
			implOK = false
			implSources = append(implSources, seq)
		}
	}
	for _, e := range events {
		if ended || aborted {
			return invalid("events after terminal observation")
		}
		d, err := detailOf(e)
		if err != nil {
			return invalid(err.Error())
		}
		switch v := d.(type) {
		case *EnvironmentDetail:
			if e.Node != "driver" || e.Key != nil || e.Cause != 0 || e.Before != 0 || e.After != 0 || e.Now != 0 || !slices.Contains([]string{"routing", "clock", "recorder"}, v.ID) || checks[v.ID] != 0 {
				return invalid("environment inventory")
			}
			checks[v.ID] = e.Sequence
			envSources = append(envSources, e.Sequence)
			envOK = envOK && v.Passed
		case *OperationDetail:
			s, ok := states[e.Node]
			if !ok || pending[e.Node].Sequence != 0 || e.Before != s.Generation || e.After != e.Before+boolInt(v.Committed) || e.Key == nil || *e.Key != keyFixture() || v.Inputs != int64(len(received[e.Node])) || v.Transactions == nil {
				return invalid("operation generation or input ledger")
			}
			if (e.Kind == "submit_result") != (v.Operation == "submit") || v.Operation != "submit" && v.Operation != "step" {
				return invalid("operation kind")
			}
			if v.Operation == "submit" && (e.Node != "A" || e.Now != 0 || v.Inputs != 0) {
				return invalid("submit context")
			}
			if v.Error != "" {
				m.Rejects++
				addImpl(false, e.Sequence)
			}
			pending[e.Node] = e
			allDecisions[e.Node] = nil
			if !v.Committed {
				if len(v.Transactions) != 0 {
					return invalid("uncommitted transaction facts")
				}
				delete(pending, e.Node)
				received[e.Node] = nil
				verdicts[e.Node] = nil
			}
		case *VerdictDetail:
			if e.Key == nil || *e.Key != keyFixture() || v.Receiver != e.Node || v.Verdict != "accept" && v.Verdict != "reject" {
				return invalid("verdict identity")
			}
			found := false
			for _, r := range received[e.Node] {
				rd, _ := detailOf(r)
				f := rd.(*FrameDetail)
				fixture := frameFixture(frames, f.Direction, f.Kind)
				if !matchedVerdicts[r.Sequence] && fixture != nil && fixture.From == v.Neighbor && fixture.Purpose == v.Purpose && f.Frame == v.Frame {
					found = true
					matchedVerdicts[r.Sequence] = true
					break
				}
			}
			if !found {
				return invalid("verdict has no received input")
			}
			verdicts[e.Node] = append(verdicts[e.Node], e)
			addImpl(v.Verdict == "accept", e.Sequence)
		case *ObservedRetry:
			op, ok := pending[e.Node]
			if !ok || e.Cause != op.Sequence || e.Before != op.Before || e.After != op.After || e.Key == nil || *e.Key != v.Key || v.Key != keyFixture() {
				return invalid("retry lacks committed operation")
			}
			before := states[e.Node]
			q := queueAt(before, v.Kind)
			tb, rb := int64(0), int64(0)
			if q != nil && q.Status != "reserved" {
				tb, rb = q.Timed, q.Recovery
				if q.Start != v.Start || q.Deadline != v.Deadline || q.Neighbor != v.Neighbor {
					return invalid("queue identity widened")
				}
			}
			if v.TimedBefore != tb || v.RecoveryBefore != rb || v.TimedAfter < tb || v.RecoveryAfter < rb {
				return invalid("retry budget discontinuity")
			}
			for _, prior := range allDecisions[e.Node] {
				if prior.Kind == v.Kind {
					return invalid("duplicate queue decision")
				}
			}
			// Independent integer token accounting, including control-first competition.
			buckets := slices.Clone(before.Buckets)
			for _, prior := range allDecisions[e.Node] {
				applyCredits(buckets, e.Node, prior, e.Now)
			}
			gb, nb, ok := expectedCredits(buckets, e.Node, *v, e.Now)
			if !ok || v.GlobalBefore != gb || v.NeighborBefore != nb {
				return invalid("retry credit before mismatch")
			}
			wantG, wantN := gb, nb
			if v.Send {
				wantG -= v.Cost * 1000
				wantN -= v.Cost * 1000
			}
			if v.GlobalAfter != wantG || v.NeighborAfter != wantN {
				return invalid("retry credit after mismatch")
			}
			fixture := frameFixture(frames, direction(e.Node, v.Neighbor), v.Kind)
			if fixture == nil || v.Cost != int64(len(fixture.Body)+4) {
				return invalid("retry frame cost")
			}
			timed := tb
			if e.Now < v.Deadline {
				for i, offset := range []int64{0, 250, 750, 1750, 3750} {
					if int64(i) < tb {
						continue
					}
					if v.Start+offset > e.Now {
						break
					}
					timed++
				}
			}
			recovery := rb
			dir := direction(e.Node, v.Neighbor)
			if rb == 0 && c.fault.Kind == "down" && dir == c.fault.Direction && upAt == e.Now {
				recovery++
			}
			attempt := timed > tb || recovery > rb
			reason, send := "waiting", false
			if !attempt && timed == 5 {
				reason = "timed_slots_exhausted"
			}
			if attempt {
				switch {
				case dir == c.fault.Direction && downAt >= 0 && upAt < 0:
					reason = "blocked_link_down"
				case gb < v.Cost*1000 || nb < v.Cost*1000:
					reason = "rejected_quota"
				default:
					reason, send = "send", true
				}
			}
			if v.Start < 0 || v.Start > e.Now || v.TimedAfter != timed || v.RecoveryAfter != recovery || v.Missed != max(int64(0), timed-tb-1) || v.Attempt != attempt || v.Send != send || v.Reason != reason {
				return invalid("retry decision contradicts schedule")
			}
			addImpl(v.TimedAfter <= 5 && v.RecoveryAfter <= 1 && v.Missed >= 0 && v.GlobalAfter >= 0 && v.NeighborAfter >= 0 && v.Deadline == 30000 && (!v.Send || v.Attempt && v.Reason == "send" && e.Now < 30000), e.Sequence)
			if v.Attempt {
				if v.Kind == "data" {
					m.DataAttempts++
				} else {
					m.ControlAttempts++
				}
			}
			allDecisions[e.Node] = append(allDecisions[e.Node], *v)
			id := queueID(e.Node, v.Key, v.Kind)
			if v.Send {
				decisions[id] = e
			}
		case *ObservedState:
			if v.Version != 1 || v.Node != e.Node || v.Generation != e.After || v.Now != e.Now || len(v.Messages) > 1 || v.Messages == nil || v.Queues == nil || v.Buckets == nil {
				return invalid("snapshot header")
			}
			old, exists := states[e.Node]
			if !slices.Contains([]string{"A", "B", "C"}, e.Node) {
				return invalid("snapshot node")
			}
			if !exists {
				if v.Generation != 0 || e.Cause != 0 || e.Before != 0 || len(v.Messages) != 0 || v.SendSteps != 0 || v.ReceiveSteps != 0 {
					return invalid("initial state")
				}
			} else {
				op, ok := pending[e.Node]
				if !ok || e.Cause != op.Sequence || e.Before != old.Generation || v.Generation != old.Generation+1 {
					return invalid("snapshot missing commit")
				}
			}
			if err := checkObserved(*v, c.size, frames[0].Core); err != nil {
				return invalid(err.Error())
			}
			if exists {
				op := pending[e.Node]
				od, _ := detailOf(op)
				operation := od.(*OperationDetail)
				for _, r := range allDecisions[e.Node] {
					q := queueAt(*v, r.Kind)
					if q == nil || q.Timed != r.TimedAfter || q.Recovery != r.RecoveryAfter {
						return invalid("snapshot and retry disagree")
					}
				}
				expected := slices.Clone(old.Buckets)
				for _, r := range allDecisions[e.Node] {
					applyCredits(expected, e.Node, r, e.Now)
				}
				if !reflect.DeepEqual(expected, v.Buckets) {
					return invalid("snapshot bucket changes lack decisions")
				}
				prev, cur := messageAt(old), messageAt(*v)
				kinds := []string{}
				if operation.Operation == "submit" {
					kinds = append(kinds, "T-A")
				} else if cur != nil && prev == nil {
					kinds = append(kinds, "T-"+e.Node)
				} else if cur != nil && prev != nil {
					if cur.State == "destination_delivered" && prev.State != cur.State {
						kinds = append(kinds, "T-D-"+e.Node)
					}
					if cur.Custody && !prev.Custody {
						kinds = append(kinds, "custody-pause")
					}
					if cur.State == "expired" && prev.State != cur.State {
						kinds = append(kinds, "expiry")
					}
				}
				if len(kinds) == 0 {
					kinds = append(kinds, "schedule")
				}
				if !slices.Equal(operation.Transactions, kinds) {
					return invalid("transaction kinds disagree with committed facts")
				}
				if prev != nil && (cur == nil || cur.Key != prev.Key || cur.Core != prev.Core || cur.Deadline != prev.Deadline) {
					return invalid("message disappeared or widened")
				}
				has := func(purpose string) bool {
					for _, ve := range verdicts[e.Node] {
						vd, _ := detailOf(ve)
						x := vd.(*VerdictDetail)
						if x.Purpose == purpose && x.Verdict == "accept" {
							return true
						}
					}
					return false
				}
				if cur != nil && prev == nil {
					switch e.Node {
					case "A":
						if operation.Operation != "submit" {
							return invalid("origin without submit")
						}
						m.Origin++
					case "B":
						if !has("admission") {
							return invalid("custody without accepted input")
						}
						m.Custody++
					case "C":
						if !has("destination") {
							return invalid("history without accepted input")
						}
						m.Destination++
					}
				}
				if cur != nil && cur.State == "destination_delivered" && (prev == nil || prev.State != cur.State) {
					purpose := "delivery"
					if e.Node == "B" {
						purpose = "relay-clear"
					}
					if !has(purpose) {
						return invalid("delivery without evidence acceptance")
					}
					if e.Node == "A" {
						m.DeliveryA++
						m.Latencies = append(m.Latencies, e.Now)
					} else {
						m.DeliveryB++
					}
				}
				if prev != nil && cur != nil && prev.BodyBytes > 0 && cur.BodyBytes == 0 && e.Node == "B" {
					if e.Now < prev.Deadline {
						q := queueAt(*v, "delivery")
						if !has("relay-clear") || q == nil || q.Status != "active" {
							return invalid("early body release without return duty")
						}
						m.ReleasedB++
					}
				}
				if cur != nil && cur.State == "expired" && (prev == nil || prev.State != "expired") {
					m.Expiries++
					addImpl(e.Now >= cur.Deadline, e.Sequence)
				}
				if cur != nil {
					addImpl(v.ReceiveSteps <= 1 && v.SendSteps <= 1 && v.ActionCount <= 1, e.Sequence)
					if e.Node == "C" {
						addImpl(v.ReceiveSteps == 1 && cur.History, e.Sequence)
					}
				}
				for _, r := range received[e.Node] {
					rd, _ := detailOf(r)
					if prev != nil && rd.(*FrameDetail).Kind == "data" {
						m.Duplicates++
					}
				}
				if len(verdicts[e.Node]) != len(received[e.Node]) && operation.Error == "" {
					return invalid("input verdict count")
				}
				// Queues may only consume budget via reports, and cannot reset when duplicate input arrives.
				for _, q := range v.Queues {
					pq := queueAt(old, q.Kind)
					reported := false
					for _, r := range allDecisions[e.Node] {
						if r.Kind == q.Kind {
							reported = true
						}
					}
					if !reported {
						timed, recovery := int64(0), int64(0)
						if pq != nil {
							timed, recovery = pq.Timed, pq.Recovery
						}
						if q.Timed != timed || q.Recovery != recovery || operation.Operation == "step" && q.Status == "active" {
							return invalid("queue budget change without report")
						}
					}
					if pq != nil && pq.Status != "reserved" {
						if q.Start != pq.Start || q.Timed < pq.Timed || q.Recovery < pq.Recovery {
							return invalid("queue reset")
						}
					}
				}
				if cur != nil {
					terminal := cur.State == "committed" || cur.State == "destination_delivered" || cur.State == "expired"
					addImpl((!terminal || !cur.Transport && cur.Tombstone == 40000) && (terminal || cur.Transport && cur.Tombstone == 0), e.Sequence)
					switch e.Node {
					case "A":
						addImpl(cur.History && v.SendSteps == 1 && v.ReceiveSteps == 0 && v.ActionCount == 1 && slices.Contains([]string{"queued", "destination_delivered", "expired"}, cur.State), e.Sequence)
					case "B":
						addImpl(!cur.History && v.SendSteps == 0 && v.ReceiveSteps == 0 && v.ActionCount == 0 && slices.Contains([]string{"custody_held", "destination_delivered", "expired"}, cur.State), e.Sequence)
					case "C":
						addImpl(cur.History && cur.State == "committed" && v.SendSteps == 0 && v.ReceiveSteps == 1 && v.ActionCount == 0, e.Sequence)
					}
				}
				delete(pending, e.Node)
				received[e.Node] = nil
				verdicts[e.Node] = nil
			}
			states[e.Node] = *v
			seenStates[e.Node] = true
			for i := range m.Peaks {
				if m.Peaks[i].Node == e.Node {
					m.Peaks[i].Usage = peak(m.Peaks[i].Usage, v.Usage)
				}
			}
		case *FrameDetail:
			f := frameFixture(frames, v.Direction, v.Kind)
			if f == nil || e.Key == nil || *e.Key != keyFixture() || v.Core != f.Core || v.Frame != scenarioDigest(f.Body) || v.Bytes != int64(len(f.Body)+4) {
				return invalid("frame identity")
			}
			if e.Before != states[e.Node].Generation || e.After != e.Before {
				return invalid("frame generation")
			}
			if e.Kind == "frame_written" {
				dec, ok := decisions[queueID(e.Node, *e.Key, v.Kind)]
				if !ok || e.Node != f.From || e.Cause != dec.Sequence || v.SendSequence != 0 || e.After != states[e.Node].Generation || e.Now != dec.Now {
					return invalid("write without current consumed send")
				}
				delete(decisions, queueID(e.Node, *e.Key, v.Kind))
				written[e.Sequence] = e
				if v.Kind == "data" {
					m.DataFrames++
				} else {
					m.ControlFrames++
				}
				addImpl(e.Now < 30000, e.Sequence)
				if c.fault.Kind == "drop" && v.Direction == c.fault.Direction && v.Kind == "delivery" {
					triggerCount++
				}
			} else {
				sent, ok := written[v.SendSequence]
				if !ok || consumed[v.SendSequence] || dropped[v.SendSequence] || e.Cause != v.SendSequence || e.Node != f.To || e.Now != sent.Now+50 {
					return invalid("receive source/delay")
				}
				sd, _ := detailOf(sent)
				expected := *sd.(*FrameDetail)
				expected.SendSequence = v.SendSequence
				if *v != expected {
					return invalid("receive frame differs")
				}
				consumed[v.SendSequence] = true
				received[e.Node] = append(received[e.Node], e)
			}
		case *FaultDetail:
			if v.Direction != c.fault.Direction || v.Trigger != c.fault.Trigger || v.Hit != 1 {
				return invalid("fault plan mismatch")
			}
			switch v.Action {
			case "drop":
				sent, ok := written[v.Matched]
				if c.fault.Kind != "drop" || !ok || m.FaultHits != 0 || triggerCount != 1 || consumed[v.Matched] || e.Cause != v.Matched || e.Now != sent.Now {
					return invalid("drop target")
				}
				sd, _ := detailOf(sent)
				f := sd.(*FrameDetail)
				if f.Direction != v.Direction || f.Kind != "delivery" {
					return invalid("wrong-direction drop")
				}
				dropped[v.Matched] = true
				m.FaultHits++
			case "down":
				if c.fault.Kind != "down" || downAt >= 0 || e.Now > 1000 {
					return invalid("down barrier")
				}
				downAt = e.Now
				m.FaultHits++
			case "up":
				if downAt < 0 || upAt >= 0 || e.Now != downAt+5000 {
					return invalid("up barrier")
				}
				upAt = e.Now
			default:
				return invalid("fault action")
			}
		case *EndDetail:
			if e.Node != "driver" || v.Now != 30000 || e.Now != 30000 || v.Pending != 0 || len(pending) != 0 {
				return invalid("observation end")
			}
			for _, name := range []string{"A", "B", "C"} {
				if !seenStates[name] || states[name].Now != 30000 {
					return invalid("missing final snapshot")
				}
			}
			ended = true
			endSequence = e.Sequence
		case *AbortDetail:
			if e.Node != "driver" || v.Now != e.Now || v.Stage == "" || v.Error == "" {
				return invalid("abort fact")
			}
			aborted = true
			endSequence = e.Sequence
			addImpl(false, e.Sequence)
		}
	}
	if !ended && !aborted {
		return invalid("missing observation terminator")
	}
	if len(checks) != 3 {
		return invalid("missing environment checks")
	}
	addImpl(m.Origin == 1 && m.Custody == 1 && m.Destination == 1 && m.DeliveryA == 1 && m.DeliveryB == 1 && m.ReleasedB == 1, endSequence)
	addImpl(len(decisions) == 0, endSequence)
	if c.fault.Kind != "none" {
		if m.FaultHits != 1 {
			if triggerCount > 0 {
				envOK = false
				envSources = append(envSources, endSequence)
			} else {
				addImpl(false, endSequence)
			}
		}
		if c.fault.Kind == "down" {
			addImpl(downAt >= 0 && upAt == downAt+5000, endSequence)
		}
	} else if m.FaultHits != 0 {
		return invalid("unexpected fault")
	}
	for seq := range written {
		if !consumed[seq] && !dropped[seq] && !aborted {
			return invalid("unaccounted written frame")
		}
	}
	m.Samples = int64(len(m.Latencies))
	if res.Schema != c.schema || res.Owned != 3 || res.Removed < 0 || res.Removed > 3 || res.Pending < 0 || res.Children < 0 {
		return invalid("residual structure")
	}
	clean := res.Complete && res.Clean && res.Removed == 3 && res.Pending == 0 && res.Children == 0
	if len(implSources) == 0 {
		implSources = []int64{endSequence}
	}
	assertions.Items = append(assertions.Items, ScenarioAssertion{"environment", "environment", envOK, envSources, "environment_checks"}, ScenarioAssertion{"message_invariants", "implementation", implOK, implSources, "transaction_and_delivery"}, ScenarioAssertion{"cleanup", "environment", clean, []int64{endSequence}, "owned_resources"})
	result := "PASS"
	if !implOK {
		result = "FAIL"
	}
	if !envOK || !clean {
		result = "INVALID"
	}
	return m, assertions, result, nil
}
func boolInt(b bool) int64 {
	if b {
		return 1
	}
	return 0
}
func expectedCredits(bs []ObservedBucket, node string, r ObservedRetry, now int64) (int64, int64, bool) {
	var g, n int64
	found := 0
	class := "control"
	if r.Kind == "data" {
		class = "data"
	}
	for _, b := range bs {
		if now < b.Last {
			return 0, 0, false
		}
		rate, burst := int64(65536), int64(32772000)
		if b.Class == "control" {
			rate, burst = 4096, 4096000
		}
		credit := min(burst, b.Credit+rate*(now-b.Last))
		if b.Neighbor == node && b.Class == "total" {
			g = credit
			found++
		}
		if b.Neighbor == r.Neighbor && b.Class == class {
			n = credit
			found++
		}
	}
	return g, n, found == 2
}
func applyCredits(bs []ObservedBucket, node string, r ObservedRetry, now int64) {
	class := "control"
	if r.Kind == "data" {
		class = "data"
	}
	for i := range bs {
		if bs[i].Neighbor == node && bs[i].Class == "total" {
			bs[i].Credit = r.GlobalAfter
			bs[i].Last = now
		}
		if bs[i].Neighbor == r.Neighbor && bs[i].Class == class {
			bs[i].Credit = r.NeighborAfter
			bs[i].Last = now
		}
	}
}
func checkObserved(s ObservedState, size int64, core string) error {
	usage := ResourceUsage{}
	if s.ActionCount < 0 || s.ActionCount > 4 || s.SendSteps < 0 || s.ReceiveSteps < 0 {
		return errors.New("snapshot counters")
	}
	for _, m := range s.Messages {
		if m.Key != keyFixture() || m.Core != core || m.PayloadBytes != size || m.Deadline != 30000 || m.BodyBytes != 0 && m.BodyBytes != size {
			return errors.New("snapshot message")
		}
		if m.History || m.Transport {
			if m.BodyBytes != size {
				return errors.New("retained body missing")
			}
		} else if m.BodyBytes != 0 {
			return errors.New("unaccounted body")
		}
		if m.Transport {
			usage.PayloadObjects++
			usage.PayloadBytes += m.BodyBytes
		}
		if m.History {
			usage.HistoryObjects++
			usage.HistoryBytes += m.BodyBytes
		}
	}
	kinds := []string{"data"}
	neighbors := []string{"B"}
	if s.Node == "B" {
		kinds = []string{"custody", "data", "delivery"}
		neighbors = []string{"A", "C"}
	}
	if s.Node == "C" {
		kinds = []string{"delivery"}
	}
	if len(s.Queues) != len(s.Messages)*len(kinds) {
		return errors.New("snapshot responsibilities")
	}
	for i, q := range s.Queues {
		if q.Key != keyFixture() || q.Kind != kinds[i] || q.Timed < 0 || q.Recovery < 0 {
			return errors.New("queue inventory")
		}
		if !slices.Contains([]string{"reserved", "active", "paused", "stopped", "expired", "schedule_limit"}, q.Status) {
			return errors.New("queue status")
		}
		neighbor, hops := "B", int64(0)
		if s.Node == "A" {
			hops = 1
		}
		if s.Node == "B" {
			neighbor = "A"
			if q.Kind == "data" {
				neighbor = "C"
			}
		}
		if q.Neighbor != neighbor || q.Hops != hops {
			return errors.New("queue route or hop")
		}
		if q.Status == "reserved" {
			if s.Node != "B" || q.Kind != "delivery" || q.Start != 0 || q.Deadline != 0 || q.Timed != 0 || q.Recovery != 0 {
				return errors.New("reserved queue")
			}
		} else if q.Start < 0 || q.Start > s.Now || q.Deadline != 30000 {
			return errors.New("queue lifetime")
		}
	}
	want := []ObservedBucket{{Neighbor: s.Node, Class: "total"}}
	for _, n := range neighbors {
		want = append(want, ObservedBucket{Neighbor: n, Class: "control"}, ObservedBucket{Neighbor: n, Class: "data"})
	}
	slices.SortFunc(want, func(a, b ObservedBucket) int { return strings.Compare(a.Neighbor+"/"+a.Class, b.Neighbor+"/"+b.Class) })
	if len(want) != len(s.Buckets) {
		return errors.New("bucket inventory")
	}
	for i, b := range s.Buckets {
		limit := int64(32772000)
		if b.Class == "control" {
			limit = 4096000
		}
		if b.Neighbor != want[i].Neighbor || b.Class != want[i].Class || b.Credit < 0 || b.Credit > limit || b.Last < 0 || b.Last > s.Now {
			return errors.New("bucket bounds")
		}
	}
	usage.ControlObjects = int64(len(s.Messages)+len(s.Queues)+len(s.Buckets)) + s.ActionCount
	usage.ControlBytes = int64(len(s.Messages)*2048+len(s.Queues)*8192+len(s.Buckets)*512) + s.ActionCount*512
	if usage != s.Usage {
		return errors.New("resource accounting")
	}
	return nil
}
