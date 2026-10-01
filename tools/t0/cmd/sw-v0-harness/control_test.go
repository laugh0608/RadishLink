package main

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"radishlink.local/t0/internal/harness"
)

type memoryNetwork struct {
	name    string
	peers   []harness.NetworkPeer
	world   map[string]*memoryNetwork
	armed   func(frameConnection) error
	failure error
}

func (n *memoryNetwork) Environment() (string, []string, string, error) {
	ips := []string{}
	for _, p := range n.peers {
		if p.Node == n.name {
			if p.AB != "" {
				ips = append(ips, p.AB)
			}
			if p.BC != "" {
				ips = append(ips, p.BC)
			}
		}
	}
	return "0", ips, strings.Repeat("a", 64), nil
}
func (n *memoryNetwork) Close() error { return nil }
func (n *memoryNetwork) Arm(_ context.Context, _ string, cb func(frameConnection) error) error {
	if n.failure != nil {
		return n.failure
	}
	if n.armed != nil {
		return errors.New("test arm collision")
	}
	n.armed = cb
	return nil
}
func (n *memoryNetwork) Dial(_ context.Context, address string) (frameConnection, error) {
	if n.failure != nil {
		return nil, n.failure
	}
	host, _, _ := net.SplitHostPort(address)
	for _, p := range n.peers {
		if (p.AB == host || p.BC == host) && neighbor(n.name, p.Node) {
			other := n.world[p.Node]
			if other.armed == nil {
				return nil, errors.New("test unarmed")
			}
			source := ""
			for _, own := range n.peers {
				if own.Node == n.name {
					source = own.AB
					if n.name == "C" || p.Node == "C" {
						source = own.BC
					}
				}
			}
			return &memoryConnection{target: other, source: source, destination: host}, nil
		}
	}
	return nil, errors.New("test forbidden numeric route")
}

type memoryConnection struct {
	target              *memoryNetwork
	source, destination string
	wire, reply         bytes.Buffer
	delivered           bool
}

func (c *memoryConnection) deliver() error {
	if c.delivered {
		return nil
	}
	c.delivered = true
	cb := c.target.armed
	c.target.armed = nil
	if cb == nil {
		return errors.New("test no consumer")
	}
	return cb(&receivedConnection{reader: bytes.NewReader(c.wire.Bytes()), reply: &c.reply, remote: c.source, local: c.destination})
}
func (c *memoryConnection) Read(p []byte) (int, error) {
	if err := c.deliver(); err != nil {
		return 0, err
	}
	return c.reply.Read(p)
}
func (c *memoryConnection) Write(p []byte) (int, error) { return c.wire.Write(p) }
func (c *memoryConnection) Close() error                { return nil }
func (c *memoryConnection) CloseWrite() error           { return c.deliver() }
func (c *memoryConnection) SetDeadline(time.Time) error { return nil }
func (c *memoryConnection) RemoteAddr() net.Addr {
	return &net.TCPAddr{IP: net.ParseIP(c.destination), Port: 7000}
}
func (c *memoryConnection) LocalAddr() net.Addr {
	return &net.TCPAddr{IP: net.ParseIP(c.source), Port: 7001}
}

type receivedConnection struct {
	reader        *bytes.Reader
	reply         io.Writer
	remote, local string
}

func (c *receivedConnection) Read(p []byte) (int, error)  { return c.reader.Read(p) }
func (c *receivedConnection) Write(p []byte) (int, error) { return c.reply.Write(p) }
func (c *receivedConnection) Close() error                { return nil }
func (c *receivedConnection) CloseWrite() error           { return nil }
func (c *receivedConnection) SetDeadline(time.Time) error { return nil }
func (c *receivedConnection) RemoteAddr() net.Addr {
	return &net.TCPAddr{IP: net.ParseIP(c.remote), Port: 7001}
}
func (c *receivedConnection) LocalAddr() net.Addr {
	return &net.TCPAddr{IP: net.ParseIP(c.local), Port: 7000}
}

type actorPeer struct {
	actor        *nodeActor
	dropResponse bool
}

