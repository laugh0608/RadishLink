package synthetic

import (
	"encoding/base64"
	"io"
	"sort"
	"sync"

	"radishlink.local/t0/internal/delivery"
)

type Verdict uint8

const (
	VerdictAccept Verdict = iota + 1
	VerdictReject
)

type VerdictRequest struct {
	Receiver, Neighbor, FrameSHA256, Purpose string
	Key                                      Key
}
type VerdictSource func(VerdictRequest) Verdict
type Config struct {
	Run, Node, Scope, Epoch string
	Verdicts                VerdictSource
}

func (c Config) validate() error {
	if !lowerHex(c.Run, 32) || neighbors(c.Node) == nil || !label(c.Scope) || !lowerHex(c.Epoch, 32) || c.Verdicts == nil {
		return fail("REJECT_CONTEXT", "node config")
	}
	return nil
}

type Node struct {
	mu            sync.Mutex
	config        Config
	storage       *store
	floor         int64
	opportunities map[string]bool
}

func InitNode(directory string, c Config) (*Node, error) {
	if err := c.validate(); err != nil {
		return nil, err
	}
	s, err := initStore(directory, c.Run, c.Node, c.Epoch)
	if err != nil {
		return nil, err
	}
	return &Node{config: c, storage: s}, nil
}
func OpenNode(directory string, c Config, r Recovery) (*Node, error) {
	if err := c.validate(); err != nil {
		return nil, err
	}
	if c.Epoch != r.Epoch {
		return nil, fail("TIME_UNCERTAIN", "configured epoch")
	}
	s, err := openStore(directory, c.Run, c.Node, r)
	if err != nil {
		return nil, err
	}
	for _, m := range s.current.Messages {
		if m.Key.Scope != c.Scope {
			return nil, fail("STORE_INVALID", "configured scope")
		}
	}
	return &Node{config: c, storage: s, floor: r.Now}, nil
}

type MessageView struct {
	Mode        string
	Key         Key
	State       string
	CustodySeen bool
	Body        []byte
}

func view(m message) (MessageView, error) {
	v := MessageView{Mode: "synthetic", Key: m.Key, State: m.State, CustodySeen: m.CustodySeen}
	if m.History {
		b, err := decodeBody(m.Body, m.Core.PayloadBytes)
		if err != nil {
			return MessageView{}, err
		}
		v.Body = b
	}
	return v, nil
}
func (n *Node) Query(ref string) (MessageView, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.storage.halted {
		return MessageView{}, fail("STORE_OUTCOME_UNKNOWN", "query while halted")
	}
	for _, a := range n.storage.current.Actions {
		if a.Ref == ref {
			m := n.storage.current.find(a.Key)
			if m != nil {
				return view(*m)
			}
		}
	}
	return MessageView{}, fail("REJECT_CONTEXT", "unknown action")
}
func (n *Node) History() ([]MessageView, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.storage.halted {
		return nil, fail("STORE_OUTCOME_UNKNOWN", "history while halted")
	}
	out := []MessageView{}
	for _, m := range n.storage.current.Messages {
		if m.History {
			v, err := view(m)
			if err != nil {
				return nil, err
			}
			out = append(out, v)
		}
	}
	return out, nil
}
func (n *Node) Generation() int64 {
	n.mu.Lock()
	defer n.mu.Unlock()
	return n.storage.current.Generation
}
func (n *Node) checkTime(now int64) error {
	if n.storage.halted {
		return fail("STORE_OUTCOME_UNKNOWN", "node halted")
	}
	if now < n.floor || now < n.storage.current.Now || now > 100000 {
		return fail("TIME_UNCERTAIN", "node clock")
	}
	return nil
}
func (n *Node) commit(s state) error {
	s.sort()
	s.Generation = n.storage.current.Generation + 1
	if err := s.validate(); err != nil {
		return err
	}
	if err := n.storage.save(s); err != nil {
		return err
	}
	n.opportunities = map[string]bool{}
	return nil
}
func newQueue(m message, kind, neighbor string, now int64, hops int64, reserved bool) queue {
	q := queue{Key: m.Key, Kind: kind, Neighbor: neighbor, Status: "active", Hops: hops, Start: now, Deadline: m.Deadline, InitialLink: "up", Batches: []retryBatch{}}
	if reserved {
		q.Status, q.Start, q.Deadline, q.InitialLink = "reserved", 0, 0, "down"
	}
	return q
}

