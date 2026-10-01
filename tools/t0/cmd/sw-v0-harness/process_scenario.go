package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"slices"
	"strings"
	"sync"
	"time"

	"radishlink.local/t0/internal/harness"
)

type controlPeer interface {
	Exchange(context.Context, harness.ControlRequest) (harness.ControlResponse, error)
	Close() error
}
type processRunner interface {
	Run(context.Context, string, ...string) ([]byte, error)
	Start(context.Context, string, ...string) (controlPeer, error)
}
type limitedOutput struct {
	mu    sync.Mutex
	b     bytes.Buffer
	limit int
	err   error
}

func (w *limitedOutput) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.b.Len()+len(p) > w.limit {
		w.err = errors.New("process output limit")
		return 0, w.err
	}
	return w.b.Write(p)
}
func (w *limitedOutput) Bytes() []byte {
	w.mu.Lock()
	defer w.mu.Unlock()
	return bytes.Clone(w.b.Bytes())
}

type osProcessRunner struct{}

func (osProcessRunner) Run(ctx context.Context, name string, args ...string) ([]byte, error) {
	c := exec.CommandContext(ctx, name, args...)
	out := &limitedOutput{limit: 4 * 1024 * 1024}
	stderr := &limitedOutput{limit: 64 * 1024}
	c.Stdout, c.Stderr = out, stderr
	err := c.Run()
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w: %s", name, strings.Join(args, " "), err, stderr.Bytes())
	}
	return out.Bytes(), errors.Join(out.err, stderr.err)
}

type pipePeer struct {
	cmd      *exec.Cmd
	in       io.WriteCloser
	out      *bufio.Reader
	stderr   *limitedOutput
	wait     chan error
	once     sync.Once
	closeErr error
}

func (osProcessRunner) Start(ctx context.Context, name string, args ...string) (controlPeer, error) {
	c := exec.CommandContext(ctx, name, args...)
	in, err := c.StdinPipe()
	if err != nil {
		return nil, err
	}
	out, err := c.StdoutPipe()
	if err != nil {
		in.Close()
		return nil, err
	}
	stderr := &limitedOutput{limit: 64 * 1024}
	c.Stderr = stderr
	if err = c.Start(); err != nil {
		in.Close()
		out.Close()
		return nil, err
	}
	p := &pipePeer{cmd: c, in: in, out: bufio.NewReaderSize(out, controlResponseCap+2), stderr: stderr, wait: make(chan error, 1)}
	return p, nil
}
func (p *pipePeer) Exchange(ctx context.Context, q harness.ControlRequest) (harness.ControlResponse, error) {
	type result struct {
		v   harness.ControlResponse
		err error
	}
	ch := make(chan result, 1)
	go func() {
		b, err := json.Marshal(q)
		if err == nil && len(b) > controlRequestCap {
			err = errors.New("request output limit")
		}
		if err == nil {
			b = append(b, '\n')
			var n int
			n, err = p.in.Write(b)
			if err == nil && n != len(b) {
				err = io.ErrShortWrite
			}
		}
		var r harness.ControlResponse
		if err == nil {
			var line []byte
			line, err = readControlLine(p.out, controlResponseCap)
			if err == nil {
				err = harness.CanonicalJSON(line, &r, controlResponseCap)
			}
		}
		ch <- result{r, err}
	}()
	select {
	case r := <-ch:
		return r.v, r.err
	case <-ctx.Done():
		p.cmd.Process.Kill()
		p.in.Close()
		r := <-ch
		return r.v, errors.Join(ctx.Err(), r.err)
	}
}
func (p *pipePeer) Close() error {
	p.once.Do(func() {
		p.in.Close()
		go func() { p.wait <- p.cmd.Wait() }()
		select {
		case p.closeErr = <-p.wait:
		case <-time.After(operationTimeout):
			p.cmd.Process.Kill()
			p.closeErr = errors.Join(errors.New("process wait timeout"), <-p.wait)
		}
		p.closeErr = errors.Join(p.closeErr, p.stderr.err)
	})
	return p.closeErr
}

