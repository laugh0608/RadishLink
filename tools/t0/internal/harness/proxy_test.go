package harness

import (
	"bytes"
	"encoding/binary"
	"strings"
	"testing"
)

func TestProxyHitsOnlySecondFrameInConfiguredDirection(t *testing.T) {
	proxy, err := NewSyntheticProxy(FaultPlan{Kind: "drop", Direction: "a-to-b", TriggerIndex: 2})
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		direction string
		payload   string
		outputs   int
		action    string
	}{
		{direction: "b-to-a", payload: "wrong-direction", outputs: 1, action: "forward"},
		{direction: "a-to-b", payload: "one", outputs: 1, action: "forward"},
		{direction: "a-to-b", payload: "two", outputs: 0, action: "drop"},
		{direction: "a-to-b", payload: "three", outputs: 1, action: "forward"},
	}
	for _, test := range tests {
		outputs, event, err := proxy.Process(test.direction, []byte(test.payload))
		if err != nil {
			t.Fatal(err)
		}
		if len(outputs) != test.outputs || event.Action != test.action {
			t.Fatalf("%s/%s: outputs=%d action=%s", test.direction, test.payload, len(outputs), event.Action)
		}
		if event.SHA256 == "" || event.Length != len(test.payload) {
			t.Fatalf("event inventory is incomplete: %+v", event)
		}
	}
	if proxy.HitCount() != 1 {
		t.Fatalf("hit count: got %d, want 1", proxy.HitCount())
	}
	if err := proxy.ValidateComplete(); err != nil {
		t.Fatal(err)
	}
}

func TestProxyReordersOnlyAdjacentPair(t *testing.T) {
	proxy, err := NewSyntheticProxy(FaultPlan{Kind: "reorder-pair", Direction: "b-to-c", TriggerIndex: 1})
	if err != nil {
		t.Fatal(err)
	}
	first, event, err := proxy.Process("b-to-c", []byte("first"))
	if err != nil || len(first) != 0 || event.Action != "reorder-buffer" {
		t.Fatalf("first reorder event: outputs=%q event=%+v err=%v", first, event, err)
	}
	second, event, err := proxy.Process("b-to-c", []byte("second"))
	if err != nil || len(second) != 2 || string(second[0]) != "second" || string(second[1]) != "first" || event.Action != "reorder-release" {
		t.Fatalf("second reorder event: outputs=%q event=%+v err=%v", second, event, err)
	}
	if err := proxy.ValidateComplete(); err != nil {
		t.Fatal(err)
	}
}

func TestProxyDetectsMissingOrMultipleFaultHits(t *testing.T) {
	missing, err := NewSyntheticProxy(FaultPlan{Kind: "drop", Direction: "a-to-b", TriggerIndex: 2})
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := missing.Process("a-to-b", []byte("one")); err != nil {
		t.Fatal(err)
	}
	if err := missing.ValidateComplete(); err == nil || !strings.Contains(err.Error(), "hit count") {
		t.Fatalf("missing hit error: %v", err)
	}

	multiple, err := NewSyntheticProxy(FaultPlan{Kind: "drop", Direction: "a-to-b", TriggerIndex: 1})
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := multiple.Process("a-to-b", []byte("one")); err != nil {
		t.Fatal(err)
	}
	multiple.hits++
	if err := multiple.ValidateComplete(); err == nil || !strings.Contains(err.Error(), "got 2") {
		t.Fatalf("multiple hit error: %v", err)
	}
}

func TestSyntheticFrameCodecRejectsOversizeAndTruncation(t *testing.T) {
	var encoded bytes.Buffer
	if err := WriteSyntheticFrame(&encoded, []byte("synthetic")); err != nil {
		t.Fatal(err)
	}
	decoded, err := ReadSyntheticFrame(&encoded)
	if err != nil || string(decoded) != "synthetic" {
		t.Fatalf("frame round trip: decoded=%q err=%v", decoded, err)
	}

	var oversized bytes.Buffer
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], MaxSyntheticFrameBytes+1)
	oversized.Write(header[:])
	if _, err := ReadSyntheticFrame(&oversized); err == nil {
		t.Fatal("oversized frame was accepted")
	}
	if _, err := ReadSyntheticFrame(bytes.NewReader([]byte{0, 0, 0, 4, 1})); err == nil {
		t.Fatal("truncated frame was accepted")
	}
}
