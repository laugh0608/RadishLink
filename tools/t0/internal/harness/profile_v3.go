package harness

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"os"
)

const NetworkMode = "docker-tcp-i3"
const NetworkVariant = "i3-small4-tcp-v1"
const NetworkTransport = "tcp-one-frame-v1"
const NetworkFaultLayer = "receiver-drop-or-sender-link-gate"

// NetworkProfile has its own strict decoder; embedding shares fields, not acceptance rules.
type NetworkProfile struct {
	ScenarioProfile
	Control    int64  `json:"control_version"`
	Transport  string `json:"transport"`
	FaultLayer string `json:"fault_layer"`
}

func CanonicalNetwork(id string) (NetworkProfile, error) {
	p, err := CanonicalScenario(id)
	if err != nil {
		return NetworkProfile{}, err
	}
	p.Schema, p.EvidenceSchema, p.Version = 3, 3, p.Version+1
	p.Mode, p.Variant = NetworkMode, NetworkVariant
	return NetworkProfile{p, 1, NetworkTransport, NetworkFaultLayer}, nil
}
func (p NetworkProfile) Validate() error {
	want, err := CanonicalNetwork(p.ID)
	if err != nil {
		return err
	}
	a, err := json.Marshal(p)
	if err != nil {
		return err
	}
	b, err := json.Marshal(want)
	if err != nil {
		return err
	}
	if !bytes.Equal(a, b) {
		return errors.New("network profile differs from canonical contract")
	}
	return nil
}
func DecodeNetworkProfile(b []byte) (NetworkProfile, error) {
	var p NetworkProfile
	if err := CanonicalJSON(b, &p, MaxProfileBytes); err != nil {
		return NetworkProfile{}, err
	}
	if err := p.Validate(); err != nil {
		return NetworkProfile{}, err
	}
	return p, nil
}
func LoadNetworkProfile(root, relative string) (NetworkProfile, []byte, error) {
	path, err := resolveRegularFile(root, relative)
	if err != nil {
		return NetworkProfile{}, nil, err
	}
	f, err := os.Open(path)
	if err != nil {
		return NetworkProfile{}, nil, err
	}
	b, e := io.ReadAll(io.LimitReader(f, MaxProfileBytes+2))
	err = errors.Join(e, f.Close())
	if err != nil {
		return NetworkProfile{}, nil, err
	}
	if len(b) == 0 || b[len(b)-1] != '\n' {
		return NetworkProfile{}, nil, errors.New("network profile final LF")
	}
	p, err := DecodeNetworkProfile(b[:len(b)-1])
	if err != nil {
		return NetworkProfile{}, nil, err
	}
	return p, b, nil
}
