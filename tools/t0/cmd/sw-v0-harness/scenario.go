package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"radishlink.local/t0/internal/harness"
	"radishlink.local/t0/internal/synthetic"
)

type scenarioRecorder struct {
	events []harness.ScenarioEvent
	bytes  int
	err    error
}

func (r *scenarioRecorder) add(now int64, node, kind string, key *harness.ObservedKey, before, after, cause int64, detail any) int64 {
	if r.err != nil {
		return 0
	}
	raw, err := json.Marshal(detail)
	if err != nil {
		r.err = err
		return 0
	}
	e := harness.ScenarioEvent{Schema: 2, Sequence: int64(len(r.events) + 1), Now: now, Node: node, Kind: kind, Key: key, Before: before, After: after, Cause: cause, Detail: raw}
	line, err := json.Marshal(e)
	if err != nil {
		r.err = err
		return 0
	}
	if len(line) > 16*1024 || len(r.events) >= 8192 || r.bytes+len(line)+1 > 4*1024*1024 {
		r.err = errors.New("scenario recorder cap")
		return 0
	}
	r.events = append(r.events, e)
	r.bytes += len(line) + 1
	return e.Sequence
}
func scenarioHash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func scenarioRoute(from, to string) bool {
	return from == "A" && to == "B" || from == "B" && (to == "A" || to == "C") || from == "C" && to == "B"
}
func scenarioDirection(from, to string) string {
	return strings.ToLower(from) + "-to-" + strings.ToLower(to)
}

type scenarioPending struct {
	at       int64
	from, to string
	wire     []byte
	frame    harness.FrameDetail
	sequence int64
}

