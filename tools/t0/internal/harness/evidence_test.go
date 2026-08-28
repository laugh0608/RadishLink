package harness

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestEvidenceBundleRoundTripAndTamperDetection(t *testing.T) {
	root := filepath.Join(t.TempDir(), "run")
	input := testEvidenceInput(t, 1, "2026-08-28T00:00:00Z", 101, "/tmp/run-one")
	if err := WriteEvidenceBundle(root, input); err != nil {
		t.Fatal(err)
	}
	if err := VerifyEvidence(root); err != nil {
		t.Fatalf("verify evidence: %v", err)
	}

	assertionPath := filepath.Join(root, "assertions.json")
	assertions, err := os.ReadFile(assertionPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(assertionPath, append(assertions, ' '), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := VerifyEvidence(root); err == nil || !strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("tampered evidence error: %v", err)
	}
}

func TestVerifyEvidenceRejectsPartialEvidenceAndSymlink(t *testing.T) {
	partial := t.TempDir()
	if err := os.Mkdir(filepath.Join(partial, "logs"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(partial, "manifest.json"), []byte("{}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := VerifyEvidence(partial); err == nil {
		t.Fatal("partial evidence was accepted")
	}

	root := filepath.Join(t.TempDir(), "run")
	if err := WriteEvidenceBundle(root, testEvidenceInput(t, 1, "2026-08-28T00:00:00Z", 101, "/tmp/run-one")); err != nil {
		t.Fatal(err)
	}
	eventsPath := filepath.Join(root, "events.ndjson")
	outside := filepath.Join(t.TempDir(), "events.ndjson")
	if err := os.WriteFile(outside, []byte("{}\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(eventsPath); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, eventsPath); err != nil {
		t.Fatal(err)
	}
	if err := VerifyEvidence(root); err == nil {
		t.Fatal("symlink evidence was accepted")
	}
}

func TestVerifyEvidenceRejectsChecksumTraversal(t *testing.T) {
	root := filepath.Join(t.TempDir(), "run")
	if err := WriteEvidenceBundle(root, testEvidenceInput(t, 1, "2026-08-28T00:00:00Z", 101, "/tmp/run-one")); err != nil {
		t.Fatal(err)
	}
	checksumPath := filepath.Join(root, "checksums.sha256")
	checksums, err := os.ReadFile(checksumPath)
	if err != nil {
		t.Fatal(err)
	}
	checksums = append(checksums, []byte(strings.Repeat("0", 64)+"  ../outside\n")...)
	if err := os.WriteFile(checksumPath, checksums, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := VerifyEvidence(root); err == nil || !strings.Contains(err.Error(), "invalid checksum path") {
		t.Fatalf("checksum traversal error: %v", err)
	}
}

func TestCompareEvidenceRunsNormalizesOnlyRuntimeFields(t *testing.T) {
	profileRoot := t.TempDir()
	for repeat := 1; repeat <= 3; repeat++ {
		input := testEvidenceInput(
			t,
			repeat,
			"2026-08-28T00:00:0"+string(rune('0'+repeat))+"Z",
			100+repeat,
			"/tmp/run-"+string(rune('0'+repeat)),
		)
		if err := WriteEvidenceBundle(filepath.Join(profileRoot, string(rune('0'+repeat))), input); err != nil {
			t.Fatal(err)
		}
	}
	if digest, err := CompareEvidenceRuns(profileRoot); err != nil || len(digest) != 64 {
		t.Fatalf("compare normalized runs: digest=%q err=%v", digest, err)
	}

	thirdRoot := filepath.Join(profileRoot, "3")
	if err := os.RemoveAll(thirdRoot); err != nil {
		t.Fatal(err)
	}
	changed := testEvidenceInput(t, 3, "2026-08-28T00:00:03Z", 103, "/tmp/run-3")
	changed.Events[3].Attributes["fault_hits"] = 2
	if err := WriteEvidenceBundle(thirdRoot, changed); err != nil {
		t.Fatal(err)
	}
	if _, err := CompareEvidenceRuns(profileRoot); err == nil || !strings.Contains(err.Error(), "differs") {
		t.Fatalf("normalization difference error: %v", err)
	}
}

func TestNormalizeEventsPreservesOrderAndExtraEvents(t *testing.T) {
	base := []EvidenceEvent{
		{Sequence: 1, Kind: "first", MonotonicMS: 1},
		{Sequence: 2, Kind: "second", MonotonicMS: 2},
	}
	raw, err := encodeEvents(base)
	if err != nil {
		t.Fatal(err)
	}
	normalized, err := NormalizeEvents(raw)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(normalized), `"kind":"first"`) || !strings.Contains(string(normalized), `"kind":"second"`) {
		t.Fatalf("normalized event order was not preserved: %s", normalized)
	}
	extra := append(base, EvidenceEvent{Sequence: 3, Kind: "extra", MonotonicMS: 3})
	extraRaw, err := encodeEvents(extra)
	if err != nil {
		t.Fatal(err)
	}
	extraNormalized, err := NormalizeEvents(extraRaw)
	if err != nil {
		t.Fatal(err)
	}
	if string(normalized) == string(extraNormalized) {
		t.Fatal("normalization ignored an extra event")
	}
}

func testEvidenceInput(t *testing.T, repeat int, wallTime string, pid int, temporaryPath string) EvidenceInput {
	t.Helper()
	profileRaw := []byte(canonicalProfileJSON(
		"SW-V0-FAULT-HIT-001",
		"0x524c535747330102",
		"drop",
		"a-to-b",
		"synthetic-frame",
		2,
	))
	profile, err := DecodeProfile(profileRaw)
	if err != nil {
		t.Fatal(err)
	}
	return EvidenceInput{
		Profile:    profile,
		ProfileRaw: profileRaw,
		Repeat:     repeat,
		Topology: TopologyEvidence{
			SchemaVersion: EvidenceSchemaVersion,
			ProfileID:     profile.ProfileID,
			Topology:      profile.Topology,
			Probes:        []ProbeResult{},
		},
		Events: []EvidenceEvent{
			{Sequence: 1, Kind: "frame_1_forwarded", MonotonicMS: 0},
			{Sequence: 2, Kind: "frame_2_dropped", MonotonicMS: 100},
			{Sequence: 3, Kind: "frame_3_forwarded", MonotonicMS: 200},
			{
				Sequence:      4,
				Kind:          "fault_hit_once",
				Node:          "proxy-ab",
				MonotonicMS:   250,
				WallTime:      wallTime,
				PID:           pid,
				ContainerID:   "container-" + string(rune('0'+repeat)),
				TemporaryPath: temporaryPath,
				Attributes:    map[string]any{"fault_hits": 1},
			},
		},
		Assertions: []Assertion{
			{Name: "fault_hit_once", Passed: true, Detail: "observed exactly once"},
			{Name: "expected:frame_1_forwarded", Passed: true, Detail: "present"},
			{Name: "expected:frame_2_dropped", Passed: true, Detail: "present"},
			{Name: "expected:frame_3_forwarded", Passed: true, Detail: "present"},
			{Name: "expected:fault_hit_once", Passed: true, Detail: "present"},
			{Name: "forbidden:fault_hit_wrong_direction", Passed: true, Detail: "not present"},
			{Name: "forbidden:fault_hit_multiple", Passed: true, Detail: "not present"},
		},
		Residuals: ResidualInventory{
			SchemaVersion:     EvidenceSchemaVersion,
			ProfileID:         profile.ProfileID,
			InventoryComplete: true,
			Containers:        []string{},
			Networks:          []string{},
			Images:            []string{},
		},
		Metadata: EvidenceMetadata{
			RunID:                 "unit-test-run",
			GitRevision:           strings.Repeat("0", 40),
			GitDirty:              true,
			StartedAt:             "2026-08-28T00:00:00Z",
			EndedAt:               "2026-08-28T00:00:01Z",
			GoVersion:             "go-test",
			HostArchitecture:      "test-host",
			DaemonArchitecture:    "test-daemon",
			ContainerArchitecture: "test-container",
			BinarySHA256:          strings.Repeat("1", 64),
			ImageDigest:           "sha256:" + strings.Repeat("2", 64),
			ExitCode:              0,
		},
	}
}
