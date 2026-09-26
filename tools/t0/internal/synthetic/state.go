package synthetic

import (
	"encoding/json"
	"math"
	"sort"

	"radishlink.local/t0/internal/delivery"
)

const maxStateBytes = 1048576

type messageCore struct {
	Mode         string `json:"security_mode"`
	Kind         string `json:"kind"`
	Run          string `json:"run_id"`
	Destination  string `json:"destination"`
	Originated   int64  `json:"originated_ms"`
	Lifetime     int64  `json:"lifetime_ms"`
	InitialHops  int64  `json:"initial_hops"`
	Priority     string `json:"priority"`
	PayloadKind  string `json:"payload_kind"`
	PayloadBytes int64  `json:"payload_bytes"`
}
type message struct {
	Key         Key         `json:"key"`
	Core        messageCore `json:"core"`
	Fingerprint string      `json:"core_sha256"`
	Body        string      `json:"body_b64"`
	Deadline    int64       `json:"accepted_deadline_ms"`
	State       string      `json:"state"`
	CustodySeen bool        `json:"custody_seen"`
	Transport   bool        `json:"transport_retained"`
	History     bool        `json:"history_retained"`
	Tombstone   int64       `json:"tombstone_until_ms"`
}

func messageFrom(e Envelope) message {
	return message{Key: e.Key(), Core: messageCore{e.Mode, e.Kind, e.Run, e.Destination, e.Originated, e.Lifetime, e.InitialHops, e.Priority, e.PayloadKind, e.PayloadBytes}, Fingerprint: e.Fingerprint, Body: e.Body, Deadline: e.deadline()}
}
func (m message) envelope(kind string, hops int64) Envelope {
	e := Envelope{dataWire: dataWire{header: header{m.Key.Version, m.Core.Mode, kind, m.Core.Run, m.Key.Origin, m.Key.Scope, m.Key.ID, m.Core.Destination}, Fingerprint: m.Fingerprint}}
	if kind == "data" {
		e.Originated, e.Lifetime, e.InitialHops, e.RemainingHops = m.Core.Originated, m.Core.Lifetime, m.Core.InitialHops, hops
		e.Priority, e.PayloadKind, e.PayloadBytes, e.Body = m.Core.Priority, m.Core.PayloadKind, m.Core.PayloadBytes, m.Body
	} else {
		e.Issuer, e.Recipient = "B", "A"
		if kind == "delivery" {
			e.Issuer = "C"
		}
	}
	return e
}

type action struct {
	Ref         string `json:"action_ref"`
	Key         Key    `json:"key"`
	Fingerprint string `json:"core_sha256"`
}
type retryBatch struct {
	Now       int64  `json:"now_ms"`
	Link      string `json:"link"`
	Signal    string `json:"signal"`
	Admission string `json:"admission"`
}

func (b retryBatch) value() (delivery.RetryBatch, error) {
	v := delivery.RetryBatch{NowMS: b.Now}
	switch b.Link {
	case "unchanged":
		v.Link = delivery.LinkUnchanged
	case "became_up":
		v.Link = delivery.LinkBecameUp
	case "became_down":
		v.Link = delivery.LinkBecameDown
	default:
		return v, fail("STORE_INVALID", "batch link")
	}
	switch b.Signal {
	case "continue":
		v.Signal = delivery.RetryContinue
	case "pause":
		v.Signal = delivery.RetryPause
	case "stop":
		v.Signal = delivery.RetryStop
	default:
		return v, fail("STORE_INVALID", "batch signal")
	}
	switch b.Admission {
	case "admit":
		v.Admission = delivery.Admit
	case "reject_quota":
		v.Admission = delivery.RejectQuota
	case "reject_hop":
		v.Admission = delivery.RejectHop
	default:
		return v, fail("STORE_INVALID", "batch admission")
	}
	if b.Now < 0 || b.Now > 100000 {
		return v, fail("STORE_INVALID", "batch time")
	}
	return v, nil
}

