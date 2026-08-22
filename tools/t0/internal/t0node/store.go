package t0node

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

const stateVersion = 0

type persistentState struct {
	Version         int              `json:"version"`
	Pending         map[string]Frame `json:"pending"`
	Delivered       map[string]int   `json:"delivered"`
	Acked           map[string]bool  `json:"acked"`
	Drops           map[string]int   `json:"drops"`
	DuplicateFrames int              `json:"duplicate_frames"`
}

func newPersistentState() persistentState {
	return persistentState{
		Version:   stateVersion,
		Pending:   make(map[string]Frame),
		Delivered: make(map[string]int),
		Acked:     make(map[string]bool),
		Drops:     make(map[string]int),
	}
}

type stateStore struct {
	directory string
	path      string
}

func openStateStore(directory string) (*stateStore, persistentState, error) {
	if directory == "" {
		return nil, persistentState{}, errors.New("data directory is required")
	}
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return nil, persistentState{}, fmt.Errorf("create data directory: %w", err)
	}

	store := &stateStore{
		directory: directory,
		path:      filepath.Join(directory, "state-v0.json"),
	}
	data, err := os.ReadFile(store.path)
	if errors.Is(err, os.ErrNotExist) {
		return store, newPersistentState(), nil
	}
	if err != nil {
		return nil, persistentState{}, fmt.Errorf("read state: %w", err)
	}

	state := newPersistentState()
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, persistentState{}, fmt.Errorf("decode state: %w", err)
	}
	if state.Version != stateVersion {
		return nil, persistentState{}, fmt.Errorf("unsupported state version: %d", state.Version)
	}
	if state.Pending == nil || state.Delivered == nil || state.Acked == nil || state.Drops == nil {
		return nil, persistentState{}, errors.New("state contains a null map")
	}
	return store, state, nil
}

func (store *stateStore) Save(state persistentState) error {
	temporaryPath := store.path + ".tmp"
	file, err := os.OpenFile(temporaryPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o600)
	if err != nil {
		return fmt.Errorf("create temporary state: %w", err)
	}

	encoder := json.NewEncoder(file)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(state); err != nil {
		_ = file.Close()
		return fmt.Errorf("encode state: %w", err)
	}
	if err := file.Sync(); err != nil {
		_ = file.Close()
		return fmt.Errorf("sync temporary state: %w", err)
	}
	if err := file.Close(); err != nil {
		return fmt.Errorf("close temporary state: %w", err)
	}
	if err := os.Rename(temporaryPath, store.path); err != nil {
		return fmt.Errorf("replace state: %w", err)
	}

	directory, err := os.Open(store.directory)
	if err != nil {
		return fmt.Errorf("open state directory for sync: %w", err)
	}
	defer directory.Close()
	if err := directory.Sync(); err != nil {
		return fmt.Errorf("sync state directory: %w", err)
	}
	return nil
}
