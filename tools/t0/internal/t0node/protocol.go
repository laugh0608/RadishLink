package t0node

import (
	"errors"
	"fmt"
	"regexp"
	"time"
)

const (
	ProtocolVersion = 0
	MaxTestBody     = 16 * 1024
	MaxWireRequest  = 64 * 1024
)

var validIdentifier = regexp.MustCompile(`^[A-Za-z0-9._-]{1,64}$`)

type FrameKind string

const (
	FrameMessage FrameKind = "message"
	FrameAck     FrameKind = "ack"
)

// Frame is a test-only transport envelope. It is intentionally not the
// RadishLink production wire format and TestBody is deliberately unencrypted.
type Frame struct {
	Version         int       `json:"version"`
	Kind            FrameKind `json:"kind"`
	ID              string    `json:"id"`
	Origin          string    `json:"origin"`
	Destination     string    `json:"destination"`
	HopLimit        int       `json:"hop_limit"`
	ExpiresAtUnixMs int64     `json:"expires_at_unix_ms"`
	AckFor          string    `json:"ack_for,omitempty"`
	TestBody        string    `json:"test_body,omitempty"`
}

func (frame Frame) Validate(now time.Time) error {
	if frame.Version != ProtocolVersion {
		return fmt.Errorf("unsupported test protocol version: %d", frame.Version)
	}
	if frame.Kind != FrameMessage && frame.Kind != FrameAck {
		return fmt.Errorf("unsupported frame kind: %q", frame.Kind)
	}
	if !validIdentifier.MatchString(frame.ID) {
		return errors.New("frame id must use 1-64 ASCII letters, digits, dot, underscore, or hyphen")
	}
	if !validIdentifier.MatchString(frame.Origin) {
		return errors.New("origin is invalid")
	}
	if !validIdentifier.MatchString(frame.Destination) {
		return errors.New("destination is invalid")
	}
	if frame.Origin == frame.Destination {
		return errors.New("origin and destination must differ")
	}
	if frame.HopLimit < 0 || frame.HopLimit > 32 {
		return errors.New("hop limit must be between 0 and 32")
	}
	if frame.ExpiresAtUnixMs <= 0 {
		return errors.New("expiry is required")
	}
	if now.UnixMilli() >= frame.ExpiresAtUnixMs {
		return errors.New("frame expired")
	}

	switch frame.Kind {
	case FrameMessage:
		if frame.AckFor != "" {
			return errors.New("message frame cannot acknowledge another frame")
		}
		if len(frame.TestBody) > MaxTestBody {
			return fmt.Errorf("test body exceeds %d bytes", MaxTestBody)
		}
	case FrameAck:
		if !validIdentifier.MatchString(frame.AckFor) {
			return errors.New("ack_for is invalid")
		}
		if frame.TestBody != "" {
			return errors.New("ack frame cannot contain a test body")
		}
	}

	return nil
}

type Request struct {
	Operation string `json:"operation"`
	Frame     *Frame `json:"frame,omitempty"`
	Force     bool   `json:"force,omitempty"`
}

type Response struct {
	Accepted bool    `json:"accepted"`
	Reason   string  `json:"reason,omitempty"`
	Status   *Status `json:"status,omitempty"`
}

type Status struct {
	NodeID          string         `json:"node_id"`
	Pending         []string       `json:"pending"`
	Delivered       map[string]int `json:"delivered"`
	Acked           []string       `json:"acked"`
	Drops           map[string]int `json:"drops"`
	DuplicateFrames int            `json:"duplicate_frames"`
}
