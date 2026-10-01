package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"radishlink.local/t0/internal/harness"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"time"
)

type dockerVersion struct {
	Client struct{ Version string }
	Server struct{ Version, Os, Arch string }
}
type networkPreflight struct {
	Revision, GoVersion, OS, Arch string
	Docker                        dockerVersion
	Profiles                      []harness.ProfileBinding
	Contract                      string
}

func preflightNetwork(ctx context.Context, r processRunner, root string) (networkPreflight, error) {
	var p networkPreflight
	raw, err := r.Run(ctx, "git", "-C", root, "status", "--porcelain")
	if err != nil {
		return p, err
	}
	if len(bytes.TrimSpace(raw)) != 0 {
		return p, errors.New("I5 run requires a clean source tree")
	}
	raw, err = r.Run(ctx, "git", "-C", root, "rev-parse", "HEAD")
	if err != nil {
		return p, err
	}
	p.Revision = strings.TrimSpace(string(raw))
	if len(p.Revision) != 40 && len(p.Revision) != 64 {
		return p, errors.New("git revision")
	}
	raw, err = r.Run(ctx, "go", "version")
	if err != nil {
		return p, err
	}
	p.GoVersion = strings.TrimSpace(string(raw))
	p.OS, p.Arch = runtime.GOOS, runtime.GOARCH
	endpoint := os.Getenv("DOCKER_HOST")
	if endpoint == "" || os.Getenv("DOCKER_CONTEXT") != "" {
		raw, err = r.Run(ctx, "docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}")
		if err != nil {
			return p, err
		}
		if err = json.Unmarshal(bytes.TrimSpace(raw), &endpoint); err != nil {
			return p, err
		}
	}
	if !strings.HasPrefix(endpoint, "unix://") {
		return p, errors.New("I5 requires a local Unix Docker endpoint")
	}
	raw, err = r.Run(ctx, "docker", "version", "--format", "{{json .}}")
	if err != nil {
		return p, err
	}
	if err = json.Unmarshal(raw, &p.Docker); err != nil {
		return p, err
	}
	if p.Docker.Server.Os != "linux" || !slices.Contains([]string{"amd64", "arm64"}, p.Docker.Server.Arch) || p.Docker.Server.Version == "" || p.Docker.Client.Version == "" {
		return p, errors.New("unsupported Docker daemon")
	}
	raw, err = r.Run(ctx, "df", "-Pk", root)
	if err != nil {
		return p, err
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	if len(lines) < 2 {
		return p, errors.New("disk inventory")
	}
	fields := strings.Fields(lines[len(lines)-1])
	if len(fields) < 4 {
		return p, errors.New("disk inventory columns")
	}
	free, err := strconv.ParseInt(fields[3], 10, 64)
	if err != nil || free < 1024*1024 {
		return p, errors.New("less than 1 GiB free disk")
	}
	p.Profiles, err = harness.NetworkProfiles()
	if err != nil {
		return p, err
	}
	for _, binding := range p.Profiles {
		file := strings.ToLower(binding.ID) + ".json"
		_, raw, err := harness.LoadNetworkProfile(filepath.Join(root, "tools/t0/profiles/i5"), file)
		if err != nil {
			return p, err
		}
		if scenarioHash(raw) != binding.Hash {
			return p, errors.New("profile file hash")
		}
	}
	raw, err = os.ReadFile(filepath.Join(root, "docs/testing/sw-g4-synthetic-i5-plan.md"))
	if err != nil {
		return p, err
	}
	p.Contract = scenarioHash(raw)
	return p, nil
}
func freshID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}
func writeNewJSON(path string, v any) error {
	raw, err := json.Marshal(v)
	if err != nil {
		return err
	}
	if len(raw) > 32*1024*1024 {
		return errors.New("artifact limit")
	}
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	_, e := f.Write(append(raw, '\n'))
	return errors.Join(e, f.Close())
}
func pathBytes(root string) (int64, error) {
	var total int64
	err := filepath.WalkDir(root, func(path string, e os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.Type()&os.ModeSymlink != 0 {
			return errors.New("artifact symlink")
		}
		if !e.IsDir() {
			i, err := e.Info()
			if err != nil {
				return err
			}
			total += i.Size()
			if total > 768*1024*1024 {
				return errors.New("batch disk cap")
			}
		}
		return nil
	})
	return total, err
}
func monitorNetwork(ctx context.Context, r processRunner, root string) error {
	raw, err := r.Run(ctx, "ps", "-o", "rss=", "-p", strconv.Itoa(os.Getpid()))
	if err != nil {
		return err
	}
	rss, err := strconv.ParseInt(strings.TrimSpace(string(raw)), 10, 64)
	if err != nil || rss > 256*1024 {
		return errors.New("supervisor RSS limit")
	}
	_, err = pathBytes(root)
	return err
}

