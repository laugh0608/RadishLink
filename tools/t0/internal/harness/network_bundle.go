package harness

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"time"
)

var networkFiles = []string{"assertions.json", "events.ndjson", "execution.ndjson", "manifest.json", "metrics.json", "profile.json", "residuals.json", "topology.json"}

func encodeNetworkLines[T any](items []T, lineCap, totalCap int) ([]byte, error) {
	var out bytes.Buffer
	for _, v := range items {
		b, err := canonicalFile(v)
		if err != nil {
			return nil, err
		}
		if len(b) > lineCap+1 || out.Len()+len(b) > totalCap {
			return nil, errors.New("network line/file limit")
		}
		out.Write(b)
	}
	return out.Bytes(), nil
}
func decodeNetworkLines[T any](raw []byte, lineCap, totalCap int) ([]T, error) {
	if len(raw) == 0 || len(raw) > totalCap || raw[len(raw)-1] != '\n' {
		return nil, errors.New("network NDJSON bounds")
	}
	lines := bytes.Split(raw[:len(raw)-1], []byte{'\n'})
	if len(lines) > 8192 {
		return nil, errors.New("network line count")
	}
	out := make([]T, len(lines))
	for i, line := range lines {
		if err := CanonicalJSON(line, &out[i], lineCap); err != nil {
			return nil, err
		}
	}
	return out, nil
}
func checkNetworkManifest(p NetworkProfile, m NetworkManifest) error {
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
	if end.Before(start) || !strings.HasSuffix(m.Started, "Z") || !strings.HasSuffix(m.Ended, "Z") || m.Schema != 3 || m.Observation != 1 || m.ProfileID != p.ID || m.ProfileVersion != p.Version || m.Seed != p.Seed || m.Variant != NetworkVariant || m.Mode != NetworkMode || m.Security != "synthetic" || m.Topology != CanonicalTopology || m.Size != sub.Size || m.Count != 1 || m.Window != 30000 || m.Control != 1 || m.Transport != NetworkTransport || m.FaultLayer != NetworkFaultLayer || m.Repeat < 1 || m.Repeat > 3 {
		return errors.New("network manifest contract")
	}
	if !validHexDigest(m.HostBinary, 64) || !validHexDigest(m.NodeBinary, 64) || !validHexDigest(m.Contract, 64) || !validHexDigest(m.GitRevision, 40, 64) || m.Dirty || !validHexDigest(strings.TrimPrefix(m.Image, "sha256:"), 64) || !validHexDigest(m.ProfileHash, 64) || !validHexDigest(m.EventsHash, 64) || !validHexDigest(m.ExecutionHash, 64) || m.Batch == "" || m.Run == "" || m.Evidence != fmt.Sprintf("%s/%s/%s/%d", m.Batch, p.ID, m.Subcase, m.Repeat) || m.DockerClient == "" || m.DockerServer == "" || m.GoVersion == "" || m.OS == "" || m.Arch == "" || m.DaemonOS != "linux" || !slices.Contains([]string{"amd64", "arm64"}, m.DaemonArch) {
		return errors.New("network manifest metadata")
	}
	want, err := NetworkProfiles()
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(want, m.Profiles) {
		return errors.New("network profile set binding")
	}
	code, ok := map[string]int64{"PASS": 0, "FAIL": 1, "INVALID": 2}[m.Result]
	if !ok || m.Exit != code {
		return errors.New("network result code")
	}
	return nil
}
func WriteNetworkBundle(root string, b NetworkBundle) error {
	metrics, assertions, result, err := AssessNetwork(b)
	if err != nil {
		return err
	}
	events, err := encodeNetworkLines(b.Events, 16*1024, 4*1024*1024)
	if err != nil {
		return err
	}
	execution, err := encodeNetworkLines(b.Execution, controlMax, 16*1024*1024)
	if err != nil {
		return err
	}
	profile, err := canonicalFile(b.Profile)
	if err != nil {
		return err
	}
	m := &b.Manifest
	m.Schema, m.Observation = 3, 1
	m.ProfileHash = scenarioDigest(profile)
	m.EventsHash = scenarioDigest(events)
	m.ExecutionHash = scenarioDigest(execution)
	m.Result = result
	m.Exit = map[string]int64{"PASS": 0, "FAIL": 1, "INVALID": 2}[result]
	if err = checkNetworkManifest(b.Profile, *m); err != nil {
		return err
	}
	files := map[string][]byte{"profile.json": profile, "events.ndjson": events, "execution.ndjson": execution}
	values := map[string]any{"manifest.json": *m, "topology.json": b.Topology, "metrics.json": metrics, "assertions.json": assertions, "residuals.json": b.Residuals}
	total := len(profile) + len(events) + len(execution)
	for name, v := range values {
		raw, err := canonicalFile(v)
		if err != nil {
			return err
		}
		if len(raw) > 4*1024*1024 {
			return errors.New("network JSON cap")
		}
		total += len(raw)
		files[name] = raw
	}
	if total > 32*1024*1024 {
		return errors.New("network bundle cap")
	}
	if err = prepareEvidenceRoot(root); err != nil {
		return err
	}
	for _, name := range networkFiles {
		limit := MaxEvidenceFileBytes
		if name == "execution.ndjson" {
			limit = 16 * 1024 * 1024
		}
		if err = atomicWriteEvidenceFileLimit(root, name, files[name], limit); err != nil {
			return err
		}
	}
	return finalizeNetwork(root)
}
func networkInventory(root string, checksum bool) (map[string][]byte, error) {
	if err := inspectEvidenceRoot(root); err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	allowed := append(slices.Clone(networkFiles), "logs", "checksums.sha256")
	for _, e := range entries {
		if !slices.Contains(allowed, e.Name()) {
			return nil, errors.New("extra network evidence file")
		}
	}
	logs, err := os.ReadDir(filepath.Join(root, "logs"))
	if err != nil || len(logs) != 0 {
		return nil, errors.New("network logs inventory")
	}
	files := map[string][]byte{}
	var total int64
	for _, name := range networkFiles {
		path, err := resolveRegularFile(root, name)
		if err != nil {
			return nil, err
		}
		info, err := os.Stat(path)
		if err != nil {
			return nil, err
		}
		cap := int64(4 * 1024 * 1024)
		if name == "execution.ndjson" {
			cap = 16 * 1024 * 1024
		}
		if info.Size() > cap {
			return nil, errors.New("network file cap")
		}
		f, err := os.Open(path)
		if err != nil {
			return nil, err
		}
		raw, readErr := io.ReadAll(io.LimitReader(f, cap+1))
		err = errors.Join(readErr, f.Close())
		if err != nil {
			return nil, err
		}
		if int64(len(raw)) > cap {
			return nil, errors.New("network file grew beyond cap")
		}
		total += int64(len(raw))
		if total > 32*1024*1024 {
			return nil, errors.New("network bundle cap")
		}
		files[name] = raw
	}
	if checksum {
		raw, err := readEvidenceFile(root, "checksums.sha256")
		if err != nil {
			return nil, err
		}
		checks, err := parseChecksums(raw)
		if err != nil || len(checks) != len(networkFiles) {
			return nil, errors.New("network checksum inventory")
		}
		for name, raw := range files {
			if checks[name] != scenarioDigest(raw) {
				return nil, errors.New("network checksum mismatch")
			}
		}
	}
	return files, nil
}
func readNetwork(root string, checksum bool) (NetworkBundle, NetworkMetrics, ScenarioAssertions, error) {
	var b NetworkBundle
	var metrics NetworkMetrics
	var a ScenarioAssertions
	files, err := networkInventory(root, checksum)
	if err != nil {
		return b, metrics, a, err
	}
	for _, v := range []struct {
		name  string
		value any
	}{{"profile.json", &b.Profile}, {"manifest.json", &b.Manifest}, {"topology.json", &b.Topology}, {"residuals.json", &b.Residuals}, {"metrics.json", &metrics}, {"assertions.json", &a}} {
		if err = decodeScenarioFile(files[v.name], v.value); err != nil {
			return b, metrics, a, err
		}
	}
	b.Events, err = decodeNetworkLines[NetworkEvent](files["events.ndjson"], 16*1024, 4*1024*1024)
	if err != nil {
		return b, metrics, a, err
	}
	b.Execution, err = decodeNetworkLines[ExecutionEvent](files["execution.ndjson"], controlMax, 16*1024*1024)
	if err != nil {
		return b, metrics, a, err
	}
	if b.Manifest.ProfileHash != scenarioDigest(files["profile.json"]) || b.Manifest.EventsHash != scenarioDigest(files["events.ndjson"]) || b.Manifest.ExecutionHash != scenarioDigest(files["execution.ndjson"]) {
		return b, metrics, a, errors.New("network manifest hashes")
	}
	return b, metrics, a, nil
}
func verifyNetwork(root string, checksum bool) (NetworkManifest, error) {
	b, m, a, err := readNetwork(root, checksum)
	if err != nil {
		return b.Manifest, err
	}
	if err = checkNetworkManifest(b.Profile, b.Manifest); err != nil {
		return b.Manifest, err
	}
	want, assertions, result, err := AssessNetwork(b)
	if err != nil {
		return b.Manifest, err
	}
	if !reflect.DeepEqual(want, m) || !reflect.DeepEqual(assertions, a) || result != b.Manifest.Result {
		return b.Manifest, errors.New("network derived result mismatch")
	}
	return b.Manifest, nil
}
func finalizeNetwork(root string) error {
	if _, err := verifyNetwork(root, false); err != nil {
		return err
	}
	files, err := networkInventory(root, false)
	if err != nil {
		return err
	}
	var out bytes.Buffer
	for _, name := range networkFiles {
		fmt.Fprintf(&out, "%s  %s\n", scenarioDigest(files[name]), name)
	}
	return atomicWriteEvidenceFile(root, "checksums.sha256", out.Bytes())
}
func networkProjection(b NetworkBundle) ([]byte, error) {
	// All raw sources were validated before this explicit, typed normalization.
	ip := map[string]string{}
	for _, p := range b.Topology.Peers {
		if p.AB != "" {
			ip[p.AB] = p.Node + "-ab"
		}
		if p.BC != "" {
			ip[p.BC] = p.Node + "-bc"
		}
	}
	events := make([]ScenarioEvent, len(b.Events))
	for i, e := range b.Events {
		events[i] = e.ScenarioEvent
	}
	execution := slices.Clone(b.Execution)
	for i := range execution {
		x := &execution[i]
		switch x.Kind {
		case "resource":
			v, _ := networkDetail[ResourceFact](x.Detail)
			v.ID = v.Alias
			v.Sample = "sample"
			x.Detail, _ = json.Marshal(v)
		case "exchange":
			v, _ := networkDetail[ControlExchange](x.Detail)
			v.Request.Session, v.Response.Session = "sample", "sample"
			v.Request.Epoch, v.Response.Epoch = "epoch", "epoch"
			if v.Request.Operation == "init" {
				d, _ := networkDetail[NodeInit](v.Request.Detail)
				for j := range d.Peers {
					d.Peers[j].AB = ip[d.Peers[j].AB]
					d.Peers[j].BC = ip[d.Peers[j].BC]
				}
				v.Request.Detail, _ = json.Marshal(d)
			}
			for j := range v.Response.Result.Facts {
				f := &v.Response.Result.Facts[j]
				switch f.Kind {
				case "node_environment":
					d, _ := networkDetail[NodeEnvironment](f.Detail)
					d.Epoch = "epoch"
					d.Routes = "route-diagnostic"
					for k := range d.Interfaces {
						d.Interfaces[k] = ip[d.Interfaces[k]]
					}
					slices.Sort(d.Interfaces)
					f.Detail, _ = json.Marshal(d)
				case "probe":
					d, _ := networkDetail[ProbeFact](f.Detail)
					for addr, alias := range ip {
						if d.Address == addr+":7000" {
							d.Address = alias + ":7000"
						}
					}
					f.Detail, _ = json.Marshal(d)
				case "socket_written", "transport_ingress":
					d, _ := networkDetail[TransportFact](f.Detail)
					d.Elapsed = 0
					f.Detail, _ = json.Marshal(d)
				}
			}
			x.Detail, _ = json.Marshal(v)
		}
	}
	return json.Marshal(struct {
		Events    []ScenarioEvent
		Execution []ExecutionEvent
	}{events, execution})
}
func compareNetworks(root string) (string, error) {
	info, err := os.Lstat(root)
	if err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return "", errors.New("network comparison root")
	}
	entries, err := os.ReadDir(root)
	if err != nil {
		return "", err
	}
	if len(entries) != 3 {
		return "", errors.New("network comparison count")
	}
	for _, e := range entries {
		if !e.IsDir() || !slices.Contains([]string{"1", "2", "3"}, e.Name()) {
			return "", errors.New("network repeat directory")
		}
	}
	runs := map[string]bool{}
	var first NetworkManifest
	var reference []byte
	for i := 1; i <= 3; i++ {
		path := filepath.Join(root, fmt.Sprint(i))
		version, err := bundleSchema(path)
		if err != nil || version != 3 {
			return "", errors.New("network mixed versions")
		}
		m, err := verifyNetwork(path, true)
		if err != nil {
			return "", err
		}
		if m.Repeat != int64(i) || m.Result != "PASS" || runs[m.Run] {
			return "", errors.New("network repeat identity/result")
		}
		runs[m.Run] = true
		b, _, _, err := readNetwork(path, true)
		if err != nil {
			return "", err
		}
		projection, err := networkProjection(b)
		if err != nil {
			return "", err
		}
		m.Run = "sample"
		m.Repeat = 0
		m.Evidence = ""
		m.Started = ""
		m.Ended = ""
		m.EventsHash = ""
		m.ExecutionHash = ""
		if i == 1 {
			first = m
			reference = projection
		} else if !reflect.DeepEqual(first, m) || !bytes.Equal(reference, projection) {
			return "", errors.New("network repeats differ")
		}
	}
	return scenarioDigest(reference), nil
}