// runScenario is shared scenario preparation, deliberately not a CLI or network runner.
func runScenario(root string, p harness.ScenarioProfile, subID string, metadata harness.ScenarioManifest) (bundle harness.ScenarioBundle, runErr error) {
	if err := p.Validate(); err != nil {
		return bundle, err
	}
	sub, err := p.Subcase(subID)
	if err != nil {
		return bundle, err
	}
	frames, err := harness.ScenarioFrames(sub.Size)
	if err != nil {
		return bundle, err
	}
	recorder := &scenarioRecorder{}
	key := harness.ObservedKey{Version: 1, Origin: "A", Scope: "i4-small4", ID: strings.Repeat("3", 32)}
	now := int64(0)
	nodes := map[string]*synthetic.Node{}
	snapshots := map[string]harness.ObservedState{}
	generation := map[string]int64{}
	owned := []string{}
	pending := []scenarioPending{}
	bundle.Profile = p
	bundle.Manifest = metadata
	bundle.Manifest.ProfileID = p.ID
	bundle.Manifest.ProfileVersion = p.Version
	bundle.Manifest.Seed = p.Seed
	bundle.Manifest.Variant = p.Variant
	bundle.Manifest.Subcase = subID
	bundle.Manifest.Mode = p.Mode
	bundle.Manifest.Security = p.Security
	bundle.Manifest.Topology = p.Topology
	bundle.Manifest.Size = sub.Size
	bundle.Manifest.Count = p.Count
	bundle.Manifest.Window = p.Window
	bundle.Residuals = harness.ScenarioResiduals{Schema: 2, Complete: true, Owned: 3}
	defer func() {
		nodes = nil
		for _, dir := range owned {
			for _, name := range []string{"state.json", "state.next"} {
				err := os.Remove(filepath.Join(dir, name))
				if err != nil && !errors.Is(err, os.ErrNotExist) {
					runErr = errors.Join(runErr, err)
				}
			}
			if err := os.Remove(dir); err != nil {
				runErr = errors.Join(runErr, err)
			} else {
				bundle.Residuals.Removed++
			}
		}
		bundle.Residuals.Pending = int64(len(pending))
		bundle.Residuals.Clean = bundle.Residuals.Removed == 3 && len(pending) == 0
		bundle.Events = recorder.events
		runErr = errors.Join(runErr, recorder.err)
	}()
	clock, err := harness.NewTestClock(time.Unix(0, 0).UTC())
	if err != nil {
		return bundle, err
	}
	routingOK := scenarioRoute("A", "B") && scenarioRoute("B", "A") && scenarioRoute("B", "C") && scenarioRoute("C", "B") && !scenarioRoute("A", "C") && !scenarioRoute("C", "A")
	routeSeq := recorder.add(0, "driver", "environment_check", nil, 0, 0, 0, harness.EnvironmentDetail{ID: "routing", Passed: routingOK, Reason: "memory_route_graph"})
	_, clockErr := clock.Advance(0)
	clockNow, _, _ := clock.Snapshot()
	recorder.add(0, "driver", "environment_check", nil, 0, 0, 0, harness.EnvironmentDetail{ID: "clock", Passed: clockErr == nil && clockNow == 0, Reason: "injected_clock"})
	probe := &scenarioRecorder{}
	probe.add(0, "driver", "environment_check", nil, 0, 0, 0, harness.EnvironmentDetail{ID: "recorder", Passed: true, Reason: "roundtrip"})
	probeRaw, _ := json.Marshal(probe.events[0])
	_, probeErr := harness.NormalizeScenarioEvents(append(probeRaw, '\n'))
	recorder.add(0, "driver", "environment_check", nil, 0, 0, 0, harness.EnvironmentDetail{ID: "recorder", Passed: probeErr == nil, Reason: "strict_event_roundtrip"})
	bundle.Topology = harness.ScenarioTopology{Schema: 2, Mode: harness.ScenarioMode, Topology: harness.CanonicalTopology, Edges: []string{"A→B", "B→A", "B→C", "C→B"}, Denied: []string{"A→C", "C→A"}, Checks: []int64{routeSeq}}
	if !routingOK || clockErr != nil || probeErr != nil {
		recorder.add(0, "driver", "execution_aborted", nil, 0, 0, 0, harness.AbortDetail{Now: 0, Stage: "preflight", Error: "ENVIRONMENT", Reason: "self_check_failed"})
		return bundle, errors.New("scenario preflight")
	}
	oracle := map[synthetic.VerdictRequest]synthetic.Verdict{}
	for _, f := range frames {
		oracle[synthetic.VerdictRequest{Receiver: f.To, Neighbor: f.From, FrameSHA256: scenarioHash(f.Body), Purpose: f.Purpose, Key: synthetic.Key(key)}] = synthetic.VerdictAccept
	}
	for _, name := range []string{"A", "B", "C"} {
		dir := filepath.Join(root, strings.ToLower(name))
		if err := os.Mkdir(dir, 0700); err != nil {
			return bundle, err
		}
		owned = append(owned, dir)
		c := synthetic.Config{Run: strings.Repeat("1", 32), Node: name, Scope: key.Scope, Epoch: strings.Repeat("2", 32), Verdicts: func(r synthetic.VerdictRequest) synthetic.Verdict {
			v, ok := oracle[r]
			if !ok {
				v = synthetic.VerdictReject
			}
			verdict := "reject"
			if v == synthetic.VerdictAccept {
				verdict = "accept"
			}
			k := harness.ObservedKey(r.Key)
			recorder.add(now, r.Receiver, "verdict_decision", &k, generation[r.Receiver], generation[r.Receiver], 0, harness.VerdictDetail{Receiver: r.Receiver, Neighbor: r.Neighbor, Frame: r.FrameSHA256, Purpose: r.Purpose, Verdict: verdict})
			return v
		}}
		n, err := synthetic.InitNode(dir, c)
		if err != nil {
			return bundle, err
		}
		nodes[name] = n
		s, err := n.Snapshot()
		if err != nil {
			return bundle, err
		}
		snapshots[name] = s
		recorder.add(0, name, "state_observed", nil, 0, 0, 0, s)
	}
	_, err = nodes["A"].Submit("one", key.ID, bytes.Repeat([]byte{'x'}, int(sub.Size)), 0, 30000)
	s, observeErr := nodes["A"].Snapshot()
	if observeErr != nil {
		return bundle, observeErr
	}
	committed := s.Generation == 1
	op := recorder.add(0, "A", "submit_result", &key, 0, s.Generation, 0, harness.OperationDetail{Operation: "submit", Error: synthetic.Code(err), Committed: committed, Transactions: []string{"T-A"}, Inputs: 0})
	if committed {
		recorder.add(0, "A", "state_observed", &key, 0, s.Generation, op, s)
	}
	snapshots["A"], generation["A"] = s, s.Generation
	if err != nil {
		recorder.add(0, "driver", "execution_aborted", nil, 0, 0, 0, harness.AbortDetail{Now: 0, Stage: "submit", Error: synthetic.Code(err), Reason: "implementation_error"})
		return bundle, err
	}
	dropPlan := harness.FaultPlan{Kind: "none", Direction: "none"}
	if p.Fault.Kind == "drop" {
		dropPlan = harness.FaultPlan{Kind: "drop", Direction: p.Fault.Direction, TriggerIndex: 1}
	}
	proxy, err := harness.NewSyntheticProxy(dropPlan)
	if err != nil {
		return bundle, err
	}
	downAt, upAt := int64(-1), int64(-1)
	for tick := 0; tick < 512; tick++ {
		next := int64(30000)
		for _, q := range pending {
			if q.at > now {
				next = min(next, q.at)
			}
		}
		for _, s := range snapshots {
			for _, q := range s.Queues {
				if q.Status != "active" {
					continue
				}
				for _, offset := range []int64{0, 250, 750, 1750, 3750} {
					at := q.Start + offset
					if at == 0 {
						at = 1
					}
					if at > now {
						next = min(next, at)
					}
				}
			}
		}
		if downAt >= 0 && upAt < 0 {
			next = min(next, downAt+5000)
		}
		if next <= now {
			return bundle, errors.New("scenario clock did not advance")
		}
		if _, err := clock.Advance(time.Duration(next-now) * time.Millisecond); err != nil {
			return bundle, err
		}
		now, _, _ = clock.Snapshot()
		for _, name := range []string{"A", "B", "C"} {
			batch := synthetic.Batch{Now: now}
			remaining := []scenarioPending{}
			for _, in := range pending {
				if in.at == now && in.to == name {
					input, err := synthetic.ReadInput(in.from, bytes.NewReader(in.wire))
					if err != nil {
						return bundle, err
					}
					batch.Inputs = append(batch.Inputs, input)
					frame := in.frame
					frame.SendSequence = in.sequence
					recorder.add(now, name, "frame_received", &key, generation[name], generation[name], in.sequence, frame)
				} else {
					remaining = append(remaining, in)
				}
			}
			pending = remaining
			due := len(batch.Inputs) > 0 || now == 30000
			for _, q := range snapshots[name].Queues {
				if q.Status != "active" {
					continue
				}
				for _, offset := range []int64{0, 250, 750, 1750, 3750} {
					at := q.Start + offset
					if at == 0 {
						at = 1
					}
					if at == now {
						due = true
					}
				}
			}
			target := ""
			if p.Fault.Kind == "down" {
				if p.Fault.Direction == "a-to-b" && name == "A" && now == 1 && downAt < 0 {
					target = "B"
				}
				if p.Fault.Direction == "b-to-c" && name == "B" && len(batch.Inputs) > 0 && len(snapshots[name].Messages) == 0 && downAt < 0 {
					target = "C"
				}
			}
			if target != "" {
				downAt = now
				batch.Links = append(batch.Links, synthetic.Link{Neighbor: target, Event: "became_down"})
				due = true
				recorder.add(now, "driver", "fault_transition", &key, 0, 0, 0, harness.FaultDetail{Direction: p.Fault.Direction, Trigger: p.Fault.Trigger, Action: "down", Hit: 1})
			}
			if downAt >= 0 && upAt < 0 && now == downAt+5000 && (p.Fault.Direction == "a-to-b" && name == "A" || p.Fault.Direction == "b-to-c" && name == "B") {
				target = "B"
				if name == "B" {
					target = "C"
				}
				batch.Links = append(batch.Links, synthetic.Link{Neighbor: target, Event: "became_up"})
				upAt = now
				due = true
				recorder.add(now, "driver", "fault_transition", &key, 0, 0, 0, harness.FaultDetail{Direction: p.Fault.Direction, Trigger: p.Fault.Trigger, Action: "up", Hit: 1})
			}
			if !due {
				continue
			}
			out, report, stepErr := nodes[name].StepWithReport(batch)
			op := recorder.add(now, name, "batch_result", &key, report.Before, report.After, 0, harness.OperationDetail{Operation: "step", Error: synthetic.Code(stepErr), Committed: report.Committed, Transactions: report.Transactions, Inputs: int64(len(batch.Inputs))})
			sendCauses := map[string]int64{}
			for _, r := range report.Decisions {
				seq := recorder.add(now, name, "retry_decision", &key, report.Before, report.After, op, r)
				if r.Send {
					sendCauses[r.Kind] = seq
				}
			}
			if report.Committed {
				s, err := nodes[name].Snapshot()
				if err != nil {
					return bundle, err
				}
				recorder.add(now, name, "state_observed", &key, report.Before, report.After, op, s)
				snapshots[name], generation[name] = s, s.Generation
			}
			if stepErr != nil {
				recorder.add(now, "driver", "execution_aborted", nil, 0, 0, 0, harness.AbortDetail{Now: now, Stage: "step", Error: synthetic.Code(stepErr), Reason: "implementation_error"})
				return bundle, stepErr
			}
			for _, send := range out {
				var wire bytes.Buffer
				if err := send.Write(&wire, now); err != nil {
					return bundle, err
				}
				body := wire.Bytes()[4:]
				e, err := synthetic.DecodeEnvelope(body)
				if err != nil {
					return bundle, err
				}
				to := send.Neighbor()
				if !scenarioRoute(name, to) {
					return bundle, errors.New("forbidden route")
				}
				frame := harness.FrameDetail{Direction: scenarioDirection(name, to), Kind: e.Kind, Core: e.Fingerprint, Frame: scenarioHash(body), Bytes: int64(wire.Len())}
				seq := recorder.add(now, name, "frame_written", &key, report.After, report.After, sendCauses[e.Kind], frame)
				if p.Fault.Kind == "drop" && e.Kind == "delivery" {
					outputs, hit, err := proxy.Process(frame.Direction, body)
					if err != nil {
						return bundle, err
					}
					if hit.Action == "drop" {
						recorder.add(now, "driver", "fault_transition", &key, 0, 0, seq, harness.FaultDetail{Direction: frame.Direction, Trigger: p.Fault.Trigger, Action: "drop", Matched: seq, Hit: 1})
						continue
					}
					if len(outputs) != 1 || !bytes.Equal(outputs[0], body) {
						return bundle, errors.New("unexpected proxy output")
					}
				}
				if len(pending) >= 128 {
					return bundle, errors.New("pending frame cap")
				}
				pending = append(pending, scenarioPending{now + 50, name, to, bytes.Clone(wire.Bytes()), frame, seq})
			}
		}
		if recorder.err != nil {
			return bundle, recorder.err
		}
		if now == 30000 {
			remaining := int64(0)
			for _, s := range snapshots {
				for _, m := range s.Messages {
					if m.Transport {
						remaining++
					}
				}
			}
			recorder.add(now, "driver", "observation_end", nil, 0, 0, 0, harness.EndDetail{Now: now, Remaining: remaining, Pending: int64(len(pending)), Reason: "window_complete"})
			return bundle, nil
		}
	}
	return bundle, fmt.Errorf("scenario exceeded %d ticks", 512)
}
