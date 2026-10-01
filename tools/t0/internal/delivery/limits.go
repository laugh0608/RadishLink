package delivery

import (
	"fmt"
	"math"
)

const (
	MaxTextBytes             int64 = 16384
	MaxSyntheticPayloadBytes int64 = 16384
	// MaxFrameBodyBytes includes the encoded envelope and payload, but not
	// the transport's four-byte length prefix. It is not a ciphertext limit.
	MaxFrameBodyBytes int64 = 32768
)

type LengthKind uint8

const (
	TextLength LengthKind = iota + 1
	SyntheticPayloadLength
	FrameBodyLength
)

// CheckLength validates numeric metadata only. Actual must be measured by the
// caller; this function neither reads bytes nor proves preallocation safety.
func CheckLength(kind LengthKind, declared, actual int64) error {
	var name string
	var limit int64
	switch kind {
	case TextLength:
		name, limit = "text", MaxTextBytes
	case SyntheticPayloadLength:
		name, limit = "synthetic payload", MaxSyntheticPayloadBytes
	case FrameBodyLength:
		name, limit = "frame body", MaxFrameBodyBytes
	default:
		return fmt.Errorf("unknown length kind: %d", kind)
	}
	if declared < 1 || actual < 1 || declared > limit || actual > limit {
		return fmt.Errorf("%s length must be within 1..%d bytes: declared=%d actual=%d", name, limit, declared, actual)
	}
	if declared != actual {
		return fmt.Errorf("%s length mismatch (limit %d bytes): declared=%d actual=%d", name, limit, declared, actual)
	}
	return nil
}

// CheckFrameBodyLength checks the sum before using it. EncodedPayload must
// describe the encoded bytes, not the raw text/payload size; header excludes
// the outer transport prefix. It returns no usable size on error.
func CheckFrameBodyLength(header, encodedPayload, declared int64) (int64, error) {
	if header <= 0 || encodedPayload <= 0 {
		return 0, fmt.Errorf("frame body components must be positive (limit %d bytes): header=%d encoded_payload=%d", MaxFrameBodyBytes, header, encodedPayload)
	}
	if header > math.MaxInt64-encodedPayload {
		return 0, fmt.Errorf("frame body length addition overflows int64 (limit %d bytes): header=%d encoded_payload=%d", MaxFrameBodyBytes, header, encodedPayload)
	}
	size := header + encodedPayload
	if err := CheckLength(FrameBodyLength, declared, size); err != nil {
		return 0, err
	}
	return size, nil
}
