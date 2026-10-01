package harness

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"slices"
	"strings"
)

const ScenarioVariant = "i3-small4-offline-v1"
const ScenarioMode = "offline-i3"

type ScenarioRetry struct {
	Backoff  []int64 `json:"backoff_ms"`
	Timed    int64   `json:"timed_max_attempts"`
	Recovery int64   `json:"recovery_max_attempts"`
	Deadline int64   `json:"deadline_ms"`
}
type ScenarioFault struct {
	Kind      string `json:"kind"`
	Direction string `json:"direction"`
	Trigger   string `json:"trigger"`
	Index     int64  `json:"index"`
	Duration  int64  `json:"duration_ms"`
}
type ScenarioSubcase struct {
	ID   string `json:"subcase_id"`
	Size int64  `json:"payload_size_bytes"`
}
type ScenarioProfile struct {
	Schema         int64             `json:"schema_version"`
	EvidenceSchema int64             `json:"evidence_schema_version"`
	ID             string            `json:"profile_id"`
	Version        int64             `json:"profile_version"`
	Seed           string            `json:"seed_hex"`
	Variant        string            `json:"variant"`
	Mode           string            `json:"execution_mode"`
	Security       string            `json:"security_mode"`
	Topology       string            `json:"topology"`
	Envelope       int64             `json:"envelope_version"`
	Store          int64             `json:"store_version"`
	Limits         string            `json:"limits_id"`
	Count          int64             `json:"message_count"`
	Lifetime       int64             `json:"lifetime_ms"`
	Hops           int64             `json:"initial_hop_budget"`
	Window         int64             `json:"observation_window_ms"`
	Delay          int64             `json:"transport_delay_ms"`
	Retry          ScenarioRetry     `json:"retry"`
	Fault          ScenarioFault     `json:"fault"`
	Subcases       []ScenarioSubcase `json:"subcases"`
}

func CanonicalScenario(id string) (ScenarioProfile, error) {
	p := ScenarioProfile{Schema: 2, EvidenceSchema: 2, ID: id, Version: 2, Variant: ScenarioVariant, Mode: ScenarioMode, Security: "synthetic", Topology: CanonicalTopology, Envelope: 1, Store: 1, Limits: "i3-small4-v1", Count: 1, Lifetime: 30000, Hops: 2, Window: 30000, Delay: 50, Retry: ScenarioRetry{[]int64{250, 500, 1000, 2000}, 5, 1, 30000}, Subcases: []ScenarioSubcase{{"p1024", 1024}}}
	switch id {
	case "SW-V1-BASE-001":
		p.Seed = "0x524c535747330201"
		p.Fault = ScenarioFault{"none", "none", "none", 0, 0}
		p.Subcases = []ScenarioSubcase{{"p1", 1}, {"p1024", 1024}, {"p16384", 16384}}
	case "SW-V1-LOSS-EVIDENCE-001":
		p.Seed = "0x524c535747330205"
		p.Fault = ScenarioFault{"drop", "c-to-b", "delivery-frame", 1, 0}
	case "SW-V1-LOSS-EVIDENCE-BA-001":
		p.Version = 1
		p.Seed = "0x524c53574733020e"
		p.Fault = ScenarioFault{"drop", "b-to-a", "delivery-frame", 1, 0}
	case "SW-V1-DOWN-BC-001":
		p.Seed = "0x524c53574733020b"
		p.Fault = ScenarioFault{"down", "b-to-c", "custody-commit-before-forward", 1, 5000}
	case "SW-V1-DOWN-AB-001":
		p.Seed = "0x524c53574733020c"
		p.Fault = ScenarioFault{"down", "a-to-b", "origin-commit-before-send", 1, 5000}
	default:
		return ScenarioProfile{}, errors.New("unknown offline scenario")
	}
	return p, nil
}
func (p ScenarioProfile) Validate() error {
	want, err := CanonicalScenario(p.ID)
	if err != nil {
		return err
	}
	a, err := json.Marshal(p)
	if err != nil {
		return err
	}
	b, err := json.Marshal(want)
	if err != nil {
		return err
	}
	if !bytes.Equal(a, b) {
		return errors.New("scenario differs from versioned canonical input")
	}
	return nil
}
func (p ScenarioProfile) Subcase(id string) (ScenarioSubcase, error) {
	for _, s := range p.Subcases {
		if s.ID == id {
			return s, nil
		}
	}
	return ScenarioSubcase{}, errors.New("unknown subcase")
}

