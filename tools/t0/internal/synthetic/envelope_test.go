package synthetic

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"strings"
	"testing"
)

const testRun = "11111111111111111111111111111111"
const testEpoch = "22222222222222222222222222222222"
const testID = "33333333333333333333333333333333"

func fixtureData(size int) Envelope {
	e := Envelope{dataWire: dataWire{header: header{1, "synthetic", "data", testRun, "A", "squad", testID, "C"}, Lifetime: 30000, InitialHops: 2, RemainingHops: 1, Priority: "normal", PayloadKind: "synthetic_opaque", PayloadBytes: int64(size), Body: base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{'x'}, size))}}
	e.Fingerprint = e.fingerprint()
	return e
}
func mustEncode(t *testing.T, e Envelope) []byte {
	t.Helper()
	b, err := e.Encode()
	if err != nil {
		t.Fatal(err)
	}
	return b
}
func TestEnvelopeVectors(t *testing.T) {
	// Fingerprint generated independently with Python hashlib from the specified bytes.
	const data = `{"envelope_version":1,"security_mode":"synthetic","kind":"data","run_id":"11111111111111111111111111111111","origin":"A","replay_scope":"squad","message_id":"33333333333333333333333333333333","destination":"C","originated_ms":0,"lifetime_ms":30000,"initial_hops":2,"remaining_hops":1,"priority":"normal","payload_kind":"synthetic_opaque","payload_bytes":1,"payload_b64":"eA==","core_sha256":"DIGEST"}`
	const fingerprint = "61d9a313c54e5bae6d5cd02ee56b67cfd8f62f9e7e6b9a1249cd40d3b0b3d5eb"
	for _, kind := range []string{"data", "custody", "delivery"} {
		t.Run(kind, func(t *testing.T) {
			wire := strings.Replace(data, "DIGEST", fingerprint, 1)
			if kind != "data" {
				issuer := "B"
				if kind == "delivery" {
					issuer = "C"
				}
				wire = `{"envelope_version":1,"security_mode":"synthetic","kind":"` + kind + `","run_id":"11111111111111111111111111111111","origin":"A","replay_scope":"squad","message_id":"33333333333333333333333333333333","destination":"C","core_sha256":"` + fingerprint + `","issuer":"` + issuer + `","recipient":"A"}`
			}
			e, err := DecodeEnvelope([]byte(wire))
			if err != nil {
				t.Fatal(err)
			}
			if got := mustEncode(t, e); string(got) != wire {
				t.Fatal("vector changed")
			}
			var stream bytes.Buffer
			if err := WriteEnvelope(&stream, e); err != nil {
				t.Fatal(err)
			}
			decoded, err := ReadEnvelope(&stream)
			if err != nil || decoded != e {
				t.Fatalf("framing: %v", err)
			}
		})
	}
}
func TestEnvelopeStrictRejection(t *testing.T) {
	valid := string(mustEncode(t, fixtureData(1)))
	cases := map[string]string{
		"unknown":   strings.Replace(valid, `"initial_hops":2`, `"extra":1,"initial_hops":2`, 1),
		"duplicate": strings.Replace(valid, `"initial_hops":2`, `"initial_hops":2,"initial_hops":2`, 1),
		"case":      strings.Replace(valid, "payload_bytes", "PAYLOAD_BYTES", 1),
		"null":      strings.Replace(valid, `"originated_ms":0`, `"originated_ms":null`, 1),
		"missing":   strings.Replace(valid, `"originated_ms":0,`, "", 1),
		"blank":     valid + "\n", "two": valid + valid,
		"float":      strings.Replace(valid, `"lifetime_ms":30000`, `"lifetime_ms":30000.0`, 1),
		"exponent":   strings.Replace(valid, `"lifetime_ms":30000`, `"lifetime_ms":3e4`, 1),
		"overflow":   strings.Replace(valid, `"lifetime_ms":30000`, `"lifetime_ms":9223372036854775808`, 1),
		"version":    strings.Replace(valid, `"envelope_version":1`, `"envelope_version":0`, 1),
		"real":       strings.Replace(valid, `"security_mode":"synthetic"`, `"security_mode":"real"`, 1),
		"padding":    strings.Replace(valid, "eA==", "eA", 1),
		"pad-bits":   strings.Replace(valid, "eA==", "eB==", 1),
		"line-break": strings.Replace(valid, "eA==", `eA==\n`, 1),
		"url-base64": strings.Replace(valid, "eA==", "_A==", 1),
		"length":     strings.Replace(valid, `"payload_bytes":1`, `"payload_bytes":2`, 1),
		"digest":     strings.Replace(valid, "eA==", "eQ==", 1),
		"deep":       strings.Repeat("[", 12000) + strings.Repeat("]", 12000),
	}
	for name, input := range cases {
		t.Run(name, func(t *testing.T) {
			e, err := DecodeEnvelope([]byte(input))
			if err == nil || e != (Envelope{}) {
				t.Fatalf("accepted partial/invalid object: %v", err)
			}
		})
	}
	for _, size := range []int{1, 16384} {
		e := fixtureData(size)
		if _, err := DecodeEnvelope(mustEncode(t, e)); err != nil {
			t.Fatal(err)
		}
	}
	for _, size := range []int{0, 16385} {
		if _, err := fixtureData(size).Encode(); err == nil {
			t.Fatal("oversized/empty payload accepted")
		}
	}
	var prefix [4]byte
	binary.BigEndian.PutUint32(prefix[:], 32769)
	if _, err := ReadEnvelope(bytes.NewReader(prefix[:])); Code(err) != "REJECT_FRAME" {
		t.Fatalf("frame: %v", err)
	}
	if _, err := DecodeEnvelope(bytes.Repeat([]byte{'x'}, 32769)); Code(err) != "REJECT_FRAME" {
		t.Fatal(err)
	}
}
