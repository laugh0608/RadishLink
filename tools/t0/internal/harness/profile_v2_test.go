package harness

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestScenarioProfileVectorsAndRejections(t *testing.T) {
	names := []string{"base", "loss-evidence", "loss-evidence-ba", "down-bc", "down-ab"}
	for _, name := range names {
		p, raw, err := LoadScenarioProfile("../../profiles/i4", "sw-v1-"+name+"-001.json")
		if err != nil {
			t.Fatal(err)
		}
		want, err := CanonicalScenario(p.ID)
		if err != nil {
			t.Fatal(err)
		}
		b, err := json.Marshal(want)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(raw, append(b, '\n')) {
			t.Fatal("fixture differs")
		}
		if _, err := DecodeProfile(raw); err == nil {
			t.Fatal("V0 accepted schema 2")
		}
	}
	p, _, err := LoadScenarioProfile("../../profiles/i4", "sw-v1-base-001.json")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(p)
	if err != nil {
		t.Fatal(err)
	}
	for name, b := range map[string][]byte{
		"unknown": append([]byte(`{"extra":0,`), raw[1:]...), "duplicate": append([]byte(`{"schema_version":2,`), raw[1:]...), "case": bytes.Replace(raw, []byte("schema_version"), []byte("SCHEMA_VERSION"), 1), "null": bytes.Replace(raw, []byte(`"message_count":1`), []byte(`"message_count":null`), 1), "missing": bytes.Replace(raw, []byte(`"message_count":1,`), nil, 1), "float": bytes.Replace(raw, []byte(`"schema_version":2`), []byte(`"schema_version":2.0`), 1), "version": bytes.Replace(raw, []byte(`"schema_version":2`), []byte(`"schema_version":3`), 1), "seed": bytes.Replace(raw, []byte("0201"), []byte("0202"), 1), "variant": bytes.Replace(raw, []byte(ScenarioVariant), []byte("production"), 1), "limits": bytes.Replace(raw, []byte("i3-small4-v1"), []byte("unlimited"), 1), "subcase": bytes.Replace(raw, []byte("p16384"), []byte("p16385"), 1), "whitespace": append(raw, ' '), "two": append(raw, raw...), "oversized": bytes.Repeat([]byte{' '}, MaxProfileBytes+1), "deep": []byte(strings.Repeat("[", 10000) + "0" + strings.Repeat("]", 10000)),
	} {
		t.Run(name, func(t *testing.T) {
			got, err := DecodeScenarioProfile(b)
			if err == nil || got.ID != "" {
				t.Fatal("invalid profile returned")
			}
		})
	}
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "p.json"), append(append(bytes.Clone(raw), '\n'), '\n'), 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err := LoadScenarioProfile(dir, "p.json"); err == nil {
		t.Fatal("extra final LF accepted")
	}
}
