package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"radishlink.local/t0/internal/harness"
)

// This runner never invokes Docker, a socket, or a subprocess. Its evidence is a verifier fixture only.
type memoryRunner struct {
	t               *testing.T
	root            string
	objects         map[string]dockerInspect
	world           map[string]*memoryNetwork
	actors          map[string]*nodeActor
	calls           [][]string
	failRemove      bool
	inspectMutation func(*dockerInspect)
}

func newMemoryRunner(t *testing.T) *memoryRunner {
	t.Helper()
	r := &memoryRunner{t: t, root: t.TempDir(), objects: map[string]dockerInspect{}, world: map[string]*memoryNetwork{}, actors: map[string]*nodeActor{}}
	for _, p := range testPeers() {
		r.world[p.Node] = &memoryNetwork{name: p.Node, peers: testPeers(), world: r.world}
	}
	return r
}
func option(args []string, key string) string {
	for i, a := range args {
		if a == key && i+1 < len(args) {
			return args[i+1]
		}
	}
	return ""
}
func labels(args []string) map[string]string {
	out := map[string]string{}
	for i, a := range args {
		if a == "--label" {
			parts := strings.SplitN(args[i+1], "=", 2)
			out[parts[0]] = parts[1]
		}
	}
	return out
}
func (r *memoryRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	r.calls = append(r.calls, append([]string{name}, args...))
	if name != "docker" {
		return nil, errors.New("unexpected external command")
	}
	if args[0] == "network" && args[1] == "connect" {
		v := r.objects[args[3]]
		v.NetworkSettings.Networks[args[2]] = struct {
			NetworkID string
			IPAddress string
		}{args[2], "10.2.0.2"}
		r.objects[args[3]] = v
		return nil, nil
	}
	if (args[0] == "network" || args[0] == "volume") && args[1] == "create" {
		id := args[len(args)-1]
		r.objects[id] = dockerInspect{ID: id, Name: id, Internal: true, Labels: labels(args)}
		return []byte(id + "\n"), nil
	}
	if args[0] == "create" {
		id := option(args, "--name")
		v := dockerInspect{ID: id, Name: id}
		v.Config.Labels = labels(args)
		node := v.Config.Labels["org.radishlink.sw-i5.node"]
		v.Config.User = option(args, "--user")
		v.HostConfig.ReadonlyRootfs = slices.Contains(args, "--read-only")
		v.HostConfig.IpcMode = option(args, "--ipc")
		mountParts := strings.SplitN(option(args, "--tmpfs"), ":", 2)
		if len(mountParts) == 2 {
			v.HostConfig.Tmpfs = map[string]string{mountParts[0]: mountParts[1]}
		}
		v.HostConfig.CapDrop = []string{option(args, "--cap-drop")}
		v.HostConfig.SecurityOpt = []string{option(args, "--security-opt")}
		v.HostConfig.Sysctls = map[string]string{"net.ipv4.ip_forward": "0"}
		v.HostConfig.RestartPolicy.Name = option(args, "--restart")
		v.HostConfig.Memory = 256 * 1024 * 1024
		v.HostConfig.NanoCpus = 500000000
		v.HostConfig.PidsLimit = 64
		v.HostConfig.LogConfig.Type = option(args, "--log-driver")
		volume := strings.Split(strings.Split(option(args, "--mount"), "src=")[1], ",")[0]
		v.Mounts = append(v.Mounts, struct {
			Type, Name, Destination string
			RW                      bool
		}{"volume", volume, "/state", true})
		netID := option(args, "--network")
		ip := map[string]string{"A": "10.1.0.2", "B": "10.1.0.3", "C": "10.2.0.3"}[node]
		v.NetworkSettings.Networks = map[string]struct {
			NetworkID string
			IPAddress string
		}{netID: {netID, ip}}
		v.State.Running = true
		r.objects[id] = v
		return []byte(id + "\n"), nil
	}
	if args[0] == "inspect" || len(args) > 1 && args[1] == "inspect" {
		v, ok := r.objects[args[len(args)-1]]
		if !ok {
			return nil, errors.New("test missing resource")
		}
		if r.inspectMutation != nil && v.Config.User != "" {
			r.inspectMutation(&v)
		}
		return json.Marshal([]dockerInspect{v})
	}
	if args[0] == "ps" || len(args) > 1 && args[1] == "ls" {
		if r.failRemove {
			return []byte("remaining\n"), nil
		}
		return nil, nil
	}
	if args[0] == "rm" || len(args) > 1 && args[1] == "rm" {
		if r.failRemove {
			return nil, errors.New("test cleanup denied")
		}
		delete(r.objects, args[len(args)-1])
		return nil, nil
	}
	return nil, fmt.Errorf("unexpected Docker command %v", args)
}
func (r *memoryRunner) Start(_ context.Context, name string, args ...string) (controlPeer, error) {
	if name != "docker" || len(args) != 3 || args[0] != "start" || args[1] != "-ai" {
		return nil, errors.New("start command")
	}
	v := r.objects[args[2]]
	node := v.Config.Labels["org.radishlink.sw-i5.node"]
	dir := filepath.Join(r.root, node)
	if err := os.Mkdir(dir, 0700); err != nil {
		return nil, err
	}
	n := &nodeActor{directory: dir, network: r.world[node]}
	r.actors[node] = n
	return &actorPeer{actor: n}, nil
}
func memoryBundle(t *testing.T, id, sub string, repeat int) harness.NetworkBundle {
	t.Helper()
	p, err := harness.CanonicalNetwork(id)
	if err != nil {
		t.Fatal(err)
	}
	r := newMemoryRunner(t)
	run := fmt.Sprintf("fixture-%d", repeat)
	s := newProcessSample(context.Background(), r, p, sub, "fixture-batch", run, strings.Repeat(fmt.Sprint(repeat), 32), "sha256:"+strings.Repeat("a", 64))
	if err = s.prepare(); err != nil {
		t.Fatal("prepare", err)
	}
	if err = s.drive(); err != nil {
		t.Fatal("drive", err)
	}
	res, err := s.cleanup()
	if err != nil {
		t.Fatal("cleanup", err)
	}
	if len(r.objects) != 0 {
		t.Fatal("residual fake objects")
	}
	profiles, _ := harness.NetworkProfiles()
	size, _ := p.Subcase(sub)
	m := harness.NetworkManifest{Schema: 3, Observation: 1, Batch: "fixture-batch", Run: run, Evidence: fmt.Sprintf("fixture-batch/%s/%s/%d", id, sub, repeat), Repeat: int64(repeat), ProfileID: id, ProfileVersion: p.Version, Seed: p.Seed, Variant: p.Variant, Subcase: sub, Mode: p.Mode, Security: p.Security, GitRevision: strings.Repeat("b", 40), GoVersion: "fixture", OS: "fixture", Arch: "fixture", Started: "2026-09-26T00:00:00Z", Ended: "2026-09-26T00:00:01Z", Topology: p.Topology, Size: size.Size, Count: 1, Window: 30000, Control: 1, Transport: p.Transport, FaultLayer: p.FaultLayer, HostBinary: strings.Repeat("c", 64), NodeBinary: strings.Repeat("d", 64), Image: s.image, DockerClient: "fixture", DockerServer: "fixture", DaemonOS: "linux", DaemonArch: "arm64", Contract: strings.Repeat("e", 64), Profiles: profiles}
	return s.bundle(m, res)
}
func TestProcessActorByteStreams(t *testing.T) {
	for _, id := range []string{"SW-V1-BASE-001", "SW-V1-LOSS-EVIDENCE-001", "SW-V1-LOSS-EVIDENCE-BA-001", "SW-V1-DOWN-AB-001", "SW-V1-DOWN-BC-001"} {
		p, _ := harness.CanonicalNetwork(id)
		for _, sub := range p.Subcases {
			t.Run(id+"/"+sub.ID, func(t *testing.T) {
				b := memoryBundle(t, id, sub.ID, 1)
				m, _, result, err := harness.AssessNetwork(b)
				if err != nil || result != "PASS" {
					t.Fatalf("contract fixture: %s %v %+v", result, err, m)
				}
				if m.Ingress != m.Written {
					t.Fatal("unpaired frames")
				}
			})
		}
	}
}
func TestNetworkBundleFixtureConsumers(t *testing.T) {
	root := t.TempDir()
	for repeat := 1; repeat <= 3; repeat++ {
		b := memoryBundle(t, "SW-V1-BASE-001", "p1024", repeat)
		path := filepath.Join(root, fmt.Sprint(repeat))
		if err := harness.WriteNetworkBundle(path, b); err != nil {
			t.Fatal(err)
		}
		if err := harness.VerifyEvidence(path); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := harness.CompareEvidenceRuns(root); err != nil {
		t.Fatal(err)
	}
	os.Mkdir(filepath.Join(root, "4"), 0700)
	if _, err := harness.CompareEvidenceRuns(root); err == nil {
		t.Fatal("fourth repeat accepted")
	}
}
func TestProcessRejectsLostResponseAndCleanupFailure(t *testing.T) {
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	r := newMemoryRunner(t)
	s := newProcessSample(context.Background(), r, p, "p1024", "batch", "sample", strings.Repeat("2", 32), "image")
	if err := s.prepare(); err != nil {
		t.Fatal(err)
	}
	peer := s.peers["A"].(*actorPeer)
	peer.dropResponse = true
	if _, err := s.call("A", "submit_fixture", struct{}{}); err == nil {
		t.Fatal("lost reply accepted")
	}
	if r.actors["A"].generation() != 1 || s.request["A"] < 2 {
		t.Fatal("lost reply setup")
	}
	r.failRemove = true
	res, err := s.cleanup()
	if err == nil || res.Clean || len(r.objects) == 0 {
		t.Fatal("failed cleanup silently succeeded")
	}
}
func TestSupervisorCommandRestrictions(t *testing.T) {
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	s := newProcessSample(context.Background(), nil, p, "p1024", "batch", "sample", strings.Repeat("2", 32), "image")
	s.resources = []ownedResource{{alias: "ab", id: "ab"}, {alias: "bc", id: "bc"}, {alias: "store-B", id: "store-B"}}
	args := s.containerArgs("B")
	for _, flag := range []string{"--read-only", "--cap-drop", "--security-opt", "--pids-limit", "--memory", "--cpus"} {
		if !slices.Contains(args, flag) {
			t.Fatal("missing", flag)
		}
	}
	for _, flag := range []string{"--privileged", "--publish", "--network=host"} {
		if slices.Contains(args, flag) {
			t.Fatal("unsafe", flag)
		}
	}
	if strings.Contains(strings.Join(args, " "), "docker.sock") {
		t.Fatal("socket mount")
	}
}
func TestScenarioTimingUsesNextEvent(t *testing.T) {
	if got := scenarioNext(1, map[string]harness.ObservedState{}, []int64{51}, -1, -1); got != 51 {
		t.Fatal(got)
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Millisecond)
	defer cancel()
	<-ctx.Done()
}

func cloneNetwork(t *testing.T, b harness.NetworkBundle) harness.NetworkBundle {
	t.Helper()
	raw, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	var out harness.NetworkBundle
	if err = json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return out
}
func TestNetworkExecutionTampering(t *testing.T) {
	original := memoryBundle(t, "SW-V1-BASE-001", "p1024", 1)
	cases := map[string]func(*harness.NetworkBundle){
		"missing-ingress-source": func(b *harness.NetworkBundle) {
			for i := range b.Events {
				if b.Events[i].Kind == "frame_received" {
					b.Events[i].Sources = b.Events[i].Sources[:1]
					return
				}
			}
		},
		"missing-write-event": func(b *harness.NetworkBundle) {
			for i := range b.Events {
				if b.Events[i].Kind == "frame_written" {
					b.Events[i].Kind = "frame_received"
					return
				}
			}
		},
		"generation": func(b *harness.NetworkBundle) {
			for i := range b.Events {
				if b.Events[i].Kind == "state_observed" {
					b.Events[i].After++
					return
				}
			}
		},
		"false-cleanup": func(b *harness.NetworkBundle) { b.Residuals.Resources = b.Residuals.Resources[:7] },
		"shared-store": func(b *harness.NetworkBundle) {
			for i := range b.Execution {
				if b.Execution[i].Kind == "resource" {
					var f harness.ResourceFact
					json.Unmarshal(b.Execution[i].Detail, &f)
					if f.Alias == "node-C" {
						f.Store = "store-A"
						b.Execution[i].Detail = rawDetail(f)
						return
					}
				}
			}
		},
		"numeric-probe": func(b *harness.NetworkBundle) {
			for i := range b.Execution {
				if b.Execution[i].Kind == "exchange" {
					var x harness.ControlExchange
					json.Unmarshal(b.Execution[i].Detail, &x)
					for j := range x.Response.Result.Facts {
						f := &x.Response.Result.Facts[j]
						if f.Kind == "probe" {
							var p harness.ProbeFact
							json.Unmarshal(f.Detail, &p)
							if !p.Received {
								p.Address = "unresolvable:7000"
								f.Detail = rawDetail(p)
								b.Execution[i].Detail = rawDetail(x)
								return
							}
						}
					}
				}
			}
		},
		"epoch": func(b *harness.NetworkBundle) {
			for i := range b.Execution {
				if b.Execution[i].Kind == "exchange" {
					var x harness.ControlExchange
					json.Unmarshal(b.Execution[i].Detail, &x)
					if x.Request.Operation == "step" {
						x.Request.Epoch = strings.Repeat("f", 32)
						b.Execution[i].Detail = rawDetail(x)
						return
					}
				}
			}
		},
		"request-sequence": func(b *harness.NetworkBundle) {
			for i := range b.Execution {
				if b.Execution[i].Kind == "exchange" {
					var x harness.ControlExchange
					json.Unmarshal(b.Execution[i].Detail, &x)
					x.Request.Sequence++
					x.Response.Sequence++
					b.Execution[i].Request++
					b.Execution[i].Detail = rawDetail(x)
					return
				}
			}
		},
		"ingress-hash": func(b *harness.NetworkBundle) {
			for i := range b.Execution {
				if b.Execution[i].Kind == "exchange" {
					var x harness.ControlExchange
					json.Unmarshal(b.Execution[i].Detail, &x)
					for j := range x.Response.Result.Facts {
						f := &x.Response.Result.Facts[j]
						if f.Kind == "transport_ingress" {
							var v harness.TransportFact
							json.Unmarshal(f.Detail, &v)
							v.Frame.Frame = strings.Repeat("f", 64)
							f.Detail = rawDetail(v)
							b.Execution[i].Detail = rawDetail(x)
							return
						}
					}
				}
			}
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			b := cloneNetwork(t, original)
			mutate(&b)
			if _, _, result, err := harness.AssessNetwork(b); err == nil && result == "PASS" {
				t.Fatal("tampering passed")
			}
			if err := harness.WriteNetworkBundle(filepath.Join(t.TempDir(), "bundle"), b); err == nil {
				t.Fatal("writer finalized corrupted fixture")
			}
		})
	}
}
func TestNetworkFullFailureFixtureAndChecksumRewrite(t *testing.T) {
	b := memoryBundle(t, "SW-V1-BASE-001", "p1024", 1)
	// Preserve a structurally coherent environment failure rather than relabeling it as a successful run.
	for i := range b.Execution {
		if b.Execution[i].Kind == "environment_check" {
			var d harness.EnvironmentDetail
			json.Unmarshal(b.Execution[i].Detail, &d)
			if d.ID == "clock" {
				d.Passed = false
				b.Execution[i].Detail = rawDetail(d)
				for j := range b.Events {
					if b.Events[j].Kind == "environment_check" && slices.Contains(b.Events[j].Sources, b.Execution[i].Sequence) {
						b.Events[j].Detail = rawDetail(d)
					}
				}
			}
		}
	}
	if _, _, result, err := harness.AssessNetwork(b); err != nil || result != "INVALID" {
		t.Fatalf("failed fixture: %s %v", result, err)
	}
	root := filepath.Join(t.TempDir(), "bundle")
	if err := harness.WriteNetworkBundle(root, b); err != nil {
		t.Fatal(err)
	}
	if err := harness.VerifyEvidence(root); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(root, "metrics.json"))
	if err != nil {
		t.Fatal(err)
	}
	raw = []byte(strings.Replace(string(raw), `"socket_writes":`, `"socket_writes":9`, 1))
	if err = os.WriteFile(filepath.Join(root, "metrics.json"), raw, 0600); err != nil {
		t.Fatal(err)
	}
	entries, _ := os.ReadDir(root)
	var sums strings.Builder
	for _, e := range entries {
		if e.IsDir() || e.Name() == "checksums.sha256" {
			continue
		}
		data, err := os.ReadFile(filepath.Join(root, e.Name()))
		if err != nil {
			t.Fatal(err)
		}
		fmt.Fprintf(&sums, "%s  %s\n", scenarioHash(data), e.Name())
	}
	os.WriteFile(filepath.Join(root, "checksums.sha256"), []byte(sums.String()), 0600)
	if err = harness.VerifyEvidence(root); err == nil {
		t.Fatal("rehashed metric tampering accepted")
	}
}

