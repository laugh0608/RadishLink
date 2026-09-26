package harness

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
)

type ScenarioEvent struct {
	Schema   int64           `json:"schema_version"`
	Sequence int64           `json:"sequence"`
	Now      int64           `json:"monotonic_ms"`
	Node     string          `json:"node"`
	Kind     string          `json:"kind"`
	Key      *ObservedKey    `json:"message_key"`
	Before   int64           `json:"generation_before"`
	After    int64           `json:"generation_after"`
	Cause    int64           `json:"cause_sequence"`
	Detail   json.RawMessage `json:"detail"`
}
type EnvironmentDetail struct {
	ID     string `json:"check_id"`
	Passed bool   `json:"passed"`
	Reason string `json:"reason_code"`
}
type OperationDetail struct {
	Operation    string   `json:"operation"`
	Error        string   `json:"error_code"`
	Committed    bool     `json:"committed"`
	Transactions []string `json:"transaction_kinds"`
	Inputs       int64    `json:"input_count"`
}
type VerdictDetail struct {
	Receiver string `json:"receiver"`
	Neighbor string `json:"neighbor"`
	Frame    string `json:"frame_sha256"`
	Purpose  string `json:"purpose"`
	Verdict  string `json:"verdict"`
}
type FrameDetail struct {
	Direction    string `json:"direction"`
	Kind         string `json:"kind"`
	Core         string `json:"core_sha256"`
	Frame        string `json:"frame_sha256"`
	Bytes        int64  `json:"wire_bytes"`
	SendSequence int64  `json:"send_sequence"`
}
type FaultDetail struct {
	Direction string `json:"direction"`
	Trigger   string `json:"trigger"`
	Action    string `json:"action"`
	Matched   int64  `json:"matched_sequence"`
	Hit       int64  `json:"hit_index"`
}
type EndDetail struct {
	Now       int64  `json:"now"`
	Remaining int64  `json:"remaining_messages"`
	Pending   int64  `json:"pending_frames"`
	Reason    string `json:"reason_code"`
}
type AbortDetail struct {
	Now    int64  `json:"now"`
	Stage  string `json:"stage"`
	Error  string `json:"error_code"`
	Reason string `json:"reason_code"`
}
type ScenarioManifest struct {
	Schema         int64  `json:"schema_version"`
	Observation    int64  `json:"observation_version"`
	Batch          string `json:"batch_id"`
	Run            string `json:"run_id"`
	Evidence       string `json:"evidence_id"`
	Repeat         int64  `json:"repeat"`
	ProfileID      string `json:"profile_id"`
	ProfileVersion int64  `json:"profile_version"`
	ProfileHash    string `json:"profile_sha256"`
	Seed           string `json:"seed_hex"`
	Variant        string `json:"variant"`
	Subcase        string `json:"subcase_id"`
	Mode           string `json:"execution_mode"`
	Security       string `json:"security_mode"`
	GitRevision    string `json:"git_revision"`
	Dirty          bool   `json:"git_dirty"`
	Binary         string `json:"binary_sha256"`
	GoVersion      string `json:"go_version"`
	OS             string `json:"host_os"`
	Arch           string `json:"host_architecture"`
	Started        string `json:"started_at"`
	Ended          string `json:"ended_at"`
	Topology       string `json:"topology"`
	Size           int64  `json:"payload_size_bytes"`
	Count          int64  `json:"message_count"`
	Window         int64  `json:"observation_window_ms"`
	Exit           int64  `json:"exit_code"`
	Result         string `json:"result"`
	EventsHash     string `json:"normalized_events_sha256"`
}
type ScenarioTopology struct {
	Schema   int64    `json:"schema_version"`
	Mode     string   `json:"execution_mode"`
	Topology string   `json:"topology"`
	Edges    []string `json:"edges"`
	Denied   []string `json:"denied_edges"`
	Checks   []int64  `json:"check_sequences"`
}
type ScenarioResiduals struct {
	Schema   int64 `json:"schema_version"`
	Complete bool  `json:"inventory_complete"`
	Owned    int64 `json:"owned_store_count"`
	Removed  int64 `json:"removed_store_count"`
	Pending  int64 `json:"pending_frame_count"`
	Children int64 `json:"active_child_count"`
	Clean    bool  `json:"cleanup_complete"`
}
type ScenarioMetrics struct {
	Schema          int64      `json:"schema_version"`
	Events          int64      `json:"source_event_count"`
	Origin          int64      `json:"origin_commits"`
	Custody         int64      `json:"custody_commits"`
	Destination     int64      `json:"destination_commits"`
	DeliveryA       int64      `json:"delivery_accepts_a"`
	DeliveryB       int64      `json:"delivery_accepts_b"`
	ReleasedB       int64      `json:"body_releases_b"`
	DataAttempts    int64      `json:"data_attempts"`
	ControlAttempts int64      `json:"control_attempts"`
	DataFrames      int64      `json:"data_frames"`
	ControlFrames   int64      `json:"control_frames"`
	Duplicates      int64      `json:"duplicate_receives"`
	Rejects         int64      `json:"rejects"`
	Expiries        int64      `json:"expiries"`
	FaultHits       int64      `json:"fault_hits"`
	Peaks           []NodePeak `json:"node_peaks"`
	Latencies       []int64    `json:"delivery_latency_ms"`
	Samples         int64      `json:"sample_count"`
}
type NodePeak struct {
	Node  string        `json:"node"`
	Usage ResourceUsage `json:"usage"`
}
type ScenarioAssertion struct {
	ID       string  `json:"id"`
	Category string  `json:"category"`
	Passed   bool    `json:"passed"`
	Sources  []int64 `json:"source_sequences"`
	Reason   string  `json:"reason_code"`
}
type ScenarioAssertions struct {
	Schema int64               `json:"schema_version"`
	Items  []ScenarioAssertion `json:"assertions"`
}
type ScenarioBundle struct {
	Profile   ScenarioProfile
	Manifest  ScenarioManifest
	Topology  ScenarioTopology
	Events    []ScenarioEvent
	Residuals ScenarioResiduals
}

