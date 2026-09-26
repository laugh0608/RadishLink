package harness

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestNetworkProfilesStrictAndSeparate(t *testing.T) {
	for _, id := range networkIDs() {
		p, err := CanonicalNetwork(id)
		if err != nil {
			t.Fatal(err)
		}
		raw, _ := json.Marshal(p)
		if _, err = DecodeNetworkProfile(raw); err != nil {
			t.Fatal(err)
		}
		if _, err = DecodeScenarioProfile(raw); err == nil {
			t.Fatal("v3 accepted by v2")
		}
		old, _ := CanonicalScenario(id)
		oldRaw, _ := json.Marshal(old)
		if _, err = DecodeNetworkProfile(oldRaw); err == nil {
			t.Fatal("v2 accepted by v3")
		}
		for _, bad := range [][]byte{append(raw, ' '), bytes.Replace(raw, []byte(`"control_version":1`), []byte(`"control_version":2`), 1), bytes.Replace(raw, []byte(`"schema_version":3`), []byte(`"schema_version":3,"schema_version":3`), 1), bytes.Replace(raw, []byte(`"message_count":1`), []byte(`"message_count":5`), 1)} {
			if _, err = DecodeNetworkProfile(bad); err == nil {
				t.Fatal("bad profile accepted")
			}
		}
	}
}

func TestNetworkFixtureFiles(t *testing.T) {
	bindings, err := NetworkProfiles()
	if err != nil {
		t.Fatal(err)
	}
	for _, binding := range bindings {
		p, raw, err := LoadNetworkProfile("../../profiles/i5", strings.ToLower(binding.ID)+".json")
		if err != nil {
			t.Fatal(err)
		}
		if p.ID != binding.ID || scenarioDigest(raw) != binding.Hash {
			t.Fatal("fixture binding")
		}
	}
}
