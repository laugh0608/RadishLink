package main

import "testing"

func TestNewCommandsRequireExactArguments(t *testing.T) {
	for _, args := range [][]string{{"synthetic-node"}, {"synthetic-node", "--store", "/tmp"}, {"synthetic-run"}, {"synthetic-run", "--matrix", "i5-seven-v1", "--repeats", "4"}, {"unknown"}} {
		if err := run(args); err == nil {
			t.Fatalf("accepted %v", args)
		}
	}
}
