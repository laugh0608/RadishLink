package harness

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
)

const (
	ProfileSchemaVersion  = 1
	EvidenceSchemaVersion = 1
	CanonicalTopology     = "a-b-c-one-relay"
	MaxProfileBytes       = 64 * 1024
)

var seedPattern = regexp.MustCompile(`^0x[0-9a-f]{16}$`)

type Fault struct {
	Kind         string         `json:"kind"`
	Direction    string         `json:"direction"`
	TriggerEvent string         `json:"trigger_event"`
	TriggerIndex int            `json:"trigger_index"`
	Parameters   map[string]int `json:"parameters"`
}

type Retry struct {
	BackoffMS   []int `json:"backoff_ms"`
	MaxAttempts int   `json:"max_attempts"`
	DeadlineMS  int   `json:"deadline_ms"`
}

type Profile struct {
	SchemaVersion         int      `json:"schema_version"`
	ProfileID             string   `json:"profile_id"`
	ProfileVersion        int      `json:"profile_version"`
	SeedHex               string   `json:"seed_hex"`
	Topology              string   `json:"topology"`
	PayloadSizeBytes      int      `json:"payload_size_bytes"`
	MessageCount          int      `json:"message_count"`
	LifetimeMS            int      `json:"lifetime_ms"`
	InitialHopBudget      int      `json:"initial_hop_budget"`
	Fault                 Fault    `json:"fault"`
	Retry                 Retry    `json:"retry"`
	ObservationWindowMS   int      `json:"observation_window_ms"`
	ExpectedEvents        []string `json:"expected_events"`
	ForbiddenEvents       []string `json:"forbidden_events"`
	EvidenceSchemaVersion int      `json:"evidence_schema_version"`
}

type canonicalProfile struct {
	Seed         string
	MessageCount int
	FaultKind    string
	Direction    string
	TriggerEvent string
	TriggerIndex int
	Expected     []string
	Forbidden    []string
}

var canonicalProfiles = map[string]canonicalProfile{
	"SW-V0-TOPOLOGY-001": {
		Seed: "0x524c535747330101", MessageCount: 4, FaultKind: "none", Direction: "none",
		TriggerEvent: "none", TriggerIndex: 0,
		Expected:  []string{"a_to_c_unreachable", "c_to_a_unreachable", "b_to_a_reachable", "b_to_c_reachable"},
		Forbidden: []string{"a_to_c_reachable", "c_to_a_reachable"},
	},
	"SW-V0-FAULT-HIT-001": {
		Seed: "0x524c535747330102", MessageCount: 3, FaultKind: "drop", Direction: "a-to-b",
		TriggerEvent: "synthetic-frame", TriggerIndex: 2,
		Expected:  []string{"frame_1_forwarded", "frame_2_dropped", "frame_3_forwarded", "fault_hit_once"},
		Forbidden: []string{"fault_hit_wrong_direction", "fault_hit_multiple"},
	},
	"SW-V0-EVIDENCE-001": {
		Seed: "0x524c535747330103", MessageCount: 1, FaultKind: "evidence-tamper", Direction: "local",
		TriggerEvent: "checksum-copy", TriggerIndex: 1,
		Expected:  []string{"evidence_complete", "tamper_rejected"},
		Forbidden: []string{"partial_evidence_accepted", "tamper_accepted"},
	},
	"SW-V0-CLOCK-001": {
		Seed: "0x524c535747330104", MessageCount: 2, FaultKind: "wall-clock-rollback", Direction: "local",
		TriggerEvent: "clock-event", TriggerIndex: 2,
		Expected:  []string{"monotonic_advanced", "wall_clock_rollback_observed"},
		Forbidden: []string{"monotonic_clock_rollback", "system_clock_modified"},
	},
}

func LoadProfile(root, relativePath string) (Profile, []byte, error) {
	path, err := resolveRegularFile(root, relativePath)
	if err != nil {
		return Profile{}, nil, err
	}
	file, err := os.Open(path)
	if err != nil {
		return Profile{}, nil, fmt.Errorf("open profile: %w", err)
	}
	defer file.Close()

	data, err := io.ReadAll(io.LimitReader(file, MaxProfileBytes+1))
	if err != nil {
		return Profile{}, nil, fmt.Errorf("read profile: %w", err)
	}
	if len(data) > MaxProfileBytes {
		return Profile{}, nil, fmt.Errorf("profile exceeds %d bytes", MaxProfileBytes)
	}
	profile, err := DecodeProfile(data)
	if err != nil {
		return Profile{}, nil, err
	}
	return profile, data, nil
}

