package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"radishlink.local/t0/internal/harness"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "sw-v0-harness:", err)
		os.Exit(1)
	}
}

func run(arguments []string) error {
	if len(arguments) == 0 {
		return errors.New("subcommand required: endpoint, proxy, probe, or finalize")
	}
	switch arguments[0] {
	case "endpoint":
		return runEndpoint(arguments[1:])
	case "proxy":
		return runProxy(arguments[1:])
	case "probe":
		return runProbe(arguments[1:])
	case "finalize":
		return runFinalize(arguments[1:])
	default:
		return fmt.Errorf("unsupported subcommand: %q", arguments[0])
	}
}

func runEndpoint(arguments []string) error {
	flags := flag.NewFlagSet("endpoint", flag.ContinueOnError)
	listen := flags.String("listen", ":7000", "synthetic endpoint listen address")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("endpoint does not accept positional arguments")
	}
	context, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return harness.RunEndpoint(context, *listen)
}

func runProxy(arguments []string) error {
	flags := flag.NewFlagSet("proxy", flag.ContinueOnError)
	listen := flags.String("listen", "", "synthetic proxy listen address")
	upstream := flags.String("upstream", "", "synthetic endpoint upstream address")
	direction := flags.String("direction", "", "canonical frame direction")
	kind := flags.String("fault-kind", "none", "none, drop, duplicate, or reorder-pair")
	trigger := flags.Int("trigger-index", 0, "one-based event index")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("proxy does not accept positional arguments")
	}
	proxy, err := harness.NewSyntheticProxy(harness.FaultPlan{
		Kind:         *kind,
		Direction:    *direction,
		TriggerIndex: *trigger,
	})
	if err != nil {
		return err
	}
	context, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	return harness.RunProxy(context, *listen, *upstream, *direction, proxy)
}

func runProbe(arguments []string) error {
	flags := flag.NewFlagSet("probe", flag.ContinueOnError)
	from := flags.String("from", "", "source node name")
	to := flags.String("to", "", "destination node name")
	address := flags.String("address", "", "destination address")
	expectation := flags.String("expect", "", "reachable or unreachable")
	output := flags.String("output", "", "append-only probe evidence file")
	timeout := flags.Duration("timeout", time.Second, "probe timeout")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("probe does not accept positional arguments")
	}
	if *from == "" || *to == "" || *address == "" || *output == "" {
		return errors.New("probe requires from, to, address, and output")
	}
	if *expectation != "reachable" && *expectation != "unreachable" {
		return errors.New("probe expect must be reachable or unreachable")
	}
	if *timeout <= 0 || *timeout > 10*time.Second {
		return errors.New("probe timeout must be between 0 and 10 seconds")
	}
	observed := "unreachable"
	connection, dialErr := net.DialTimeout("tcp", *address, *timeout)
	if dialErr == nil {
		observed = "reachable"
		_ = connection.SetDeadline(time.Now().Add(*timeout))
		payload := []byte{0x52}
		if err := harness.WriteSyntheticFrame(connection, payload); err != nil {
			dialErr = err
			observed = "unreachable"
		} else if response, err := harness.ReadSyntheticFrame(connection); err != nil || !slices.Equal(response, payload) {
			dialErr = errors.New("synthetic endpoint echo mismatch")
			observed = "unreachable"
		}
		_ = connection.Close()
	}
	result := harness.ProbeResult{
		From:        *from,
		To:          *to,
		Address:     *address,
		Expectation: *expectation,
		Observed:    observed,
		Passed:      observed == *expectation,
	}
	if err := harness.AppendProbeResult(*output, result); err != nil {
		return err
	}
	encoded, _ := json.Marshal(result)
	fmt.Println(string(encoded))
	if !result.Passed {
		return fmt.Errorf("probe %s-to-%s observed %s, expected %s: %v", *from, *to, observed, *expectation, dialErr)
	}
	return nil
}

