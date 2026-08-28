package harness

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"
)

const MaxEvidenceFileBytes = 4 * 1024 * 1024

var requiredEvidenceFiles = []string{
	"assertions.json",
	"events.ndjson",
	"manifest.json",
	"profile.json",
	"residuals.json",
	"topology.json",
}

type EvidenceEvent struct {
	Sequence      uint64         `json:"sequence"`
	Kind          string         `json:"kind"`
	Node          string         `json:"node,omitempty"`
	MonotonicMS   int64          `json:"monotonic_ms"`
	WallTime      string         `json:"wall_time,omitempty"`
	PID           int            `json:"pid,omitempty"`
	ContainerID   string         `json:"container_id,omitempty"`
	TemporaryPath string         `json:"temporary_path,omitempty"`
	Attributes    map[string]any `json:"attributes,omitempty"`
}

type ProbeResult struct {
	From        string `json:"from"`
	To          string `json:"to"`
	Address     string `json:"address"`
	Expectation string `json:"expectation"`
	Observed    string `json:"observed"`
	Passed      bool   `json:"passed"`
}

type TopologyEvidence struct {
	SchemaVersion int           `json:"schema_version"`
	ProfileID     string        `json:"profile_id"`
	Topology      string        `json:"topology"`
	Probes        []ProbeResult `json:"probes"`
}

type Assertion struct {
	Name   string `json:"name"`
	Passed bool   `json:"passed"`
	Detail string `json:"detail"`
}

type AssertionSet struct {
	SchemaVersion int         `json:"schema_version"`
	ProfileID     string      `json:"profile_id"`
	Assertions    []Assertion `json:"assertions"`
}

type ResidualInventory struct {
	SchemaVersion     int      `json:"schema_version"`
	ProfileID         string   `json:"profile_id"`
	InventoryComplete bool     `json:"inventory_complete"`
	Containers        []string `json:"containers"`
	Networks          []string `json:"networks"`
	Images            []string `json:"images"`
}

type EvidenceManifest struct {
	SchemaVersion          int    `json:"schema_version"`
	EvidenceID             string `json:"evidence_id"`
	RunID                  string `json:"run_id"`
	GitRevision            string `json:"git_revision"`
	GitDirty               bool   `json:"git_dirty"`
	ProfileID              string `json:"profile_id"`
	ProfileVersion         int    `json:"profile_version"`
	ProfileSHA256          string `json:"profile_sha256"`
	SeedHex                string `json:"seed_hex"`
	Repeat                 int    `json:"repeat"`
	StartedAt              string `json:"started_at"`
	EndedAt                string `json:"ended_at"`
	GoVersion              string `json:"go_version"`
	HostArchitecture       string `json:"host_architecture"`
	DaemonArchitecture     string `json:"daemon_architecture"`
	ContainerArchitecture  string `json:"container_architecture"`
	BinarySHA256           string `json:"binary_sha256"`
	ImageDigest            string `json:"image_digest"`
	Topology               string `json:"topology"`
	PayloadSizeBytes       int    `json:"payload_size_bytes"`
	MessageCount           int    `json:"message_count"`
	ObservationWindowMS    int    `json:"observation_window_ms"`
	ExitCode               int    `json:"exit_code"`
	Result                 string `json:"result"`
	NormalizedEventsSHA256 string `json:"normalized_events_sha256"`
}

type EvidenceMetadata struct {
	RunID                 string
	GitRevision           string
	GitDirty              bool
	StartedAt             string
	EndedAt               string
	GoVersion             string
	HostArchitecture      string
	DaemonArchitecture    string
	ContainerArchitecture string
	BinarySHA256          string
	ImageDigest           string
	ExitCode              int
}

type EvidenceInput struct {
	Profile    Profile
	ProfileRaw []byte
	Repeat     int
	Topology   TopologyEvidence
	Events     []EvidenceEvent
	Assertions []Assertion
	Residuals  ResidualInventory
	Metadata   EvidenceMetadata
}

