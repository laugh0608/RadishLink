// Package synthetic implements the I3 offline test model, never real authentication.
package synthetic

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"

	"radishlink.local/t0/internal/delivery"
	"radishlink.local/t0/internal/harness"
)

// Failure retains a local classification and the underlying cause without body data.
type Failure struct {
	Code, Stage string
	Cause       error
}

func (e *Failure) Error() string               { return fmt.Sprintf("%s at %s: %v", e.Code, e.Stage, e.Cause) }
func (e *Failure) Unwrap() error               { return e.Cause }
func fail(code, stage string) error            { return &Failure{code, stage, errors.New("contract rejected")} }
func wrap(code, stage string, err error) error { return &Failure{code, stage, err} }
func Code(err error) string {
	var f *Failure
	if errors.As(err, &f) {
		return f.Code
	}
	return ""
}

type Key struct {
	Version int64  `json:"envelope_version"`
	Origin  string `json:"origin"`
	Scope   string `json:"replay_scope"`
	ID      string `json:"message_id"`
}

func (k Key) order() string { return k.Origin + "/" + k.Scope + "/" + k.ID }
func (k Key) valid() bool {
	return k.Version == 1 && k.Origin == "A" && label(k.Scope) && lowerHex(k.ID, 32)
}

type header struct {
	Version     int64  `json:"envelope_version"`
	Mode        string `json:"security_mode"`
	Kind        string `json:"kind"`
	Run         string `json:"run_id"`
	Origin      string `json:"origin"`
	Scope       string `json:"replay_scope"`
	ID          string `json:"message_id"`
	Destination string `json:"destination"`
}

func (h header) key() Key { return Key{h.Version, h.Origin, h.Scope, h.ID} }

type dataWire struct {
	header
	Originated    int64  `json:"originated_ms"`
	Lifetime      int64  `json:"lifetime_ms"`
	InitialHops   int64  `json:"initial_hops"`
	RemainingHops int64  `json:"remaining_hops"`
	Priority      string `json:"priority"`
	PayloadKind   string `json:"payload_kind"`
	PayloadBytes  int64  `json:"payload_bytes"`
	Body          string `json:"payload_b64"`
	Fingerprint   string `json:"core_sha256"`
}
type controlWire struct {
	header
	Fingerprint string `json:"core_sha256"`
	Issuer      string `json:"issuer"`
	Recipient   string `json:"recipient"`
}

// Envelope has an opaque synthetic body; its digest is not a credential.
type Envelope struct {
	dataWire
	Issuer, Recipient string
}

func (e Envelope) Key() Key        { return e.header.key() }
func (e Envelope) deadline() int64 { return e.Originated + e.Lifetime }
func lowerHex(s string, n int) bool {
	if len(s) != n {
		return false
	}
	for _, c := range s {
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f') {
			return false
		}
	}
	return true
}
func label(s string) bool {
	if len(s) < 1 || len(s) > 64 {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return false
		}
	}
	return true
}
func digest(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }

func strictJSON(data []byte, value any) error {
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(value); err != nil {
		return fail("REJECT_STRUCTURE", "json decode")
	}
	encoded, err := json.Marshal(value)
	if err != nil || !bytes.Equal(data, encoded) {
		return fail("REJECT_STRUCTURE", "canonical json")
	}
	return nil
}

func decodeBody(s string, size int64) ([]byte, error) {
	if size < 1 || size > delivery.MaxSyntheticPayloadBytes || len(s) != base64.StdEncoding.EncodedLen(int(size)) || strings.ContainsAny(s, "\r\n") {
		return nil, fail("REJECT_STRUCTURE", "payload length")
	}
	b, err := base64.StdEncoding.Strict().DecodeString(s)
	if err != nil || int64(len(b)) != size || base64.StdEncoding.EncodeToString(b) != s {
		return nil, fail("REJECT_STRUCTURE", "payload encoding")
	}
	return b, nil
}