type queue struct {
	Key         Key          `json:"key"`
	Kind        string       `json:"kind"`
	Neighbor    string       `json:"neighbor"`
	Status      string       `json:"status"`
	Hops        int64        `json:"remaining_hops"`
	Start       int64        `json:"start_ms"`
	Deadline    int64        `json:"deadline_ms"`
	InitialLink string       `json:"initial_link"`
	Batches     []retryBatch `json:"batches"`
}

func (q queue) order() string { return q.Key.order() + "/" + q.Kind + "/" + q.Neighbor }
func (q queue) replay() (delivery.RetryState, error) {
	link := delivery.LinkDown
	if q.InitialLink == "up" {
		link = delivery.LinkUp
	} else if q.InitialLink != "down" {
		return delivery.RetryState{}, fail("STORE_INVALID", "initial link")
	}
	s, err := delivery.NewRetryState(q.Start, q.Deadline, link)
	if err != nil {
		return s, err
	}
	if q.Batches == nil || len(q.Batches) > 64 {
		return s, fail("STORE_INVALID", "batch count")
	}
	var last delivery.RetryDecision
	for i, b := range q.Batches {
		if i > 0 && b.Now <= q.Batches[i-1].Now {
			return s, fail("STORE_INVALID", "batch order")
		}
		v, err := b.value()
		if err != nil {
			return s, err
		}
		s, last, err = s.Advance(v)
		if err != nil {
			return s, err
		}
	}
	if q.Status == "active" && (last.Reason == delivery.RetryStopped || last.Reason == delivery.RetryPaused || last.Reason == delivery.RetryExpired) {
		return s, fail("STORE_INVALID", "active retry phase")
	}
	return s, nil
}
func (q *queue) advance(b retryBatch) (delivery.RetryDecision, error) {
	s, err := q.replay()
	if err != nil {
		return delivery.RetryDecision{}, err
	}
	v, err := b.value()
	if err != nil {
		return delivery.RetryDecision{}, err
	}
	_, decision, err := s.Advance(v)
	if err != nil {
		return decision, wrap("REJECT_CONTEXT", "retry batch", err)
	}
	if decision.Reason == delivery.RetryDuplicateBatch {
		return decision, nil
	}
	if len(q.Batches) == 64 {
		q.Status = "schedule_limit"
		return delivery.RetryDecision{}, fail("SCHEDULE_LIMIT", "queue ledger")
	}
	q.Batches = append(q.Batches, b)
	return decision, nil
}

type bucket struct {
	Neighbor string `json:"neighbor"`
	Class    string `json:"class"`
	Credit   int64  `json:"credit_millibytes"`
	Last     int64  `json:"last_refill_ms"`
}

func (b bucket) order() string { return b.Neighbor + "/" + b.Class }
func (b bucket) limits() (int64, int64) {
	if b.Class == "control" {
		return 4096, 4096000
	}
	return 65536, 32772000
}
func (b *bucket) refill(now int64) error {
	if now < b.Last || now > 100000 {
		return fail("TIME_UNCERTAIN", "bucket clock")
	}
	rate, burst := b.limits()
	delta := now - b.Last
	if delta > (math.MaxInt64-b.Credit)/rate {
		return fail("REJECT_QUOTA", "bucket overflow")
	}
	b.Credit = min(burst, b.Credit+rate*delta)
	b.Last = now
	return nil
}

type state struct {
	Version      int64     `json:"store_version"`
	Limits       string    `json:"limits_id"`
	Run          string    `json:"run_id"`
	Node         string    `json:"node"`
	Generation   int64     `json:"generation"`
	Epoch        string    `json:"clock_epoch"`
	Now          int64     `json:"last_now_ms"`
	SendSteps    int64     `json:"synthetic_send_steps"`
	ReceiveSteps int64     `json:"synthetic_receive_steps"`
	Messages     []message `json:"messages"`
	Actions      []action  `json:"actions"`
	Queues       []queue   `json:"queues"`
	Buckets      []bucket  `json:"buckets"`
	Checksum     string    `json:"checksum_sha256"`
}