// Submit is a local fixture action; the ID and bytes are not real user credentials.
func (n *Node) Submit(ref, id string, body []byte, now, lifetime int64) (MessageView, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if err := n.checkTime(now); err != nil {
		return MessageView{}, err
	}
	if n.config.Node != "A" || !label(ref) || !lowerHex(id, 32) {
		return MessageView{}, fail("REJECT_CONTEXT", "submit scope")
	}
	if err := delivery.CheckLength(delivery.SyntheticPayloadLength, int64(len(body)), int64(len(body))); err != nil {
		return MessageView{}, wrap("REJECT_STRUCTURE", "submit length", err)
	}
	// A repeated action retains its original creation time rather than renewing lifetime.
	originated := now
	for _, a := range n.storage.current.Actions {
		if a.Ref == ref {
			originated = n.storage.current.find(a.Key).Core.Originated
		}
	}
	e := Envelope{dataWire: dataWire{header: header{1, "synthetic", "data", n.config.Run, "A", n.config.Scope, id, "C"}, Originated: originated, Lifetime: lifetime, InitialHops: 2, RemainingHops: 1, Priority: "normal", PayloadKind: "synthetic_opaque", PayloadBytes: int64(len(body)), Body: base64.StdEncoding.EncodeToString(body)}}
	e.Fingerprint = e.fingerprint()
	if err := e.validate(); err != nil {
		return MessageView{}, err
	}
	for _, a := range n.storage.current.Actions {
		if a.Ref == ref {
			if a.Key != e.Key() || a.Fingerprint != e.Fingerprint {
				return MessageView{}, fail("CONFLICT", "action binding")
			}
			return view(*n.storage.current.find(a.Key))
		}
	}
	if n.storage.current.find(e.Key()) != nil {
		return MessageView{}, fail("CONFLICT", "message already bound")
	}
	s := n.storage.current.clone()
	m := messageFrom(e)
	m.State, m.Transport, m.History = "queued", true, true
	s.Messages = append(s.Messages, m)
	s.Actions = append(s.Actions, action{ref, e.Key(), e.Fingerprint})
	s.Queues = append(s.Queues, newQueue(m, "data", "B", now, 1, false))
	s.SendSteps++
	s.Now = now
	if err := n.commit(s); err != nil {
		return MessageView{}, err
	}
	return view(m)
}

type Input struct {
	Neighbor string
	Frame    []byte
}
type Link struct{ Neighbor, Event string }
type Batch struct {
	Now    int64
	Inputs []Input
	Links  []Link
}

// Transmission is a consumed opportunity. Write sends it at most once in this process.
type Transmission struct {
	node           *Node
	generation     int64
	key            Key
	kind, neighbor string
	envelope       Envelope
	used           bool
}