func (e Envelope) fingerprint() string {
	// Explicit ordered fields exclude only the mutable remaining hop and digest.
	core := struct {
		header
		Originated   int64  `json:"originated_ms"`
		Lifetime     int64  `json:"lifetime_ms"`
		InitialHops  int64  `json:"initial_hops"`
		Priority     string `json:"priority"`
		PayloadKind  string `json:"payload_kind"`
		PayloadBytes int64  `json:"payload_bytes"`
		Body         string `json:"payload_b64"`
	}{e.header, e.Originated, e.Lifetime, e.InitialHops, e.Priority, e.PayloadKind, e.PayloadBytes, e.Body}
	b, _ := json.Marshal(core)
	return digest(b)
}
func (e Envelope) validate() error {
	if e.Version != 1 {
		return fail("REJECT_VERSION", "envelope")
	}
	if e.Mode != "synthetic" || !lowerHex(e.Run, 32) || !e.Key().valid() || e.Destination != "C" || !lowerHex(e.Fingerprint, 64) {
		return fail("REJECT_STRUCTURE", "header")
	}
	switch e.Kind {
	case "data":
		if e.Originated < 0 || e.Originated > 60000 || e.Lifetime < 1 || e.Lifetime > 30000 || e.InitialHops != 2 || e.RemainingHops < 0 || e.RemainingHops > 2 || e.Priority != "normal" || e.PayloadKind != "synthetic_opaque" || e.Issuer != "" || e.Recipient != "" {
			return fail("REJECT_STRUCTURE", "data")
		}
		if _, err := decodeBody(e.Body, e.PayloadBytes); err != nil {
			return err
		}
		if e.fingerprint() != e.Fingerprint {
			return fail("CONFLICT", "core fingerprint")
		}
	case "custody", "delivery":
		issuer := "B"
		if e.Kind == "delivery" {
			issuer = "C"
		}
		if e.Issuer != issuer || e.Recipient != "A" || e.Originated != 0 || e.Lifetime != 0 || e.InitialHops != 0 || e.RemainingHops != 0 || e.Priority != "" || e.PayloadKind != "" || e.PayloadBytes != 0 || e.Body != "" {
			return fail("REJECT_STRUCTURE", "control")
		}
	default:
		return fail("REJECT_STRUCTURE", "kind")
	}
	return nil
}
func (e Envelope) Encode() ([]byte, error) {
	if err := e.validate(); err != nil {
		return nil, err
	}
	var value any = e.dataWire
	limit := int(delivery.MaxFrameBodyBytes)
	if e.Kind != "data" {
		value = controlWire{e.header, e.Fingerprint, e.Issuer, e.Recipient}
		limit = 2048
	}
	b, err := json.Marshal(value)
	if err != nil {
		return nil, wrap("REJECT_STRUCTURE", "encode", err)
	}
	if len(b) > limit {
		return nil, fail("REJECT_FRAME", "encoded limit")
	}
	return b, nil
}
func DecodeEnvelope(data []byte) (Envelope, error) {
	if len(data) < 1 || int64(len(data)) > delivery.MaxFrameBodyBytes {
		return Envelope{}, fail("REJECT_FRAME", "body limit")
	}
	var tag struct {
		Kind string `json:"kind"`
	}
	if err := json.Unmarshal(data, &tag); err != nil {
		return Envelope{}, fail("REJECT_STRUCTURE", "kind decode")
	}
	var e Envelope
	if tag.Kind == "data" {
		if err := strictJSON(data, &e.dataWire); err != nil {
			return Envelope{}, err
		}
	} else if tag.Kind == "custody" || tag.Kind == "delivery" {
		if len(data) > 2048 {
			return Envelope{}, fail("REJECT_FRAME", "control limit")
		}
		var c controlWire
		if err := strictJSON(data, &c); err != nil {
			return Envelope{}, err
		}
		e.header, e.Fingerprint, e.Issuer, e.Recipient = c.header, c.Fingerprint, c.Issuer, c.Recipient
	} else {
		return Envelope{}, fail("REJECT_STRUCTURE", "kind")
	}
	if err := e.validate(); err != nil {
		return Envelope{}, err
	}
	return e, nil
}
func ReadEnvelope(r io.Reader) (Envelope, error) {
	b, err := harness.ReadSyntheticFrameWithLimit(r, delivery.MaxFrameBodyBytes)
	if err != nil {
		return Envelope{}, wrap("REJECT_FRAME", "read", err)
	}
	return DecodeEnvelope(b)
}
func WriteEnvelope(w io.Writer, e Envelope) error {
	b, err := e.Encode()
	if err != nil {
		return err
	}
	if err = harness.WriteSyntheticFrameWithLimit(w, b, delivery.MaxFrameBodyBytes); err != nil {
		return wrap("REJECT_FRAME", "write", err)
	}
	return nil
}
