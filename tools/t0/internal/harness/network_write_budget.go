package harness

import (
	"errors"
	"fmt"
	"sync"
)

// These sublimits sum to the existing 768 MiB batch cap. They are storage
// domain capacities, not promises that a cold build or the matrix will fit.
const (
	NetworkBuildStorageBytes      int64 = 256 << 20
	NetworkDaemonStorageBytes     int64 = 160 << 20
	NetworkEvidenceStorageBytes   int64 = 240 << 20
	NetworkDiagnosticStorageBytes int64 = 64 << 20
	NetworkTemporaryStorageBytes  int64 = 48 << 20
	NetworkBatchStorageBytes      int64 = 768 << 20
)

// NetworkWriteBudget accounts for output bytes before any file is created.
// A failed writer retains its reservation, including possible partial/temp
// files. There is no implicit refund or reset. This is NOT the OS storage
// boundary for compilers, Docker or filesystem metadata.
type NetworkWriteBudget struct {
	mu      sync.Mutex
	limit   int64
	charged int64
	check   func() error
	stopped error
}

func NewNetworkWriteBudget(limit int64, check func() error) (*NetworkWriteBudget, error) {
	if limit <= 0 || limit > NetworkBatchStorageBytes || check == nil {
		return nil, errors.New("network write budget requires a bounded capacity and space checker")
	}
	return &NetworkWriteBudget{limit: limit, check: check}, nil
}

func (b *NetworkWriteBudget) Reserve(size int64) error {
	if b == nil {
		return errors.New("network write budget is required")
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.stopped != nil {
		return b.stopped
	}
	if size <= 0 || size > b.limit-b.charged {
		b.stopped = fmt.Errorf("network write budget: requested %d bytes, remaining %d", size, b.limit-b.charged)
		return b.stopped
	}
	if err := b.check(); err != nil {
		b.stopped = fmt.Errorf("network write space check: %w", err)
		return b.stopped
	}
	b.charged += size
	return nil
}

// Check rechecks space between reserved writes. An error permanently stops
// this budget; a later successful probe must not silently resume a failed run.
func (b *NetworkWriteBudget) Check() error {
	if b == nil {
		return errors.New("network write budget is required")
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.stopped == nil && b.check == nil {
		b.stopped = errors.New("network write budget is not initialized")
	}
	if b.stopped == nil {
		if err := b.check(); err != nil {
			b.stopped = fmt.Errorf("network write space check: %w", err)
		}
	}
	return b.stopped
}

func (b *NetworkWriteBudget) Charged() int64 {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.charged
}
