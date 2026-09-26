package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"hash"
	"io"
	"net"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"radishlink.local/t0/internal/harness"
	"radishlink.local/t0/internal/synthetic"
)

const controlRequestCap = 64 * 1024
const controlResponseCap = 256 * 1024
const operationTimeout = 5 * time.Second

type frameConnection interface {
	io.ReadWriteCloser
	CloseWrite() error
	SetDeadline(time.Time) error
	RemoteAddr() net.Addr
	LocalAddr() net.Addr
}
type nodeNetwork interface {
	Arm(context.Context, string, func(frameConnection) error) error
	Dial(context.Context, string) (frameConnection, error)
	Close() error
	Environment() (string, []string, string, error)
}
type tcpNodeNetwork struct {
	listener    *net.TCPListener
	mu          sync.Mutex
	active      bool
	wg          sync.WaitGroup
	connections map[*net.TCPConn]bool
}

func (n *tcpNodeNetwork) Arm(ctx context.Context, _ string, consume func(frameConnection) error) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.active {
		return errors.New("receive already armed")
	}
	n.active = true
	n.wg.Add(1)
	go func() {
		defer n.wg.Done()

		if err := n.listener.SetDeadline(time.Now().Add(operationTimeout)); err != nil {
			n.mu.Lock()
			n.active = false
			n.mu.Unlock()
			consume(&failedConnection{err: err})
			return
		}
		c, err := n.listener.AcceptTCP()
		if err != nil {
			n.mu.Lock()
			n.active = false
			n.mu.Unlock()
			consume(&failedConnection{err: err})
			return
		}
		n.mu.Lock()
		n.connections[c] = true
		n.mu.Unlock()
		defer func() { c.Close(); n.mu.Lock(); delete(n.connections, c); n.mu.Unlock() }()
		if err := ctx.Err(); err != nil {
			n.mu.Lock()
			n.active = false
			n.mu.Unlock()
			consume(&failedConnection{err: err})
			return
		}
		n.mu.Lock()
		n.active = false
		n.mu.Unlock()
		consume(c)
	}()
	return nil
}

// Accept errors go through the same bounded completion channel as read errors.
type failedConnection struct{ err error }

func (c *failedConnection) Read([]byte) (int, error)    { return 0, c.err }
func (c *failedConnection) Write([]byte) (int, error)   { return 0, c.err }
func (c *failedConnection) Close() error                { return nil }
func (c *failedConnection) CloseWrite() error           { return c.err }
func (c *failedConnection) SetDeadline(time.Time) error { return c.err }
func (c *failedConnection) RemoteAddr() net.Addr        { return &net.TCPAddr{} }
func (c *failedConnection) LocalAddr() net.Addr         { return &net.TCPAddr{} }
func (n *tcpNodeNetwork) Dial(ctx context.Context, address string) (frameConnection, error) {
	c, err := (&net.Dialer{Timeout: operationTimeout}).DialContext(ctx, "tcp4", address)
	if err != nil {
		return nil, err
	}
	return c.(*net.TCPConn), nil
}
func (n *tcpNodeNetwork) Close() error {
	err := n.listener.Close()
	n.mu.Lock()
	for c := range n.connections {
		err = errors.Join(err, c.Close())
	}
	n.mu.Unlock()
	n.wg.Wait()
	return err
}
func (n *tcpNodeNetwork) Environment() (string, []string, string, error) {
	b, err := os.ReadFile("/proc/sys/net/ipv4/ip_forward")
	if err != nil {
		return "", nil, "", err
	}
	routes, err := os.ReadFile("/proc/net/route")
	if err != nil {
		return "", nil, "", err
	}
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return "", nil, "", err
	}
	ips := []string{}
	for _, a := range addrs {
		ip, _, err := net.ParseCIDR(a.String())
		if err != nil {
			return "", nil, "", err
		}
		if ip.To4() != nil && !ip.IsLoopback() {
			ips = append(ips, ip.String())
		}
	}
	slices.Sort(ips)
	return strings.TrimSpace(string(b)), ips, scenarioHash(routes), nil
}