func DecodeProfile(data []byte) (Profile, error) {
	if err := rejectDuplicateJSONKeys(data); err != nil {
		return Profile{}, fmt.Errorf("validate profile JSON keys: %w", err)
	}

	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var profile Profile
	if err := decoder.Decode(&profile); err != nil {
		return Profile{}, fmt.Errorf("decode profile: %w", err)
	}
	if err := requireJSONEOF(decoder); err != nil {
		return Profile{}, err
	}
	if err := profile.Validate(); err != nil {
		return Profile{}, err
	}
	return profile, nil
}

func (profile Profile) Validate() error {
	if profile.SchemaVersion != ProfileSchemaVersion {
		return fmt.Errorf("unsupported profile schema version: %d", profile.SchemaVersion)
	}
	if profile.ProfileVersion != 1 {
		return fmt.Errorf("unsupported profile version: %d", profile.ProfileVersion)
	}
	canonical, ok := canonicalProfiles[profile.ProfileID]
	if !ok {
		return fmt.Errorf("profile id is not canonical: %q", profile.ProfileID)
	}
	if !seedPattern.MatchString(profile.SeedHex) {
		return errors.New("seed_hex must be a lowercase 64-bit hexadecimal string")
	}
	if profile.SeedHex != canonical.Seed {
		return fmt.Errorf("profile seed does not match %s", profile.ProfileID)
	}
	if profile.Topology != CanonicalTopology {
		return fmt.Errorf("unsupported topology: %q", profile.Topology)
	}
	if profile.PayloadSizeBytes != 1 {
		return fmt.Errorf("SW-V0 payload size must be 1 byte: %d", profile.PayloadSizeBytes)
	}
	if profile.MessageCount != canonical.MessageCount {
		return fmt.Errorf("message_count does not match canonical profile %s: %d", profile.ProfileID, profile.MessageCount)
	}
	if profile.LifetimeMS != 30000 {
		return fmt.Errorf("SW-V0 lifetime_ms must be 30000: %d", profile.LifetimeMS)
	}
	if profile.InitialHopBudget != 2 {
		return fmt.Errorf("SW-V0 initial_hop_budget must be 2: %d", profile.InitialHopBudget)
	}
	if profile.ObservationWindowMS != 10000 {
		return fmt.Errorf("SW-V0 observation window must be 10000 ms: %d", profile.ObservationWindowMS)
	}
	if profile.EvidenceSchemaVersion != EvidenceSchemaVersion {
		return fmt.Errorf("unsupported evidence schema version: %d", profile.EvidenceSchemaVersion)
	}
	if len(profile.ExpectedEvents) == 0 {
		return errors.New("expected_events must not be empty")
	}
	if hasDuplicate(profile.ExpectedEvents) || hasDuplicate(profile.ForbiddenEvents) {
		return errors.New("event expectations must not contain duplicates")
	}
	if !slices.Equal(profile.ExpectedEvents, canonical.Expected) || !slices.Equal(profile.ForbiddenEvents, canonical.Forbidden) {
		return fmt.Errorf("event expectations do not match canonical profile %s", profile.ProfileID)
	}
	if profile.Fault.Parameters == nil {
		return errors.New("fault parameters must be an object")
	}
	if profile.Fault.Kind != canonical.FaultKind ||
		profile.Fault.Direction != canonical.Direction ||
		profile.Fault.TriggerEvent != canonical.TriggerEvent ||
		profile.Fault.TriggerIndex != canonical.TriggerIndex {
		return fmt.Errorf("fault plan does not match canonical profile %s", profile.ProfileID)
	}
	if err := validateFaultParameters(profile); err != nil {
		return err
	}
	if !slices.Equal(profile.Retry.BackoffMS, []int{250, 500, 1000, 2000}) {
		return errors.New("retry backoff must be 250/500/1000/2000 ms")
	}
	if profile.Retry.MaxAttempts != 4 {
		return fmt.Errorf("retry max_attempts must be 4: %d", profile.Retry.MaxAttempts)
	}
	if profile.Retry.DeadlineMS != 10000 {
		return fmt.Errorf("retry deadline_ms must be 10000: %d", profile.Retry.DeadlineMS)
	}
	return nil
}

