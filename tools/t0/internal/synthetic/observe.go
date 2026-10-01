package synthetic

import "radishlink.local/t0/internal/harness"

// Snapshot is a detached, body-free observation of published state.
func (n *Node) Snapshot() (harness.ObservedState, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.storage.halted {
		return harness.ObservedState{}, fail("STORE_OUTCOME_UNKNOWN", "snapshot while halted")
	}
	return observe(n.storage.current)
}

type BatchReport struct {
	Committed     bool
	Before, After int64
	Transactions  []string
	Decisions     []harness.ObservedRetry
}

func observe(s state) (harness.ObservedState, error) {
	v := harness.ObservedState{Version: 1, Node: s.Node, Generation: s.Generation, Now: s.Now, SendSteps: s.SendSteps, ReceiveSteps: s.ReceiveSteps, ActionCount: int64(len(s.Actions)), Messages: []harness.ObservedMessage{}, Queues: []harness.ObservedQueue{}, Buckets: []harness.ObservedBucket{}}
	for _, m := range s.Messages {
		size := int64(0)
		if m.Body != "" {
			size = m.Core.PayloadBytes
		}
		v.Messages = append(v.Messages, harness.ObservedMessage{Key: harness.ObservedKey(m.Key), Core: m.Fingerprint, Deadline: m.Deadline, State: m.State, Custody: m.CustodySeen, History: m.History, Transport: m.Transport, BodyBytes: size, PayloadBytes: m.Core.PayloadBytes, Tombstone: m.Tombstone})
		if m.Transport {
			v.Usage.PayloadObjects++
			v.Usage.PayloadBytes += size
		}
		if m.History {
			v.Usage.HistoryObjects++
			v.Usage.HistoryBytes += size
		}
	}
	for _, q := range s.Queues {
		timed, recovery, err := q.consumed()
		if err != nil {
			return harness.ObservedState{}, err
		}
		v.Queues = append(v.Queues, harness.ObservedQueue{Key: harness.ObservedKey(q.Key), Kind: q.Kind, Neighbor: q.Neighbor, Start: q.Start, Deadline: q.Deadline, Hops: q.Hops, Status: q.Status, Timed: timed, Recovery: recovery})
	}
	for _, b := range s.Buckets {
		v.Buckets = append(v.Buckets, harness.ObservedBucket{Neighbor: b.Neighbor, Class: b.Class, Credit: b.Credit, Last: b.Last})
	}
	v.Usage.ControlObjects = int64(len(s.Messages) + len(s.Queues) + len(s.Actions) + len(s.Buckets))
	v.Usage.ControlBytes = int64(len(s.Messages)*2048 + len(s.Queues)*8192 + len(s.Actions)*512 + len(s.Buckets)*512)
	return v, nil
}
func transactionKinds(before, after state) []string {
	kinds := []string{}
	for _, m := range after.Messages {
		old := before.find(m.Key)
		if old == nil {
			if after.Node == "B" {
				kinds = append(kinds, "T-B")
			} else if after.Node == "C" {
				kinds = append(kinds, "T-C")
			}
		} else {
			if m.State == "destination_delivered" && old.State != m.State {
				kinds = append(kinds, "T-D-"+after.Node)
			}
			if m.CustodySeen && !old.CustodySeen {
				kinds = append(kinds, "custody-pause")
			}
			if m.State == "expired" && old.State != m.State {
				kinds = append(kinds, "expiry")
			}
		}
	}
	if len(kinds) == 0 {
		kinds = append(kinds, "schedule")
	}
	return kinds
}