func TestNetworkCompleteImplementationFailureIsFAIL(t *testing.T) {
	b := memoryBundle(t, "SW-V1-BASE-001", "p1", 1)
	alter := func(raw json.RawMessage) json.RawMessage {
		var s harness.ObservedState
		if err := json.Unmarshal(raw, &s); err != nil {
			t.Fatal(err)
		}
		if len(s.Messages) > 0 {
			s.ReceiveSteps = 2
		}
		return rawDetail(s)
	}
	for i := range b.Events {
		e := &b.Events[i]
		if e.Node == "C" && e.Kind == "state_observed" {
			e.Detail = alter(e.Detail)
		}
	}
	for i := range b.Execution {
		x := &b.Execution[i]
		if x.Source == "C" && x.Kind == "exchange" {
			var v harness.ControlExchange
			json.Unmarshal(x.Detail, &v)
			for j := range v.Response.Result.Facts {
				f := &v.Response.Result.Facts[j]
				if f.Kind == "state_observed" {
					f.Detail = alter(f.Detail)
				}
			}
			x.Detail = rawDetail(v)
		}
	}
	if _, _, result, err := harness.AssessNetwork(b); err != nil || result != "FAIL" {
		t.Fatalf("expected complete implementation FAIL, got %s %v", result, err)
	}
	root := filepath.Join(t.TempDir(), "bundle")
	if err := harness.WriteNetworkBundle(root, b); err != nil {
		t.Fatal(err)
	}
	if err := harness.VerifyEvidence(root); err != nil {
		t.Fatal(err)
	}
}