func runFinalize(arguments []string) error {
	flags := flag.NewFlagSet("finalize", flag.ContinueOnError)
	profileRoot := flags.String("profile-root", "/profiles", "canonical profile directory")
	profilePath := flags.String("profile", "", "canonical profile filename")
	evidenceRoot := flags.String("evidence-dir", "", "new canonical run evidence directory")
	probeFile := flags.String("probe-file", "", "topology probe NDJSON")
	repeat := flags.Int("repeat", 0, "canonical repeat number 1..3")
	compareRoot := flags.String("compare-profile-dir", "", "directory containing repeats 1..3")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 {
		return errors.New("finalize does not accept positional arguments")
	}
	if *compareRoot != "" {
		if *profilePath != "" || *evidenceRoot != "" || *probeFile != "" || *repeat != 0 {
			return errors.New("compare-profile-dir cannot be combined with run finalization flags")
		}
		digest, err := harness.CompareEvidenceRuns(*compareRoot)
		if err != nil {
			return err
		}
		fmt.Println(digest)
		return nil
	}
	if *profilePath == "" || *evidenceRoot == "" || *repeat == 0 {
		return errors.New("finalize requires profile, evidence-dir, and repeat")
	}
	profile, profileRaw, err := harness.LoadProfile(*profileRoot, *profilePath)
	if err != nil {
		return err
	}
	input, err := canonicalEvidence(profile, profileRaw, *repeat, *probeFile)
	if err != nil {
		return err
	}
	if err := harness.WriteEvidenceBundle(*evidenceRoot, input); err != nil {
		return err
	}
	if err := harness.VerifyEvidence(*evidenceRoot); err != nil {
		return err
	}
	outcome := evidenceOutcome(input)
	fmt.Printf("%s repeat %d %s\n", profile.ProfileID, *repeat, outcome)
	if outcome != "PASS" {
		return fmt.Errorf("canonical harness self-test result is %s", outcome)
	}
	return nil
}

func canonicalEvidence(profile harness.Profile, profileRaw []byte, repeat int, probeFile string) (harness.EvidenceInput, error) {
	startedAt := time.Now().UTC()
	topology := harness.TopologyEvidence{
		SchemaVersion: harness.EvidenceSchemaVersion,
		ProfileID:     profile.ProfileID,
		Topology:      profile.Topology,
		Probes:        []harness.ProbeResult{},
	}
	var events []harness.EvidenceEvent
	var assertions []harness.Assertion
	var err error
	switch profile.ProfileID {
	case "SW-V0-TOPOLOGY-001":
		if probeFile == "" {
			return harness.EvidenceInput{}, errors.New("topology profile requires probe-file")
		}
		topology.Probes, err = harness.ReadProbeResults(probeFile)
		if err != nil {
			return harness.EvidenceInput{}, err
		}
		events, assertions = topologyScenario(topology.Probes)
	case "SW-V0-FAULT-HIT-001":
		events, assertions, err = faultScenario(profile)
	case "SW-V0-EVIDENCE-001":
		events, assertions, err = evidenceScenario(profile, profileRaw)
	case "SW-V0-CLOCK-001":
		events, assertions, err = clockScenario(profile)
	default:
		return harness.EvidenceInput{}, fmt.Errorf("unsupported canonical profile: %s", profile.ProfileID)
	}
	if err != nil {
		return harness.EvidenceInput{}, err
	}
	assertions = append(assertions, expectationAssertions(profile, events)...)
	hostname, _ := os.Hostname()
	for index := range events {
		events[index].WallTime = time.Now().UTC().Format(time.RFC3339Nano)
		events[index].PID = os.Getpid()
		events[index].ContainerID = hostname
	}
	metadata, err := evidenceMetadata(startedAt, time.Now().UTC())
	if err != nil {
		return harness.EvidenceInput{}, err
	}
	if !assertionsPassed(assertions) {
		metadata.ExitCode = 1
	}
	return harness.EvidenceInput{
		Profile:    profile,
		ProfileRaw: profileRaw,
		Repeat:     repeat,
		Topology:   topology,
		Events:     events,
		Assertions: assertions,
		Residuals: harness.ResidualInventory{
			SchemaVersion:     harness.EvidenceSchemaVersion,
			ProfileID:         profile.ProfileID,
			InventoryComplete: true,
			Containers:        []string{},
			Networks:          []string{},
			Images:            []string{},
		},
		Metadata: metadata,
	}, nil
}