func WriteEvidenceBundle(root string, input EvidenceInput) error {
	if err := input.Profile.Validate(); err != nil {
		return fmt.Errorf("validate evidence profile: %w", err)
	}
	decoded, err := DecodeProfile(input.ProfileRaw)
	if err != nil {
		return fmt.Errorf("decode evidence profile copy: %w", err)
	}
	if decoded.ProfileID != input.Profile.ProfileID {
		return errors.New("profile copy does not match evidence input")
	}
	if input.Repeat < 1 || input.Repeat > 3 {
		return fmt.Errorf("repeat must be between 1 and 3: %d", input.Repeat)
	}
	if err := validateEvidenceMetadata(input.Metadata); err != nil {
		return err
	}
	if err := prepareEvidenceRoot(root); err != nil {
		return err
	}

	eventsRaw, err := encodeEvents(input.Events)
	if err != nil {
		return err
	}
	normalized, err := NormalizeEvents(eventsRaw)
	if err != nil {
		return fmt.Errorf("normalize events: %w", err)
	}
	profileCopy := append(bytes.TrimSpace(input.ProfileRaw), '\n')
	profileDigest := sha256.Sum256(profileCopy)
	eventDigest := sha256.Sum256(normalized)
	result := evidenceResult(input.Assertions, input.Residuals)
	manifest := EvidenceManifest{
		SchemaVersion:          EvidenceSchemaVersion,
		EvidenceID:             fmt.Sprintf("%s/%s/%d", input.Metadata.RunID, input.Profile.ProfileID, input.Repeat),
		RunID:                  input.Metadata.RunID,
		GitRevision:            input.Metadata.GitRevision,
		GitDirty:               input.Metadata.GitDirty,
		ProfileID:              input.Profile.ProfileID,
		ProfileVersion:         input.Profile.ProfileVersion,
		ProfileSHA256:          hex.EncodeToString(profileDigest[:]),
		SeedHex:                input.Profile.SeedHex,
		Repeat:                 input.Repeat,
		StartedAt:              input.Metadata.StartedAt,
		EndedAt:                input.Metadata.EndedAt,
		GoVersion:              input.Metadata.GoVersion,
		HostArchitecture:       input.Metadata.HostArchitecture,
		DaemonArchitecture:     input.Metadata.DaemonArchitecture,
		ContainerArchitecture:  input.Metadata.ContainerArchitecture,
		BinarySHA256:           input.Metadata.BinarySHA256,
		ImageDigest:            input.Metadata.ImageDigest,
		Topology:               input.Profile.Topology,
		PayloadSizeBytes:       input.Profile.PayloadSizeBytes,
		MessageCount:           input.Profile.MessageCount,
		ObservationWindowMS:    input.Profile.ObservationWindowMS,
		ExitCode:               input.Metadata.ExitCode,
		Result:                 result,
		NormalizedEventsSHA256: hex.EncodeToString(eventDigest[:]),
	}
	assertions := AssertionSet{
		SchemaVersion: EvidenceSchemaVersion,
		ProfileID:     input.Profile.ProfileID,
		Assertions:    input.Assertions,
	}
	topologyRaw, err := marshalEvidenceJSON(input.Topology)
	if err != nil {
		return fmt.Errorf("encode topology evidence: %w", err)
	}
	assertionsRaw, err := marshalEvidenceJSON(assertions)
	if err != nil {
		return fmt.Errorf("encode assertions evidence: %w", err)
	}
	residualsRaw, err := marshalEvidenceJSON(input.Residuals)
	if err != nil {
		return fmt.Errorf("encode residual evidence: %w", err)
	}
	manifestRaw, err := marshalEvidenceJSON(manifest)
	if err != nil {
		return fmt.Errorf("encode manifest evidence: %w", err)
	}

	files := []struct {
		name string
		data []byte
	}{
		{name: "profile.json", data: profileCopy},
		{name: "topology.json", data: topologyRaw},
		{name: "events.ndjson", data: eventsRaw},
		{name: "assertions.json", data: assertionsRaw},
		{name: "residuals.json", data: residualsRaw},
		{name: "manifest.json", data: manifestRaw},
	}
	for _, file := range files {
		if err := atomicWriteEvidenceFile(root, file.name, file.data); err != nil {
			return err
		}
	}
	return FinalizeEvidence(root)
}

