package harness

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestScenarioEventStrictRejection(t *testing.T) {
	raw := []byte(`{"schema_version":2,"sequence":1,"monotonic_ms":0,"node":"driver","kind":"environment_check","message_key":null,"generation_before":0,"generation_after":0,"cause_sequence":0,"detail":{"check_id":"routing","passed":true,"reason_code":"memory_route_graph"}}` + "\n")
	if _, err := NormalizeScenarioEvents(raw); err != nil {
		t.Fatal(err)
	}
	for name, b := range map[string][]byte{"null-detail": bytes.Replace(raw, []byte(`{"check_id":"routing","passed":true,"reason_code":"memory_route_graph"}`), []byte("null"), 1), "missing-detail-field": bytes.Replace(raw, []byte(`"reason_code":"memory_route_graph"`), []byte(`"extra":0`), 1), "duplicate-field": bytes.Replace(raw, []byte(`"passed":true`), []byte(`"passed":true,"passed":true`), 1), "unknown-kind": bytes.Replace(raw, []byte("environment_check"), []byte("success"), 1), "sequence": bytes.Replace(raw, []byte(`"sequence":1`), []byte(`"sequence":2`), 1), "future-cause": bytes.Replace(raw, []byte(`"cause_sequence":0`), []byte(`"cause_sequence":1`), 1), "time": bytes.Replace(raw, []byte(`"monotonic_ms":0`), []byte(`"monotonic_ms":-1`), 1), "blank": append(bytes.Clone(raw), '\n'), "no-lf": raw[:len(raw)-1], "huge": bytes.Repeat([]byte{' '}, MaxEvidenceFileBytes+1)} {
		t.Run(name, func(t *testing.T) {
			if _, err := NormalizeScenarioEvents(b); err == nil {
				t.Fatal("bad event accepted")
			}
		})
	}
}
func TestScenarioManifestContextRejection(t *testing.T) {
	p, err := CanonicalScenario("SW-V1-BASE-001")
	if err != nil {
		t.Fatal(err)
	}
	good := ScenarioManifest{Schema: 2, Observation: 1, Batch: "batch", Run: "one", Evidence: "batch/SW-V1-BASE-001/p1/1", Repeat: 1, ProfileID: p.ID, ProfileVersion: p.Version, ProfileHash: strings.Repeat("a", 64), Seed: p.Seed, Variant: p.Variant, Subcase: "p1", Mode: p.Mode, Security: p.Security, GitRevision: strings.Repeat("b", 40), Dirty: true, Binary: strings.Repeat("c", 64), GoVersion: "test", OS: "test", Arch: "test", Started: "2026-09-26T00:00:00Z", Ended: "2026-09-26T00:00:01Z", Topology: p.Topology, Size: 1, Count: 1, Window: 30000, Result: "PASS", EventsHash: strings.Repeat("d", 64)}
	if err := checkScenarioManifest(p, good); err != nil {
		t.Fatal(err)
	}
	changes := []func(*ScenarioManifest){func(m *ScenarioManifest) { m.Schema = 1 }, func(m *ScenarioManifest) { m.Observation = 2 }, func(m *ScenarioManifest) { m.Subcase = "p1024" }, func(m *ScenarioManifest) { m.Seed = "wrong" }, func(m *ScenarioManifest) { m.Mode = "docker" }, func(m *ScenarioManifest) { m.Variant = "canonical" }, func(m *ScenarioManifest) { m.Repeat = 4 }, func(m *ScenarioManifest) { m.Ended = "2026-09-25T00:00:00Z" }, func(m *ScenarioManifest) { m.Exit = 1 }, func(m *ScenarioManifest) { m.Run = "/tmp/private" }, func(m *ScenarioManifest) { m.ProfileHash = "" }}
	for i, change := range changes {
		bad := good
		change(&bad)
		if err := checkScenarioManifest(p, bad); err == nil {
			t.Fatalf("manifest mutation %d accepted", i)
		}
	}
	raw, err := canonicalFile(good)
	if err != nil {
		t.Fatal(err)
	}
	var got ScenarioManifest
	if err := decodeScenarioFile(raw, &got); err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		t.Fatal(err)
	}
	fields["container_id"] = json.RawMessage(`"fake"`)
	bad, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	if err := decodeScenarioFile(append(bad, '\n'), &got); err == nil {
		t.Fatal("production metadata accepted")
	}
}