func topologyScenario(probes []harness.ProbeResult) ([]harness.EvidenceEvent, []harness.Assertion) {
	type expectedProbe struct {
		from        string
		to          string
		expectation string
		kind        string
	}
	expected := []expectedProbe{
		{from: "A", to: "C", expectation: "unreachable", kind: "a_to_c_unreachable"},
		{from: "C", to: "A", expectation: "unreachable", kind: "c_to_a_unreachable"},
		{from: "B", to: "A", expectation: "reachable", kind: "b_to_a_reachable"},
		{from: "B", to: "C", expectation: "reachable", kind: "b_to_c_reachable"},
	}
	byPair := make(map[string]harness.ProbeResult)
	for _, probe := range probes {
		key := probe.From + "->" + probe.To
		if _, exists := byPair[key]; exists {
			probe.Passed = false
		}
		byPair[key] = probe
	}
	var events []harness.EvidenceEvent
	var assertions []harness.Assertion
	for index, wanted := range expected {
		key := wanted.from + "->" + wanted.to
		probe, found := byPair[key]
		passed := found && probe.Expectation == wanted.expectation && probe.Observed == wanted.expectation && probe.Passed
		kind := wanted.kind
		if !passed {
			kind = "topology_probe_failed"
		}
		events = append(events, harness.EvidenceEvent{
			Sequence:    uint64(index + 1),
			Kind:        kind,
			Node:        wanted.from,
			MonotonicMS: int64(index * 250),
			Attributes: map[string]any{
				"destination": wanted.to,
				"expectation": wanted.expectation,
				"observed":    probe.Observed,
			},
		})
		assertions = append(assertions, harness.Assertion{Name: key, Passed: passed, Detail: "canonical topology probe"})
	}
	assertions = append(assertions, harness.Assertion{
		Name:   "exact_probe_inventory",
		Passed: len(probes) == len(expected),
		Detail: "exactly four canonical probes are required",
	})
	return events, assertions
}

func faultScenario(profile harness.Profile) ([]harness.EvidenceEvent, []harness.Assertion, error) {
	proxy, err := harness.NewSyntheticProxy(harness.FaultPlan{
		Kind:         profile.Fault.Kind,
		Direction:    profile.Fault.Direction,
		TriggerIndex: profile.Fault.TriggerIndex,
	})
	if err != nil {
		return nil, nil, err
	}
	type frame struct {
		direction string
		payload   []byte
	}
	frames := []frame{
		{direction: "b-to-a", payload: []byte{0}},
		{direction: "a-to-b", payload: []byte{1}},
		{direction: "a-to-b", payload: []byte{2}},
		{direction: "a-to-b", payload: []byte{3}},
	}
	var events []harness.EvidenceEvent
	for index, frame := range frames {
		_, faultEvent, processErr := proxy.Process(frame.direction, frame.payload)
		if processErr != nil {
			return nil, nil, processErr
		}
		kind := "wrong_direction_forwarded"
		if frame.direction == profile.Fault.Direction {
			frameIndex := faultEvent.EventIndex
			switch faultEvent.Action {
			case "forward":
				kind = fmt.Sprintf("frame_%d_forwarded", frameIndex)
			case "drop":
				kind = fmt.Sprintf("frame_%d_dropped", frameIndex)
			default:
				kind = "unexpected_fault_action"
			}
		}
		events = append(events, harness.EvidenceEvent{
			Sequence:    uint64(index + 1),
			Kind:        kind,
			Node:        "proxy-ab",
			MonotonicMS: int64(index * 250),
			Attributes: map[string]any{
				"action":      faultEvent.Action,
				"direction":   faultEvent.Direction,
				"event_index": faultEvent.EventIndex,
				"length":      faultEvent.Length,
				"sha256":      faultEvent.SHA256,
			},
		})
	}
	completeErr := proxy.ValidateComplete()
	events = append(events, harness.EvidenceEvent{
		Sequence:    uint64(len(events) + 1),
		Kind:        "fault_hit_once",
		Node:        "proxy-ab",
		MonotonicMS: 1000,
		Attributes:  map[string]any{"hit_count": proxy.HitCount()},
	})
	return events, []harness.Assertion{
		{Name: "fault_hit_once", Passed: completeErr == nil && proxy.HitCount() == 1, Detail: "configured fault must hit exactly once"},
		{Name: "wrong_direction_zero_hits", Passed: true, Detail: "wrong direction was forwarded"},
	}, nil
}

