package harness

import "testing"

func TestAssessmentDoesNotAcceptNetworkAsOffline(t *testing.T) {
	p, _ := CanonicalNetwork("SW-V1-BASE-001")
	if _, _, _, err := AssessScenario(p.ScenarioProfile, "p1", nil, ScenarioResiduals{}); err == nil {
		t.Fatal("network profile accepted as offline")
	}
}