type uncertainCreateRunner struct {
	*memoryRunner
	failOnce bool
}

func (r *uncertainCreateRunner) Run(ctx context.Context, name string, args ...string) ([]byte, error) {
	out, err := r.memoryRunner.Run(ctx, name, args...)
	if err == nil && len(args) > 1 && args[0] == "network" && args[1] == "create" && !r.failOnce {
		r.failOnce = true
		return nil, errors.New("timeout after resource creation")
	}
	return out, err
}
func TestUncertainCreateIsOwnedAndCleaned(t *testing.T) {
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	r := &uncertainCreateRunner{memoryRunner: newMemoryRunner(t)}
	s := newProcessSample(context.Background(), r, p, "p1", "batch", "sample", strings.Repeat("2", 32), "image")
	if err := s.prepare(); err == nil {
		t.Fatal("uncertain creation treated as success")
	}
	if len(r.objects) != 1 || len(s.resources) != 1 || s.resources[0].id != "" {
		t.Fatal("missing unresolved inventory")
	}
	res, err := s.cleanup()
	if err != nil {
		t.Fatal(err)
	}
	if len(r.objects) != 0 || res.Complete || res.Clean {
		t.Fatal("uncertain run falsely completed or leaked resource")
	}
}
func TestCleanupRefusesForeignLabel(t *testing.T) {
	p, _ := harness.CanonicalNetwork("SW-V1-BASE-001")
	r := newMemoryRunner(t)
	s := newProcessSample(context.Background(), r, p, "p1", "batch", "sample", strings.Repeat("2", 32), "image")
	args := []string{"network", "create", "--internal"}
	args = append(args, s.labelArgs("")...)
	args = append(args, "sample-ab")
	id, err := s.resource("network", "ab", "", args)
	if err != nil {
		t.Fatal(err)
	}
	v := r.objects[id]
	v.Labels["org.radishlink.sw-i5.batch"] = "someone-else"
	r.objects[id] = v
	if _, err = s.cleanup(); err == nil {
		t.Fatal("foreign ownership accepted")
	}
	if _, ok := r.objects[id]; !ok {
		t.Fatal("foreign resource deleted")
	}
	for _, args := range r.calls {
		if len(args) > 2 && args[1] == "network" && args[2] == "rm" {
			t.Fatal("attempted foreign deletion")
		}
	}
}