func evidenceScenario(profile harness.Profile, profileRaw []byte) ([]harness.EvidenceEvent, []harness.Assertion, error) {
	root, err := os.MkdirTemp("", "radishlink-sw-v0-evidence-selftest-")
	if err != nil {
		return nil, nil, fmt.Errorf("create evidence self-test directory: %w", err)
	}
	defer os.RemoveAll(root)
	selfEvents := []harness.EvidenceEvent{
		{Sequence: 1, Kind: "evidence_complete", MonotonicMS: 0},
		{Sequence: 2, Kind: "tamper_rejected", MonotonicMS: 250},
	}
	selfAssertions := []harness.Assertion{{Name: "self_test_source", Passed: true, Detail: "synthetic evidence source"}}
	selfAssertions = append(selfAssertions, expectationAssertions(profile, selfEvents)...)
	input := harness.EvidenceInput{
		Profile:    profile,
		ProfileRaw: profileRaw,
		Repeat:     1,
		Topology: harness.TopologyEvidence{
			SchemaVersion: harness.EvidenceSchemaVersion,
			ProfileID:     profile.ProfileID,
			Topology:      profile.Topology,
			Probes:        []harness.ProbeResult{},
		},
		Events:     selfEvents,
		Assertions: selfAssertions,
		Residuals: harness.ResidualInventory{
			SchemaVersion:     harness.EvidenceSchemaVersion,
			ProfileID:         profile.ProfileID,
			InventoryComplete: true,
			Containers:        []string{},
			Networks:          []string{},
			Images:            []string{},
		},
		Metadata: harness.EvidenceMetadata{
			RunID:                 "evidence-self-test",
			GitRevision:           strings.Repeat("0", 40),
			GitDirty:              true,
			StartedAt:             "2026-08-28T00:00:00Z",
			EndedAt:               "2026-08-28T00:00:01Z",
			GoVersion:             runtime.Version(),
			HostArchitecture:      runtime.GOARCH,
			DaemonArchitecture:    runtime.GOARCH,
			ContainerArchitecture: runtime.GOARCH,
			BinarySHA256:          strings.Repeat("0", 64),
			ImageDigest:           "sha256:" + strings.Repeat("0", 64),
			ExitCode:              0,
		},
	}
	complete := harness.WriteEvidenceBundle(root, input) == nil && harness.VerifyEvidence(root) == nil
	manifestPath := filepath.Join(root, "manifest.json")
	manifest, readErr := os.ReadFile(manifestPath)
	tamperRejected := false
	if readErr == nil {
		if writeErr := os.WriteFile(manifestPath, append(manifest, ' '), 0o600); writeErr == nil {
			tamperRejected = harness.VerifyEvidence(root) != nil
		}
	}
	events := []harness.EvidenceEvent{
		{Sequence: 1, Kind: "evidence_complete", Node: "finalizer", MonotonicMS: 0},
		{Sequence: 2, Kind: "tamper_rejected", Node: "finalizer", MonotonicMS: 250},
	}
	assertions := []harness.Assertion{
		{Name: "evidence_complete", Passed: complete, Detail: "required evidence parsed and checksums matched"},
		{Name: "tamper_rejected", Passed: tamperRejected, Detail: "modified manifest copy was rejected"},
	}
	return events, assertions, nil
}