// CanonicalJSON rejects aliases, null/missing fields, duplicates and alternate encodings.
func CanonicalJSON(data []byte, dst any, limit int) error {
	if len(data) == 0 || len(data) > limit {
		return errors.New("canonical JSON size")
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.DisallowUnknownFields()
	if err := d.Decode(dst); err != nil {
		return fmt.Errorf("canonical JSON decode: %w", err)
	}
	b, err := json.Marshal(dst)
	if err != nil {
		return err
	}
	if !bytes.Equal(data, b) {
		return errors.New("noncanonical JSON")
	}
	return nil
}
func DecodeScenarioProfile(data []byte) (ScenarioProfile, error) {
	var p ScenarioProfile
	if err := CanonicalJSON(data, &p, MaxProfileBytes); err != nil {
		return ScenarioProfile{}, err
	}
	if err := p.Validate(); err != nil {
		return ScenarioProfile{}, err
	}
	return p, nil
}
func LoadScenarioProfile(root, relative string) (ScenarioProfile, []byte, error) {
	path, err := resolveRegularFile(root, relative)
	if err != nil {
		return ScenarioProfile{}, nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		return ScenarioProfile{}, nil, err
	}
	data, e := io.ReadAll(io.LimitReader(f, MaxProfileBytes+2))
	err = errors.Join(e, f.Close())
	if err != nil {
		return ScenarioProfile{}, nil, err
	}
	if len(data) == 0 || data[len(data)-1] != '\n' {
		return ScenarioProfile{}, nil, errors.New("profile file requires one final LF")
	}
	p, err := DecodeScenarioProfile(data[:len(data)-1])
	if err != nil {
		return ScenarioProfile{}, nil, err
	}
	return p, slices.Clone(data), nil
}

// ScenarioFrames independently encodes public, fixed fixture inputs. It never trusts runtime output.
type ScenarioFrame struct {
	From, To, Kind, Purpose, Core string
	Body                          []byte
}

func ScenarioFrames(size int64) ([]ScenarioFrame, error) {
	if size != 1 && size != 1024 && size != 16384 {
		return nil, errors.New("fixture size")
	}
	head := `"envelope_version":1,"security_mode":"synthetic","kind":"data","run_id":"11111111111111111111111111111111","origin":"A","replay_scope":"i4-small4","message_id":"33333333333333333333333333333333","destination":"C"`
	body := base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{'x'}, int(size)))
	tail := fmt.Sprintf(`"priority":"normal","payload_kind":"synthetic_opaque","payload_bytes":%d,"payload_b64":"%s"`, size, body)
	core := scenarioDigest([]byte("{" + head + `,"originated_ms":0,"lifetime_ms":30000,"initial_hops":2,` + tail + "}"))
	data := func(hops int) []byte {
		return []byte(fmt.Sprintf(`{%s,"originated_ms":0,"lifetime_ms":30000,"initial_hops":2,"remaining_hops":%d,%s,"core_sha256":"%s"}`, head, hops, tail, core))
	}
	control := func(kind, issuer string) []byte {
		return []byte("{" + strings.Replace(head, `"kind":"data"`, `"kind":"`+kind+`"`, 1) + `,"core_sha256":"` + core + `","issuer":"` + issuer + `","recipient":"A"}`)
	}
	return []ScenarioFrame{{"A", "B", "data", "admission", core, data(1)}, {"B", "C", "data", "destination", core, data(0)}, {"B", "A", "custody", "custody", core, control("custody", "B")}, {"C", "B", "delivery", "relay-clear", core, control("delivery", "C")}, {"B", "A", "delivery", "delivery", core, control("delivery", "C")}}, nil
}
