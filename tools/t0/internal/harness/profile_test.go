package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLoadCanonicalProfiles(t *testing.T) {
	root := filepath.Join("..", "..", "profiles")
	tests := map[string]string{
		"sw-v0-topology-001.json":  "SW-V0-TOPOLOGY-001",
		"sw-v0-fault-hit-001.json": "SW-V0-FAULT-HIT-001",
		"sw-v0-evidence-001.json":  "SW-V0-EVIDENCE-001",
		"sw-v0-clock-001.json":     "SW-V0-CLOCK-001",
	}
	for name, expectedID := range tests {
		profile, raw, err := LoadProfile(root, name)
		if err != nil {
			t.Fatalf("load %s: %v", name, err)
		}
		if profile.ProfileID != expectedID || len(raw) == 0 {
			t.Fatalf("load %s: id=%q bytes=%d", name, profile.ProfileID, len(raw))
		}
	}
}

func TestDecodeProfileRejectsDuplicateCriticalField(t *testing.T) {
	data := canonicalProfileJSON("SW-V0-FAULT-HIT-001", "0x524c535747330102", "drop", "a-to-b", "synthetic-frame", 2)
	data = strings.Replace(data, `"schema_version":1`, `"schema_version":1,"schema_version":1`, 1)
	if _, err := DecodeProfile([]byte(data)); err == nil || !strings.Contains(err.Error(), "duplicate JSON key") {
		t.Fatalf("duplicate field error: %v", err)
	}
}

func TestDecodeProfileRejectsUnknownAndInvalidValues(t *testing.T) {
	tests := []struct {
		name    string
		replace string
		with    string
	}{
		{name: "unknown", replace: `"schema_version":1`, with: `"schema_version":1,"surprise":true`},
		{name: "schema", replace: `"schema_version":1`, with: `"schema_version":2`},
		{name: "seed", replace: `0x524c535747330102`, with: `0X524C535747330102`},
		{name: "negative", replace: `"message_count":3`, with: `"message_count":-1`},
		{name: "overflow", replace: `"observation_window_ms":10000`, with: `"observation_window_ms":9223372036854775807`},
	}
	base := canonicalProfileJSON("SW-V0-FAULT-HIT-001", "0x524c535747330102", "drop", "a-to-b", "synthetic-frame", 2)
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := DecodeProfile([]byte(strings.Replace(base, test.replace, test.with, 1))); err == nil {
				t.Fatal("invalid profile was accepted")
			}
		})
	}
}

func TestLoadProfileRejectsTraversalAndSymlink(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "profile.json")
	if err := os.WriteFile(outside, []byte("{}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := LoadProfile(root, "../profile.json"); err == nil {
		t.Fatal("path traversal was accepted")
	}

	link := filepath.Join(root, "profile.json")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	if _, _, err := LoadProfile(root, "profile.json"); err == nil {
		t.Fatal("symlink profile was accepted")
	}

	parentLink := filepath.Join(root, "linked")
	if err := os.Symlink(filepath.Dir(outside), parentLink); err != nil {
		t.Fatal(err)
	}
	if _, _, err := LoadProfile(root, "linked/profile.json"); err == nil {
		t.Fatal("profile below a symlinked parent was accepted")
	}
}

func TestDecodeProfileRejectsUnknownFaultParameter(t *testing.T) {
	data := canonicalProfileJSON("SW-V0-FAULT-HIT-001", "0x524c535747330102", "drop", "a-to-b", "synthetic-frame", 2)
	data = strings.Replace(data, `"parameters":{}`, `"parameters":{"surprise":1}`, 1)
	if _, err := DecodeProfile([]byte(data)); err == nil {
		t.Fatal("unknown fault parameter was accepted")
	}
}

func TestDecodeProfileRejectsChangedCanonicalExpectation(t *testing.T) {
	data := canonicalProfileJSON("SW-V0-FAULT-HIT-001", "0x524c535747330102", "drop", "a-to-b", "synthetic-frame", 2)
	data = strings.Replace(data, `"frame_2_dropped"`, `"different"`, 1)
	if _, err := DecodeProfile([]byte(data)); err == nil {
		t.Fatal("changed canonical expectation was accepted")
	}
}

func canonicalProfileJSON(id, seed, kind, direction, trigger string, triggerIndex int) string {
	return `{
  "schema_version":1,
  "profile_id":"` + id + `",
  "profile_version":1,
  "seed_hex":"` + seed + `",
  "topology":"a-b-c-one-relay",
  "payload_size_bytes":1,
  "message_count":3,
  "lifetime_ms":30000,
  "initial_hop_budget":2,
  "fault":{"kind":"` + kind + `","direction":"` + direction + `","trigger_event":"` + trigger + `","trigger_index":` + stringIndex(triggerIndex) + `,"parameters":{}},
  "retry":{"backoff_ms":[250,500,1000,2000],"max_attempts":4,"deadline_ms":10000},
  "observation_window_ms":10000,
  "expected_events":["frame_1_forwarded","frame_2_dropped","frame_3_forwarded","fault_hit_once"],
  "forbidden_events":["fault_hit_wrong_direction","fault_hit_multiple"],
  "evidence_schema_version":1
}`
}

func stringIndex(value int) string {
	if value == 0 {
		return "0"
	}
	if value == 1 {
		return "1"
	}
	if value == 2 {
		return "2"
	}
	return "-1"
}
