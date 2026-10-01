package main

import "errors"

var errNetworkResourceIsolation = errors.New("I5_RESOURCE_ISOLATION_REQUIRED: the 768 MiB batch storage boundary is not implemented; see docs/testing/sw-g4-synthetic-i5-resource-isolation.md")

// The owner's 2026-10-01 decision keeps builds, caches, volumes and evidence in
// one batch limit. Neither the host bootstrap nor the Docker builder currently
// has an enforceable aggregate storage boundary. Sampling cannot authorize run.
// This policy has no environment/CLI bypass. Replace it only with the accepted
// isolation implementation and its failure-path evidence, not a readiness flag.
func requireNetworkResourceIsolation() error {
	return &networkExit{2, errNetworkResourceIsolation}
}
