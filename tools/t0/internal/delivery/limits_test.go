package delivery

import (
	"math"
	"strings"
	"testing"
)

func TestLengthBoundaries(t *testing.T) {
	for _, test := range []struct {
		kind  LengthKind
		name  string
		limit int64
	}{
		{TextLength, "text", 16384},
		{SyntheticPayloadLength, "synthetic payload", 16384},
		{FrameBodyLength, "frame body", 32768},
	} {
		t.Run(test.name, func(t *testing.T) {
			for _, size := range []int64{1, test.limit} {
				if err := CheckLength(test.kind, size, size); err != nil {
					t.Fatal(err)
				}
			}
			for _, pair := range [][2]int64{
				{0, 0}, {-1, 1}, {1, -1}, {0, 1}, {1, 0},
				{test.limit + 1, test.limit + 1}, {test.limit + 1, 1}, {1, test.limit + 1},
				{math.MaxInt64, math.MaxInt64}, {2, 1}, {1, 2},
			} {
				err := CheckLength(test.kind, pair[0], pair[1])
				if err == nil || !strings.Contains(err.Error(), test.name) || !strings.Contains(err.Error(), "bytes") {
					t.Fatalf("invalid lengths %v: %v", pair, err)
				}
			}
		})
	}
	for _, kind := range []LengthKind{0, 99} {
		if err := CheckLength(kind, 1, 1); err == nil {
			t.Fatalf("unknown kind %d accepted", kind)
		}
	}
}

func TestFrameBodyUsesEncodedLengthsAndExcludesTransportPrefix(t *testing.T) {
	for _, test := range []struct{ header, encoded, declared, want int64 }{
		{1, 1, 2, 2}, {128, 32640, 32768, 32768}, {128, 21848, 21976, 21976},
	} {
		got, err := CheckFrameBodyLength(test.header, test.encoded, test.declared)
		if err != nil || got != test.want {
			t.Fatalf("%+v: size=%d error=%v", test, got, err)
		}
	}
	// A raw 16384-byte payload may occupy 21848 encoded bytes. Neither the raw
	// size nor the outer transport's four bytes can substitute for frame body size.
	for _, declared := range []int64{16512, 21980} {
		if _, err := CheckFrameBodyLength(128, 21848, declared); err == nil {
			t.Fatalf("wrong encoded size %d accepted", declared)
		}
	}
}

func TestFrameBodyRejectsOverflowAndMismatchesWithoutUsableSize(t *testing.T) {
	for _, test := range []struct {
		name                      string
		header, encoded, declared int64
		errorPart                 string
	}{
		{"header_zero", 0, 1, 1, "positive"},
		{"header_negative", -1, 2, 1, "positive"},
		{"payload_zero", 1, 0, 1, "positive"},
		{"payload_negative", 2, -1, 1, "positive"},
		{"over_limit", 128, 32641, 32769, "1..32768"},
		{"overflow", math.MaxInt64, 1, 1, "overflows"},
		{"overflow_reversed", 1, math.MaxInt64, 1, "overflows"},
		{"large_without_overflow", math.MaxInt64 - 1, 1, math.MaxInt64, "1..32768"},
		{"truncated", 128, 128, 257, "mismatch"},
		{"undeclared_extra", 128, 128, 255, "mismatch"},
		{"declared_zero", 1, 1, 0, "1..32768"},
		{"declared_negative", 1, 1, -1, "1..32768"},
	} {
		t.Run(test.name, func(t *testing.T) {
			size, err := CheckFrameBodyLength(test.header, test.encoded, test.declared)
			if size != 0 || err == nil || !strings.Contains(err.Error(), test.errorPart) {
				t.Fatalf("invalid frame: size=%d error=%v", size, err)
			}
		})
	}
}
