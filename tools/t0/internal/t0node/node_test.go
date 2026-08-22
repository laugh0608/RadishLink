package t0node

import (
	"testing"
	"time"
)

func TestDestinationSuppressesDuplicateAndQueuesAck(t *testing.T) {
	node := newTestNode(t, "C", map[string]string{"A": "b:7000"})
	now := time.Unix(1_800_000_000, 0)
	frame := testMessage("message-1", "A", "C", 0, now.Add(time.Minute))

	accepted, reason, err := node.Receive(frame, now)
	if err != nil {
		t.Fatal(err)
	}
	if !accepted || reason != "delivered" {
		t.Fatalf("first delivery: accepted=%v reason=%q", accepted, reason)
	}

	accepted, reason, err = node.Receive(frame, now)
	if err != nil {
		t.Fatal(err)
	}
	if !accepted || reason != "duplicate_suppressed" {
		t.Fatalf("duplicate delivery: accepted=%v reason=%q", accepted, reason)
	}

	status := node.Status()
	if status.Delivered[frame.ID] != 1 {
		t.Fatalf("delivery count: got %d, want 1", status.Delivered[frame.ID])
	}
	if status.DuplicateFrames != 1 {
		t.Fatalf("duplicate count: got %d, want 1", status.DuplicateFrames)
	}
	if len(status.Pending) != 1 || status.Pending[0] != acknowledgementID(frame.ID) {
		t.Fatalf("pending acknowledgements: got %v", status.Pending)
	}
}

func TestRelayRejectsExhaustedHopLimit(t *testing.T) {
	node := newTestNode(t, "B", map[string]string{"C": "c:7000"})
	now := time.Unix(1_800_000_000, 0)
	frame := testMessage("message-ttl", "A", "C", 0, now.Add(time.Minute))

	accepted, reason, err := node.Receive(frame, now)
	if err != nil {
		t.Fatal(err)
	}
	if accepted || reason != "hop_limit_exhausted" {
		t.Fatalf("hop limit result: accepted=%v reason=%q", accepted, reason)
	}
	status := node.Status()
	if status.Drops["hop_limit_exhausted"] != 1 {
		t.Fatalf("hop-limit drops: got %d, want 1", status.Drops["hop_limit_exhausted"])
	}
	if len(status.Pending) != 0 {
		t.Fatalf("exhausted frame entered queue: %v", status.Pending)
	}
}

func TestPendingStateSurvivesRestart(t *testing.T) {
	directory := t.TempDir()
	now := time.Unix(1_800_000_000, 0)
	frame := testMessage("message-persist", "A", "C", 1, now.Add(time.Minute))

	node, err := New(testConfig("B", directory, map[string]string{"C": "c:7000"}))
	if err != nil {
		t.Fatal(err)
	}
	accepted, _, err := node.Receive(frame, now)
	if err != nil || !accepted {
		t.Fatalf("store frame: accepted=%v err=%v", accepted, err)
	}

	restarted, err := New(testConfig("B", directory, map[string]string{"C": "c:7000"}))
	if err != nil {
		t.Fatal(err)
	}
	status := restarted.Status()
	if len(status.Pending) != 1 || status.Pending[0] != frame.ID {
		t.Fatalf("pending after restart: got %v", status.Pending)
	}
}

func TestExpiredFrameIsRejectedAndCounted(t *testing.T) {
	node := newTestNode(t, "B", map[string]string{"C": "c:7000"})
	now := time.Unix(1_800_000_000, 0)
	frame := testMessage("message-expired", "A", "C", 1, now.Add(-time.Millisecond))

	accepted, reason, err := node.Receive(frame, now)
	if err != nil {
		t.Fatal(err)
	}
	if accepted || reason != "expired" {
		t.Fatalf("expiry result: accepted=%v reason=%q", accepted, reason)
	}
	if node.Status().Drops["expired"] != 1 {
		t.Fatal("expired frame was not counted")
	}
}

func newTestNode(t *testing.T, id string, routes map[string]string) *Node {
	t.Helper()
	node, err := New(testConfig(id, t.TempDir(), routes))
	if err != nil {
		t.Fatal(err)
	}
	return node
}

func testConfig(id, directory string, routes map[string]string) Config {
	return Config{
		NodeID:        id,
		ListenAddress: "127.0.0.1:0",
		Routes:        routes,
		DataDirectory: directory,
		RetryInterval: 10 * time.Millisecond,
		DialTimeout:   10 * time.Millisecond,
		AckHopLimit:   8,
	}
}

func testMessage(id, origin, destination string, hopLimit int, expiry time.Time) Frame {
	return Frame{
		Version:         ProtocolVersion,
		Kind:            FrameMessage,
		ID:              id,
		Origin:          origin,
		Destination:     destination,
		HopLimit:        hopLimit,
		ExpiresAtUnixMs: expiry.UnixMilli(),
		TestBody:        "synthetic",
	}
}