type preflightRunner struct {
	calls [][]string
	dirty bool
}

func (r *preflightRunner) Start(context.Context, string, ...string) (controlPeer, error) {
	return nil, errors.New("preflight attempted start")
}
func (r *preflightRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	r.calls = append(r.calls, append([]string{name}, args...))
	switch name {
	case "git":
		if args[len(args)-1] == "--porcelain" {
			if r.dirty {
				return []byte(" M file\n"), nil
			}
			return nil, nil
		}
		return []byte(strings.Repeat("a", 40) + "\n"), nil
	case "go":
		return []byte("go version go1.26 fixture\n"), nil
	case "docker":
		if len(args) > 0 && args[0] == "version" {
			return []byte(`{"Client":{"Version":"fixture"},"Server":{"Version":"fixture","Os":"linux","Arch":"arm64"}}`), nil
		}
	case "df":
		return []byte("Filesystem 1024-blocks Used Available Capacity Mounted\nfixture 9000000 1000000 8000000 11% /fixture\n"), nil
	}
	return nil, fmt.Errorf("unexpected preflight command %s %v", name, args)
}
func TestNetworkPreflightUsesOneReadOnlyContract(t *testing.T) {
	t.Setenv("DOCKER_HOST", "unix:///fixture/docker.sock")
	t.Setenv("DOCKER_CONTEXT", "")
	root, err := filepath.Abs("../../../..")
	if err != nil {
		t.Fatal(err)
	}
	r := &preflightRunner{}
	p, err := preflightNetwork(context.Background(), r, root)
	if err != nil || len(p.Profiles) != 5 || p.Contract == "" {
		t.Fatalf("preflight %v %+v", err, p)
	}
	for _, call := range r.calls {
		for _, arg := range call {
			if slices.Contains([]string{"create", "start", "rm", "build", "run"}, arg) {
				t.Fatal("preflight mutation", call)
			}
		}
	}
	r.dirty = true
	if _, err = preflightNetwork(context.Background(), r, root); err == nil {
		t.Fatal("dirty source accepted")
	}
	r.dirty = false
	t.Setenv("DOCKER_HOST", "tcp://fixture.invalid:2375")
	if _, err = preflightNetwork(context.Background(), r, root); err == nil {
		t.Fatal("remote daemon accepted")
	}
}
