package harness

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"time"
)

var scenarioFiles = []string{"assertions.json", "events.ndjson", "manifest.json", "metrics.json", "profile.json", "residuals.json", "topology.json"}

func WriteScenarioBundle(root string, b ScenarioBundle) error {
	metrics, assertions, result, err := AssessScenario(b.Profile, b.Manifest.Subcase, b.Events, b.Residuals)
	if err != nil {
		return err
	}
	profile, err := canonicalFile(b.Profile)
	if err != nil {
		return err
	}
	events, err := encodeScenarioEvents(b.Events)
	if err != nil {
		return err
	}
	b.Manifest.Schema = 2
	b.Manifest.Observation = 1
	b.Manifest.ProfileHash = scenarioDigest(profile)
	b.Manifest.EventsHash = scenarioDigest(events)
	b.Manifest.Result = result
	b.Manifest.Exit = 0
	if result == "FAIL" {
		b.Manifest.Exit = 1
	}
	if result == "INVALID" {
		b.Manifest.Exit = 2
	}
	if err := checkScenarioManifest(b.Profile, b.Manifest); err != nil {
		return err
	}
	values := map[string]any{"profile.json": b.Profile, "manifest.json": b.Manifest, "topology.json": b.Topology, "metrics.json": metrics, "assertions.json": assertions, "residuals.json": b.Residuals}
	files := map[string][]byte{"events.ndjson": events}
	total := len(events)
	for name, v := range values {
		raw, e := canonicalFile(v)
		if e != nil {
			return e
		}
		if len(raw) > MaxEvidenceFileBytes {
			return errors.New("scenario file cap")
		}
		total += len(raw)
		files[name] = raw
	}
	if total > 8*1024*1024 {
		return errors.New("scenario bundle cap")
	}
	if err := prepareEvidenceRoot(root); err != nil {
		return err
	}
	for _, name := range scenarioFiles {
		if err := atomicWriteEvidenceFile(root, name, files[name]); err != nil {
			return err
		}
	}
	return FinalizeEvidence(root)
}
func checkScenarioManifest(p ScenarioProfile, m ScenarioManifest) error {
	sub, err := p.Subcase(m.Subcase)
	if err != nil {
		return err
	}
	start, err := time.Parse(time.RFC3339Nano, m.Started)
	if err != nil {
		return err
	}
	end, err := time.Parse(time.RFC3339Nano, m.Ended)
	if err != nil {
		return err
	}
	if end.Before(start) || !strings.HasSuffix(m.Started, "Z") || !strings.HasSuffix(m.Ended, "Z") {
		return errors.New("manifest time")
	}
	if m.Schema != 2 || m.Observation != 1 || m.ProfileID != p.ID || m.ProfileVersion != p.Version || m.Seed != p.Seed || m.Variant != p.Variant || m.Mode != p.Mode || m.Security != p.Security || m.Topology != p.Topology || m.Size != sub.Size || m.Count != 1 || m.Window != 30000 || m.Repeat < 1 || m.Repeat > 3 {
		return errors.New("manifest profile binding")
	}
	label := func(s string) bool {
		if len(s) < 1 || len(s) > 128 {
			return false
		}
		for _, c := range s {
			if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-' || c == '_') {
				return false
			}
		}
		return true
	}
	if !label(m.Batch) || !label(m.Run) || m.Evidence != fmt.Sprintf("%s/%s/%s/%d", m.Batch, p.ID, m.Subcase, m.Repeat) || !validHexDigest(m.GitRevision, 40, 64) || !validHexDigest(m.Binary, 64) || !validHexDigest(m.ProfileHash, 64) || !validHexDigest(m.EventsHash, 64) || m.GoVersion == "" || m.OS == "" || m.Arch == "" {
		return errors.New("manifest execution metadata")
	}
	want := map[string]int64{"PASS": 0, "FAIL": 1, "INVALID": 2}
	exit, ok := want[m.Result]
	if !ok || m.Exit != exit {
		return errors.New("manifest result/exit")
	}
	return nil
}
func bundleSchema(root string) (int64, error) {
	if err := inspectEvidenceRoot(root); err != nil {
		return 0, err
	}
	raw, err := readEvidenceFile(root, "manifest.json")
	if err != nil {
		return 0, err
	}
	if err := rejectDuplicateJSONKeys(raw); err != nil {
		return 0, err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return 0, err
	}
	var version int64
	if err := json.Unmarshal(fields["schema_version"], &version); err != nil {
		return 0, err
	}
	if version != 1 && version != 2 && version != 3 {
		return 0, errors.New("unsupported evidence schema")
	}
	return version, nil
}
func scenarioInventory(root string, requireChecksum bool) (map[string][]byte, error) {
	if err := inspectEvidenceRoot(root); err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	allowed := append(slices.Clone(scenarioFiles), "logs", "checksums.sha256")
	for _, e := range entries {
		if !slices.Contains(allowed, e.Name()) {
			return nil, errors.New("unexpected scenario evidence file")
		}
	}
	logs, err := os.ReadDir(filepath.Join(root, "logs"))
	if err != nil {
		return nil, err
	}
	if len(logs) != 0 {
		return nil, errors.New("scenario logs must be empty")
	}
	files := map[string][]byte{}
	total := 0
	for _, name := range scenarioFiles {
		raw, err := readEvidenceFile(root, name)
		if err != nil {
			return nil, err
		}
		total += len(raw)
		if total > 8*1024*1024 {
			return nil, errors.New("scenario bundle cap")
		}
		files[name] = raw
	}
	if requireChecksum {
		raw, err := readEvidenceFile(root, "checksums.sha256")
		if err != nil {
			return nil, err
		}
		checks, err := parseChecksums(raw)
		if err != nil {
			return nil, err
		}
		if len(checks) != len(scenarioFiles) {
			return nil, errors.New("scenario checksum inventory")
		}
		for name, b := range files {
			if checks[name] != scenarioDigest(b) {
				return nil, errors.New("scenario checksum mismatch")
			}
		}
	}
	return files, nil
}
func verifyScenario(root string, checksum bool) (ScenarioManifest, error) {
	files, err := scenarioInventory(root, checksum)
	if err != nil {
		return ScenarioManifest{}, err
	}
	var p ScenarioProfile
	var m ScenarioManifest
	var top ScenarioTopology
	var res ScenarioResiduals
	var metrics ScenarioMetrics
	var assertions ScenarioAssertions
	for _, item := range []struct {
		name  string
		value any
	}{{"profile.json", &p}, {"manifest.json", &m}, {"topology.json", &top}, {"residuals.json", &res}, {"metrics.json", &metrics}, {"assertions.json", &assertions}} {
		if err := decodeScenarioFile(files[item.name], item.value); err != nil {
			return m, fmt.Errorf("%s: %w", item.name, err)
		}
	}
	if err := p.Validate(); err != nil {
		return m, err
	}
	if err := checkScenarioManifest(p, m); err != nil {
		return m, err
	}
	if m.ProfileHash != scenarioDigest(files["profile.json"]) || m.EventsHash != scenarioDigest(files["events.ndjson"]) {
		return m, errors.New("manifest digest mismatch")
	}
	events, err := decodeScenarioEvents(files["events.ndjson"])
	if err != nil {
		return m, err
	}
	checks := []int64{}
	for _, e := range events {
		if e.Kind == "environment_check" {
			d, _ := detailOf(e)
			if d.(*EnvironmentDetail).ID == "routing" {
				checks = append(checks, e.Sequence)
			}
		}
	}
	want := ScenarioTopology{2, ScenarioMode, CanonicalTopology, []string{"A→B", "B→A", "B→C", "C→B"}, []string{"A→C", "C→A"}, checks}
	if !reflect.DeepEqual(top, want) {
		return m, errors.New("offline topology binding")
	}
	wantMetrics, wantAssertions, result, err := AssessScenario(p, m.Subcase, events, res)
	if err != nil {
		return m, err
	}
	if !reflect.DeepEqual(metrics, wantMetrics) || !reflect.DeepEqual(assertions, wantAssertions) || m.Result != result {
		return m, errors.New("derived metrics/assertions/result mismatch")
	}
	return m, nil
}
func finalizeScenario(root string) error {
	if _, err := verifyScenario(root, false); err != nil {
		return err
	}
	files, err := scenarioInventory(root, false)
	if err != nil {
		return err
	}
	var b bytes.Buffer
	for _, name := range scenarioFiles {
		fmt.Fprintf(&b, "%s  %s\n", scenarioDigest(files[name]), name)
	}
	return atomicWriteEvidenceFile(root, "checksums.sha256", b.Bytes())
}
func compareScenarios(root string) (string, error) {
	info, err := os.Lstat(root)
	if err != nil {
		return "", err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", errors.New("comparison root type")
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		return "", err
	}
	if len(entries) != 3 {
		return "", errors.New("comparison needs exactly three repeats")
	}
	for _, e := range entries {
		if !e.IsDir() || !slices.Contains([]string{"1", "2", "3"}, e.Name()) {
			return "", errors.New("comparison repeat directory")
		}
	}
	var ref ScenarioManifest
	var reference map[string][]byte
	runs := map[string]bool{}
	for i := 1; i <= 3; i++ {
		path := filepath.Join(root, fmt.Sprint(i))
		schema, err := bundleSchema(path)
		if err != nil {
			return "", err
		}
		if schema != 2 {
			return "", errors.New("mixed comparison schemas")
		}
		m, err := verifyScenario(path, true)
		if err != nil {
			return "", err
		}
		if m.Repeat != int64(i) || m.Result != "PASS" || runs[m.Run] {
			return "", errors.New("repeat inventory/result")
		}
		runs[m.Run] = true
		files, err := scenarioInventory(path, true)
		if err != nil {
			return "", err
		}
		if i == 1 {
			ref = m
			reference = files
			continue
		}
		if m.Batch != ref.Batch || m.GitRevision != ref.GitRevision || m.Binary != ref.Binary || m.Dirty != ref.Dirty || m.OS != ref.OS || m.Arch != ref.Arch || m.GoVersion != ref.GoVersion || m.ProfileID != ref.ProfileID || m.ProfileVersion != ref.ProfileVersion || m.Subcase != ref.Subcase || m.Variant != ref.Variant || m.Mode != ref.Mode || m.Observation != ref.Observation {
			return "", errors.New("comparison execution binding")
		}
		for _, name := range []string{"profile.json", "events.ndjson", "metrics.json", "assertions.json"} {
			if !bytes.Equal(files[name], reference[name]) {
				return "", fmt.Errorf("repeat %d differs: %s", i, name)
			}
		}
	}
	return ref.EventsHash, nil
}