type ownedResource struct {
	kind, id, alias, node, name string
	fact                        harness.ResourceFact
	ready                       bool
}
type processSample struct {
	guard                    func() error
	storeUsage               map[string]int64
	runner                   processRunner
	batch, run, epoch, image string
	ctx                      context.Context
	profile                  harness.NetworkProfile
	subcase                  string
	peers                    map[string]controlPeer
	addresses                []harness.NetworkPeer
	resources                []ownedResource
	execution                []harness.ExecutionEvent
	events                   []harness.NetworkEvent
	local                    map[string]int64
	request                  map[string]int64
	generation               map[string]int64
	snapshots                map[string]harness.ObservedState
	operations               map[string]int64
	sends                    map[string]int64
	writes                   map[string]int64
	ingress                  map[string]int64
	pending                  map[string]struct {
		node string
		at   int64
	}
	handles  map[string][]harness.SendHandle
	ordinals map[string]int64
	now      int64
	bytes    int
	err      error
}

func newProcessSample(ctx context.Context, r processRunner, p harness.NetworkProfile, sub, batch, run, epoch, image string) *processSample {
	return &processSample{ctx: ctx, runner: r, profile: p, subcase: sub, batch: batch, run: run, epoch: epoch, image: image, peers: map[string]controlPeer{}, local: map[string]int64{}, request: map[string]int64{}, generation: map[string]int64{}, snapshots: map[string]harness.ObservedState{}, operations: map[string]int64{}, sends: map[string]int64{}, writes: map[string]int64{}, ingress: map[string]int64{}, pending: map[string]struct {
		node string
		at   int64
	}{}, handles: map[string][]harness.SendHandle{}, ordinals: map[string]int64{}}
}
func (s *processSample) record(source, kind string, request int64, detail any) int64 {
	if s.err != nil {
		return 0
	}
	s.local[source]++
	x := harness.ExecutionEvent{Schema: 3, Sequence: int64(len(s.execution) + 1), Source: source, Local: s.local[source], Request: request, Now: s.now, Kind: kind, Detail: rawDetail(detail)}
	b := rawDetail(x)
	if len(b) > 256*1024 || s.bytes+len(b) > 16*1024*1024 || len(s.execution) >= 8192 {
		s.err = errors.New("execution record cap")
		return 0
	}
	s.bytes += len(b)
	s.execution = append(s.execution, x)
	return x.Sequence
}
func (s *processSample) semantic(node, kind string, before, after, cause int64, id string, detail any, refs ...int64) {
	if s.err != nil {
		return
	}
	var key *harness.ObservedKey
	if node != "driver" && (before > 0 || after > 0 || kind != "state_observed") {
		k := harness.ObservedKey{Version: 1, Origin: "A", Scope: "i4-small4", ID: strings.Repeat("3", 32)}
		key = &k
	}
	if kind == "fault_transition" {
		k := harness.ObservedKey{Version: 1, Origin: "A", Scope: "i4-small4", ID: strings.Repeat("3", 32)}
		key = &k
	}
	e := harness.NetworkEvent{ScenarioEvent: harness.ScenarioEvent{Schema: 3, Sequence: int64(len(s.events) + 1), Now: s.now, Node: node, Kind: kind, Key: key, Before: before, After: after, Cause: cause, Detail: rawDetail(detail)}, Sources: refs}
	if len(rawDetail(e)) > 16*1024 || len(s.events) >= 8192 {
		s.err = errors.New("semantic record cap")
		return
	}
	s.events = append(s.events, e)
	switch kind {
	case "submit_result", "batch_result":
		s.operations[node] = e.Sequence
	case "retry_decision":
		var v harness.ObservedRetry
		json.Unmarshal(e.Detail, &v)
		if v.Send {
			s.sends[node+"/"+v.Kind] = e.Sequence
		}
	case "frame_written":
		s.writes[id] = e.Sequence
	}
}
func (s *processSample) consume(node string, r harness.ControlResponse, ref int64) error {
	for _, f := range r.Result.Facts {
		switch f.Kind {
		case "node_environment", "probe", "socket_written":
		case "link_gate":
			var l harness.ControlLink
			if err := json.Unmarshal(f.Detail, &l); err != nil {
				return err
			}
			action := "up"
			if l.Event == "became_down" {
				action = "down"
			}
			s.semantic("driver", "fault_transition", 0, 0, 0, "", harness.FaultDetail{Direction: scenarioDirection(node, l.Neighbor), Trigger: s.profile.Fault.Trigger, Action: action, Hit: 1}, ref)
		case "transport_ingress":
			var t harness.TransportFact
			if err := json.Unmarshal(f.Detail, &t); err != nil {
				return err
			}
			s.ingress[t.ID] = ref
			if t.Dropped {
				s.semantic("driver", "fault_transition", 0, 0, s.writes[t.ID], "", harness.FaultDetail{Direction: t.Frame.Direction, Trigger: s.profile.Fault.Trigger, Action: "drop", Matched: s.writes[t.ID], Hit: 1}, ref)
			} else {
				s.pending[t.ID] = struct {
					node string
					at   int64
				}{node, s.now + 50}
			}
		case "frame_written", "frame_received":
			var frame harness.FrameDetail
			if err := json.Unmarshal(f.Detail, &frame); err != nil {
				return err
			}
			cause := s.sends[node+"/"+frame.Kind]
			refs := []int64{ref}
			if f.Kind == "frame_received" {
				cause = s.writes[f.Transfer]
				frame.SendSequence = cause
				refs = append(refs, s.ingress[f.Transfer])
				delete(s.pending, f.Transfer)
			}
			s.semantic(node, f.Kind, f.Before, f.After, cause, f.Transfer, frame, refs...)
		case "state_observed":
			var v harness.ObservedState
			if err := json.Unmarshal(f.Detail, &v); err != nil {
				return err
			}
			s.snapshots[node] = v
			cause := s.operations[node]
			if v.Generation == 0 {
				cause = 0
			}
			s.semantic(node, f.Kind, f.Before, f.After, cause, "", v, ref)
		case "submit_result", "batch_result", "verdict_decision":
			s.semantic(node, f.Kind, f.Before, f.After, 0, "", f.Detail, ref)
		case "retry_decision":
			s.semantic(node, f.Kind, f.Before, f.After, s.operations[node], "", f.Detail, ref)
		default:
			return fmt.Errorf("unknown node fact %s", f.Kind)
		}
	}
	s.handles[node] = slices.Clone(r.Result.Sends)
	return s.err
}
func (s *processSample) call(node, operation string, detail any) (harness.ControlResponse, error) {
	if s.guard != nil {
		if err := s.guard(); err != nil {
			return harness.ControlResponse{}, err
		}
	}
	s.request[node]++
	q := harness.ControlRequest{Version: 1, Session: s.run, Node: node, Sequence: s.request[node], Epoch: s.epoch, Now: s.now, Generation: s.generation[node], Operation: operation, Detail: rawDetail(detail)}
	ctx, cancel := context.WithTimeout(s.ctx, operationTimeout)
	defer cancel()
	r, err := s.peers[node].Exchange(ctx, q)
	if err != nil {
		return r, fmt.Errorf("%s %s: %w", node, operation, err)
	}
	if r.Version != 1 || r.Node != node || r.Sequence != q.Sequence || r.Local != q.Sequence || r.Session != q.Session || r.Epoch != q.Epoch || r.Now != q.Now || r.Operation != operation || r.Generation < q.Generation || r.Generation > q.Generation+1 {
		return r, errors.New("control response binding")
	}
	ref := s.record(node, "exchange", q.Sequence, harness.ControlExchange{Request: q, Response: r})
	s.generation[node] = r.Generation
	if s.storeUsage == nil {
		s.storeUsage = map[string]int64{}
	}
	s.storeUsage[node] = r.Result.StoreBytes
	var storeTotal int64
	for _, size := range s.storeUsage {
		if size < 0 || size > 4*1024*1024 {
			return r, errors.New("store resource bound")
		}
		storeTotal += size
	}
	if storeTotal > 12*1024*1024 {
		return r, errors.New("store aggregate bound")
	}
	if err = s.consume(node, r, ref); err != nil {
		return r, err
	}
	if r.Error != "" {
		return r, fmt.Errorf("%s %s: %s", node, operation, r.Error)
	}
	return r, nil
}
func (s *processSample) docker(ctx context.Context, args ...string) ([]byte, error) {
	deadline, cancel := context.WithTimeout(ctx, operationTimeout)
	defer cancel()
	return s.runner.Run(deadline, "docker", args...)
}
func (s *processSample) labelArgs(node string) []string {
	return []string{"--label", "org.radishlink.sw-i5.batch=" + s.batch, "--label", "org.radishlink.sw-i5.sample=" + s.run, "--label", "org.radishlink.sw-i5.node=" + node}
}
func (s *processSample) resource(kind, alias, node string, args []string) (string, error) {
	name := args[len(args)-1]
	if kind == "container" {
		name = ""
		for i, arg := range args {
			if arg == "--name" && i+1 < len(args) {
				name = args[i+1]
			}
		}
	}
	if name == "" {
		return "", errors.New("resource name missing")
	}
	index := len(s.resources)
	s.resources = append(s.resources, ownedResource{kind: kind, alias: alias, node: node, name: name})
	raw, err := s.docker(s.ctx, args...)
	if err != nil {
		return "", err
	}
	id := strings.TrimSpace(string(raw))
	if id == "" || strings.ContainsAny(id, " \n\t") {
		return "", errors.New("resource identifier")
	}
	s.resources[index].id = id
	return id, nil
}
func (s *processSample) resourceID(alias string) string {
	for _, r := range s.resources {
		if r.alias == alias {
			return r.id
		}
	}
	return ""
}
func (s *processSample) containerArgs(node string) []string {
	args := []string{"create", "-i", "--name", s.run + "-" + strings.ToLower(node), "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--user", "65532:65532", "--cpus", "0.5", "--memory", "256m", "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--sysctl", "net.ipv4.ip_forward=0", "--restart", "no", "--log-driver", "none"}
	args = append(args, s.labelArgs(node)...)
	network := "ab"
	if node == "C" {
		network = "bc"
	}
	args = append(args, "--network", s.resourceID(network), "--mount", "type=volume,src="+s.resourceID("store-"+node)+",dst=/state", s.image, "synthetic-node", "--store", "/state")
	return args
}

