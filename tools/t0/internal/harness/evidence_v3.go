package harness

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"reflect"
	"slices"
	"time"
)

type ExecutionEvent struct {
	Schema   int64           `json:"schema_version"`
	Sequence int64           `json:"sequence"`
	Source   string          `json:"source"`
	Local    int64           `json:"local_sequence"`
	Request  int64           `json:"request_sequence"`
	Now      int64           `json:"logical_ms"`
	Kind     string          `json:"kind"`
	Detail   json.RawMessage `json:"detail"`
}
type ControlExchange struct {
	Request  ControlRequest  `json:"request"`
	Response ControlResponse `json:"response"`
}
type NetworkEvent struct {
	ScenarioEvent
	Sources []int64 `json:"execution_refs"`
}
type ResourceFact struct {
	Action       string   `json:"action"`
	Kind         string   `json:"resource_kind"`
	Alias        string   `json:"alias"`
	ID           string   `json:"id"`
	Batch        string   `json:"batch"`
	Sample       string   `json:"sample"`
	Node         string   `json:"node"`
	Networks     []string `json:"networks"`
	Store        string   `json:"store"`
	ReadOnly     bool     `json:"read_only"`
	NoPorts      bool     `json:"no_published_ports"`
	NoPrivileges bool     `json:"no_privileges"`
	Error        string   `json:"error_code"`
}
type NetworkTopology struct {
	Schema   int64         `json:"schema_version"`
	Mode     string        `json:"execution_mode"`
	Topology string        `json:"topology"`
	Peers    []NetworkPeer `json:"peers"`
	Sources  []int64       `json:"execution_refs"`
}
type NetworkResiduals struct {
	Schema      int64          `json:"schema_version"`
	Complete    bool           `json:"inventory_complete"`
	Resources   []ResourceFact `json:"resources"`
	Pending     int64          `json:"pending_frames"`
	Children    int64          `json:"active_child_count"`
	Connections int64          `json:"active_connections"`
	Clean       bool           `json:"cleanup_complete"`
}
type NetworkMetrics struct {
	ScenarioMetrics
	Timing  string `json:"latency_clock"`
	Written int64  `json:"socket_writes"`
	Ingress int64  `json:"socket_ingress"`
	Drops   int64  `json:"socket_drops"`
	Errors  int64  `json:"execution_errors"`
}
type NetworkBundle struct {
	Profile   NetworkProfile
	Manifest  NetworkManifest
	Topology  NetworkTopology
	Events    []NetworkEvent
	Execution []ExecutionEvent
	Residuals NetworkResiduals
}
type NetworkManifest struct {
	Schema         int64            `json:"schema_version"`
	Observation    int64            `json:"observation_version"`
	Batch          string           `json:"batch_id"`
	Run            string           `json:"run_id"`
	Evidence       string           `json:"evidence_id"`
	Repeat         int64            `json:"repeat"`
	ProfileID      string           `json:"profile_id"`
	ProfileVersion int64            `json:"profile_version"`
	ProfileHash    string           `json:"profile_sha256"`
	Seed           string           `json:"seed_hex"`
	Variant        string           `json:"variant"`
	Subcase        string           `json:"subcase_id"`
	Mode           string           `json:"execution_mode"`
	Security       string           `json:"security_mode"`
	GitRevision    string           `json:"git_revision"`
	Dirty          bool             `json:"git_dirty"`
	GoVersion      string           `json:"go_version"`
	OS             string           `json:"host_os"`
	Arch           string           `json:"host_architecture"`
	Started        string           `json:"started_at"`
	Ended          string           `json:"ended_at"`
	Topology       string           `json:"topology"`
	Size           int64            `json:"payload_size_bytes"`
	Count          int64            `json:"message_count"`
	Window         int64            `json:"observation_window_ms"`
	Exit           int64            `json:"exit_code"`
	Result         string           `json:"result"`
	EventsHash     string           `json:"normalized_events_sha256"`
	Control        int64            `json:"control_version"`
	Transport      string           `json:"transport"`
	FaultLayer     string           `json:"fault_layer"`
	HostBinary     string           `json:"host_binary_sha256"`
	NodeBinary     string           `json:"node_binary_sha256"`
	Image          string           `json:"image_id"`
	DockerClient   string           `json:"docker_client"`
	DockerServer   string           `json:"docker_server"`
	DaemonOS       string           `json:"daemon_os"`
	DaemonArch     string           `json:"daemon_arch"`
	Contract       string           `json:"contract_sha256"`
	Profiles       []ProfileBinding `json:"profiles"`
	ExecutionHash  string           `json:"execution_sha256"`
}
type ProfileBinding struct {
	ID   string `json:"profile_id"`
	Hash string `json:"sha256"`
}