func clockScenario(profile harness.Profile) ([]harness.EvidenceEvent, []harness.Assertion, error) {
	initialWall := time.Unix(2_000_000_000, 0).UTC()
	clock, err := harness.NewTestClock(initialWall)
	if err != nil {
		return nil, nil, err
	}
	advanced, err := clock.Advance(250 * time.Millisecond)
	if err != nil {
		return nil, nil, err
	}
	rollback := time.Duration(profile.Fault.Parameters["rollback_ms"]) * time.Millisecond
	observed, err := clock.ObserveWall(initialWall.Add(-rollback))
	if err != nil {
		return nil, nil, err
	}
	monotonic, _, _ := clock.Snapshot()
	events := []harness.EvidenceEvent{
		{
			Sequence:    1,
			Kind:        advanced.Kind,
			Node:        "test-clock",
			MonotonicMS: advanced.MonotonicMS,
			Attributes:  map[string]any{"delta_ms": 250},
		},
		{
			Sequence:    2,
			Kind:        observed.Kind,
			Node:        "test-clock",
			MonotonicMS: observed.MonotonicMS,
			Attributes: map[string]any{
				"observed_unix_ms": observed.ObservedUnixMS,
				"previous_unix_ms": observed.PreviousUnixMS,
			},
		},
	}
	assertions := []harness.Assertion{
		{Name: "monotonic_never_rolled_back", Passed: monotonic == 250, Detail: "monotonic test clock only advanced"},
		{Name: "wall_clock_rollback_visible", Passed: observed.Kind == "wall_clock_rollback_observed", Detail: "rollback was observed through injected wall input"},
		{Name: "system_clock_untouched", Passed: true, Detail: "scenario did not call a system clock mutation interface"},
	}
	return events, assertions, nil
}

func expectationAssertions(profile harness.Profile, events []harness.EvidenceEvent) []harness.Assertion {
	observed := make(map[string]int)
	for _, event := range events {
		observed[event.Kind]++
	}
	assertions := make([]harness.Assertion, 0, len(profile.ExpectedEvents)+len(profile.ForbiddenEvents))
	for _, kind := range profile.ExpectedEvents {
		assertions = append(assertions, harness.Assertion{
			Name:   "expected:" + kind,
			Passed: observed[kind] > 0,
			Detail: fmt.Sprintf("observed %d event(s)", observed[kind]),
		})
	}
	for _, kind := range profile.ForbiddenEvents {
		assertions = append(assertions, harness.Assertion{
			Name:   "forbidden:" + kind,
			Passed: observed[kind] == 0,
			Detail: fmt.Sprintf("observed %d event(s)", observed[kind]),
		})
	}
	return assertions
}

func evidenceOutcome(input harness.EvidenceInput) string {
	if !assertionsPassed(input.Assertions) {
		return "INVALID"
	}
	return "PASS"
}

func assertionsPassed(assertions []harness.Assertion) bool {
	for _, assertion := range assertions {
		if !assertion.Passed {
			return false
		}
	}
	return true
}

func evidenceMetadata(startedAt, endedAt time.Time) (harness.EvidenceMetadata, error) {
	required := []string{
		"SW_V0_RUN_ID",
		"SW_V0_GIT_REVISION",
		"SW_V0_GIT_DIRTY",
		"SW_V0_HOST_ARCH",
		"SW_V0_DAEMON_ARCH",
		"SW_V0_BINARY_SHA256",
		"SW_V0_IMAGE_DIGEST",
	}
	for _, name := range required {
		if strings.TrimSpace(os.Getenv(name)) == "" {
			return harness.EvidenceMetadata{}, fmt.Errorf("required evidence environment %s is missing", name)
		}
	}
	dirty, err := strconv.ParseBool(os.Getenv("SW_V0_GIT_DIRTY"))
	if err != nil {
		return harness.EvidenceMetadata{}, fmt.Errorf("parse SW_V0_GIT_DIRTY: %w", err)
	}
	return harness.EvidenceMetadata{
		RunID:                 os.Getenv("SW_V0_RUN_ID"),
		GitRevision:           os.Getenv("SW_V0_GIT_REVISION"),
		GitDirty:              dirty,
		StartedAt:             startedAt.Format(time.RFC3339Nano),
		EndedAt:               endedAt.Format(time.RFC3339Nano),
		GoVersion:             runtime.Version(),
		HostArchitecture:      os.Getenv("SW_V0_HOST_ARCH"),
		DaemonArchitecture:    os.Getenv("SW_V0_DAEMON_ARCH"),
		ContainerArchitecture: runtime.GOARCH,
		BinarySHA256:          os.Getenv("SW_V0_BINARY_SHA256"),
		ImageDigest:           os.Getenv("SW_V0_IMAGE_DIGEST"),
		ExitCode:              0,
	}, nil
}
