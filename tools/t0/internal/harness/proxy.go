package harness

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net"
	"sync"
	"time"
)

const MaxSyntheticFrameBytes = 64 * 1024

type FaultPlan struct {
	Kind         string
	Direction    string
	TriggerIndex int
}

type FaultEvent struct {
	Direction  string `json:"direction"`
	EventIndex int    `json:"event_index"`
	Action     string `json:"action"`
	Length     int    `json:"length"`
	SHA256     string `json:"sha256"`
}

type SyntheticProxy struct {
	mu            sync.Mutex
	plan          FaultPlan
	seen          map[string]int
	hits          int
	reorderBuffer []byte
}

func NewSyntheticProxy(plan FaultPlan) (*SyntheticProxy, error) {
	if plan.Direction == "" {
		return nil, errors.New("fault direction is required")
	}
	switch plan.Kind {
	case "none":
		if plan.TriggerIndex != 0 {
			return nil, errors.New("none fault must have trigger index 0")
		}
	case "drop", "duplicate", "reorder-pair":
		if plan.TriggerIndex < 1 {
			return nil, errors.New("fault trigger index must be positive")
		}
	default:
		return nil, fmt.Errorf("unsupported fault kind: %q", plan.Kind)
	}
	return &SyntheticProxy{plan: plan, seen: make(map[string]int)}, nil
}

func (proxy *SyntheticProxy) Process(direction string, payload []byte) ([][]byte, FaultEvent, error) {
	if direction == "" {
		return nil, FaultEvent{}, errors.New("frame direction is required")
	}
	if len(payload) == 0 || len(payload) > MaxSyntheticFrameBytes {
		return nil, FaultEvent{}, fmt.Errorf("synthetic frame length must be between 1 and %d", MaxSyntheticFrameBytes)
	}
	proxy.mu.Lock()
	defer proxy.mu.Unlock()

	proxy.seen[direction]++
	index := proxy.seen[direction]
	action := "forward"
	outputs := [][]byte{cloneBytes(payload)}
	if direction == proxy.plan.Direction && index == proxy.plan.TriggerIndex {
		proxy.hits++
		switch proxy.plan.Kind {
		case "drop":
			action = "drop"
			outputs = nil
		case "duplicate":
			action = "duplicate"
			outputs = [][]byte{cloneBytes(payload), cloneBytes(payload)}
		case "reorder-pair":
			action = "reorder-buffer"
			proxy.reorderBuffer = cloneBytes(payload)
			outputs = nil
		}
	} else if proxy.plan.Kind == "reorder-pair" && direction == proxy.plan.Direction && index == proxy.plan.TriggerIndex+1 && proxy.reorderBuffer != nil {
		action = "reorder-release"
		outputs = [][]byte{cloneBytes(payload), proxy.reorderBuffer}
		proxy.reorderBuffer = nil
	}

	digest := sha256.Sum256(payload)
	return outputs, FaultEvent{
		Direction:  direction,
		EventIndex: index,
		Action:     action,
		Length:     len(payload),
		SHA256:     hex.EncodeToString(digest[:]),
	}, nil
}

func (proxy *SyntheticProxy) HitCount() int {
	proxy.mu.Lock()
	defer proxy.mu.Unlock()
	return proxy.hits
}

func (proxy *SyntheticProxy) ValidateComplete() error {
	proxy.mu.Lock()
	defer proxy.mu.Unlock()
	if proxy.plan.Kind != "none" && proxy.hits != 1 {
		return fmt.Errorf("fault hit count: got %d, want 1", proxy.hits)
	}
	if proxy.reorderBuffer != nil {
		return errors.New("reorder pair ended with a buffered frame")
	}
	return nil
}

func WriteSyntheticFrame(writer io.Writer, payload []byte) error {
	return WriteSyntheticFrameWithLimit(writer, payload, MaxSyntheticFrameBytes)
}

// WriteSyntheticFrameWithLimit writes one opaque frame. The limit excludes the
// four-byte prefix and must be within 1..MaxSyntheticFrameBytes. On any write
// error the caller must abandon the stream; partial writes are not retried.
func WriteSyntheticFrameWithLimit(writer io.Writer, payload []byte, maxBodyBytes int64) error {
	if err := checkSyntheticFrameLimit(maxBodyBytes); err != nil {
		return err
	}
	if len(payload) == 0 || int64(len(payload)) > maxBodyBytes {
		return fmt.Errorf("synthetic frame length must be between 1 and %d: %d", maxBodyBytes, len(payload))
	}
	var header [4]byte
	binary.BigEndian.PutUint32(header[:], uint32(len(payload)))
	n, err := writer.Write(header[:])
	if err != nil {
		return fmt.Errorf("write synthetic frame header: %w", err)
	}
	if n != len(header) {
		return fmt.Errorf("write synthetic frame header: wrote %d of %d bytes: %w", n, len(header), io.ErrShortWrite)
	}
	n, err = writer.Write(payload)
	if err != nil {
		return fmt.Errorf("write synthetic frame payload: %w", err)
	}
	if n != len(payload) {
		return fmt.Errorf("write synthetic frame payload: wrote %d of %d bytes: %w", n, len(payload), io.ErrShortWrite)
	}
	return nil
}

