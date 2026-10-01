package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"

	"radishlink.local/t0/internal/harness"
)

type artifactFile interface {
	Write([]byte) (int, error)
	Sync() error
	Close() error
}

func writeNewJSON(path string, v any, budget *harness.NetworkWriteBudget, limit int) error {
	return writeNewJSONWithCreate(path, v, budget, limit, func(path string) (artifactFile, error) {
		return os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	})
}

func writeNewJSONWithCreate(path string, v any, budget *harness.NetworkWriteBudget, limit int, create func(string) (artifactFile, error)) error {
	if budget == nil || limit <= 0 || limit > 32<<20 {
		return errors.New("artifact requires budget and a limit of at most 32 MiB")
	}
	raw, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("encode artifact %s: %w", path, err)
	}
	if len(raw) >= limit { // Include the LF in the file limit and reservation.
		return fmt.Errorf("artifact %s exceeds %d bytes including LF", path, limit)
	}
	raw = append(raw, '\n')
	if err = budget.Reserve(int64(len(raw))); err != nil {
		return fmt.Errorf("reserve artifact %s: %w", path, err)
	}
	f, err := create(path)
	if err != nil {
		return fmt.Errorf("create artifact %s: %w", path, err)
	}
	n, writeErr := f.Write(raw)
	if writeErr == nil && n != len(raw) {
		writeErr = io.ErrShortWrite
	}
	var syncErr error
	if writeErr == nil {
		syncErr = f.Sync()
	}
	if err = errors.Join(writeErr, syncErr, f.Close()); err != nil {
		return fmt.Errorf("persist artifact %s: %w", path, err)
	}
	return nil
}