func (t *Transmission) Neighbor() string { return t.neighbor }
func (t *Transmission) Write(w io.Writer, now int64) error {
	n := t.node
	n.mu.Lock()
	defer n.mu.Unlock()
	if t.used {
		return fail("REJECT_CONTEXT", "opportunity already used")
	}
	t.used = true
	if t.generation != n.storage.current.Generation {
		return fail("EXPIRED", "send generation no longer current")
	}
	id := t.key.order() + "/" + t.kind + "/" + t.neighbor
	if !n.opportunities[id] {
		return fail("REJECT_CONTEXT", "opportunity unavailable")
	}
	n.opportunities[id] = false
	if err := n.checkTime(now); err != nil {
		return err
	}
	q := n.storage.current.findQueue(t.key, t.kind)
	if q == nil || q.Status != "active" || now >= q.Deadline {
		return fail("EXPIRED", "send no longer current")
	}
	return WriteEnvelope(w, t.envelope)
}
func (n *Node) verdict(e Envelope, neighbor, purpose string) error {
	b, err := e.Encode()
	if err != nil {
		return err
	}
	v := n.config.Verdicts(VerdictRequest{n.config.Node, neighbor, digest(b), purpose, e.Key()})
	if v != VerdictAccept {
		return fail("REJECT_VERDICT", purpose)
	}
	return nil
}
func (n *Node) receive(s *state, in Input, e Envelope, now int64) error {
	if e.Run != n.config.Run || e.Scope != n.config.Scope {
		return fail("REJECT_CONTEXT", "frame scope")
	}
	purpose := ""
	if e.Kind == "data" {
		if e.Originated > now {
			return fail("TIME_UNCERTAIN", "future origin")
		}
		if now >= e.deadline() {
			return fail("EXPIRED", "data deadline")
		}
		if n.config.Node == "B" && in.Neighbor == "A" {
			purpose = "admission"
			if e.RemainingHops != 1 {
				return fail("REJECT_HOP", "AB")
			}
		} else if n.config.Node == "C" && in.Neighbor == "B" {
			purpose = "destination"
			if e.RemainingHops != 0 {
				return fail("REJECT_HOP", "BC")
			}
		} else {
			return fail("REJECT_CONTEXT", "data route")
		}
	} else if e.Kind == "custody" && n.config.Node == "A" && in.Neighbor == "B" {
		purpose = "custody"
	} else if e.Kind == "delivery" && n.config.Node == "B" && in.Neighbor == "C" {
		purpose = "relay-clear"
	} else if e.Kind == "delivery" && n.config.Node == "A" && in.Neighbor == "B" {
		purpose = "delivery"
	} else {
		return fail("REJECT_CONTEXT", "control route")
	}
	if err := n.verdict(e, in.Neighbor, purpose); err != nil {
		return err
	}
	m := s.find(e.Key())
	if m != nil && m.Fingerprint != e.Fingerprint {
		return fail("CONFLICT", "stored core")
	}
	if m != nil && now >= m.Deadline {
		return fail("EXPIRED", "accepted deadline")
	}
	if e.Kind == "data" {
		if m != nil {
			return nil
		}
		created := messageFrom(e)
		if n.config.Node == "B" {
			created.State, created.Transport = "custody_held", true
			s.Queues = append(s.Queues, newQueue(created, "data", "C", now, 0, false), newQueue(created, "custody", "A", now, 0, false), newQueue(created, "delivery", "A", now, 0, true))
		} else {
			created.State, created.History, created.Tombstone = "committed", true, created.Deadline+10000
			s.ReceiveSteps++
			s.Queues = append(s.Queues, newQueue(created, "delivery", "B", now, 0, false))
		}
		s.Messages = append(s.Messages, created)
		return nil
	}
	if m == nil {
		return fail("REJECT_CONTEXT", "unknown evidence key")
	}
	if e.Kind == "custody" {
		if m.State == "queued" {
			m.CustodySeen = true
			s.findQueue(m.Key, "data").Status = "paused"
		}
		return nil
	}
	if m.State == "destination_delivered" {
		return nil
	}
	if m.State == "expired" {
		return fail("EXPIRED", "terminal message")
	}
	m.State, m.Transport, m.Tombstone = "destination_delivered", false, m.Deadline+10000
	s.findQueue(m.Key, "data").Status = "stopped"
	if n.config.Node == "B" {
		m.Body = ""
		s.findQueue(m.Key, "custody").Status = "stopped"
		q := s.findQueue(m.Key, "delivery")
		*q = newQueue(*m, "delivery", "A", now, 0, false)
	}
	return nil
}
func expire(s *state, now int64) bool {
	changed := false
	for i := range s.Messages {
		m := &s.Messages[i]
		if now < m.Deadline {
			continue
		}
		before := *m
		m.Transport = false
		m.Tombstone = m.Deadline + 10000
		if m.State != "committed" && m.State != "destination_delivered" {
			m.State = "expired"
		}
		if !m.History {
			m.Body = ""
		}
		changed = changed || before != *m
		for j := range s.Queues {
			q := &s.Queues[j]
			if q.Key == m.Key && q.Status != "reserved" {
				changed = changed || q.Status != "expired"
				q.Status = "expired"
			}
		}
	}
	return changed
}