func FinalizeEvidence(root string) error {
	if err := validateEvidenceBundle(root); err != nil {
		return err
	}
	files, err := collectEvidenceFiles(root)
	if err != nil {
		return err
	}
	var checksum bytes.Buffer
	for _, name := range files {
		data, err := readEvidenceFile(root, name)
		if err != nil {
			return err
		}
		digest := sha256.Sum256(data)
		fmt.Fprintf(&checksum, "%s  %s\n", hex.EncodeToString(digest[:]), filepath.ToSlash(name))
	}
	return atomicWriteEvidenceFile(root, "checksums.sha256", checksum.Bytes())
}

func VerifyEvidence(root string) error {
	if err := validateEvidenceBundle(root); err != nil {
		return err
	}
	expectedFiles, err := collectEvidenceFiles(root)
	if err != nil {
		return err
	}
	checksumRaw, err := readEvidenceFile(root, "checksums.sha256")
	if err != nil {
		return fmt.Errorf("read checksum inventory: %w", err)
	}
	checksums, err := parseChecksums(checksumRaw)
	if err != nil {
		return err
	}
	checksumFiles := make([]string, 0, len(checksums))
	for name := range checksums {
		checksumFiles = append(checksumFiles, name)
	}
	slices.Sort(checksumFiles)
	if !slices.Equal(checksumFiles, expectedFiles) {
		return fmt.Errorf("checksum inventory mismatch: got %v, want %v", checksumFiles, expectedFiles)
	}
	for _, name := range expectedFiles {
		data, err := readEvidenceFile(root, name)
		if err != nil {
			return err
		}
		digest := sha256.Sum256(data)
		if hex.EncodeToString(digest[:]) != checksums[name] {
			return fmt.Errorf("checksum mismatch for %s", name)
		}
	}
	return nil
}

func NormalizeEvents(data []byte) ([]byte, error) {
	events, err := decodeEvents(data)
	if err != nil {
		return nil, err
	}
	var normalized bytes.Buffer
	for _, event := range events {
		event.WallTime = ""
		event.PID = 0
		event.ContainerID = ""
		event.TemporaryPath = ""
		encoded, err := json.Marshal(event)
		if err != nil {
			return nil, fmt.Errorf("encode normalized event: %w", err)
		}
		normalized.Write(encoded)
		normalized.WriteByte('\n')
	}
	return normalized.Bytes(), nil
}

func CompareEvidenceRuns(profileRoot string) (string, error) {
	var reference []byte
	var referenceProfile []byte
	var referenceAssertions []byte
	var referenceRunID string
	for repeat := 1; repeat <= 3; repeat++ {
		root := filepath.Join(profileRoot, fmt.Sprintf("%d", repeat))
		if err := VerifyEvidence(root); err != nil {
			return "", fmt.Errorf("verify repeat %d: %w", repeat, err)
		}
		manifestRaw, err := readEvidenceFile(root, "manifest.json")
		if err != nil {
			return "", err
		}
		var manifest EvidenceManifest
		if err := decodeEvidenceJSON(manifestRaw, &manifest); err != nil {
			return "", fmt.Errorf("decode repeat %d manifest: %w", repeat, err)
		}
		if manifest.Result != "PASS" {
			return "", fmt.Errorf("repeat %d result is %s", repeat, manifest.Result)
		}
		events, err := readEvidenceFile(root, "events.ndjson")
		if err != nil {
			return "", err
		}
		normalized, err := NormalizeEvents(events)
		if err != nil {
			return "", fmt.Errorf("normalize repeat %d: %w", repeat, err)
		}
		profile, err := readEvidenceFile(root, "profile.json")
		if err != nil {
			return "", err
		}
		assertions, err := readEvidenceFile(root, "assertions.json")
		if err != nil {
			return "", err
		}
		if repeat == 1 {
			reference = normalized
			referenceProfile = profile
			referenceAssertions = assertions
			referenceRunID = manifest.RunID
			continue
		}
		if manifest.RunID != referenceRunID {
			return "", fmt.Errorf("repeat %d run id differs", repeat)
		}
		if !bytes.Equal(reference, normalized) {
			return "", fmt.Errorf("repeat %d normalized event stream differs", repeat)
		}
		if !bytes.Equal(referenceProfile, profile) {
			return "", fmt.Errorf("repeat %d canonical profile differs", repeat)
		}
		if !bytes.Equal(referenceAssertions, assertions) {
			return "", fmt.Errorf("repeat %d assertion result differs", repeat)
		}
	}
	digest := sha256.Sum256(reference)
	return hex.EncodeToString(digest[:]), nil
}

