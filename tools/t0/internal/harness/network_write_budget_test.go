package harness

import (
	"errors"
	"math"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
)

func TestNetworkStorageDomainsStayWithinBatchContract(t *testing.T) {
	total := NetworkBuildStorageBytes + NetworkDaemonStorageBytes + NetworkEvidenceStorageBytes + NetworkDiagnosticStorageBytes + NetworkTemporaryStorageBytes
	if NetworkBatchStorageBytes != 768<<20 {
		t.Fatal("batch cap changed")
	}
	if total != NetworkBatchStorageBytes {
		t.Fatalf("storage domains exceed or silently change batch contract: %d", total)
	}
}

func TestNetworkWriteBudgetBoundsAndStickyFailure(t *testing.T) {
	checks := 0
	b, err := NewNetworkWriteBudget(10, func() error { checks++; return nil })
	if err != nil {
		t.Fatal(err)
	}
	if err = b.Reserve(10); err != nil || b.Charged() != 10 {
		t.Fatal("exact bound", err)
	}
	if err = b.Reserve(1); err == nil || b.Charged() != 10 || checks != 1 {
		t.Fatal("over limit reached writer/probe", err, checks)
	}
	if b.Check() != err || b.Reserve(1) != err {
		t.Fatal("budget failure did not stop subsequent operations")
	}
	for _, size := range []int64{-1, 0, math.MaxInt64} {
		b, _ := NewNetworkWriteBudget(10, func() error { t.Fatal("invalid size probed"); return nil })
		if b.Reserve(size) == nil || b.Charged() != 0 {
			t.Fatal("invalid reservation accepted", size)
		}
	}
	for _, limit := range []int64{0, -1, NetworkBatchStorageBytes + 1} {
		if _, err := NewNetworkWriteBudget(limit, func() error { return nil }); err == nil {
			t.Fatal("invalid capacity accepted", limit)
		}
	}
	if _, err := NewNetworkWriteBudget(1, nil); err == nil {
		t.Fatal("missing space checker accepted")
	}
	var absent *NetworkWriteBudget
	if absent.Check() == nil || absent.Reserve(1) == nil {
		t.Fatal("missing budget accepted")
	}
	var uninitialized NetworkWriteBudget
	if uninitialized.Check() == nil || uninitialized.Reserve(1) == nil {
		t.Fatal("uninitialized budget accepted")
	}
}

func TestNetworkWriteBudgetSpaceErrorIsPreserved(t *testing.T) {
	cause := errors.New("fixture filesystem inventory failed")
	checks := 0
	b, _ := NewNetworkWriteBudget(10, func() error {
		checks++
		if checks == 1 {
			return nil
		}
		return cause
	})
	if err := b.Reserve(5); err != nil {
		t.Fatal(err)
	}
	if err := b.Check(); !errors.Is(err, cause) {
		t.Fatalf("lost probe cause: %v", err)
	}
	if !errors.Is(b.Reserve(1), cause) || b.Charged() != 5 || checks != 2 {
		t.Fatal("space error refunded or resumed budget")
	}
}

func TestNetworkWriteBudgetConcurrentReservations(t *testing.T) {
	b, _ := NewNetworkWriteBudget(50, func() error { return nil })
	var accepted atomic.Int64
	var wg sync.WaitGroup
	for range 100 {
		wg.Go(func() {
			if b.Reserve(1) == nil {
				accepted.Add(1)
			}
		})
	}
	wg.Wait()
	if accepted.Load() != 50 || b.Charged() != 50 {
		t.Fatalf("concurrent budget overflow: accepted %d, charged %d", accepted.Load(), b.Charged())
	}
}

func TestNetworkInventoryCountsChecksumBeforeFinalizing(t *testing.T) {
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "logs"), 0700); err != nil {
		t.Fatal(err)
	}
	// Individually legal files fill 32 MiB without the checksum. Inventory is
	// intentionally tested below semantic validation to exercise the disk cap.
	sizes := map[string]int64{"execution.ndjson": 16 << 20, "events.ndjson": 4 << 20, "assertions.json": 4 << 20, "metrics.json": 4 << 20, "manifest.json": 4 << 20}
	for _, name := range networkFiles {
		f, err := os.OpenFile(filepath.Join(root, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			t.Fatal(err)
		}
		err = errors.Join(f.Truncate(sizes[name]), f.Close())
		if err != nil {
			t.Fatal(err)
		}
	}
	if _, err := networkInventory(root, false); err == nil {
		t.Fatal("pre-finalization inventory forgot checksum capacity")
	}
	// Fixed names and SHA-256 widths make checksum length independent of data.
	checksumSize := int64(len(networkChecksum(map[string][]byte{})))
	if err := os.Truncate(filepath.Join(root, "manifest.json"), (4<<20)-checksumSize); err != nil {
		t.Fatal(err)
	}
	if _, err := networkInventory(root, false); err != nil {
		t.Fatal("exact total including checksum rejected", err)
	}
}