func neighbors(node string) []string {
	switch node {
	case "A", "C":
		return []string{"B"}
	case "B":
		return []string{"A", "C"}
	}
	return nil
}
func newState(run, node, epoch string) state {
	s := state{Version: 1, Limits: "i3-small4-v1", Run: run, Node: node, Epoch: epoch, Messages: []message{}, Actions: []action{}, Queues: []queue{}, Buckets: []bucket{{Neighbor: node, Class: "total"}}}
	for _, n := range neighbors(node) {
		s.Buckets = append(s.Buckets, bucket{Neighbor: n, Class: "data"}, bucket{Neighbor: n, Class: "control"})
	}
	s.sort()
	return s
}
func (s *state) sort() {
	sort.Slice(s.Messages, func(i, j int) bool { return s.Messages[i].Key.order() < s.Messages[j].Key.order() })
	sort.Slice(s.Actions, func(i, j int) bool { return s.Actions[i].Ref < s.Actions[j].Ref })
	sort.Slice(s.Queues, func(i, j int) bool { return s.Queues[i].order() < s.Queues[j].order() })
	sort.Slice(s.Buckets, func(i, j int) bool { return s.Buckets[i].order() < s.Buckets[j].order() })
}
func (s state) clone() state {
	n := s
	n.Messages = append([]message{}, s.Messages...)
	n.Actions = append([]action{}, s.Actions...)
	n.Queues = append([]queue{}, s.Queues...)
	n.Buckets = append([]bucket{}, s.Buckets...)
	for i := range n.Queues {
		n.Queues[i].Batches = append([]retryBatch{}, s.Queues[i].Batches...)
	}
	return n
}
func (s *state) find(k Key) *message {
	for i := range s.Messages {
		if s.Messages[i].Key == k {
			return &s.Messages[i]
		}
	}
	return nil
}
func (s *state) findQueue(k Key, kind string) *queue {
	for i := range s.Queues {
		if s.Queues[i].Key == k && s.Queues[i].Kind == kind {
			return &s.Queues[i]
		}
	}
	return nil
}
func (s *state) bucketFor(neighbor, class string) *bucket {
	for i := range s.Buckets {
		if s.Buckets[i].Neighbor == neighbor && s.Buckets[i].Class == class {
			return &s.Buckets[i]
		}
	}
	return nil
}
func (s *state) credits(neighbor, kind string, now int64) (*bucket, *bucket, error) {
	class := "control"
	if kind == "data" {
		class = "data"
	}
	a, b := s.bucketFor(s.Node, "total"), s.bucketFor(neighbor, class)
	if a == nil || b == nil {
		return nil, nil, fail("STORE_INVALID", "missing bucket")
	}
	if err := a.refill(now); err != nil {
		return nil, nil, err
	}
	if err := b.refill(now); err != nil {
		return nil, nil, err
	}
	return a, b, nil
}
func ordered(previous, current string, i int) bool { return i == 0 || previous < current }
func fits(v any, limit int) bool                   { b, err := json.Marshal(v); return err == nil && len(b) <= limit }