func AppendProbeResult(path string, result ProbeResult) error {
	if path == "" {
		return errors.New("probe output path is required")
	}
	encoded, err := json.Marshal(result)
	if err != nil {
		return fmt.Errorf("encode probe result: %w", err)
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("open probe output: %w", err)
	}
	defer file.Close()
	if _, err := file.Write(append(encoded, '\n')); err != nil {
		return fmt.Errorf("append probe output: %w", err)
	}
	return file.Sync()
}

func ReadProbeResults(path string) ([]ProbeResult, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read probe results: %w", err)
	}
	if len(data) > MaxEvidenceFileBytes {
		return nil, errors.New("probe result file is too large")
	}
	var results []ProbeResult
	scanner := bufio.NewScanner(bytes.NewReader(data))
	for scanner.Scan() {
		line := bytes.TrimSpace(scanner.Bytes())
		if len(line) == 0 {
			return nil, errors.New("probe result contains a blank line")
		}
		if err := rejectDuplicateJSONKeys(line); err != nil {
			return nil, fmt.Errorf("validate probe result: %w", err)
		}
		var result ProbeResult
		if err := decodeStrictJSON(line, &result); err != nil {
			return nil, fmt.Errorf("decode probe result: %w", err)
		}
		results = append(results, result)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan probe results: %w", err)
	}
	if len(results) == 0 {
		return nil, errors.New("probe result file is empty")
	}
	return results, nil
}