func (p *actorPeer) Exchange(ctx context.Context, q harness.ControlRequest) (harness.ControlResponse, error) {
	r := p.actor.handle(ctx, q)
	if p.dropResponse {
		return harness.ControlResponse{}, io.ErrUnexpectedEOF
	}
	return r, nil
}
func (p *actorPeer) Close() error { return nil }
func testPeers() []harness.NetworkPeer {
	return []harness.NetworkPeer{{Node: "A", AB: "10.1.0.2"}, {Node: "B", AB: "10.1.0.3", BC: "10.2.0.2"}, {Node: "C", BC: "10.2.0.3"}}
}
func testStore(t *testing.T) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "state")
	if err := os.Mkdir(p, 0700); err != nil {
		t.Fatal(err)
	}
	return p
}
func testActor(t *testing.T) (*nodeActor, harness.ControlRequest) {
	t.Helper()
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	n := &nodeActor{directory: testStore(t), network: &memoryNetwork{name: "A", peers: testPeers()}}
	q := harness.ControlRequest{Version: 1, Session: "test", Node: "A", Sequence: 1, Epoch: strings.Repeat("2", 32), Operation: "init", Detail: rawDetail(harness.NodeInit{Profile: p, Subcase: "p1024", Peers: testPeers(), Store: "store-A"})}
	r := n.handle(context.Background(), q)
	if r.Error != "" {
		t.Fatal(r.Error)
	}
	return n, q
}
func TestControlContextAndSendBarrier(t *testing.T) {
	for _, name := range []string{"epoch", "session", "generation", "sequence", "unknown", "same-time"} {
		t.Run(name, func(t *testing.T) {
			n, q := testActor(t)
			q.Sequence = 2
			q.Operation = "submit_fixture"
			q.Detail = rawDetail(struct{}{})
			r := n.handle(context.Background(), q)
			if r.Error != "" {
				t.Fatal(r.Error)
			}
			q.Sequence = 3
			q.Generation = 1
			q.Operation = "step"
			q.Now = 1
			q.Detail = rawDetail(harness.NodeStep{Inputs: []string{}, Links: []harness.ControlLink{}})
			switch name {
			case "epoch":
				q.Epoch = strings.Repeat("4", 32)
			case "session":
				q.Session = "other"
			case "generation":
				q.Generation = 0
			case "sequence":
				q.Sequence = 2
			case "unknown":
				q.Operation = "inject_frame"
			case "same-time":
				q.Now = 0
			}
			before := n.generation()
			r = n.handle(context.Background(), q)
			if r.Error == "" || n.generation() != before {
				t.Fatalf("accepted %s: %+v", name, r)
			}
		})
	}
	n, q := testActor(t)
	q.Sequence = 2
	q.Operation = "submit_fixture"
	q.Detail = rawDetail(struct{}{})
	n.handle(context.Background(), q)
	q.Sequence = 3
	q.Generation = 1
	q.Now = 1
	q.Operation = "step"
	q.Detail = rawDetail(harness.NodeStep{Inputs: []string{}, Links: []harness.ControlLink{}})
	r := n.handle(context.Background(), q)
	q.Sequence++
	q.Generation = r.Generation
	q.Now = 250
	r = n.handle(context.Background(), q)
	if r.Error != "" || len(r.Result.Sends) != 1 {
		t.Fatalf("step: error=%s sends=%d", r.Error, len(r.Result.Sends))
	}
	q.Sequence++
	q.Generation = r.Generation
	q.Now = 500
	r = n.handle(context.Background(), q)
	if r.Error != "STEP_BARRIER" {
		t.Fatalf("pending send allowed commit: %+v", r)
	}
}
func TestControlLostReplyDoesNotReplay(t *testing.T) {
	n, q := testActor(t)
	peer := &actorPeer{actor: n, dropResponse: true}
	q.Sequence = 2
	q.Operation = "submit_fixture"
	q.Detail = rawDetail(struct{}{})
	_, err := peer.Exchange(context.Background(), q)
	if err == nil || n.generation() != 1 {
		t.Fatal("missing committed lost reply")
	}
	peer.dropResponse = false
	r, _ := peer.Exchange(context.Background(), q)
	if r.Error == "" || n.generation() != 1 {
		t.Fatal("replayed lost response command")
	}
}
func TestControlMalformedAndOutputErrors(t *testing.T) {
	n, _ := testActor(t)
	for _, raw := range []string{"{}\n", strings.Repeat("x", controlRequestCap+1) + "\n", "{\"control_version\":1,\"control_version\":1}\n"} {
		if err := serveNodeControl(context.Background(), strings.NewReader(raw), io.Discard, n); err == nil {
			t.Fatal("malformed control accepted")
		}
	}
}
func TestReadInputRejectsTrailingAndWrongNeighbor(t *testing.T) {
	for _, bad := range []string{"trailing", "neighbor", "short"} {
		t.Run(bad, func(t *testing.T) {
			peers := testPeers()
			world := map[string]*memoryNetwork{}
			for _, p := range peers {
				world[p.Node] = &memoryNetwork{name: p.Node, peers: peers, world: world}
			}
			p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
			n := &nodeActor{directory: testStore(t), network: world["B"]}
			q := harness.ControlRequest{Version: 1, Session: "test", Node: "B", Sequence: 1, Epoch: strings.Repeat("2", 32), Operation: "init", Detail: rawDetail(harness.NodeInit{Profile: p, Subcase: "p1024", Peers: peers, Store: "store-B"})}
			if r := n.handle(context.Background(), q); r.Error != "" {
				t.Fatal(r.Error)
			}
			permit := harness.ReceivePermit{ID: "A-2-0", Sender: "A", Generation: 2, Index: 0, Ordinal: 1}
			if err := n.arm(context.Background(), permit); err != nil {
				t.Fatal(err)
			}
			frames, _ := harness.ScenarioFrames(1024)
			var wire bytes.Buffer
			harness.WriteSyntheticFrame(&wire, frames[0].Body)
			if bad == "trailing" {
				wire.WriteByte(1)
			}
			raw := wire.Bytes()
			if bad == "short" {
				raw = raw[:len(raw)-1]
			}
			remote := "10.1.0.2"
			if bad == "neighbor" {
				remote = "10.9.0.1"
			}
			cb := world["B"].armed
			_ = cb(&receivedConnection{reader: bytes.NewReader(raw), reply: io.Discard, remote: remote, local: "10.1.0.3"})
			if err := n.drain(context.Background()); err == nil {
				t.Fatal("bad frame accepted")
			}
			if len(n.pending) != 0 || n.generation() != 0 {
				t.Fatal("bad frame changed state")
			}
		})
	}
}
func TestNoControlAccessToOtherStore(t *testing.T) {
	n, q := testActor(t)
	q.Sequence = 2
	q.Operation = "init"
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	q.Detail = rawDetail(harness.NodeInit{Profile: p, Subcase: "p1024", Peers: testPeers(), Store: "store-B"})
	if r := n.handle(context.Background(), q); r.Error == "" {
		t.Fatal("second init accepted")
	}
	if _, err := os.Stat(filepath.Join(n.directory, "state.json")); err != nil {
		t.Fatal(err)
	}
}