func (s state) validate() error {
	if s.Version != 1 || s.Limits != "i3-small4-v1" || !lowerHex(s.Run, 32) || !lowerHex(s.Epoch, 32) || neighbors(s.Node) == nil || s.Generation < 0 || s.Now < 0 || s.Now > 100000 {
		return fail("STORE_INVALID", "state header")
	}
	if s.Messages == nil || s.Actions == nil || s.Queues == nil || s.Buckets == nil || len(s.Messages) > 128 || len(s.Queues) > 128 || len(s.Actions) > 4 {
		return fail("REJECT_QUOTA", "state arrays")
	}
	objects := len(s.Messages) + len(s.Queues) + len(s.Actions) + len(s.Buckets)
	charge := len(s.Messages)*2048 + len(s.Queues)*8192 + len(s.Actions)*512 + len(s.Buckets)*512
	if objects > 128 || charge > 262144 {
		return fail("REJECT_QUOTA", "metadata reservations")
	}
	var pending, history int
	var pendingBytes, historyBytes int64
	var scope, previous string
	for i, m := range s.Messages {
		if !m.Key.valid() || !ordered(previous, m.Key.order(), i) || !lowerHex(m.Fingerprint, 64) {
			return fail("STORE_INVALID", "message key")
		}
		previous = m.Key.order()
		if scope != "" && scope != m.Key.Scope {
			return fail("STORE_INVALID", "multiple scopes")
		}
		scope = m.Key.Scope
		c := m.Core
		if c.Mode != "synthetic" || c.Kind != "data" || c.Run != s.Run || c.Destination != "C" || c.Originated < 0 || c.Originated > min(int64(60000), s.Now) || c.Lifetime < 1 || c.Lifetime > 30000 || c.InitialHops != 2 || c.Priority != "normal" || c.PayloadKind != "synthetic_opaque" || c.PayloadBytes < 1 || c.PayloadBytes > 16384 || m.Deadline < c.Originated || m.Deadline > c.Originated+c.Lifetime {
			return fail("STORE_INVALID", "message core")
		}
		if m.Body != "" {
			if err := m.envelope("data", 0).validate(); err != nil {
				return wrap("STORE_INVALID", "retained body", err)
			}
		}
		if (m.History || m.Transport) != (m.Body != "") {
			return fail("STORE_INVALID", "body retention")
		}
		if m.Transport {
			pending++
			pendingBytes += c.PayloadBytes
		}
		if m.History {
			history++
			historyBytes += c.PayloadBytes
		}
		meta := m
		meta.Body = ""
		if !fits(meta, 2048) {
			return fail("REJECT_QUOTA", "message metadata")
		}
		terminal := m.State == "expired" || m.State == "destination_delivered" || m.State == "committed"
		if terminal {
			if m.Tombstone != m.Deadline+10000 || m.Transport {
				return fail("STORE_INVALID", "terminal retention")
			}
		} else if m.Tombstone != 0 || !m.Transport {
			return fail("STORE_INVALID", "pending retention")
		}
		switch s.Node {
		case "A":
			if !m.History || !(m.State == "queued" || m.State == "destination_delivered" || m.State == "expired") {
				return fail("STORE_INVALID", "origin facts")
			}
		case "B":
			if m.History || m.CustodySeen || !(m.State == "custody_held" || m.State == "destination_delivered" || m.State == "expired") {
				return fail("STORE_INVALID", "relay facts")
			}
		case "C":
			if !m.History || m.CustodySeen || m.State != "committed" {
				return fail("STORE_INVALID", "destination facts")
			}
		}
	}
	if pending > 4 || pendingBytes > 65536 || history > 4 || historyBytes > 65536 {
		return fail("REJECT_QUOTA", "payload or history")
	}
	if s.SendSteps < 0 || s.SendSteps > 4 || s.ReceiveSteps < 0 || s.ReceiveSteps > 4 {
		return fail("STORE_INVALID", "synthetic counters")
	}
	if s.Node == "A" {
		if s.SendSteps != int64(len(s.Actions)) || len(s.Actions) != len(s.Messages) || s.ReceiveSteps != 0 {
			return fail("STORE_INVALID", "origin counters")
		}
	} else if len(s.Actions) != 0 || s.SendSteps != 0 || s.Node == "B" && s.ReceiveSteps != 0 || s.Node == "C" && s.ReceiveSteps != int64(history) {
		return fail("STORE_INVALID", "role counters")
	}
	previous = ""
	actionKeys := map[Key]bool{}
	for i, a := range s.Actions {
		m := s.find(a.Key)
		if !label(a.Ref) || !ordered(previous, a.Ref, i) || m == nil || a.Fingerprint != m.Fingerprint || actionKeys[a.Key] || !fits(a, 512) {
			return fail("STORE_INVALID", "action binding")
		}
		previous = a.Ref
		actionKeys[a.Key] = true
	}
	previous = ""
	for i, q := range s.Queues {
		m := s.find(q.Key)
		if m == nil || !ordered(previous, q.order(), i) || !fits(q, 8192) {
			return fail("STORE_INVALID", "queue reference")
		}
		previous = q.order()
		wantNeighbor, wantHops := "B", int64(0)
		switch s.Node {
		case "A":
			if q.Kind != "data" {
				return fail("STORE_INVALID", "origin queue")
			}
			wantHops = 1
		case "B":
			if q.Kind == "data" {
				wantNeighbor = "C"
			} else if q.Kind == "custody" || q.Kind == "delivery" {
				wantNeighbor = "A"
			} else {
				return fail("STORE_INVALID", "relay queue")
			}
		case "C":
			if q.Kind != "delivery" {
				return fail("STORE_INVALID", "destination queue")
			}
		}
		if q.Neighbor != wantNeighbor || q.Hops != wantHops || q.Batches == nil || len(q.Batches) > 64 {
			return fail("STORE_INVALID", "queue fields")
		}
		if q.Status == "reserved" {
			if s.Node != "B" || q.Kind != "delivery" || m.State == "destination_delivered" || q.Start != 0 || q.Deadline != 0 || q.InitialLink != "down" || len(q.Batches) != 0 {
				return fail("STORE_INVALID", "reservation")
			}
			continue
		}
		if q.Start < m.Core.Originated || q.Start > s.Now || q.Deadline != m.Deadline {
			return fail("STORE_INVALID", "queue time")
		}
		switch q.Status {
		case "active", "paused", "stopped", "expired", "schedule_limit":
		default:
			return fail("STORE_INVALID", "queue status")
		}
		if q.Status == "paused" && (s.Node != "A" || !m.CustodySeen || m.State != "queued") {
			return fail("STORE_INVALID", "custody pause")
		}
		if s.Node == "A" && m.State == "queued" && m.CustodySeen && q.Status != "paused" {
			return fail("STORE_INVALID", "custody must pause")
		}
		if q.Status == "active" && (q.Kind == "data" && !m.Transport || q.Kind == "custody" && m.State != "custody_held" || q.Kind == "delivery" && m.State != "committed" && m.State != "destination_delivered") {
			return fail("STORE_INVALID", "active responsibility")
		}
		if q.Status == "schedule_limit" && len(q.Batches) != 64 {
			return fail("STORE_INVALID", "schedule limit")
		}
		for _, b := range q.Batches {
			if b.Now > s.Now {
				return fail("STORE_INVALID", "future batch")
			}
		}
		if _, err := q.replay(); err != nil {
			return wrap("STORE_INVALID", "retry replay", err)
		}
	}
	for _, m := range s.Messages {
		kinds := []string{"data"}
		if s.Node == "B" {
			kinds = []string{"data", "custody", "delivery"}
		}
		if s.Node == "C" {
			kinds = []string{"delivery"}
		}
		for _, kind := range kinds {
			if s.findQueue(m.Key, kind) == nil {
				return fail("STORE_INVALID", "missing responsibility")
			}
		}
	}
	want := newState(s.Run, s.Node, s.Epoch).Buckets
	if len(want) != len(s.Buckets) {
		return fail("STORE_INVALID", "bucket inventory")
	}
	for i, b := range s.Buckets {
		_, burst := b.limits()
		if b.order() != want[i].order() || b.Credit < 0 || b.Credit > burst || b.Last < 0 || b.Last > s.Now || !fits(b, 512) {
			return fail("STORE_INVALID", "bucket bounds")
		}
	}
	return nil
}
