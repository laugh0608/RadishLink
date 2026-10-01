package harness

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
	"strings"
	"testing"

	"radishlink.local/t0/internal/delivery"
)

type frameWriterFunc func([]byte) (int, error)

func (write frameWriterFunc) Write(p []byte) (int, error) { return write(p) }

type frameReaderFunc func([]byte) (int, error)

func (read frameReaderFunc) Read(p []byte) (int, error) { return read(p) }

func TestSyntheticFrameWriterRejectsShortWrites(t *testing.T) {
	for _, stage := range []string{"header", "payload"} {
		t.Run(stage, func(t *testing.T) {
			calls := 0
			writer := frameWriterFunc(func(p []byte) (int, error) {
				calls++
				if stage == "header" || calls == 2 {
					return len(p) - 1, nil
				}
				return len(p), nil
			})
			err := WriteSyntheticFrame(writer, []byte("synthetic-only-body"))
			wantCalls := 1
			if stage == "payload" {
				wantCalls = 2
			}
			if !errors.Is(err, io.ErrShortWrite) || calls != wantCalls {
				t.Fatalf("short write: err=%v calls=%d, want ErrShortWrite and %d calls", err, calls, wantCalls)
			}
		})
	}
}

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

func TestSyntheticFrameLegacyEncoding(t *testing.T) {
	for _, test := range []struct {
		size   int
		header [4]byte
	}{
		{1, [4]byte{0, 0, 0, 1}},
		{32769, [4]byte{0, 0, 128, 1}},
		{65536, [4]byte{0, 1, 0, 0}},
	} {
		t.Run(fmt.Sprint(test.size), func(t *testing.T) {
			payload := bytes.Repeat([]byte{0xab}, test.size)
			var wire bytes.Buffer
			if err := WriteSyntheticFrame(&wire, payload); err != nil {
				t.Fatal(err)
			}
			if wire.Len() != test.size+4 || !bytes.Equal(wire.Bytes()[:4], test.header[:]) || !bytes.Equal(wire.Bytes()[4:], payload) {
				t.Fatal("legacy wire encoding changed")
			}
			got, err := ReadSyntheticFrame(&wire)
			if err != nil || !bytes.Equal(got, payload) || wire.Len() != 0 {
				t.Fatalf("legacy round trip: length=%d remaining=%d err=%v", len(got), wire.Len(), err)
			}
		})
	}
	for _, size := range []int{0, 65537} {
		calls := 0
		writer := frameWriterFunc(func(p []byte) (int, error) { calls++; return len(p), nil })
		if err := WriteSyntheticFrame(writer, make([]byte, size)); err == nil || calls != 0 {
			t.Fatalf("legacy invalid length=%d: calls=%d err=%v", size, calls, err)
		}
		var header [4]byte
		binary.BigEndian.PutUint32(header[:], uint32(size))
		if got, err := ReadSyntheticFrame(bytes.NewReader(header[:])); err == nil || got != nil || !strings.Contains(err.Error(), "length") {
			t.Fatalf("legacy invalid read length=%d: returned=%d err=%v", size, len(got), err)
		}
	}
}

func TestSyntheticFrameLimits(t *testing.T) {
	for _, test := range []struct {
		limit int64
		size  int
		valid bool
	}{
		{1, 1, true}, {1, 2, false},
		{delivery.MaxFrameBodyBytes, 32768, true},
		{delivery.MaxFrameBodyBytes, 32769, false},
		{delivery.MaxFrameBodyBytes, 65536, false},
		{65536, 65536, true}, {65536, 65537, false},
	} {
		t.Run(fmt.Sprintf("%d/%d", test.limit, test.size), func(t *testing.T) {
			payload := bytes.Repeat([]byte{0xcd}, test.size)
			var wire bytes.Buffer
			err := WriteSyntheticFrameWithLimit(&wire, payload, test.limit)
			if !test.valid {
				if err == nil || wire.Len() != 0 {
					t.Fatalf("invalid write: bytes=%d err=%v", wire.Len(), err)
				}
				return
			}
			if err != nil || wire.Len() != test.size+4 {
				t.Fatalf("valid write: bytes=%d err=%v", wire.Len(), err)
			}
			got, err := ReadSyntheticFrameWithLimit(&wire, test.limit)
			if err != nil || !bytes.Equal(got, payload) || wire.Len() != 0 {
				t.Fatalf("bounded round trip: bytes=%d remaining=%d err=%v", len(got), wire.Len(), err)
			}
		})
	}
	for _, limit := range []int64{-1, 0, 65537, math.MaxInt64} {
		calls := 0
		reader := frameReaderFunc(func([]byte) (int, error) { calls++; return 0, io.EOF })
		writer := frameWriterFunc(func(p []byte) (int, error) { calls++; return len(p), nil })
		got, readErr := ReadSyntheticFrameWithLimit(reader, limit)
		writeErr := WriteSyntheticFrameWithLimit(writer, []byte{1}, limit)
		if got != nil || readErr == nil || writeErr == nil || calls != 0 {
			t.Fatalf("invalid limit=%d: read=%v write=%v calls=%d", limit, readErr, writeErr, calls)
		}
	}
}