type networkExit struct {
	code int
	err  error
}

func (e *networkExit) Error() string { return e.err.Error() }
func (e *networkExit) Unwrap() error { return e.err }
func runSyntheticSupervisor(args []string) error {
	flags := flag.NewFlagSet("synthetic-run", flag.ContinueOnError)
	root := flags.String("repo-root", "", "repository root")
	inventoryOnly := flags.Bool("preflight", false, "prepare only; no Docker mutations")
	matrix := flags.String("matrix", "", "fixed matrix")
	repeats := flags.Int("repeats", 0, "exactly three repeats")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if flags.NArg() != 0 || *root == "" || (!*inventoryOnly && (*matrix != "i5-seven-v1" || *repeats != 3)) || (*inventoryOnly && (*matrix != "" || *repeats != 0)) {
		return errors.New("synthetic-run requires repo-root, i5-seven-v1 and three repeats")
	}
	if err := requireNetworkResourceIsolation(); err != nil {
		return err
	}
	resolved, err := filepath.EvalSymlinks(*root)
	if err != nil || !filepath.IsAbs(resolved) {
		return errors.New("repository root")
	}
	if *inventoryOnly {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		p, err := preflightNetwork(ctx, osProcessRunner{}, resolved)
		if err != nil {
			return &networkExit{2, err}
		}
		return json.NewEncoder(os.Stdout).Encode(p)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Minute)
	defer cancel()
	err = runNetworkMatrix(ctx, osProcessRunner{}, resolved)
	var classified *networkExit
	if err != nil && !errors.As(err, &classified) {
		return &networkExit{2, err}
	}
	return err
}
func runNetworkMatrix(ctx context.Context, r processRunner, root string) (runErr error) {
	if err := requireNetworkResourceIsolation(); err != nil {
		return err
	}
	preCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	p, err := preflightNetwork(preCtx, r, root)
	cancel()
	if err != nil {
		return &networkExit{2, err}
	}
	nonce, err := freshID()
	if err != nil {
		return err
	}
	batch := "i5-" + nonce
	artifact := filepath.Join(root, "artifacts/sw-v", batch)
	if err = os.MkdirAll(filepath.Dir(artifact), 0700); err != nil {
		return err
	}
	if err = os.Mkdir(artifact, 0700); err != nil {
		return err
	}
	build := filepath.Join(artifact, "build")
	if err = os.Mkdir(build, 0700); err != nil {
		return err
	}
	nodePath := filepath.Join(build, "sw-v0-harness")
	raw, err := os.ReadFile(filepath.Join(root, "tools/t0/Dockerfile.i5"))
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(build, "Dockerfile"), raw, 0600); err != nil {
		return err
	}
	if err = os.Mkdir(filepath.Join(build, "state"), 0700); err != nil {
		return err
	}
	if err = os.Mkdir(filepath.Join(build, "profiles"), 0700); err != nil {
		return err
	}
	for _, binding := range p.Profiles {
		file := strings.ToLower(binding.ID) + ".json"
		raw, err := os.ReadFile(filepath.Join(root, "tools/t0/profiles/i5", file))
		if err != nil {
			return err
		}
		if err = os.WriteFile(filepath.Join(build, "profiles", file), raw, 0600); err != nil {
			return err
		}
	}
	buildCtx, buildCancel := context.WithTimeout(ctx, 5*time.Minute)
	_, err = r.Run(buildCtx, "env", "GOTOOLCHAIN=local", "GOPROXY=off", "GOSUMDB=off", "CGO_ENABLED=0", "GOOS=linux", "GOARCH="+p.Docker.Server.Arch, "go", "-C", filepath.Join(root, "tools/t0"), "build", "-trimpath", "-o", nodePath, "./cmd/sw-v0-harness")
	buildCancel()
	if err != nil {
		return err
	}
	status, err := r.Run(ctx, "git", "-C", root, "status", "--porcelain")
	if err != nil || len(bytes.TrimSpace(status)) != 0 {
		return errors.Join(err, errors.New("source changed during build"))
	}
	head, err := r.Run(ctx, "git", "-C", root, "rev-parse", "HEAD")
	if err != nil || strings.TrimSpace(string(head)) != p.Revision {
		return errors.Join(err, errors.New("revision changed during build"))
	}
	nodeBytes, err := os.ReadFile(nodePath)
	if err != nil {
		return err
	}
	nodeHash := scenarioHash(nodeBytes)
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	hostBytes, err := os.ReadFile(executable)
	if err != nil {
		return err
	}
	hostHash := scenarioHash(hostBytes)
	nodeBytes, hostBytes = nil, nil
	imageTag := "radishlink/i5:" + nonce
	image := ""
	var sampleCount int
	batchResult := "INVALID"
	defer func() {
		cleanupCtx, stop := context.WithTimeout(context.Background(), 60*time.Second)
		defer stop()
		imageRemoved := false
		if image == "" {
			if raw, err := os.ReadFile(filepath.Join(build, "image-id")); err == nil {
				candidate := strings.TrimSpace(string(raw))
				if strings.HasPrefix(candidate, "sha256:") && len(candidate) == 71 {
					image = candidate
				}
			}
		}
		if image != "" {
			raw, e := r.Run(cleanupCtx, "docker", "image", "inspect", "--format", "{{ index .Config.Labels \"org.radishlink.sw-i5.batch\" }}", image)
			if e == nil && strings.TrimSpace(string(raw)) == batch {
				_, e = r.Run(cleanupCtx, "docker", "image", "rm", image)
				imageRemoved = e == nil
			} else if e == nil {
				e = errors.New("image label mismatch")
			}
			if e != nil {
				runErr = &networkExit{2, errors.Join(runErr, e)}
			}
		}
		if !imageRemoved {
			batchResult = "INVALID"
		}
		if runErr != nil {
			batchResult = "INVALID"
			var classified *networkExit
			if imageRemoved && errors.As(runErr, &classified) && classified.code == 1 {
				batchResult = "FAIL"
			}
		}
		e := writeNewJSON(filepath.Join(artifact, "batch-result.json"), struct {
			Batch, Result    string
			CompletedSamples int
			ImageID          string
			ImageRemoved     bool
			Error            string
		}{batch, batchResult, sampleCount, image, imageRemoved, fmt.Sprint(runErr)})
		runErr = errors.Join(runErr, e)
	}()
	buildCtx, buildCancel = context.WithTimeout(ctx, 5*time.Minute)
	_, err = r.Run(buildCtx, "docker", "build", "--network=none", "--pull=false", "--label", "org.radishlink.sw-i5.batch="+batch, "--iidfile", filepath.Join(build, "image-id"), "--tag", imageTag, build)
	buildCancel()
	if err != nil {
		return err
	}
	raw, err = os.ReadFile(filepath.Join(build, "image-id"))
	if err != nil {
		return err
	}
	image = strings.TrimSpace(string(raw))
	if !strings.HasPrefix(image, "sha256:") || len(image) != 71 {
		return errors.New("image ID")
	}
	for _, binding := range p.Profiles {
		profile, err := harness.CanonicalNetwork(binding.ID)
		if err != nil {
			return err
		}
		for _, sub := range profile.Subcases {
			group := filepath.Join(artifact, binding.ID, sub.ID)
			if err = os.MkdirAll(group, 0700); err != nil {
				return err
			}
			for repeat := 1; repeat <= 3; repeat++ {
				if err = monitorNetwork(ctx, r, artifact); err != nil {
					return err
				}
				epoch, err := freshID()
				if err != nil {
					return err
				}
				run := fmt.Sprintf("%s-%02d", batch, sampleCount+1)
				started := time.Now().UTC().Format(time.RFC3339Nano)
				sampleCtx, sampleCancel := context.WithTimeout(ctx, 120*time.Second)
				s := newProcessSample(sampleCtx, r, profile, sub.ID, batch, run, epoch, image)
				lastBudgetCheck := time.Time{}
				s.guard = func() error {
					if time.Since(lastBudgetCheck) < 250*time.Millisecond {
						return nil
					}
					lastBudgetCheck = time.Now()
					checkCtx, done := context.WithTimeout(sampleCtx, operationTimeout)
					defer done()
					if err := monitorNetwork(checkCtx, r, artifact); err != nil {
						return err
					}
					used, err := pathBytes(artifact)
					if err != nil {
						return err
					}
					for _, size := range s.storeUsage {
						used += size
					}
					if used > 768*1024*1024 {
						return errors.New("batch plus volume cap")
					}
					return nil
				}
				callErr := s.prepare()
				if callErr == nil {
					callErr = s.drive()
				}
				if callErr != nil {
					abort := harness.AbortDetail{Now: s.now, Stage: "process_scenario", Error: "EXECUTION", Reason: "sample_stopped"}
					ref := s.record("driver", "execution_aborted", 0, abort)
					s.semantic("driver", "execution_aborted", 0, 0, 0, "", abort, ref)
				}
				s.guard = nil
				residuals, cleanupErr := s.cleanup()
				sampleCancel()
				callErr = errors.Join(callErr, cleanupErr, s.err)
				m := harness.NetworkManifest{Schema: 3, Observation: 1, Batch: batch, Run: run, Evidence: fmt.Sprintf("%s/%s/%s/%d", batch, profile.ID, sub.ID, repeat), Repeat: int64(repeat), ProfileID: profile.ID, ProfileVersion: profile.Version, Seed: profile.Seed, Variant: profile.Variant, Subcase: sub.ID, Mode: profile.Mode, Security: profile.Security, GitRevision: p.Revision, GoVersion: p.GoVersion, OS: p.OS, Arch: p.Arch, Started: started, Ended: time.Now().UTC().Format(time.RFC3339Nano), Topology: profile.Topology, Size: sub.Size, Count: 1, Window: 30000, Control: 1, Transport: harness.NetworkTransport, FaultLayer: harness.NetworkFaultLayer, HostBinary: hostHash, NodeBinary: nodeHash, Image: image, DockerClient: p.Docker.Client.Version, DockerServer: p.Docker.Server.Version, DaemonOS: p.Docker.Server.Os, DaemonArch: p.Docker.Server.Arch, Contract: p.Contract, Profiles: p.Profiles}
				b := s.bundle(m, residuals)
				dest := filepath.Join(group, strconv.Itoa(repeat))
				if callErr != nil {
					e := writeNewJSON(filepath.Join(artifact, run+"-incomplete.json"), struct {
						Error  string
						Bundle harness.NetworkBundle
					}{callErr.Error(), b})
					return &networkExit{2, errors.Join(callErr, e)}
				}
				if err = harness.WriteNetworkBundle(dest, b); err != nil {
					e := writeNewJSON(filepath.Join(artifact, run+"-rejected.json"), struct {
						Error  string
						Bundle harness.NetworkBundle
					}{err.Error(), b})
					return &networkExit{2, errors.Join(err, e)}
				}
				_, _, result, err := harness.AssessNetwork(b)
				if err != nil {
					return err
				}
				sampleCount++
				if result != "PASS" {
					code := 2
					if result == "FAIL" {
						code = 1
					}
					return &networkExit{code, fmt.Errorf("sample %s: %s", run, result)}
				}
			}
			if _, err = harness.CompareEvidenceRuns(group); err != nil {
				return err
			}
		}
	}
	batchResult = "PASS"
	return nil
}