func scenarioDigest(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func canonicalFile(v any) ([]byte, error) {
	b, e := json.Marshal(v)
	if e != nil {
		return nil, e
	}
	return append(b, '\n'), nil
}
func decodeScenarioFile(b []byte, v any) error {
	if len(b) == 0 || b[len(b)-1] != '\n' {
		return errors.New("missing final LF")
	}
	return CanonicalJSON(b[:len(b)-1], v, MaxEvidenceFileBytes)
}

func detailOf(e ScenarioEvent) (any, error) {
	var v any
	switch e.Kind {
	case "environment_check":
		v = &EnvironmentDetail{}
	case "submit_result", "batch_result":
		v = &OperationDetail{}
	case "verdict_decision":
		v = &VerdictDetail{}
	case "state_observed":
		v = &ObservedState{}
	case "retry_decision":
		v = &ObservedRetry{}
	case "frame_written", "frame_received":
		v = &FrameDetail{}
	case "fault_transition":
		v = &FaultDetail{}
	case "observation_end":
		v = &EndDetail{}
	case "execution_aborted":
		v = &AbortDetail{}
	default:
		return nil, errors.New("unknown scenario event")
	}
	if err := CanonicalJSON(e.Detail, v, 16*1024); err != nil {
		return nil, fmt.Errorf("event %d detail: %w", e.Sequence, err)
	}
	return v, nil
}
func NormalizeScenarioEvents(raw []byte) ([]byte, error) { return normalizeSemanticEvents(raw, 2) }
func normalizeSemanticEvents(raw []byte, schema int64) ([]byte, error) {
	if len(raw) == 0 || len(raw) > MaxEvidenceFileBytes || raw[len(raw)-1] != '\n' {
		return nil, errors.New("event file bounds")
	}
	lines := bytes.Split(raw[:len(raw)-1], []byte{'\n'})
	if len(lines) > 8192 {
		return nil, errors.New("event count")
	}
	var last int64
	for i, line := range lines {
		var e ScenarioEvent
		if err := CanonicalJSON(line, &e, 16*1024); err != nil {
			return nil, err
		}
		if e.Schema != schema || e.Sequence != int64(i+1) || e.Now < last || e.Now > 30000 || e.Before < 0 || e.After < 0 || e.Cause < 0 || e.Cause >= e.Sequence {
			return nil, errors.New("event header")
		}
		if _, err := detailOf(e); err != nil {
			return nil, err
		}
		last = e.Now
	}
	return slices.Clone(raw), nil
}
func decodeScenarioEvents(raw []byte) ([]ScenarioEvent, error) {
	if _, err := NormalizeScenarioEvents(raw); err != nil {
		return nil, err
	}
	lines := bytes.Split(raw[:len(raw)-1], []byte{'\n'})
	out := make([]ScenarioEvent, len(lines))
	for i, line := range lines {
		if err := json.Unmarshal(line, &out[i]); err != nil {
			return nil, err
		}
	}
	return out, nil
}
func encodeScenarioEvents(events []ScenarioEvent) ([]byte, error) {
	return encodeSemanticEvents(events, 2)
}
func encodeSemanticEvents(events []ScenarioEvent, schema int64) ([]byte, error) {
	var b bytes.Buffer
	if len(events) > 8192 {
		return nil, errors.New("too many events")
	}
	for _, e := range events {
		raw, err := canonicalFile(e)
		if err != nil {
			return nil, err
		}
		if len(raw) > 16*1024+1 || b.Len()+len(raw) > MaxEvidenceFileBytes {
			return nil, errors.New("event output bounds")
		}
		b.Write(raw)
	}
	return normalizeSemanticEvents(b.Bytes(), schema)
}