func resolveRegularFile(root, relativePath string) (string, error) {
	if root == "" {
		return "", errors.New("profile root is required")
	}
	if err := validateRelativePath(relativePath); err != nil {
		return "", err
	}
	rootPath, err := filepath.Abs(root)
	if err != nil {
		return "", fmt.Errorf("resolve profile root: %w", err)
	}
	rootInfo, err := os.Lstat(rootPath)
	if err != nil {
		return "", fmt.Errorf("inspect profile root: %w", err)
	}
	if rootInfo.Mode()&os.ModeSymlink != 0 || !rootInfo.IsDir() {
		return "", errors.New("profile root must be a non-symlink directory")
	}
	path := filepath.Join(rootPath, relativePath)
	if err := rejectSymlinkPath(rootPath, relativePath); err != nil {
		return "", err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return "", fmt.Errorf("inspect profile: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return "", errors.New("profile must be a regular non-symlink file")
	}
	return path, nil
}

func validateRelativePath(path string) error {
	if path == "" || filepath.IsAbs(path) {
		return errors.New("path must be a non-empty relative path")
	}
	cleaned := filepath.Clean(path)
	if cleaned == "." || cleaned != path || cleaned == ".." || strings.HasPrefix(cleaned, ".."+string(filepath.Separator)) {
		return errors.New("path must not contain traversal or non-canonical components")
	}
	return nil
}

func rejectSymlinkPath(root, relativePath string) error {
	current := root
	for _, component := range strings.Split(relativePath, string(filepath.Separator)) {
		current = filepath.Join(current, component)
		info, err := os.Lstat(current)
		if err != nil {
			return fmt.Errorf("inspect path component: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return errors.New("path must not contain symlinks")
		}
	}
	return nil
}

func validateFaultParameters(profile Profile) error {
	if profile.ProfileID == "SW-V0-CLOCK-001" {
		if len(profile.Fault.Parameters) != 1 || profile.Fault.Parameters["rollback_ms"] != 3600000 {
			return errors.New("clock profile requires only rollback_ms=3600000")
		}
		return nil
	}
	if len(profile.Fault.Parameters) != 0 {
		return fmt.Errorf("profile %s does not accept fault parameters", profile.ProfileID)
	}
	return nil
}

func rejectDuplicateJSONKeys(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := scanJSONValue(decoder); err != nil {
		return err
	}
	return requireJSONEOF(decoder)
}

func scanJSONValue(decoder *json.Decoder) error {
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delimiter {
	case '{':
		keys := make(map[string]struct{})
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return err
			}
			key, ok := keyToken.(string)
			if !ok {
				return errors.New("JSON object key is not a string")
			}
			if _, exists := keys[key]; exists {
				return fmt.Errorf("duplicate JSON key: %q", key)
			}
			keys[key] = struct{}{}
			if err := scanJSONValue(decoder); err != nil {
				return err
			}
		}
		_, err = decoder.Token()
		return err
	case '[':
		for decoder.More() {
			if err := scanJSONValue(decoder); err != nil {
				return err
			}
		}
		_, err = decoder.Token()
		return err
	default:
		return fmt.Errorf("unexpected JSON delimiter: %q", delimiter)
	}
}

func requireJSONEOF(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); errors.Is(err, io.EOF) {
		return nil
	} else if err != nil {
		return fmt.Errorf("decode trailing JSON: %w", err)
	}
	return errors.New("profile contains multiple JSON values")
}

func hasDuplicate(values []string) bool {
	seen := make(map[string]struct{}, len(values))
	for _, value := range values {
		if value == "" {
			return true
		}
		if _, exists := seen[value]; exists {
			return true
		}
		seen[value] = struct{}{}
	}
	return false
}
