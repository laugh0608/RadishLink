package harness

import "testing"

func TestNetworkRejectsUnboundEvidence(t *testing.T) {
	p, _ := CanonicalNetwork("SW-V1-BASE-001")
	for _, b := range []NetworkBundle{{Profile: p}, {Profile: p, Manifest: NetworkManifest{Subcase: "p1024"}, Execution: []ExecutionEvent{{Schema: 3, Sequence: 1, Source: "driver", Local: 1, Kind: "success"}}}} {
		if _, _, _, err := AssessNetwork(b); err == nil {
			t.Fatal("unbound network trace accepted")
		}
	}
}