type dockerInspect struct {
	ID       string `json:"Id"`
	Name     string
	Internal bool
	Labels   map[string]string
	Config   struct {
		Labels map[string]string
		User   string
	}
	HostConfig struct {
		ReadonlyRootfs bool
		Privileged     bool
		CapDrop        []string
		SecurityOpt    []string
		NetworkMode    string
		Binds          []string
		PortBindings   map[string]json.RawMessage
		Sysctls        map[string]string
		RestartPolicy  struct{ Name string }
		Memory         int64
		NanoCpus       int64
		PidsLimit      int64
		LogConfig      struct{ Type string }
	}
	NetworkSettings struct {
		Networks map[string]struct {
			NetworkID string
			IPAddress string
		}
		Ports map[string]json.RawMessage
	}
	Mounts []struct {
		Type, Name, Destination string
		RW                      bool
	}
	State struct {
		Running  bool
		ExitCode int
	}
	Containers map[string]json.RawMessage
}

func (s *processSample) inspect(ctx context.Context, r ownedResource) (dockerInspect, error) {
	identifier := r.id
	if identifier == "" {
		identifier = r.name
	}
	if identifier == "" {
		return dockerInspect{}, errors.New("unresolved resource")
	}
	args := []string{"inspect", identifier}
	if r.kind == "network" || r.kind == "volume" {
		args = []string{r.kind, "inspect", identifier}
	}
	raw, err := s.docker(ctx, args...)
	if err != nil {
		return dockerInspect{}, err
	}
	var all []dockerInspect
	if err = json.Unmarshal(raw, &all); err != nil || len(all) != 1 {
		return dockerInspect{}, errors.New("inspect shape")
	}
	v := all[0]
	labels := v.Labels
	if r.kind == "container" {
		labels = v.Config.Labels
	}
	if labels["org.radishlink.sw-i5.batch"] != s.batch || labels["org.radishlink.sw-i5.sample"] != s.run || labels["org.radishlink.sw-i5.node"] != r.node {
		return v, errors.New("resource ownership mismatch")
	}
	if r.id == "" {
		expected := r.name
		if r.kind == "container" {
			expected = "/" + expected
		}
		if v.Name != expected {
			return v, errors.New("unresolved resource name mismatch")
		}
		return v, nil
	}
	if r.kind == "volume" {
		if v.Name != r.id {
			return v, errors.New("volume name mismatch")
		}
	} else if v.ID != r.id {
		return v, errors.New("resource ID mismatch")
	}
	return v, nil
}
func (s *processSample) prepare() error {
	for _, alias := range []string{"ab", "bc"} {
		args := []string{"network", "create", "--internal"}
		args = append(args, s.labelArgs("")...)
		args = append(args, s.run+"-"+alias)
		if _, err := s.resource("network", alias, "", args); err != nil {
			return err
		}
	}
	for _, node := range []string{"A", "B", "C"} {
		args := []string{"volume", "create"}
		args = append(args, s.labelArgs(node)...)
		args = append(args, s.run+"-store-"+strings.ToLower(node))
		if _, err := s.resource("volume", "store-"+node, node, args); err != nil {
			return err
		}
	}
	for _, node := range []string{"A", "B", "C"} {
		if _, err := s.resource("container", "node-"+node, node, s.containerArgs(node)); err != nil {
			return err
		}
	}
	if _, err := s.docker(s.ctx, "network", "connect", s.resourceID("bc"), s.resourceID("node-B")); err != nil {
		return err
	}
	for _, name := range []string{"A", "B", "C"} {
		peer, err := s.runner.Start(s.ctx, "docker", "start", "-ai", s.resourceID("node-"+name))
		if err != nil {
			return err
		}
		s.peers[name] = peer
	}
	addresses := map[string]harness.NetworkPeer{}
	for i := range s.resources {
		r := &s.resources[i]
		v, err := s.inspect(s.ctx, *r)
		if err == nil && r.kind == "container" {
			deadline := time.Now().Add(operationTimeout)
			for !v.State.Running && time.Now().Before(deadline) {
				select {
				case <-s.ctx.Done():
					err = s.ctx.Err()
				case <-time.After(20 * time.Millisecond):
					v, err = s.inspect(s.ctx, *r)
				}
				if err != nil {
					break
				}
			}
			if err == nil && !v.State.Running {
				err = errors.New("container start timeout")
			}
		}
		if err != nil {
			return err
		}
		f := harness.ResourceFact{Action: "ready", Kind: r.kind, Alias: r.alias, ID: r.id, Batch: s.batch, Sample: s.run, Node: r.node, Networks: []string{}}
		if r.kind == "network" && !v.Internal {
			return errors.New("network is not internal")
		}
		if r.kind == "container" {
			h := v.HostConfig
			if !h.ReadonlyRootfs || h.Privileged || !slices.Equal(h.CapDrop, []string{"ALL"}) || !slices.Contains(h.SecurityOpt, "no-new-privileges") || h.Sysctls["net.ipv4.ip_forward"] != "0" || h.RestartPolicy.Name != "no" || h.Memory != 256*1024*1024 || h.NanoCpus != 500000000 || h.PidsLimit != 64 || h.LogConfig.Type != "none" || len(h.Binds) != 0 || len(h.PortBindings) != 0 || v.Config.User != "65532:65532" {
				return errors.New("container controls mismatch")
			}
			stores := 0
			for _, mount := range v.Mounts {
				if mount.Type == "tmpfs" && mount.Destination == "/tmp" {
					continue
				}
				if mount.Type != "volume" || mount.Name != s.resourceID("store-"+r.node) || mount.Destination != "/state" || !mount.RW {
					return errors.New("container store mismatch")
				}
				stores++
			}
			if stores != 1 {
				return errors.New("container store inventory")
			}
			peer := harness.NetworkPeer{Node: r.node}
			for _, netw := range v.NetworkSettings.Networks {
				switch netw.NetworkID {
				case s.resourceID("ab"):
					f.Networks = append(f.Networks, "ab")
					peer.AB = netw.IPAddress
				case s.resourceID("bc"):
					f.Networks = append(f.Networks, "bc")
					peer.BC = netw.IPAddress
				default:
					return errors.New("extra container network")
				}
			}
			slices.Sort(f.Networks)
			want := []string{"ab"}
			if r.node == "B" {
				want = []string{"ab", "bc"}
			}
			if r.node == "C" {
				want = []string{"bc"}
			}
			if !slices.Equal(want, f.Networks) {
				return errors.New("container network inventory")
			}
			addresses[r.node] = peer
			f.Store = "store-" + r.node
			f.ReadOnly, f.NoPorts, f.NoPrivileges = true, true, true
		}
		r.fact, r.ready = f, true
		s.record("driver", "resource", 0, f)
	}
	for _, name := range []string{"A", "B", "C"} {
		s.addresses = append(s.addresses, addresses[name])
	}
	for _, name := range []string{"A", "B", "C"} {
		if _, err := s.call(name, "init", harness.NodeInit{Profile: s.profile, Subcase: s.subcase, Peers: s.addresses, Store: "store-" + name}); err != nil {
			return err
		}
	}
	for _, pair := range [][2]string{{"A", "B"}, {"B", "A"}, {"B", "C"}, {"C", "B"}, {"A", "C"}, {"C", "A"}} {
		from, to := pair[0], pair[1]
		allowed := neighbor(from, to)
		if allowed {
			if _, err := s.call(to, "probe", harness.NodeProbe{Target: from, Listen: true, Expected: true}); err != nil {
				return err
			}
		}
		if _, err := s.call(from, "probe", harness.NodeProbe{Target: to, Expected: allowed}); err != nil {
			return err
		}
		if allowed {
			if _, err := s.call(to, "drain", struct{}{}); err != nil {
				return err
			}
		}
	}
	clock, clockErr := harness.NewTestClock(time.Unix(0, 0).UTC())
	if clockErr != nil {
		return clockErr
	}
	if _, err := clock.Advance(0); err != nil {
		return err
	}
	logical, _, _ := clock.Snapshot()
	if logical != 0 {
		return errors.New("clock preflight")
	}
	for _, x := range s.execution {
		var decoded harness.ExecutionEvent
		if err := harness.CanonicalJSON(rawDetail(x), &decoded, 256*1024); err != nil {
			return err
		}
	}
	for _, check := range []harness.EnvironmentDetail{{ID: "routing", Passed: true, Reason: "numeric_tcp_probes"}, {ID: "clock", Passed: true, Reason: "supervisor_clock"}, {ID: "recorder", Passed: true, Reason: "strict_execution_records"}} {
		ref := s.record("driver", "environment_check", 0, check)
		s.semantic("driver", "environment_check", 0, 0, 0, "", check, ref)
	}
	return s.err
}
func scenarioNext(now int64, snapshots map[string]harness.ObservedState, pendingTimes []int64, downAt, upAt int64) int64 {
	next := int64(30000)
	for _, at := range pendingTimes {
		if at > now {
			next = min(next, at)
		}
	}
	for _, st := range snapshots {
		for _, q := range st.Queues {
			if q.Status != "active" {
				continue
			}
			for _, offset := range []int64{0, 250, 750, 1750, 3750} {
				at := max(int64(1), q.Start+offset)
				if at > now {
					next = min(next, at)
				}
			}
		}
	}
	if downAt >= 0 && upAt < 0 {
		next = min(next, downAt+5000)
	}
	return next
}
func scenarioDue(now int64, st harness.ObservedState) bool {
	if now == 30000 {
		return true
	}
	for _, q := range st.Queues {
		if q.Status == "active" {
			for _, offset := range []int64{0, 250, 750, 1750, 3750} {
				if max(int64(1), q.Start+offset) == now {
					return true
				}
			}
		}
	}
	return false
}
func (s *processSample) drive() error {
	if _, err := s.call("A", "submit_fixture", struct{}{}); err != nil {
		return err
	}
	clock, err := harness.NewTestClock(time.Unix(0, 0).UTC())
	if err != nil {
		return err
	}
	downAt, upAt := int64(-1), int64(-1)
	for tick := 0; tick < 512; tick++ {
		pendingTimes := []int64{}
		for _, p := range s.pending {
			pendingTimes = append(pendingTimes, p.at)
		}
		next := scenarioNext(s.now, s.snapshots, pendingTimes, downAt, upAt)
		if next <= s.now {
			return errors.New("clock stalled")
		}
		if _, err = clock.Advance(time.Duration(next-s.now) * time.Millisecond); err != nil {
			return err
		}
		s.now, _, _ = clock.Snapshot()
		for _, node := range []string{"A", "B", "C"} {
			d := harness.NodeStep{Inputs: []string{}, Links: []harness.ControlLink{}}
			for id, p := range s.pending {
				if p.at == s.now && p.node == node {
					d.Inputs = append(d.Inputs, id)
				}
			}
			slices.Sort(d.Inputs)
			due := len(d.Inputs) > 0 || scenarioDue(s.now, s.snapshots[node])
			target := ""
			if s.profile.Fault.Kind == "down" && downAt < 0 {
				if s.profile.Fault.Direction == "a-to-b" && node == "A" && s.now == 1 {
					target = "B"
				}
				if s.profile.Fault.Direction == "b-to-c" && node == "B" && len(d.Inputs) > 0 && len(s.snapshots[node].Messages) == 0 {
					target = "C"
				}
				if target != "" {
					downAt = s.now
					d.Links = append(d.Links, harness.ControlLink{Neighbor: target, Event: "became_down"})
					due = true
				}
			}
			if downAt >= 0 && upAt < 0 && s.now == downAt+5000 && (node == "A" && s.profile.Fault.Direction == "a-to-b" || node == "B" && s.profile.Fault.Direction == "b-to-c") {
				target = "B"
				if node == "B" {
					target = "C"
				}
				d.Links = append(d.Links, harness.ControlLink{Neighbor: target, Event: "became_up"})
				upAt = s.now
				due = true
			}
			if !due {
				continue
			}
			r, err := s.call(node, "step", d)
			if err != nil {
				return err
			}
			for _, h := range r.Result.Sends {
				id := transferID(node, r.Generation, h.Index)
				dir := scenarioDirection(node, h.Neighbor)
				s.ordinals[dir]++
				ordinal := s.ordinals[dir]
				if _, err = s.call(h.Neighbor, "arm_receive", harness.ReceivePermit{ID: id, Sender: node, Generation: r.Generation, Index: h.Index, Ordinal: ordinal}); err != nil {
					return err
				}
				if _, err = s.call(node, "send", harness.NodeSend{ID: id, Index: h.Index, Ordinal: ordinal}); err != nil {
					return err
				}
				if _, err = s.call(h.Neighbor, "drain", struct{}{}); err != nil {
					return err
				}
			}
		}
		if s.now == 30000 {
			var remaining int64
			for _, state := range s.snapshots {
				for _, m := range state.Messages {
					if m.Transport {
						remaining++
					}
				}
			}
			end := harness.EndDetail{Now: s.now, Remaining: remaining, Pending: int64(len(s.pending)), Reason: "window_complete"}
			ref := s.record("driver", "observation_end", 0, end)
			s.semantic("driver", "observation_end", 0, 0, 0, "", end, ref)
			return s.err
		}
	}
	return errors.New("scenario tick cap")
}
func (s *processSample) cleanup() (harness.NetworkResiduals, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	var result error
	active := int64(0)
	for _, name := range []string{"A", "B", "C"} {
		if p := s.peers[name]; p != nil {
			if s.now == 30000 && s.err == nil {
				_, err := s.call(name, "shutdown", struct{}{})
				result = errors.Join(result, err)
			}
			if err := p.Close(); err != nil {
				result = errors.Join(result, err)
				active++
			}
		}
	}
	removed := []harness.ResourceFact{}
	for _, kind := range []string{"container", "network", "volume"} {
		for _, r := range s.resources {
			if r.kind != kind {
				continue
			}
			observed, err := s.inspect(ctx, r)
			if err == nil && r.id == "" {
				r.id = observed.ID
				if r.kind == "volume" {
					r.id = observed.Name
				}
				if r.id == "" {
					err = errors.New("cleanup could not resolve resource ID")
				}
			}
			if err == nil {
				args := []string{"rm", "-f", r.id}
				if kind != "container" {
					args = []string{kind, "rm", r.id}
				}
				_, err = s.docker(ctx, args...)
			}
			f := r.fact
			if !r.ready {
				f = harness.ResourceFact{Kind: r.kind, ID: r.id, Alias: r.alias, Batch: s.batch, Sample: s.run, Node: r.node, Networks: []string{}}
			}
			f.Action = "removed"
			if err != nil {
				f.Error = "cleanup_failed"
				result = errors.Join(result, err)
			}
			s.record("driver", "resource", 0, f)
			removed = append(removed, f)
		}
	}
	for _, kind := range []string{"container", "network", "volume"} {
		args := []string{"ps", "-aq", "--filter", "label=org.radishlink.sw-i5.sample=" + s.run}
		if kind != "container" {
			args = []string{kind, "ls", "-q", "--filter", "label=org.radishlink.sw-i5.sample=" + s.run}
		}
		raw, err := s.docker(ctx, args...)
		if err != nil || len(bytes.TrimSpace(raw)) != 0 {
			result = errors.Join(result, err, fmt.Errorf("%s residual inventory incomplete", kind))
		}
	}
	slices.SortFunc(removed, func(a, b harness.ResourceFact) int { return strings.Compare(a.Alias, b.Alias) })
	complete := len(s.resources) == 8 && result == nil
	for _, r := range s.resources {
		complete = complete && r.ready
	}
	res := harness.NetworkResiduals{Schema: 3, Complete: complete, Resources: removed, Pending: int64(len(s.pending)), Children: active, Connections: 0, Clean: result == nil && complete && len(s.pending) == 0}
	return res, result
}
func (s *processSample) bundle(m harness.NetworkManifest, res harness.NetworkResiduals) harness.NetworkBundle {
	refs := []int64{}
	for _, x := range s.execution {
		if x.Kind != "exchange" {
			continue
		}
		var ex harness.ControlExchange
		json.Unmarshal(x.Detail, &ex)
		for _, f := range ex.Response.Result.Facts {
			if f.Kind == "probe" {
				var p harness.ProbeFact
				json.Unmarshal(f.Detail, &p)
				if !p.Received {
					refs = append(refs, x.Sequence)
				}
			}
		}
	}
	return harness.NetworkBundle{Profile: s.profile, Manifest: m, Topology: harness.NetworkTopology{Schema: 3, Mode: harness.NetworkMode, Topology: harness.CanonicalTopology, Peers: s.addresses, Sources: refs}, Events: s.events, Execution: s.execution, Residuals: res}
}