func TestSyntheticFrameRejectsLengthBeforeReadingBody(t *testing.T) {
	for _, test := range []struct {
		limit  int64
		length uint32
	}{
		{1, 0}, {1, 2}, {65536, 65537},
		{delivery.MaxFrameBodyBytes, 0},
		{delivery.MaxFrameBodyBytes, 32769},
		{delivery.MaxFrameBodyBytes, 65536},
		{delivery.MaxFrameBodyBytes, math.MaxUint32},
	} {
		var header [4]byte
		binary.BigEndian.PutUint32(header[:], test.length)
		calls := 0
		reader := frameReaderFunc(func(p []byte) (int, error) {
			calls++
			if calls != 1 || len(p) != 4 {
				t.Fatalf("length=%d: unexpected body read, calls=%d requested=%d", test.length, calls, len(p))
			}
			return copy(p, header[:]), nil
		})
		got, err := ReadSyntheticFrameWithLimit(reader, test.limit)
		if got != nil || err == nil || calls != 1 || !strings.Contains(err.Error(), "length") {
			t.Fatalf("length=%d: returned=%d calls=%d err=%v", test.length, len(got), calls, err)
		}
	}
}

func TestSyntheticFrameReadFailuresPreserveCause(t *testing.T) {
	sentinel := errors.New("injected read failure")
	for _, test := range []struct {
		name  string
		input []byte
		cause error
		want  error
		stage string
	}{
		{"empty", nil, io.EOF, io.EOF, "header"},
		{"header1", []byte{0}, io.EOF, io.ErrUnexpectedEOF, "header"},
		{"header2", []byte{0, 0}, io.EOF, io.ErrUnexpectedEOF, "header"},
		{"header3", []byte{0, 0, 0}, io.EOF, io.ErrUnexpectedEOF, "header"},
		{"no-body", []byte{0, 0, 0, 2}, io.EOF, io.EOF, "payload"},
		{"short-body", []byte{0, 0, 0, 2, 1}, io.EOF, io.ErrUnexpectedEOF, "payload"},
		{"header-error", []byte{0}, sentinel, sentinel, "header"},
		{"body-error", []byte{0, 0, 0, 2, 1}, sentinel, sentinel, "payload"},
		{"header-unexpected-eof", nil, io.ErrUnexpectedEOF, io.ErrUnexpectedEOF, "header"},
		{"body-unexpected-eof", []byte{0, 0, 0, 2}, io.ErrUnexpectedEOF, io.ErrUnexpectedEOF, "payload"},
	} {
		t.Run(test.name, func(t *testing.T) {
			source := bytes.NewReader(test.input)
			reader := frameReaderFunc(func(p []byte) (int, error) {
				if source.Len() == 0 {
					return 0, test.cause
				}
				return source.Read(p)
			})
			got, err := ReadSyntheticFrameWithLimit(reader, delivery.MaxFrameBodyBytes)
			if got != nil || !errors.Is(err, test.want) || !strings.Contains(err.Error(), test.stage) {
				t.Fatalf("read failure: returned=%d err=%v, want %s/%v", len(got), err, test.stage, test.want)
			}
		})
	}
}

func TestSyntheticFrameConsumesOneFrameWithFragmentedReader(t *testing.T) {
	// Hand-encoded frames avoid using the writer to generate the reader oracle.
	source := bytes.NewReader([]byte{0, 0, 0, 2, 'a', 'b', 0, 0, 0, 1, 'c'})
	reader := frameReaderFunc(func(p []byte) (int, error) { return source.Read(p[:1]) })
	for _, test := range []struct {
		body      string
		remaining int
	}{{"ab", 5}, {"c", 0}} {
		got, err := ReadSyntheticFrameWithLimit(reader, delivery.MaxFrameBodyBytes)
		if err != nil || string(got) != test.body || source.Len() != test.remaining {
			t.Fatalf("fragmented frame: got=%q remaining=%d err=%v", got, source.Len(), err)
		}
	}
}

func TestSyntheticFrameWriteFailuresPreserveCause(t *testing.T) {
	sentinel := errors.New("injected write failure")
	const body = "synthetic-body-must-not-appear-in-errors"
	for _, stage := range []string{"header", "payload"} {
		for _, test := range []struct {
			name  string
			count int // -1 means the complete supplied slice; -2 means one byte short.
			cause error
			want  error
		}{
			{"zero", 0, nil, io.ErrShortWrite},
			{"short", -2, nil, io.ErrShortWrite},
			{"zero-error", 0, sentinel, sentinel},
			{"partial-error", 1, sentinel, sentinel},
			{"complete-error", -1, sentinel, sentinel},
		} {
			t.Run(stage+"/"+test.name, func(t *testing.T) {
				calls := 0
				wantCalls := 1
				if stage == "payload" {
					wantCalls = 2
				}
				writer := frameWriterFunc(func(p []byte) (int, error) {
					calls++
					if calls != wantCalls {
						return len(p), nil
					}
					n := test.count
					if n == -1 {
						n = len(p)
					} else if n == -2 {
						n = len(p) - 1
					}
					return n, test.cause
				})
				err := WriteSyntheticFrameWithLimit(writer, []byte(body), delivery.MaxFrameBodyBytes)
				if !errors.Is(err, test.want) || calls != wantCalls || !strings.Contains(err.Error(), stage) || strings.Contains(err.Error(), body) {
					t.Fatalf("write failure: calls=%d err=%v, want %s/%v", calls, err, stage, test.want)
				}
			})
		}
	}
}