func validateEvidenceBundle(root string) error {
	if err := inspectEvidenceRoot(root); err != nil {
		return err
	}
	for _, name := range requiredEvidenceFiles {
		if _, err := evidenceRegularFile(root, name); err != nil {
			return fmt.Errorf("required evidence %s: %w", name, err)
		}
	}

	profileRaw, err := readEvidenceFile(root, "profile.json")
	if err != nil {
		return err
	}
	profile, err := DecodeProfile(profileRaw)
	if err != nil {
		return fmt.Errorf("validate profile evidence: %w", err)
	}
	manifestRaw, err := readEvidenceFile(root, "manifest.json")
	if err != nil {
		return err
	}
	var manifest EvidenceManifest
	if err := decodeEvidenceJSON(manifestRaw, &manifest); err != nil {
		return fmt.Errorf("validate manifest: %w", err)
	}
	if manifest.SchemaVersion != EvidenceSchemaVersion || manifest.ProfileID != profile.ProfileID || manifest.Repeat < 1 || manifest.Repeat > 3 {
		return errors.New("manifest does not reference the canonical profile and repeat")
	}
	if manifest.EvidenceID != fmt.Sprintf("%s/%s/%d", manifest.RunID, manifest.ProfileID, manifest.Repeat) ||
		manifest.ProfileVersion != profile.ProfileVersion || manifest.SeedHex != profile.SeedHex ||
		manifest.Topology != profile.Topology || manifest.PayloadSizeBytes != profile.PayloadSizeBytes ||
		manifest.MessageCount != profile.MessageCount || manifest.ObservationWindowMS != profile.ObservationWindowMS {
		return errors.New("manifest canonical profile fields do not match profile.json")
	}
	metadata := EvidenceMetadata{
		RunID:                 manifest.RunID,
		GitRevision:           manifest.GitRevision,
		GitDirty:              manifest.GitDirty,
		StartedAt:             manifest.StartedAt,
		EndedAt:               manifest.EndedAt,
		GoVersion:             manifest.GoVersion,
		HostArchitecture:      manifest.HostArchitecture,
		DaemonArchitecture:    manifest.DaemonArchitecture,
		ContainerArchitecture: manifest.ContainerArchitecture,
		BinarySHA256:          manifest.BinarySHA256,
		ImageDigest:           manifest.ImageDigest,
		ExitCode:              manifest.ExitCode,
	}
	if err := validateEvidenceMetadata(metadata); err != nil {
		return fmt.Errorf("manifest metadata: %w", err)
	}
	profileDigest := sha256.Sum256(profileRaw)
	if manifest.ProfileSHA256 != hex.EncodeToString(profileDigest[:]) {
		return errors.New("manifest profile checksum does not match profile.json")
	}

	topologyRaw, err := readEvidenceFile(root, "topology.json")
	if err != nil {
		return err
	}
	var topology TopologyEvidence
	if err := decodeEvidenceJSON(topologyRaw, &topology); err != nil {
		return fmt.Errorf("validate topology: %w", err)
	}
	if topology.SchemaVersion != EvidenceSchemaVersion || topology.ProfileID != profile.ProfileID || topology.Topology != profile.Topology {
		return errors.New("topology evidence does not reference the canonical profile")
	}
	eventsRaw, err := readEvidenceFile(root, "events.ndjson")
	if err != nil {
		return err
	}

	assertionRaw, err := readEvidenceFile(root, "assertions.json")
	if err != nil {
		return err
	}
	var assertions AssertionSet
	if err := decodeEvidenceJSON(assertionRaw, &assertions); err != nil {
		return fmt.Errorf("validate assertions: %w", err)
	}
	if assertions.SchemaVersion != EvidenceSchemaVersion || assertions.ProfileID != profile.ProfileID || len(assertions.Assertions) == 0 {
		return errors.New("assertions do not reference the canonical profile")
	}
	if err := validateExpectationAssertions(profile, eventsRaw, assertions.Assertions); err != nil {
		return err
	}

	residualRaw, err := readEvidenceFile(root, "residuals.json")
	if err != nil {
		return err
	}
	var residuals ResidualInventory
	if err := decodeEvidenceJSON(residualRaw, &residuals); err != nil {
		return fmt.Errorf("validate residuals: %w", err)
	}
	if residuals.SchemaVersion != EvidenceSchemaVersion || residuals.ProfileID != profile.ProfileID {
		return errors.New("residual inventory does not reference the canonical profile")
	}
	if manifest.Result != evidenceResult(assertions.Assertions, residuals) {
		return errors.New("manifest result does not match assertions and residual inventory")
	}

	normalized, err := NormalizeEvents(eventsRaw)
	if err != nil {
		return fmt.Errorf("validate events: %w", err)
	}
	digest := sha256.Sum256(normalized)
	if manifest.NormalizedEventsSHA256 != hex.EncodeToString(digest[:]) {
		return errors.New("manifest normalized event checksum does not match events.ndjson")
	}
	return nil
}

func prepareEvidenceRoot(root string) error {
	if root == "" {
		return errors.New("evidence root is required")
	}
	info, err := os.Lstat(root)
	if errors.Is(err, fs.ErrNotExist) {
		if err := os.MkdirAll(root, 0o700); err != nil {
			return fmt.Errorf("create evidence root: %w", err)
		}
	} else if err != nil {
		return fmt.Errorf("inspect evidence root: %w", err)
	} else if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("evidence root must be a non-symlink directory")
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		return fmt.Errorf("read evidence root: %w", err)
	}
	if len(entries) != 0 {
		return errors.New("evidence root must be empty")
	}
	if err := os.Mkdir(filepath.Join(root, "logs"), 0o700); err != nil {
		return fmt.Errorf("create evidence log directory: %w", err)
	}
	return nil
}