func ReadSyntheticFrame(reader io.Reader) ([]byte, error) {
	return ReadSyntheticFrameWithLimit(reader, MaxSyntheticFrameBytes)
}

// ReadSyntheticFrameWithLimit checks the declared body length before allocating
// or reading it. It consumes one frame on success and returns no partial body on
// failure. The caller owns timeouts and must abandon the stream after an error.
func ReadSyntheticFrameWithLimit(reader io.Reader, maxBodyBytes int64) ([]byte, error) {
	if err := checkSyntheticFrameLimit(maxBodyBytes); err != nil {
		return nil, err
	}
	var header [4]byte
	if _, err := io.ReadFull(reader, header[:]); err != nil {
		return nil, fmt.Errorf("read synthetic frame header: %w", err)
	}
	length := binary.BigEndian.Uint32(header[:])
	if length == 0 || int64(length) > maxBodyBytes {
		return nil, fmt.Errorf("synthetic frame length must be between 1 and %d: %d", maxBodyBytes, length)
	}
	payload := make([]byte, length)
	if _, err := io.ReadFull(reader, payload); err != nil {
		return nil, fmt.Errorf("read synthetic frame payload: %w", err)
	}
	return payload, nil
}

func checkSyntheticFrameLimit(maxBodyBytes int64) error {
	if maxBodyBytes < 1 || maxBodyBytes > MaxSyntheticFrameBytes {
		return fmt.Errorf("synthetic frame body limit must be between 1 and %d: %d", MaxSyntheticFrameBytes, maxBodyBytes)
	}
	return nil
}

func RunEndpoint(ctx context.Context, listenAddress string) error {
	if listenAddress == "" {
		return errors.New("endpoint listen address is required")
	}
	listener, err := net.Listen("tcp", listenAddress)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", listenAddress, err)
	}
	defer listener.Close()
	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()
	for {
		connection, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("accept endpoint connection: %w", err)
		}
		go serveEndpointConnection(connection)
	}
}

func RunProxy(ctx context.Context, listenAddress, upstreamAddress, direction string, proxy *SyntheticProxy) error {
	if listenAddress == "" || upstreamAddress == "" || direction == "" || proxy == nil {
		return errors.New("proxy listen, upstream, direction, and plan are required")
	}
	listener, err := net.Listen("tcp", listenAddress)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", listenAddress, err)
	}
	defer listener.Close()
	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()
	for {
		connection, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("accept proxy connection: %w", err)
		}
		go serveProxyConnection(connection, upstreamAddress, direction, proxy)
	}
}

func serveEndpointConnection(connection net.Conn) {
	defer connection.Close()
	_ = connection.SetDeadline(time.Now().Add(5 * time.Second))
	payload, err := ReadSyntheticFrame(connection)
	if err != nil {
		return
	}
	_ = WriteSyntheticFrame(connection, payload)
}

func serveProxyConnection(connection net.Conn, upstreamAddress, direction string, proxy *SyntheticProxy) {
	defer connection.Close()
	_ = connection.SetDeadline(time.Now().Add(5 * time.Second))
	payload, err := ReadSyntheticFrame(connection)
	if err != nil {
		return
	}
	outputs, _, err := proxy.Process(direction, payload)
	if err != nil {
		return
	}
	for _, output := range outputs {
		upstream, err := net.DialTimeout("tcp", upstreamAddress, time.Second)
		if err != nil {
			return
		}
		_ = upstream.SetDeadline(time.Now().Add(2 * time.Second))
		if err := WriteSyntheticFrame(upstream, output); err != nil {
			_ = upstream.Close()
			return
		}
		response, err := ReadSyntheticFrame(upstream)
		_ = upstream.Close()
		if err != nil {
			return
		}
		if err := WriteSyntheticFrame(connection, response); err != nil {
			return
		}
	}
}

func cloneBytes(value []byte) []byte {
	return append([]byte(nil), value...)
}