type pendingInput struct {
	input     synthetic.Input
	transport harness.TransportFact
	at        int64
}
type receiveCompletion struct {
	input     synthetic.Input
	transport harness.TransportFact
	probe     *harness.ProbeFact
	err       error
}
type nodeActor struct {
	node                                 *synthetic.Node
	network                              nodeNetwork
	directory, session, name, epoch      string
	profile                              harness.NetworkProfile
	subcase                              string
	peers                                []harness.NetworkPeer
	sequence, local, now, factGeneration int64
	pending                              map[string]pendingInput
	sends                                []*synthetic.Transmission
	handles                              []harness.SendHandle
	consumed                             map[int64]bool
	ordinals                             map[string]int64
	gates                                map[string]bool
	receive                              chan receiveCompletion
	armed                                bool
	dropped                              bool
	halted                               bool
	facts                                []harness.NodeFact
}

func emptyNodeResult() harness.NodeResult {
	return harness.NodeResult{Facts: []harness.NodeFact{}, Sends: []harness.SendHandle{}}
}
func rawDetail(v any) json.RawMessage {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}
func controlLabel(s string) bool {
	if len(s) < 1 || len(s) > 128 {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-' || c == '_') {
			return false
		}
	}
	return true
}
func neighbor(a, b string) bool {
	return a == "A" && b == "B" || a == "B" && (b == "A" || b == "C") || a == "C" && b == "B"
}
func validEpoch(s string) bool {
	if len(s) != 32 {
		return false
	}
	for _, c := range s {
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f') {
			return false
		}
	}
	return true
}
func transferID(node string, generation, index int64) string {
	return fmt.Sprintf("%s-%d-%d", node, generation, index)
}
func (n *nodeActor) generation() int64 {
	if n.node == nil {
		return 0
	}
	return n.node.Generation()
}
func (n *nodeActor) add(kind string, before, after int64, id string, detail any) {
	n.facts = append(n.facts, harness.NodeFact{Now: n.now, Kind: kind, Before: before, After: after, Transfer: id, Detail: rawDetail(detail)})
}
func (n *nodeActor) unspent() bool {
	for i := range n.sends {
		if !n.consumed[int64(i)] {
			return true
		}
	}
	return false
}
func (n *nodeActor) address(from, to string) string {
	network := "ab"
	if from == "C" || to == "C" {
		network = "bc"
	}
	for _, p := range n.peers {
		if p.Node == to {
			ip := p.AB
			if network == "bc" {
				ip = p.BC
			}
			if ip != "" {
				return net.JoinHostPort(ip, "7000")
			}
		}
	}
	return ""
}
func (n *nodeActor) peerIP(name string) string {
	a := n.address(n.name, name)
	h, _, _ := net.SplitHostPort(a)
	return h
}
func (n *nodeActor) storeBytes() (int64, error) {
	entries, err := os.ReadDir(n.directory)
	if err != nil {
		return 0, err
	}
	var total int64
	for _, e := range entries {
		if e.Name() != "state.json" && e.Name() != "state.next" {
			return 0, errors.New("unexpected store entry")
		}
		i, err := e.Info()
		if err != nil {
			return 0, err
		}
		if !i.Mode().IsRegular() {
			return 0, errors.New("store entry type")
		}
		total += i.Size()
	}
	return total, nil
}
func (n *nodeActor) handle(ctx context.Context, q harness.ControlRequest) harness.ControlResponse {
	n.local++
	n.facts = []harness.NodeFact{}
	r := harness.ControlResponse{Version: 1, Session: q.Session, Node: q.Node, Sequence: q.Sequence, Local: n.local, Epoch: q.Epoch, Now: q.Now, Generation: n.generation(), Operation: q.Operation, Result: emptyNodeResult()}
	reject := func(err error) harness.ControlResponse {
		r.Error = err.Error()
		if len(r.Error) > 256 {
			r.Error = r.Error[:256]
		}
		r.Generation = n.generation()
		r.Result.Facts = n.facts
		n.halted = true
		return r
	}
	if n.halted {
		return reject(errors.New("HALTED"))
	}
	if q.Version != 1 || !controlLabel(q.Session) || !slices.Contains([]string{"A", "B", "C"}, q.Node) || !validEpoch(q.Epoch) || q.Sequence != n.sequence+1 || q.Now < n.now || q.Now > 30000 || q.Generation != n.generation() {
		return reject(errors.New("CONTROL_CONTEXT"))
	}
	if n.node != nil && (q.Session != n.session || q.Node != n.name || q.Epoch != n.epoch) {
		return reject(errors.New("CONTROL_BINDING"))
	}
	if n.node == nil && q.Operation != "init" {
		return reject(errors.New("INIT_REQUIRED"))
	}
	n.sequence, n.now = q.Sequence, q.Now
	n.factGeneration = n.generation()
	decode := func(dst any) error { return harness.CanonicalJSON(q.Detail, dst, controlRequestCap) }
	var err error
	switch q.Operation {
	case "init":
		var d harness.NodeInit
		if err = decode(&d); err == nil {
			err = n.init(q, d)
		}
	case "submit_fixture":
		var d struct{}
		if err = decode(&d); err != nil {
			break
		}
		if n.name != "A" || n.unspent() || q.Now != 0 {
			err = errors.New("SUBMIT_CONTEXT")
			break
		}
		sub, _ := n.profile.Subcase(n.subcase)
		before := n.generation()
		_, callErr := n.node.Submit("one", strings.Repeat("3", 32), bytes.Repeat([]byte{'x'}, int(sub.Size)), q.Now, 30000)
		after := n.generation()
		kinds := []string{}
		if after > before {
			kinds = append(kinds, "T-A")
		}
		n.add("submit_result", before, after, "", harness.OperationDetail{Operation: "submit", Error: synthetic.Code(callErr), Committed: after > before, Transactions: kinds})
		if after > before {
			err = n.snapshot(before)
		}
		err = errors.Join(err, callErr)
	case "step":
		var d harness.NodeStep
		if err = decode(&d); err == nil {
			err = n.step(d)
		}
	case "arm_receive":
		var d harness.ReceivePermit
		if err = decode(&d); err == nil {
			err = n.arm(ctx, d)
		}
	case "send":
		var d harness.NodeSend
		if err = decode(&d); err == nil {
			err = n.send(ctx, d)
		}
	case "drain":
		var d struct{}
		if err = decode(&d); err == nil {
			err = n.drain(ctx)
		}
	case "snapshot":
		var d struct{}
		if err = decode(&d); err == nil {
			err = n.snapshot(n.generation())
		}
	case "probe":
		var d harness.NodeProbe
		if err = decode(&d); err == nil {
			err = n.probe(ctx, d)
		}
	case "shutdown":
		var d struct{}
		if err = decode(&d); err == nil && (n.armed || n.unspent() || len(n.pending) != 0) {
			err = errors.New("SHUTDOWN_PENDING")
		}
	default:
		err = errors.New("UNKNOWN_OPERATION")
	}
	if err != nil {
		return reject(err)
	}
	r.Generation = n.generation()
	r.Result.Facts = n.facts
	r.Result.Pending = int64(len(n.pending))
	r.Result.Sends = append(r.Result.Sends, n.handles...)
	if r.Result.StoreBytes, err = n.storeBytes(); err != nil {
		return reject(err)
	}
	return r
}
func (n *nodeActor) init(q harness.ControlRequest, d harness.NodeInit) error {
	if n.node != nil || q.Now != 0 || q.Generation != 0 || d.Store != "store-"+q.Node {
		return errors.New("INIT_CONTEXT")
	}
	if err := d.Profile.Validate(); err != nil {
		return err
	}
	sub, err := d.Profile.Subcase(d.Subcase)
	if err != nil {
		return err
	}
	if len(d.Peers) != 3 {
		return errors.New("PEER_INVENTORY")
	}
	seen := map[string]bool{}
	for i, p := range d.Peers {
		if p.Node != []string{"A", "B", "C"}[i] {
			return errors.New("PEER_ORDER")
		}
		for _, ip := range []string{p.AB, p.BC} {
			if ip == "" {
				continue
			}
			parsed := net.ParseIP(ip)
			if parsed == nil || parsed.To4() == nil || parsed.String() != ip || seen[ip] {
				return errors.New("PEER_IP")
			}
			seen[ip] = true
		}
		if (p.AB != "") != (p.Node != "C") || (p.BC != "") != (p.Node != "A") {
			return errors.New("PEER_NETWORK")
		}
	}
	forwarding, ips, routes, err := n.network.Environment()
	if err != nil {
		return fmt.Errorf("node environment: %w", err)
	}
	expected := []string{}
	for _, p := range d.Peers {
		if p.Node == q.Node {
			if p.AB != "" {
				expected = append(expected, p.AB)
			}
			if p.BC != "" {
				expected = append(expected, p.BC)
			}
		}
	}
	slices.Sort(expected)
	if forwarding != "0" || !slices.Equal(ips, expected) {
		return errors.New("NODE_NETWORK_ENVIRONMENT")
	}
	n.session, n.name, n.epoch = q.Session, q.Node, q.Epoch
	n.profile, n.subcase, n.peers = d.Profile, d.Subcase, slices.Clone(d.Peers)
	n.pending = map[string]pendingInput{}
	n.consumed = map[int64]bool{}
	n.ordinals = map[string]int64{}
	n.gates = map[string]bool{}
	n.receive = make(chan receiveCompletion, 1)
	frames, err := harness.ScenarioFrames(sub.Size)
	if err != nil {
		return err
	}
	oracle := map[synthetic.VerdictRequest]bool{}
	for _, f := range frames {
		oracle[synthetic.VerdictRequest{Receiver: f.To, Neighbor: f.From, FrameSHA256: scenarioHash(f.Body), Purpose: f.Purpose, Key: synthetic.Key{Version: 1, Origin: "A", Scope: "i4-small4", ID: strings.Repeat("3", 32)}}] = true
	}
	c := synthetic.Config{Run: strings.Repeat("1", 32), Node: n.name, Scope: "i4-small4", Epoch: n.epoch, Verdicts: func(v synthetic.VerdictRequest) synthetic.Verdict {
		verdict := synthetic.VerdictReject
		label := "reject"
		if oracle[v] {
			verdict = synthetic.VerdictAccept
			label = "accept"
		}
		n.add("verdict_decision", n.factGeneration, n.factGeneration, "", harness.VerdictDetail{Receiver: v.Receiver, Neighbor: v.Neighbor, Frame: v.FrameSHA256, Purpose: v.Purpose, Verdict: label})
		return verdict
	}}
	n.node, err = synthetic.InitNode(n.directory, c)
	if err != nil {
		return err
	}
	n.add("node_environment", 0, 0, "", harness.NodeEnvironment{Store: d.Store, Epoch: n.epoch, Forwarding: forwarding, Interfaces: ips, Routes: routes})
	return n.snapshot(0)
}
func (n *nodeActor) snapshot(before int64) error {
	s, err := n.node.Snapshot()
	if err != nil {
		return err
	}
	n.add("state_observed", before, s.Generation, "", s)
	return nil
}
func (n *nodeActor) step(d harness.NodeStep) error {
	if n.unspent() || n.armed || d.Inputs == nil || d.Links == nil || len(d.Inputs) > 128 || len(d.Links) > 2 {
		return errors.New("STEP_BARRIER")
	}
	inputs := []synthetic.Input{}
	seen := map[string]bool{}
	for _, id := range d.Inputs {
		p, ok := n.pending[id]
		if !ok || seen[id] || p.at != n.now {
			return errors.New("INPUT_BINDING")
		}
		seen[id] = true
		inputs = append(inputs, p.input)
	}
	for id, p := range n.pending {
		if p.at <= n.now && !seen[id] {
			return errors.New("INPUT_OMITTED")
		}
	}
	links := []synthetic.Link{}
	for _, l := range d.Links {
		dir := scenarioDirection(n.name, l.Neighbor)
		if n.profile.Fault.Kind != "down" || dir != n.profile.Fault.Direction || !neighbor(n.name, l.Neighbor) || (l.Event != "became_down" && l.Event != "became_up") {
			return errors.New("GATE_CONTEXT")
		}
		n.gates[l.Neighbor] = l.Event == "became_down"
		links = append(links, synthetic.Link{Neighbor: l.Neighbor, Event: l.Event})
		n.add("link_gate", n.generation(), n.generation(), "", l)
	}
	before := n.generation()
	for _, id := range d.Inputs {
		p := n.pending[id]
		n.add("frame_received", before, before, id, p.transport.Frame)
		delete(n.pending, id)
	}
	sends, report, err := n.node.StepWithReport(synthetic.Batch{Now: n.now, Inputs: inputs, Links: links})
	n.add("batch_result", report.Before, report.After, "", harness.OperationDetail{Operation: "step", Error: synthetic.Code(err), Committed: report.Committed, Transactions: report.Transactions, Inputs: int64(len(inputs))})
	for _, r := range report.Decisions {
		n.add("retry_decision", report.Before, report.After, "", r)
	}
	if report.Committed {
		if e := n.snapshot(before); e != nil {
			return errors.Join(err, e)
		}
	}
	if err != nil {
		return err
	}
	n.sends = sends
	n.handles = []harness.SendHandle{}
	n.consumed = map[int64]bool{}
	for _, r := range report.Decisions {
		if r.Send {
			if n.gates[r.Neighbor] {
				return errors.New("SEND_WHILE_GATE_DOWN")
			}
			n.handles = append(n.handles, harness.SendHandle{Index: int64(len(n.handles)), Kind: r.Kind, Neighbor: r.Neighbor})
		}
	}
	if len(n.handles) != len(sends) {
		return errors.New("SEND_REPORT_COUNT")
	}
	return nil
}
func (n *nodeActor) arm(ctx context.Context, p harness.ReceivePermit) error {
	if n.armed || !neighbor(p.Sender, n.name) || p.Index < 0 || p.Generation < 1 || p.ID != transferID(p.Sender, p.Generation, p.Index) || p.Ordinal != n.ordinals["recv-"+p.Sender]+1 || len(n.pending) >= 128 {
		return errors.New("ARM_CONTEXT")
	}
	n.armed = true
	n.ordinals["recv-"+p.Sender] = p.Ordinal
	err := n.network.Arm(ctx, n.peerIP(p.Sender), func(c frameConnection) error {
		started := time.Now()
		defer c.Close()
		result := receiveCompletion{}
		result.err = c.SetDeadline(time.Now().Add(operationTimeout))
		remote, _, _ := net.SplitHostPort(c.RemoteAddr().String())
		local, _, _ := net.SplitHostPort(c.LocalAddr().String())
		own, _, _ := net.SplitHostPort(n.address(p.Sender, n.name))
		if result.err == nil && (remote != n.peerIP(p.Sender) || local != own) {
			result.err = errors.New("SOCKET_NEIGHBOR")
		}
		if result.err == nil {
			result.input, result.err = synthetic.ReadInput(p.Sender, c)
		}
		if result.err == nil {
			var extra [1]byte
			count, err := c.Read(extra[:])
			if count != 0 || err != io.EOF {
				result.err = errors.New("FRAME_TRAILING_OR_TIMEOUT")
			}
		}
		if result.err == nil {
			e, err := synthetic.DecodeEnvelope(result.input.Frame)
			result.err = err
			if err == nil {
				result.transport = harness.TransportFact{ID: p.ID, Sender: p.Sender, Receiver: n.name, Generation: p.Generation, Index: p.Index, Ordinal: p.Ordinal, Frame: harness.FrameDetail{Direction: scenarioDirection(p.Sender, n.name), Kind: e.Kind, Core: e.Fingerprint, Frame: scenarioHash(result.input.Frame), Bytes: int64(len(result.input.Frame) + 4)}, Elapsed: time.Since(started).Nanoseconds()}
			}
		}
		n.receive <- result
		return result.err
	})
	if err != nil {
		n.armed = false
	}
	return err
}
func (n *nodeActor) drain(ctx context.Context) error {
	if !n.armed {
		return errors.New("DRAIN_UNARMED")
	}
	var v receiveCompletion
	select {
	case v = <-n.receive:
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(operationTimeout):
		return errors.New("DRAIN_TIMEOUT")
	}
	n.armed = false
	if v.err != nil {
		return fmt.Errorf("receive: %w", v.err)
	}
	if v.probe != nil {
		n.add("probe", n.generation(), n.generation(), "", *v.probe)
		return nil
	}
	f := v.transport
	if n.profile.Fault.Kind == "drop" && f.Frame.Kind == "delivery" && f.Frame.Direction == n.profile.Fault.Direction && !n.dropped {
		f.Dropped = true
		n.dropped = true
	}
	n.add("transport_ingress", n.generation(), n.generation(), f.ID, f)
	if !f.Dropped {
		size := len(v.input.Frame)
		for _, p := range n.pending {
			size += len(p.input.Frame)
		}
		if len(n.pending) >= 128 || size > 4*1024*1024 {
			return errors.New("PENDING_LIMIT")
		}
		if _, ok := n.pending[f.ID]; ok {
			return errors.New("DUPLICATE_TRANSFER")
		}
		n.pending[f.ID] = pendingInput{v.input, f, n.now + 50}
	}
	return nil
}
func (n *nodeActor) send(ctx context.Context, d harness.NodeSend) error {
	if d.Index < 0 || d.Index >= int64(len(n.sends)) || n.consumed[d.Index] || d.ID != transferID(n.name, n.generation(), d.Index) {
		return errors.New("SEND_HANDLE")
	}
	h := n.handles[d.Index]
	if d.Ordinal != n.ordinals["send-"+h.Neighbor]+1 || n.gates[h.Neighbor] {
		return errors.New("SEND_CONTEXT")
	}
	n.consumed[d.Index] = true
	n.ordinals["send-"+h.Neighbor] = d.Ordinal
	started := time.Now()
	c, err := n.network.Dial(ctx, n.address(n.name, h.Neighbor))
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer c.Close()
	if err = c.SetDeadline(time.Now().Add(operationTimeout)); err != nil {
		return err
	}
	counter := &wireSummary{writer: c, body: sha256.New()}
	if err = n.sends[d.Index].Write(counter, n.now); err != nil {
		return fmt.Errorf("write: %w", err)
	}
	if err = c.CloseWrite(); err != nil {
		return err
	}
	sub, _ := n.profile.Subcase(n.subcase)
	fixtures, _ := harness.ScenarioFrames(sub.Size)
	var frame harness.FrameDetail
	for _, f := range fixtures {
		if f.From == n.name && f.To == h.Neighbor && f.Kind == h.Kind {
			frame = harness.FrameDetail{Direction: scenarioDirection(n.name, h.Neighbor), Kind: h.Kind, Core: f.Core, Frame: counter.digest(), Bytes: counter.count}
		}
	}
	if frame.Bytes == 0 {
		return errors.New("SEND_FRAME_KIND")
	}
	t := harness.TransportFact{ID: d.ID, Sender: n.name, Receiver: h.Neighbor, Generation: n.generation(), Index: d.Index, Ordinal: d.Ordinal, Frame: frame, Elapsed: time.Since(started).Nanoseconds()}
	n.add("socket_written", n.generation(), n.generation(), d.ID, t)
	n.add("frame_written", n.generation(), n.generation(), d.ID, frame)
	return nil
}