func inspectEvidenceRoot(root string) error {
	if root == "" {
		return errors.New("evidence root is required")
	}
	info, err := os.Lstat(root)
	if err != nil {
		return fmt.Errorf("inspect evidence root: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.IsDir() {
		return errors.New("evidence root must be a non-symlink directory")
	}
	logs, err := os.Lstat(filepath.Join(root, "logs"))
	if err != nil || logs.Mode()&os.ModeSymlink != 0 || !logs.IsDir() {
		return errors.New("evidence logs must be a non-symlink directory")
	}
	return nil
}

func collectEvidenceFiles(root string) ([]string, error) {
	allowedTop := make(map[string]struct{}, len(requiredEvidenceFiles)+2)
	for _, name := range requiredEvidenceFiles {
		allowedTop[name] = struct{}{}
	}
	allowedTop["checksums.sha256"] = struct{}{}
	allowedTop["logs"] = struct{}{}
	var files []string
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if path == root {
			return nil
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		if entry.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("evidence path is a symlink: %s", relative)
		}
		parts := strings.Split(relative, string(filepath.Separator))
		if _, ok := allowedTop[parts[0]]; !ok {
			return fmt.Errorf("unexpected evidence path: %s", relative)
		}
		if len(parts) > 1 && parts[0] != "logs" {
			return fmt.Errorf("unexpected nested evidence path: %s", relative)
		}
		if entry.IsDir() {
			if parts[0] != "logs" {
				return fmt.Errorf("unexpected evidence directory: %s", relative)
			}
			return nil
		}
		if !entry.Type().IsRegular() {
			return fmt.Errorf("evidence path is not a regular file: %s", relative)
		}
		if relative != "checksums.sha256" {
			files = append(files, filepath.ToSlash(relative))
		}
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("inventory evidence files: %w", err)
	}
	slices.Sort(files)
	return files, nil
}