type shortControlWriter struct{}

func (shortControlWriter) Write(b []byte) (int, error) { return len(b) - 1, nil }
func TestControlShortResponseAndStrictEncoding(t *testing.T) {
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	q := harness.ControlRequest{Version: 1, Session: "test", Node: "A", Sequence: 1, Epoch: strings.Repeat("2", 32), Operation: "init", Detail: rawDetail(harness.NodeInit{Profile: p, Subcase: "p1", Peers: testPeers(), Store: "store-A"})}
	raw := append(rawDetail(q), '\n')
	n := &nodeActor{directory: testStore(t), network: &memoryNetwork{name: "A", peers: testPeers()}}
	if err := serveNodeControl(context.Background(), bytes.NewReader(raw), shortControlWriter{}, n); !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("short response: %v", err)
	}
	if n.node == nil {
		t.Fatal("test did not reach init")
	}
}
func TestConsumedSendCannotBeRetriedAfterDialFailure(t *testing.T) {
	n, q := testActor(t)
	q.Sequence = 2
	q.Operation = "submit_fixture"
	q.Detail = rawDetail(struct{}{})
	r := n.handle(context.Background(), q)
	for _, now := range []int64{1, 250} {
		q.Sequence++
		q.Generation = r.Generation
		q.Now = now
		q.Operation = "step"
		q.Detail = rawDetail(harness.NodeStep{Inputs: []string{}, Links: []harness.ControlLink{}})
		r = n.handle(context.Background(), q)
	}
	n.network.(*memoryNetwork).failure = errors.New("injected dial failure")
	d := harness.NodeSend{ID: transferID("A", r.Generation, 0), Index: 0, Ordinal: 1}
	if err := n.send(context.Background(), d); err == nil {
		t.Fatal("dial failure lost")
	}
	if !n.consumed[0] {
		t.Fatal("send opportunity refunded")
	}
	if err := n.send(context.Background(), d); err == nil {
		t.Fatal("send retried")
	}
}
