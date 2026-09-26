package synthetic

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"math"
	"os"
	"path/filepath"
)

// Recovery is supplied by the surviving test supervisor, not inferred from disk.
type Recovery struct {
	Epoch                  string
	Now, MinimumGeneration int64
}
type syncedFile interface {
	Write([]byte) (int, error)
	Sync() error
	Close() error
}
type syncedDir interface {
	Sync() error
	Close() error
}
type fileOps struct {
	create    func(string) (syncedFile, error)
	rename    func(string, string) error
	directory func(string) (syncedDir, error)
	hook      func(string) error
}

func realOps() fileOps {
	return fileOps{
		create: func(p string) (syncedFile, error) { return os.OpenFile(p, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600) },
		rename: os.Rename, directory: func(p string) (syncedDir, error) { return os.Open(p) }, hook: func(string) error { return nil },
	}
}

type store struct {
	directory string
	current   state
	ops       fileOps
	halted    bool
}
type cappedBuffer struct {
	bytes.Buffer
	limit int
}

func (b *cappedBuffer) Write(p []byte) (int, error) {
	if len(p) > b.limit-b.Len() {
		return 0, fail("REJECT_QUOTA", "state encoded size")
	}
	return b.Buffer.Write(p)
}
func encodeState(s state) ([]byte, error) {
	if err := s.validate(); err != nil {
		return nil, err
	}
	s.Checksum = ""
	var buffer = cappedBuffer{limit: maxStateBytes}
	if err := json.NewEncoder(&buffer).Encode(s); err != nil {
		return nil, err
	}
	unsigned := bytes.TrimSuffix(buffer.Bytes(), []byte(",\"checksum_sha256\":\"\"}\n"))
	if len(unsigned) == buffer.Len() {
		return nil, fail("STORE_INVALID", "checksum encoding")
	}
	input := append(append([]byte{}, unsigned...), '}')
	s.Checksum = digest(input)
	buffer.Reset()
	if err := json.NewEncoder(&buffer).Encode(s); err != nil {
		return nil, err
	}
	return bytes.TrimSuffix(buffer.Bytes(), []byte{'\n'}), nil
}
func decodeState(data []byte) (state, error) {
	var s state
	if len(data) == 0 || len(data) > maxStateBytes {
		return s, fail("STORE_INVALID", "state size")
	}
	if err := strictJSON(data, &s); err != nil {
		return state{}, wrap("STORE_INVALID", "state json", err)
	}
	if !lowerHex(s.Checksum, 64) {
		return state{}, fail("STORE_INVALID", "checksum shape")
	}
	want, err := encodeState(s)
	if err != nil {
		return state{}, wrap("STORE_INVALID", "state validation", err)
	}
	if !bytes.Equal(data, want) {
		return state{}, fail("STORE_INVALID", "checksum")
	}
	return s, nil
}
func checkDirectory(path string) error {
	i, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !i.IsDir() || i.Mode()&os.ModeSymlink != 0 || i.Mode().Perm() != 0700 {
		return fail("STORE_INVALID", "exclusive directory")
	}
	return nil
}
func checkRegular(path string, missingOK bool) error {
	i, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) && missingOK {
		return nil
	}
	if err != nil {
		return err
	}
	if !i.Mode().IsRegular() || i.Mode().Perm() != 0600 || i.Size() > maxStateBytes {
		return fail("STORE_INVALID", "state file type or size")
	}
	return nil
}
func readState(path string) (state, error) {
	if err := checkRegular(path, false); err != nil {
		return state{}, wrap("STORE_INVALID", "file check", err)
	}
	f, err := os.Open(path)
	if err != nil {
		return state{}, wrap("STORE_INVALID", "open", err)
	}
	b, readErr := io.ReadAll(io.LimitReader(f, maxStateBytes+1))
	closeErr := f.Close()
	if err := errors.Join(readErr, closeErr); err != nil {
		return state{}, wrap("STORE_INVALID", "read/close", err)
	}
	return decodeState(b)
}
func initStore(directory, run, node, epoch string) (*store, error) {
	if err := checkDirectory(directory); err != nil {
		return nil, wrap("STORE_INVALID", "init directory", err)
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, err
	}
	if len(entries) != 0 {
		return nil, fail("STORE_INVALID", "init requires empty directory")
	}
	s := newState(run, node, epoch)
	st := &store{directory: directory, current: s, ops: realOps()}
	if err := st.write(s); err != nil {
		return nil, err
	}
	return st, nil
}
func openStore(directory, run, node string, r Recovery) (*store, error) {
	if err := checkDirectory(directory); err != nil {
		return nil, wrap("STORE_INVALID", "open directory", err)
	}
	entries, err := os.ReadDir(directory)
	if err != nil {
		return nil, err
	}
	for _, entry := range entries {
		if entry.Name() != "state.json" && entry.Name() != "state.next" {
			return nil, fail("STORE_INVALID", "unexpected directory entry")
		}
	}
	s, err := readState(filepath.Join(directory, "state.json"))
	if err != nil {
		return nil, err
	}
	if s.Run != run || s.Node != node {
		return nil, fail("STORE_INVALID", "store binding")
	}
	if !lowerHex(r.Epoch, 32) || r.Epoch != s.Epoch || r.Now < s.Now || r.Now > 100000 || r.MinimumGeneration < 0 {
		return nil, fail("TIME_UNCERTAIN", "recovery context")
	}
	if s.Generation < r.MinimumGeneration {
		return nil, fail("STORE_INVALID", "generation rollback")
	}
	st := &store{directory: directory, current: s, ops: realOps()}
	next := filepath.Join(directory, "state.next")
	if _, err := os.Lstat(next); !errors.Is(err, os.ErrNotExist) {
		if err != nil {
			return nil, err
		}
		if err := checkRegular(next, false); err != nil {
			return nil, err
		}
		if err := os.Remove(next); err != nil {
			return nil, wrap("STORE_INVALID", "remove abandoned next", err)
		}
	}
	if err := st.syncDirectory(); err != nil {
		return nil, wrap("STORE_INVALID", "recover directory", err)
	}
	return st, nil
}
func (st *store) syncDirectory() error {
	d, err := st.ops.directory(st.directory)
	if err != nil {
		return err
	}
	err = st.ops.hook("directory_sync")
	if err == nil {
		err = d.Sync()
	}
	closeErr := d.Close()
	if closeErr == nil {
		closeErr = st.ops.hook("directory_close")
	}
	return errors.Join(err, closeErr)
}
func (st *store) save(next state) error {
	if st.halted {
		return fail("STORE_OUTCOME_UNKNOWN", "node halted")
	}
	if st.current.Generation == math.MaxInt64 || next.Generation != st.current.Generation+1 || next.Now < st.current.Now || next.Run != st.current.Run || next.Node != st.current.Node || next.Epoch != st.current.Epoch {
		return fail("STORE_INVALID", "save predecessor")
	}
	if err := st.write(next); err != nil {
		st.halted = true
		return err
	}
	st.current = next.clone()
	return nil
}
func (st *store) write(next state) error {
	data, err := encodeState(next)
	if err != nil {
		return err
	}
	path, temp := filepath.Join(st.directory, "state.json"), filepath.Join(st.directory, "state.next")
	if err = checkRegular(path, true); err != nil {
		return wrap("STORE_NOT_COMMITTED", "prior state", err)
	}
	if err = st.ops.hook("before_create"); err != nil {
		return wrap("STORE_NOT_COMMITTED", "create", err)
	}
	f, err := st.ops.create(temp)
	if err != nil {
		return wrap("STORE_NOT_COMMITTED", "create next", err)
	}
	closed := false
	defer func() {
		if !closed {
			_ = f.Close()
		}
	}()
	if err = st.ops.hook("before_write"); err == nil {
		var n int
		n, err = f.Write(data)
		if err == nil && n != len(data) {
			err = io.ErrShortWrite
		}
	}
	if err != nil {
		closeErr := f.Close()
		closed = true
		return wrap("STORE_NOT_COMMITTED", "write", errors.Join(err, closeErr))
	}
	if err = st.ops.hook("file_sync"); err == nil {
		err = f.Sync()
	}
	if err != nil {
		closeErr := f.Close()
		closed = true
		return wrap("STORE_NOT_COMMITTED", "file sync", errors.Join(err, closeErr))
	}
	err = f.Close()
	closed = true
	if err == nil {
		err = st.ops.hook("file_close")
	}
	if err != nil {
		return wrap("STORE_NOT_COMMITTED", "file close", err)
	}
	if err = st.ops.hook("rename"); err == nil {
		err = st.ops.rename(temp, path)
	}
	if err != nil {
		return wrap("STORE_OUTCOME_UNKNOWN", "rename", err)
	}
	if err = st.ops.hook("after_rename"); err != nil {
		return wrap("STORE_OUTCOME_UNKNOWN", "after rename", err)
	}
	if err = st.syncDirectory(); err != nil {
		return wrap("STORE_OUTCOME_UNKNOWN", "directory sync/close", err)
	}
	if err = st.ops.hook("committed"); err != nil {
		return wrap("STORE_OUTCOME_UNKNOWN", "committed notification", err)
	}
	return nil
}