// wireSummary hashes only actual body bytes successfully written, excluding the I2 prefix.
type wireSummary struct {
	writer io.Writer
	count  int64
	body   hash.Hash
}

func (w *wireSummary) Write(p []byte) (int, error) {
	n, err := w.writer.Write(p)
	if n < 0 || n > len(p) {
		return n, errors.New("invalid write count")
	}
	start := max(int64(0), 4-w.count)
	if start < int64(n) {
		w.body.Write(p[start:n])
	}
	w.count += int64(n)
	if w.count > 32772 {
		return n, errors.New("frame limit")
	}
	return n, err
}
func (w *wireSummary) digest() string { return hex.EncodeToString(w.body.Sum(nil)) }
func (n *nodeActor) probe(ctx context.Context, p harness.NodeProbe) error {
	if n.now != 0 || n.generation() != 0 || n.armed || p.Target == n.name || !slices.Contains([]string{"A", "B", "C"}, p.Target) {
		return errors.New("PROBE_CONTEXT")
	}
	if p.Listen {
		n.armed = true
		return n.network.Arm(ctx, "", func(c frameConnection) error {
			defer c.Close()
			v := receiveCompletion{}
			v.err = c.SetDeadline(time.Now().Add(operationTimeout))
			buf := make([]byte, 8)
			if v.err == nil {
				_, v.err = io.ReadFull(c, buf)
			}
			if v.err == nil && !bytes.Equal(buf, []byte("i5-probe")) {
				v.err = errors.New("PROBE_BYTES")
			}
			if v.err == nil {
				_, v.err = c.Write(buf)
			}
			v.probe = &harness.ProbeFact{From: p.Target, To: n.name, Expected: p.Expected, Reachable: v.err == nil, Received: true}
			n.receive <- v
			return v.err
		})
	}
	address := n.address(n.name, p.Target)
	if address == "" {
		for _, peer := range n.peers {
			if peer.Node == p.Target {
				ip := peer.AB
				if ip == "" {
					ip = peer.BC
				}
				address = net.JoinHostPort(ip, "7000")
			}
		}
	}
	c, err := n.network.Dial(ctx, address)
	reachable := false
	code := ""
	if err == nil && !p.Expected {
		c.Close()
		n.add("probe", 0, 0, "", harness.ProbeFact{From: n.name, To: p.Target, Address: address, Expected: false, Reachable: true})
		return errors.New("FORBIDDEN_REACHABLE")
	}
	if err == nil {
		defer c.Close()
		err = c.SetDeadline(time.Now().Add(operationTimeout))
		if err == nil {
			var k int
			k, err = c.Write([]byte("i5-probe"))
			if err == nil && k != 8 {
				err = io.ErrShortWrite
			}
		}
		buf := make([]byte, 8)
		if err == nil {
			_, err = io.ReadFull(c, buf)
		}
		reachable = err == nil && bytes.Equal(buf, []byte("i5-probe"))
		if !reachable {
			code = "probe_response"
		}
	} else {
		code = "dial_failed"
	}
	n.add("probe", 0, 0, "", harness.ProbeFact{From: n.name, To: p.Target, Address: address, Expected: p.Expected, Reachable: reachable, Error: code})
	if reachable != p.Expected {
		return errors.New("PROBE_MISMATCH")
	}
	return nil
}
func readControlLine(reader *bufio.Reader, cap int) ([]byte, error) {
	line, err := reader.ReadSlice('\n')
	if err != nil {
		return nil, err
	}
	if len(line) > cap+1 {
		return nil, errors.New("control line limit")
	}
	return line[:len(line)-1], nil
}
func serveNodeControl(ctx context.Context, in io.Reader, out io.Writer, n *nodeActor) error {
	reader := bufio.NewReaderSize(in, controlRequestCap+2)
	for {
		line, err := readControlLine(reader, controlRequestCap)
		if err != nil {
			return fmt.Errorf("control read: %w", err)
		}
		var q harness.ControlRequest
		if err = harness.CanonicalJSON(line, &q, controlRequestCap); err != nil {
			return err
		}
		r := n.handle(ctx, q)
		b, err := json.Marshal(r)
		if err != nil {
			return err
		}
		if len(b) > controlResponseCap {
			return errors.New("control response limit")
		}
		b = append(b, '\n')
		k, err := out.Write(b)
		if err != nil {
			return err
		}
		if k != len(b) {
			return io.ErrShortWrite
		}
		if r.Error != "" {
			return errors.New(r.Error)
		}
		if q.Operation == "shutdown" {
			return nil
		}
	}
}
func runSyntheticNode(args []string) (runErr error) {
	flags := flag.NewFlagSet("synthetic-node", flag.ContinueOnError)
	store := flags.String("store", "", "exclusive store directory")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 || *store != "/state" {
		return errors.New("synthetic-node requires --store /state")
	}
	path, err := filepath.EvalSymlinks(*store)
	if err != nil || path != *store {
		return errors.New("store path")
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	listener, err := net.ListenTCP("tcp4", &net.TCPAddr{Port: 7000})
	if err != nil {
		return err
	}
	network := &tcpNodeNetwork{listener: listener, connections: map[*net.TCPConn]bool{}}
	defer func() { runErr = errors.Join(runErr, network.Close()) }()
	return serveNodeControl(ctx, os.Stdin, os.Stdout, &nodeActor{directory: *store, network: network})
}