func atomicWriteEvidenceFile(root, relativePath string, data []byte) error {
	if len(data) > MaxEvidenceFileBytes {
		return fmt.Errorf("evidence file %s exceeds %d bytes", relativePath, MaxEvidenceFileBytes)
	}
	if err := validateRelativePath(relativePath); err != nil {
		return err
	}
	if strings.Contains(relativePath, string(filepath.Separator)) {
		return errors.New("atomic evidence writer only accepts top-level files")
	}
	if info, err := os.Lstat(filepath.Join(root, relativePath)); err == nil && info.Mode()&os.ModeSymlink != 0 {
		return errors.New("refusing to replace a symlink evidence file")
	} else if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return fmt.Errorf("inspect evidence target: %w", err)
	}
	temporary, err := os.CreateTemp(root, ".sw-v0-evidence-*")
	if err != nil {
		return fmt.Errorf("create temporary evidence file: %w", err)
	}
	temporaryPath := temporary.Name()
	removeTemporary := true
	defer func() {
		if removeTemporary {
			_ = os.Remove(temporaryPath)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("set evidence file mode: %w", err)
	}
	if _, err := temporary.Write(data); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("write evidence file: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		_ = temporary.Close()
		return fmt.Errorf("sync evidence file: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("close evidence file: %w", err)
	}
	if err := os.Rename(temporaryPath, filepath.Join(root, relativePath)); err != nil {
		return fmt.Errorf("publish evidence file: %w", err)
	}
	removeTemporary = false
	directory, err := os.Open(root)
	if err != nil {
		return fmt.Errorf("open evidence directory for sync: %w", err)
	}
	defer directory.Close()
	if err := directory.Sync(); err != nil {
		return fmt.Errorf("sync evidence directory: %w", err)
	}
	return nil
}

func evidenceRegularFile(root, relativePath string) (string, error) {
	if err := validateRelativePath(relativePath); err != nil {
		return "", err
	}
	path := filepath.Join(root, relativePath)
	info, err := os.Lstat(path)
	if err != nil {
		return "", err
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", errors.New("path must be a regular non-symlink file")
	}
	return path, nil
}

func readEvidenceFile(root, relativePath string) ([]byte, error) {
	path, err := evidenceRegularFile(root, filepath.FromSlash(relativePath))
	if err != nil {
		return nil, fmt.Errorf("inspect evidence %s: %w", relativePath, err)
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open evidence %s: %w", relativePath, err)
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, MaxEvidenceFileBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read evidence %s: %w", relativePath, err)
	}
	if len(data) > MaxEvidenceFileBytes {
		return nil, fmt.Errorf("evidence %s exceeds %d bytes", relativePath, MaxEvidenceFileBytes)
	}
	return data, nil
}

func encodeEvents(events []EvidenceEvent) ([]byte, error) {
	if len(events) == 0 {
		return nil, errors.New("event stream must not be empty")
	}
	var output bytes.Buffer
	for _, event := range events {
		encoded, err := json.Marshal(event)
		if err != nil {
			return nil, fmt.Errorf("encode event: %w", err)
		}
		output.Write(encoded)
		output.WriteByte('\n')
	}
	return output.Bytes(), nil
}

func decodeEvents(data []byte) ([]EvidenceEvent, error) {
	if len(data) == 0 || len(data) > MaxEvidenceFileBytes {
		return nil, errors.New("event stream must be non-empty and bounded")
	}
	var events []EvidenceEvent
	scanner := bufio.NewScanner(bytes.NewReader(data))
	buffer := make([]byte, 64*1024)
	scanner.Buffer(buffer, MaxEvidenceFileBytes)
	var previousSequence uint64
	var previousMonotonic int64
	for scanner.Scan() {
		line := bytes.TrimSpace(scanner.Bytes())
		if len(line) == 0 {
			return nil, errors.New("event stream contains a blank line")
		}
		if err := rejectDuplicateJSONKeys(line); err != nil {
			return nil, fmt.Errorf("validate event JSON: %w", err)
		}
		var event EvidenceEvent
		if err := decodeStrictJSON(line, &event); err != nil {
			return nil, fmt.Errorf("decode event: %w", err)
		}
		if event.Sequence != previousSequence+1 || event.Kind == "" || event.MonotonicMS < 0 || event.MonotonicMS < previousMonotonic {
			return nil, fmt.Errorf("event sequence or monotonic time is invalid at sequence %d", event.Sequence)
		}
		previousSequence = event.Sequence
		previousMonotonic = event.MonotonicMS
		events = append(events, event)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan events: %w", err)
	}
	if len(events) == 0 {
		return nil, errors.New("event stream is empty")
	}
	return events, nil
}

func decodeEvidenceJSON(data []byte, destination any) error {
	if err := rejectDuplicateJSONKeys(data); err != nil {
		return err
	}
	return decodeStrictJSON(data, destination)
}

func decodeStrictJSON(data []byte, destination any) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	return requireJSONEOF(decoder)
}

func parseChecksums(data []byte) (map[string]string, error) {
	checksums := make(map[string]string)
	scanner := bufio.NewScanner(bytes.NewReader(data))
	for scanner.Scan() {
		line := scanner.Text()
		if len(line) < 67 || line[64:66] != "  " {
			return nil, fmt.Errorf("invalid checksum line: %q", line)
		}
		digest := line[:64]
		if _, err := hex.DecodeString(digest); err != nil {
			return nil, fmt.Errorf("invalid checksum digest: %w", err)
		}
		name := line[66:]
		if err := validateRelativePath(filepath.FromSlash(name)); err != nil || filepath.ToSlash(filepath.Clean(filepath.FromSlash(name))) != name {
			return nil, fmt.Errorf("invalid checksum path: %q", name)
		}
		if _, exists := checksums[name]; exists {
			return nil, fmt.Errorf("duplicate checksum path: %s", name)
		}
		checksums[name] = digest
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("scan checksums: %w", err)
	}
	if len(checksums) == 0 {
		return nil, errors.New("checksum inventory is empty")
	}
	return checksums, nil
}