func networkDetail[T any](raw []byte) (T, error) {
	var v T
	err := CanonicalJSON(raw, &v, controlMax)
	return v, err
}

const controlMax = 256 * 1024

func networkDirection(a, b string) bool {
	return a == "A" && b == "B" || a == "B" && (b == "A" || b == "C") || a == "C" && b == "B"
}
func networkIDs() []string {
	return []string{"SW-V1-BASE-001", "SW-V1-LOSS-EVIDENCE-001", "SW-V1-LOSS-EVIDENCE-BA-001", "SW-V1-DOWN-AB-001", "SW-V1-DOWN-BC-001"}
}
func NetworkProfiles() ([]ProfileBinding, error) {
	out := []ProfileBinding{}
	for _, id := range networkIDs() {
		p, err := CanonicalNetwork(id)
		if err != nil {
			return nil, err
		}
		raw, err := canonicalFile(p)
		if err != nil {
			return nil, err
		}
		out = append(out, ProfileBinding{id, scenarioDigest(raw)})
	}
	return out, nil
}
func matchNodeFact(e NetworkEvent, x ExecutionEvent) int {
	if x.Kind != "exchange" || x.Source != e.Node {
		return -1
	}
	v, err := networkDetail[ControlExchange](x.Detail)
	if err != nil {
		return -1
	}
	for index, f := range v.Response.Result.Facts {
		if f.Kind != e.Kind || f.Now != e.Now || f.Before != e.Before || f.After != e.After {
			continue
		}
		if e.Kind == "frame_received" {
			a, err := networkDetail[FrameDetail](f.Detail)
			if err != nil {
				continue
			}
			b, err := networkDetail[FrameDetail](e.Detail)
			if err != nil {
				continue
			}
			a.SendSequence = b.SendSequence
			if a == b {
				return index
			}
		} else if bytes.Equal(f.Detail, e.Detail) {
			return index
		}
	}
	return -1
}
func AssessNetwork(b NetworkBundle) (NetworkMetrics, ScenarioAssertions, string, error) {
	bad := func(s string) (NetworkMetrics, ScenarioAssertions, string, error) {
		return NetworkMetrics{}, ScenarioAssertions{}, "", errors.New(s)
	}
	if err := b.Profile.Validate(); err != nil {
		return bad(err.Error())
	}
	sub, err := b.Profile.Subcase(b.Manifest.Subcase)
	if err != nil {
		return bad(err.Error())
	}
	if len(b.Execution) == 0 || len(b.Execution) > 8192 || len(b.Events) == 0 {
		return bad("network trace inventory")
	}
	peerByNode := map[string]NetworkPeer{}
	seenIPs := map[string]bool{}
	if len(b.Topology.Peers) != 3 {
		return bad("peer inventory")
	}
	for i, p := range b.Topology.Peers {
		if p.Node != []string{"A", "B", "C"}[i] || (p.AB != "") != (p.Node != "C") || (p.BC != "") != (p.Node != "A") {
			return bad("peer layout")
		}
		for _, ip := range []string{p.AB, p.BC} {
			if ip == "" {
				continue
			}
			v := net.ParseIP(ip)
			if v == nil || v.To4() == nil || v.String() != ip || seenIPs[ip] {
				return bad("peer numeric address")
			}
			seenIPs[ip] = true
		}
		peerByNode[p.Node] = p
	}
	sequence := map[string]int64{}
	generation := map[string]int64{}
	times := map[string]int64{}
	sessions := map[string]string{}
	epochs := map[string]string{}
	initSeen := map[string]bool{}
	environments := map[string]NodeEnvironment{}
	probes := map[string]ProbeFact{}
	probeRefs := []int64{}
	resources := map[string]ResourceFact{}
	removed := map[string]ResourceFact{}
	writes := map[string]TransportFact{}
	ingress := map[string]TransportFact{}
	arms := map[string]ReceivePermit{}
	consumed := map[string]bool{}
	writeRefs := map[string]int64{}
	ingressRefs := map[string]int64{}
	commands := map[int64]ControlExchange{}
	shutdown := map[string]bool{}
	var execErrors int64
	var executionBytes int
	for i, x := range b.Execution {
		raw, e := canonicalFile(x)
		executionBytes += len(raw)
		if e != nil || len(raw) > controlMax+1 || executionBytes > 16*1024*1024 {
			return bad("execution bytes")
		}
		if x.Schema != 3 || x.Sequence != int64(i+1) || x.Now < 0 || x.Now > 30000 || !slices.Contains([]string{"driver", "A", "B", "C"}, x.Source) || x.Local != sequence[x.Source]+1 {
			return bad("execution header")
		}
		sequence[x.Source] = x.Local
		switch x.Kind {
		case "exchange":
			v, err := networkDetail[ControlExchange](x.Detail)
			if err != nil {
				return bad(err.Error())
			}
			q, r := v.Request, v.Response
			if x.Source == "driver" || q.Version != 1 || r.Version != 1 || q.Sequence != x.Request || q.Sequence != x.Local || r.Sequence != q.Sequence || r.Local != x.Local || q.Node != x.Source || r.Node != q.Node || q.Session == "" || q.Epoch == "" || r.Session != q.Session || r.Epoch != q.Epoch || q.Now != x.Now || r.Now != q.Now || q.Now < times[q.Node] || r.Operation != q.Operation || q.Generation != generation[q.Node] || r.Generation < q.Generation || r.Generation > q.Generation+1 || r.Result.Facts == nil || r.Result.Sends == nil || r.Result.Pending < 0 || r.Result.Pending > 128 || r.Result.StoreBytes < 0 || r.Result.StoreBytes > 4*1024*1024 {
				return bad("control continuity")
			}
			if sessions[q.Node] != "" && (q.Session != sessions[q.Node] || q.Epoch != epochs[q.Node]) {
				return bad("control epoch binding")
			}
			sessions[q.Node], epochs[q.Node] = q.Session, q.Epoch
			times[q.Node] = q.Now
			generation[q.Node] = r.Generation
			commands[x.Sequence] = v
			if r.Error != "" {
				execErrors++
			}
			switch q.Operation {
			case "init":
				d, e := networkDetail[NodeInit](q.Detail)
				if e != nil || initSeen[q.Node] || q.Now != 0 || r.Generation != 0 || d.Store != "store-"+q.Node || !reflect.DeepEqual(d.Profile, b.Profile) || d.Subcase != b.Manifest.Subcase || !reflect.DeepEqual(d.Peers, b.Topology.Peers) {
					return bad("node init")
				}
				initSeen[q.Node] = true
			case "submit_fixture", "snapshot", "drain", "shutdown":
				if _, e := networkDetail[struct{}](q.Detail); e != nil {
					return bad("empty control detail")
				}
				if q.Operation == "shutdown" {
					shutdown[q.Node] = r.Error == "" && r.Result.Pending == 0
				}
			case "step":
				d, e := networkDetail[NodeStep](q.Detail)
				if e != nil || d.Inputs == nil || d.Links == nil || len(d.Inputs) > 128 || len(d.Links) > 2 {
					return bad("step detail")
				}
				for _, id := range d.Inputs {
					f, ok := ingress[id]
					if !ok || f.Receiver != q.Node || f.Dropped || consumed[id] {
						return bad("step ingress ledger")
					}
					consumed[id] = true
				}
			case "arm_receive":
				d, e := networkDetail[ReceivePermit](q.Detail)
				if e != nil || !networkDirection(d.Sender, q.Node) || d.ID != fmt.Sprintf("%s-%d-%d", d.Sender, d.Generation, d.Index) || d.Ordinal < 1 || arms[d.ID].ID != "" {
					return bad("receive permit")
				}
				arms[d.ID] = d
			case "send":
				d, e := networkDetail[NodeSend](q.Detail)
				if e != nil || d.ID != fmt.Sprintf("%s-%d-%d", q.Node, q.Generation, d.Index) || d.Ordinal < 1 || arms[d.ID].ID == "" {
					return bad("send permit")
				}
			case "probe":
				if _, e := networkDetail[NodeProbe](q.Detail); e != nil {
					return bad("probe detail")
				}
			default:
				return bad("unknown control operation")
			}
			if q.Operation != "init" && !initSeen[q.Node] {
				return bad("operation before init")
			}
			for _, f := range r.Result.Facts {
				if f.Now != q.Now || f.Before < q.Generation || f.After > r.Generation || f.Before > f.After {
					return bad("node fact generation")
				}
				switch f.Kind {
				case "node_environment":
					d, e := networkDetail[NodeEnvironment](f.Detail)
					if e != nil || q.Operation != "init" || d.Epoch != q.Epoch || d.Store != "store-"+q.Node || d.Forwarding != "0" || !validHexDigest(d.Routes, 64) || environments[q.Node].Store != "" {
						return bad("node environment")
					}
					environments[q.Node] = d
				case "probe":
					d, e := networkDetail[ProbeFact](f.Detail)
					if e != nil {
						return bad("probe fact")
					}
					if !d.Received {
						target := peerByNode[d.To]
						expectedIP := target.AB
						if d.From == "C" || d.To == "C" {
							expectedIP = target.BC
						}
						if expectedIP == "" {
							expectedIP = target.AB
							if expectedIP == "" {
								expectedIP = target.BC
							}
						}
						if d.Address != net.JoinHostPort(expectedIP, "7000") {
							return bad("probe did not target inspected numeric IP")
						}
						key := direction(d.From, d.To)
						if d.From != q.Node || d.Address == "" || d.Expected != networkDirection(d.From, d.To) || d.Reachable != d.Expected || probes[key].From != "" {
							return bad("topology probe")
						}
						probes[key] = d
						probeRefs = append(probeRefs, x.Sequence)
					}
				case "socket_written", "transport_ingress":
					d, e := networkDetail[TransportFact](f.Detail)
					if e != nil || d.ID != f.Transfer || !networkDirection(d.Sender, d.Receiver) || d.Elapsed < 0 || d.Elapsed > int64(5*time.Second) || d.ID != fmt.Sprintf("%s-%d-%d", d.Sender, d.Generation, d.Index) {
						return bad("transport fact")
					}
					permit := arms[d.ID]
					if permit.Sender != d.Sender || permit.Generation != d.Generation || permit.Index != d.Index || permit.Ordinal != d.Ordinal {
						return bad("transport arm binding")
					}
					if f.Kind == "socket_written" {
						if q.Operation != "send" || d.Sender != q.Node || writes[d.ID].ID != "" || d.Dropped {
							return bad("socket write source")
						}
						writes[d.ID] = d
						writeRefs[d.ID] = x.Sequence
					} else {
						if q.Operation != "drain" || d.Receiver != q.Node || ingress[d.ID].ID != "" {
							return bad("ingress source")
						}
						sent, ok := writes[d.ID]
						if !ok || sent.Frame != d.Frame || sent.Ordinal != d.Ordinal {
							return bad("ingress write mismatch")
						}
						ingress[d.ID] = d
						ingressRefs[d.ID] = x.Sequence
					}
				case "link_gate":
					d, e := networkDetail[ControlLink](f.Detail)
					if e != nil || q.Operation != "step" || b.Profile.Fault.Kind != "down" || direction(q.Node, d.Neighbor) != b.Profile.Fault.Direction || !slices.Contains([]string{"became_down", "became_up"}, d.Event) {
						return bad("gate fact")
					}
				case "state_observed", "submit_result", "batch_result", "retry_decision", "verdict_decision", "frame_written", "frame_received":
					allowed := map[string][]string{"state_observed": {"init", "submit_fixture", "step", "snapshot"}, "submit_result": {"submit_fixture"}, "batch_result": {"step"}, "retry_decision": {"step"}, "verdict_decision": {"step"}, "frame_written": {"send"}, "frame_received": {"step"}}
					if !slices.Contains(allowed[f.Kind], q.Operation) {
						return bad("fact operation mismatch")
					}
					if _, e := detailOf(ScenarioEvent{Kind: f.Kind, Detail: f.Detail}); e != nil {
						return bad("semantic fact detail")
					}
				default:
					return bad("unknown node fact")
				}
			}
		case "resource":
			if x.Source != "driver" || x.Request != 0 {
				return bad("resource source")
			}
			v, e := networkDetail[ResourceFact](x.Detail)
			if e != nil || v.ID == "" || v.Batch != b.Manifest.Batch || v.Sample != b.Manifest.Run || v.Networks == nil {
				return bad("resource binding")
			}
			if v.Error != "" {
				execErrors++
			}
			switch v.Action {
			case "ready":
				if resources[v.Alias].ID != "" || v.Error != "" {
					return bad("resource duplicate/error")
				}
				resources[v.Alias] = v
			case "removed":
				if resources[v.Alias].ID != v.ID || removed[v.Alias].ID != "" {
					return bad("resource removal")
				}
				removed[v.Alias] = v
			default:
				return bad("resource action")
			}
		case "environment_check", "observation_end", "execution_aborted":
			if x.Source != "driver" || x.Request != 0 {
				return bad("driver source")
			}
			if _, e := detailOf(ScenarioEvent{Kind: x.Kind, Detail: x.Detail}); e != nil {
				return bad(e.Error())
			}
		default:
			return bad("execution kind")
		}
	}
	if len(initSeen) != 3 || len(environments) != 3 || len(probes) != 6 || len(b.Topology.Peers) != 3 {
		return bad("network environment incomplete")
	}
	if b.Topology.Schema != 3 || b.Topology.Mode != NetworkMode || b.Topology.Topology != CanonicalTopology || !slices.Equal(b.Topology.Sources, probeRefs) {
		return bad("topology references")
	}
	for _, name := range []string{"A", "B", "C"} {
		if sessions[name] != b.Manifest.Run || epochs[name] != epochs["A"] {
			return bad("sample epoch/session")
		}
		ips := []string{}
		for _, p := range b.Topology.Peers {
			if p.Node == name {
				if p.AB != "" {
					ips = append(ips, p.AB)
				}
				if p.BC != "" {
					ips = append(ips, p.BC)
				}
			}
		}
		slices.Sort(ips)
		if !slices.Equal(ips, environments[name].Interfaces) {
			return bad("interfaces")
		}
	}
	expected := map[string]string{"node-A": "container", "node-B": "container", "node-C": "container", "ab": "network", "bc": "network", "store-A": "volume", "store-B": "volume", "store-C": "volume"}
	if len(resources) != len(expected) {
		return bad("owned resource inventory")
	}
	ids := map[string]bool{}
	for alias, kind := range expected {
		v := resources[alias]
		if v.Kind != kind || v.Alias != alias || ids[v.ID] {
			return bad("exclusive resources")
		}
		ids[v.ID] = true
		if kind == "container" {
			nets := []string{"ab"}
			if v.Node == "B" {
				nets = []string{"ab", "bc"}
			}
			if v.Node == "C" {
				nets = []string{"bc"}
			}
			if alias != "node-"+v.Node || v.Store != "store-"+v.Node || !slices.Equal(v.Networks, nets) || !v.ReadOnly || !v.NoPorts || !v.NoPrivileges {
				return bad("container isolation")
			}
		}
	}
	sem := make([]ScenarioEvent, len(b.Events))
	writtenEvents := map[string]int64{}
	usedFacts := map[string]bool{}
	for i, e := range b.Events {
		if e.Schema != 3 || len(e.Sources) == 0 {
			return bad("semantic source inventory")
		}
		sem[i] = e.ScenarioEvent
		matched := false
		for _, ref := range e.Sources {
			if ref < 1 || ref > int64(len(b.Execution)) {
				return bad("semantic source range")
			}
			x := b.Execution[ref-1]
			if e.Node == "driver" && x.Source == "driver" && e.Kind == x.Kind && e.Now == x.Now && bytes.Equal(e.Detail, x.Detail) {
				matched = true
			}
			if index := matchNodeFact(e, x); index >= 0 {
				k := fmt.Sprintf("%d/%d", ref, index)
				if usedFacts[k] {
					return bad("duplicate fact reference")
				}
				usedFacts[k] = true
				matched = true
			}
			if x.Kind == "exchange" {
				v := commands[ref]
				for _, f := range v.Response.Result.Facts {
					if e.Kind == "frame_written" && f.Kind == "frame_written" && matchNodeFact(e, x) >= 0 {
						if writtenEvents[f.Transfer] != 0 {
							return bad("duplicate write event")
						}
						writtenEvents[f.Transfer] = e.Sequence
					}
					if e.Kind == "frame_received" && f.Kind == "frame_received" && matchNodeFact(e, x) >= 0 {
						d, err := networkDetail[FrameDetail](e.Detail)
						if err != nil || d.SendSequence != writtenEvents[f.Transfer] || !slices.Contains(e.Sources, ingressRefs[f.Transfer]) {
							return bad("receive fact binding")
						}
					}
					if e.Kind == "fault_transition" {
						d, err := networkDetail[FaultDetail](e.Detail)
						if err != nil {
							return bad("fault detail")
						}
						if f.Kind == "transport_ingress" && d.Action == "drop" {
							t, _ := networkDetail[TransportFact](f.Detail)
							if t.Dropped && d.Matched == writtenEvents[t.ID] && d.Direction == t.Frame.Direction {
								matched = true
							}
						}
						if f.Kind == "link_gate" {
							l, _ := networkDetail[ControlLink](f.Detail)
							if d.Direction == direction(x.Source, l.Neighbor) && (d.Action == "down" && l.Event == "became_down" || d.Action == "up" && l.Event == "became_up") {
								matched = true
							}
						}
					}
				}
			}
		}
		if !matched {
			return bad("semantic event lacks matching execution fact")
		}
	}
	for ref, exchange := range commands {
		for index, f := range exchange.Response.Result.Facts {
			if slices.Contains([]string{"state_observed", "submit_result", "batch_result", "retry_decision", "verdict_decision", "frame_written", "frame_received"}, f.Kind) && exchange.Request.Operation != "snapshot" && !usedFacts[fmt.Sprintf("%d/%d", ref, index)] {
				return bad("execution semantic fact omitted")
			}
		}
	}
	for id := range writes {
		if ingress[id].ID == "" || writtenEvents[id] == 0 {
			return bad("write without ingress/event")
		}
	}
	for id, t := range ingress {
		if !t.Dropped && !consumed[id] {
			return bad("unconsumed ingress")
		}
	}
	res := b.Residuals
	if res.Schema != 3 || res.Resources == nil || res.Pending < 0 || res.Children < 0 || res.Connections < 0 {
		return bad("network residual shape")
	}
	cleanup := len(removed) == 8 && shutdown["A"] && shutdown["B"] && shutdown["C"]
	wantResidual := []ResourceFact{}
	for _, alias := range []string{"ab", "bc", "node-A", "node-B", "node-C", "store-A", "store-B", "store-C"} {
		if v, ok := removed[alias]; ok {
			wantResidual = append(wantResidual, v)
			cleanup = cleanup && v.Error == ""
		}
	}
	if !reflect.DeepEqual(res.Resources, wantResidual) {
		return bad("residual removal sources")
	}
	cleanup = cleanup && res.Complete && res.Clean && res.Pending == 0 && res.Children == 0 && res.Connections == 0
	removedStores := int64(0)
	for _, v := range removed {
		if v.Kind == "volume" && v.Error == "" {
			removedStores++
		}
	}
	m, a, result, err := assessSemantics(semanticContract{3, sub.Size, b.Profile.Fault}, sem, ScenarioResiduals{Schema: 3, Complete: res.Complete, Owned: 3, Removed: removedStores, Pending: res.Pending, Children: res.Children, Clean: cleanup})
	if err != nil {
		return bad(err.Error())
	}
	out := NetworkMetrics{ScenarioMetrics: m, Timing: "supervisor_logical_ms", Written: int64(len(writes)), Ingress: int64(len(ingress)), Errors: execErrors}
	for _, f := range ingress {
		if f.Dropped {
			out.Drops++
		}
	}
	good := cleanup && execErrors == 0
	a.Items = append(a.Items, ScenarioAssertion{ID: "network_execution", Category: "environment", Passed: good, Sources: probeRefs, Reason: "control_transport_and_owned_resources"})
	if !good {
		result = "INVALID"
	}
	return out, a, result, nil
}