// Step commits one complete event batch before returning any transmission.
// Repeated node timestamps are rejected; each queue's identical replay remains inert.
func (n *Node) Step(batch Batch) ([]*Transmission, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if err := n.checkTime(batch.Now); err != nil {
		return nil, err
	}
	if batch.Now <= n.storage.current.Now {
		return nil, fail("REJECT_CONTEXT", "batch timestamp already settled")
	}
	if len(batch.Inputs) > 128 || len(batch.Links) > 2 {
		return nil, fail("REJECT_QUOTA", "batch size")
	}
	links := map[string]string{}
	for _, link := range batch.Links {
		valid := false
		for _, neighbor := range neighbors(n.config.Node) {
			if neighbor == link.Neighbor {
				valid = true
			}
		}
		if !valid || links[link.Neighbor] != "" || (link.Event != "became_up" && link.Event != "became_down") {
			return nil, fail("REJECT_CONTEXT", "link batch")
		}
		links[link.Neighbor] = link.Event
	}
	expired := n.storage.current.clone()
	expired.Now = batch.Now
	expiryChanged := expire(&expired, batch.Now)
	// Local deadline cleanup is independent of input acceptance. On rejection,
	// publish only cleanup, never any partially applied input or send decision.
	reject := func(err error) ([]*Transmission, error) {
		if expiryChanged {
			if saveErr := n.commit(expired); saveErr != nil {
				return nil, saveErr
			}
		}
		return nil, err
	}
	type parsedInput struct {
		input    Input
		envelope Envelope
	}
	inputs := make([]parsedInput, 0, len(batch.Inputs))
	for _, in := range batch.Inputs {
		e, err := DecodeEnvelope(in.Frame)
		if err != nil {
			return reject(err)
		}
		inputs = append(inputs, parsedInput{in, e})
	}
	s := expired.clone()
	// Delivery facts settle before custody pauses; conflicting inputs abort the batch.
	sort.SliceStable(inputs, func(i, j int) bool {
		a, b := inputs[i].envelope, inputs[j].envelope
		if a.Kind != b.Kind {
			return rank(a.Kind) < rank(b.Kind)
		}
		return a.Key().order() < b.Key().order()
	})
	for _, in := range inputs {
		if err := n.receive(&s, in.input, in.envelope, batch.Now); err != nil {
			return reject(err)
		}
	}
	s.sort()
	indices := make([]int, len(s.Queues))
	for i := range indices {
		indices[i] = i
	}
	sort.SliceStable(indices, func(i, j int) bool {
		a, b := s.Queues[indices[i]], s.Queues[indices[j]]
		if rank(a.Kind) != rank(b.Kind) {
			return rank(a.Kind) < rank(b.Kind)
		}
		return a.order() < b.order()
	})
	out := []*Transmission{}
	var scheduleErr error
	for _, index := range indices {
		q := &s.Queues[index]
		if q.Status != "active" {
			continue
		}
		m := s.find(q.Key)
		e := m.envelope(q.Kind, q.Hops)
		encoded, err := e.Encode()
		if err != nil {
			return nil, err
		}
		a, b, err := s.credits(q.Neighbor, q.Kind, batch.Now)
		if err != nil {
			return nil, err
		}
		cost := int64(len(encoded)+4) * 1000
		admit := "admit"
		if a.Credit < cost || b.Credit < cost {
			admit = "reject_quota"
		}
		link := links[q.Neighbor]
		if link == "" {
			link = "unchanged"
		}
		decision, err := q.advance(retryBatch{batch.Now, link, "continue", admit})
		if Code(err) == "SCHEDULE_LIMIT" {
			scheduleErr = err
			continue
		}
		if err != nil {
			return nil, err
		}
		if decision.Send {
			a.Credit -= cost
			b.Credit -= cost
			out = append(out, &Transmission{node: n, generation: s.Generation + 1, key: q.Key, kind: q.Kind, neighbor: q.Neighbor, envelope: e})
		}
	}
	if err := n.commit(s); err != nil {
		return nil, err
	}
	if scheduleErr != nil {
		return nil, scheduleErr
	} // Other consumed decisions are deliberately lost, never refunded.
	for _, send := range out {
		n.opportunities[send.key.order()+"/"+send.kind+"/"+send.neighbor] = true
	}
	return out, nil
}
func rank(kind string) int {
	switch kind {
	case "delivery":
		return 0
	case "custody":
		return 1
	case "data":
		return 2
	}
	return 3
}

// ReadInput applies I2 framing before any message transaction. Errors return no input.
func ReadInput(neighbor string, r io.Reader) (Input, error) {
	e, err := ReadEnvelope(r)
	if err != nil {
		return Input{}, err
	}
	b, err := e.Encode()
	if err != nil {
		return Input{}, err
	}
	return Input{neighbor, b}, nil
}