func evidenceResult(assertions []Assertion, residuals ResidualInventory) string {
	if !residuals.InventoryComplete {
		return "INVALID"
	}
	for _, assertion := range assertions {
		if assertion.Name == "" || !assertion.Passed {
			return "INVALID"
		}
	}
	if len(residuals.Containers) != 0 || len(residuals.Networks) != 0 || len(residuals.Images) != 0 {
		return "INVALID"
	}
	return "PASS"
}

func validateExpectationAssertions(profile Profile, eventsRaw []byte, assertions []Assertion) error {
	events, err := decodeEvents(eventsRaw)
	if err != nil {
		return fmt.Errorf("decode events for assertion validation: %w", err)
	}
	observed := make(map[string]int)
	for _, event := range events {
		observed[event.Kind]++
	}
	byName := make(map[string]Assertion, len(assertions))
	for _, assertion := range assertions {
		if assertion.Name == "" {
			return errors.New("assertion name must not be empty")
		}
		if _, exists := byName[assertion.Name]; exists {
			return fmt.Errorf("duplicate assertion name: %s", assertion.Name)
		}
		byName[assertion.Name] = assertion
	}
	for _, kind := range profile.ExpectedEvents {
		name := "expected:" + kind
		assertion, exists := byName[name]
		if !exists || assertion.Passed != (observed[kind] > 0) {
			return fmt.Errorf("assertion %s does not match the event stream", name)
		}
	}
	for _, kind := range profile.ForbiddenEvents {
		name := "forbidden:" + kind
		assertion, exists := byName[name]
		if !exists || assertion.Passed != (observed[kind] == 0) {
			return fmt.Errorf("assertion %s does not match the event stream", name)
		}
	}
	return nil
}

func validateEvidenceMetadata(metadata EvidenceMetadata) error {
	values := map[string]string{
		"run id":                 metadata.RunID,
		"git revision":           metadata.GitRevision,
		"started_at":             metadata.StartedAt,
		"ended_at":               metadata.EndedAt,
		"Go version":             metadata.GoVersion,
		"host architecture":      metadata.HostArchitecture,
		"daemon architecture":    metadata.DaemonArchitecture,
		"container architecture": metadata.ContainerArchitecture,
		"binary checksum":        metadata.BinarySHA256,
		"image digest":           metadata.ImageDigest,
	}
	for name, value := range values {
		if strings.TrimSpace(value) == "" {
			return fmt.Errorf("evidence metadata %s is required", name)
		}
	}
	if metadata.ExitCode < 0 || metadata.ExitCode > 255 {
		return fmt.Errorf("evidence exit code is out of range: %d", metadata.ExitCode)
	}
	startedAt, err := time.Parse(time.RFC3339Nano, metadata.StartedAt)
	if err != nil {
		return fmt.Errorf("parse evidence started_at: %w", err)
	}
	endedAt, err := time.Parse(time.RFC3339Nano, metadata.EndedAt)
	if err != nil {
		return fmt.Errorf("parse evidence ended_at: %w", err)
	}
	if endedAt.Before(startedAt) {
		return errors.New("evidence ended_at precedes started_at")
	}
	if !validHexDigest(metadata.GitRevision, 40, 64) {
		return errors.New("evidence git revision must be a lowercase 40- or 64-character hexadecimal digest")
	}
	if !validHexDigest(metadata.BinarySHA256, 64) {
		return errors.New("evidence binary checksum must be a lowercase SHA-256 digest")
	}
	if !strings.HasPrefix(metadata.ImageDigest, "sha256:") || !validHexDigest(strings.TrimPrefix(metadata.ImageDigest, "sha256:"), 64) {
		return errors.New("evidence image digest must be a sha256 digest")
	}
	return nil
}

func validHexDigest(value string, lengths ...int) bool {
	if !slices.Contains(lengths, len(value)) || strings.ToLower(value) != value {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil
}

func marshalEvidenceJSON(value any) ([]byte, error) {
	data, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return nil, err
	}
	return append(data, '\n'), nil
}
