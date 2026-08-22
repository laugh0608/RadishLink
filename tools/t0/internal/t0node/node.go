package t0node

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"sort"
	"sync"
	"time"
)

type Config struct {
	NodeID        string
	ListenAddress string
	Routes        map[string]string
	DataDirectory string
	RetryInterval time.Duration
	DialTimeout   time.Duration
	AckHopLimit   int
	Logger        *slog.Logger
}

type Node struct {
	config Config
	store  *stateStore

	mu    sync.Mutex
	state persistentState
}

func New(config Config) (*Node, error) {
	if !validIdentifier.MatchString(config.NodeID) {
		return nil, errors.New("node id is invalid")
	}
	if config.ListenAddress == "" {
		return nil, errors.New("listen address is required")
	}
	if config.RetryInterval <= 0 {
		config.RetryInterval = 100 * time.Millisecond
	}
	if config.DialTimeout <= 0 {
		config.DialTimeout = 500 * time.Millisecond
	}
	if config.AckHopLimit <= 0 || config.AckHopLimit > 32 {
		config.AckHopLimit = 8
	}
	if config.Logger == nil {
		config.Logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	for destination, address := range config.Routes {
		if !validIdentifier.MatchString(destination) {
			return nil, fmt.Errorf("route destination is invalid: %q", destination)
		}
		if address == "" {
			return nil, fmt.Errorf("route address is empty for %s", destination)
		}
	}

	store, state, err := openStateStore(config.DataDirectory)
	if err != nil {
		return nil, err
	}
	return &Node{config: config, store: store, state: state}, nil
}

func (node *Node) Run(ctx context.Context) error {
	listener, err := net.Listen("tcp", node.config.ListenAddress)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", node.config.ListenAddress, err)
	}
	defer listener.Close()

	node.config.Logger.Info("node_started", "node_id", node.config.NodeID)
	defer node.config.Logger.Info("node_stopped", "node_id", node.config.NodeID)

	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()
	go node.retryLoop(ctx)

	for {
		connection, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("accept connection: %w", err)
		}
		go node.serveConnection(connection)
	}
}

func (node *Node) serveConnection(connection net.Conn) {
	defer connection.Close()
	_ = connection.SetDeadline(time.Now().Add(5 * time.Second))

	decoder := json.NewDecoder(io.LimitReader(connection, MaxWireRequest))
	var request Request
	if err := decoder.Decode(&request); err != nil {
		node.writeResponse(connection, Response{Reason: fmt.Sprintf("decode request: %v", err)})
		return
	}

	response := node.handleRequest(request)
	node.writeResponse(connection, response)
}

func (node *Node) writeResponse(connection net.Conn, response Response) {
	if err := json.NewEncoder(connection).Encode(response); err != nil {
		node.config.Logger.Error("response_write_failed", "error", err)
	}
}

func (node *Node) handleRequest(request Request) Response {
	switch request.Operation {
	case "status":
		status := node.Status()
		return Response{Accepted: true, Status: &status}
	case "submit":
		if request.Frame == nil {
			return Response{Reason: "submit requires a frame"}
		}
		accepted, reason, err := node.Submit(*request.Frame, request.Force, time.Now())
		if err != nil {
			return Response{Reason: err.Error()}
		}
		return Response{Accepted: accepted, Reason: reason}
	case "receive":
		if request.Frame == nil {
			return Response{Reason: "receive requires a frame"}
		}
		accepted, reason, err := node.Receive(*request.Frame, time.Now())
		if err != nil {
			return Response{Reason: err.Error()}
		}
		return Response{Accepted: accepted, Reason: reason}
	default:
		return Response{Reason: fmt.Sprintf("unsupported operation: %q", request.Operation)}
	}
}

func (node *Node) Submit(frame Frame, force bool, now time.Time) (bool, string, error) {
	if err := frame.Validate(now); err != nil {
		return false, "", err
	}
	if frame.Kind != FrameMessage {
		return false, "", errors.New("only message frames can be submitted")
	}
	if frame.Origin != node.config.NodeID {
		return false, "", errors.New("submitted frame origin must match the node id")
	}
	if frame.Destination == node.config.NodeID {
		return false, "", errors.New("submitted frame destination must be remote")
	}
	if frame.HopLimit == 0 {
		return false, "", errors.New("submitted frame requires a positive hop limit")
	}
	if _, ok := node.config.Routes[frame.Destination]; !ok {
		return false, "", fmt.Errorf("no route for destination %s", frame.Destination)
	}

	node.mu.Lock()
	defer node.mu.Unlock()
	if _, ok := node.state.Pending[frame.ID]; ok {
		return true, "already_pending", nil
	}
	if node.state.Acked[frame.ID] && !force {
		return true, "already_acked", nil
	}
	if err := node.mutateLocked(func(state *persistentState) {
		if force {
			delete(state.Acked, frame.ID)
		}
		state.Pending[frame.ID] = frame
	}); err != nil {
		return false, "", err
	}
	node.config.Logger.Info("message_submitted", "node_id", node.config.NodeID, "message_id", frame.ID)
	return true, "queued", nil
}

func (node *Node) Receive(frame Frame, now time.Time) (bool, string, error) {
	if err := frame.Validate(now); err != nil {
		reason := "invalid_frame"
		if err.Error() == "frame expired" {
			reason = "expired"
		}
		if recordErr := node.recordDrop(reason); recordErr != nil {
			return false, "", errors.Join(err, recordErr)
		}
		return false, reason, nil
	}

	if frame.Destination == node.config.NodeID {
		return node.receiveAtDestination(frame, now)
	}
	if frame.HopLimit == 0 {
		if err := node.recordDrop("hop_limit_exhausted"); err != nil {
			return false, "", err
		}
		return false, "hop_limit_exhausted", nil
	}
	if _, ok := node.config.Routes[frame.Destination]; !ok {
		if err := node.recordDrop("no_route"); err != nil {
			return false, "", err
		}
		return false, "no_route", nil
	}

	node.mu.Lock()
	defer node.mu.Unlock()
	reason := "stored_for_forwarding"
	if err := node.mutateLocked(func(state *persistentState) {
		if frame.Kind == FrameAck {
			delete(state.Pending, frame.AckFor)
		}
		if _, exists := state.Pending[frame.ID]; exists {
			state.DuplicateFrames++
			reason = "duplicate_in_queue"
			return
		}
		state.Pending[frame.ID] = frame
	}); err != nil {
		return false, "", err
	}
	return true, reason, nil
}

func (node *Node) receiveAtDestination(frame Frame, now time.Time) (bool, string, error) {
	node.mu.Lock()
	defer node.mu.Unlock()

	reason := "accepted_at_destination"
	if err := node.mutateLocked(func(state *persistentState) {
		switch frame.Kind {
		case FrameMessage:
			if state.Delivered[frame.ID] == 0 {
				state.Delivered[frame.ID] = 1
				reason = "delivered"
			} else {
				state.DuplicateFrames++
				reason = "duplicate_suppressed"
			}
			ack := Frame{
				Version:         ProtocolVersion,
				Kind:            FrameAck,
				ID:              acknowledgementID(frame.ID),
				Origin:          node.config.NodeID,
				Destination:     frame.Origin,
				HopLimit:        node.config.AckHopLimit,
				ExpiresAtUnixMs: now.Add(30 * time.Second).UnixMilli(),
				AckFor:          frame.ID,
			}
			state.Pending[ack.ID] = ack
		case FrameAck:
			if state.Acked[frame.AckFor] {
				state.DuplicateFrames++
				reason = "duplicate_ack"
			} else {
				state.Acked[frame.AckFor] = true
				reason = "acked"
			}
			delete(state.Pending, frame.AckFor)
		}
	}); err != nil {
		return false, "", err
	}

	if frame.Kind == FrameMessage {
		node.config.Logger.Info("message_delivery_processed", "node_id", node.config.NodeID, "message_id", frame.ID, "result", reason)
	}
	return true, reason, nil
}

func acknowledgementID(messageID string) string {
	digest := sha256.Sum256([]byte(messageID))
	return "ack-" + hex.EncodeToString(digest[:30])
}

func (node *Node) retryLoop(ctx context.Context) {
	ticker := time.NewTicker(node.config.RetryInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-ticker.C:
			if err := node.retryOnce(now); err != nil {
				node.config.Logger.Error("retry_failed", "node_id", node.config.NodeID, "error", err)
			}
		}
	}
}

func (node *Node) retryOnce(now time.Time) error {
	node.mu.Lock()
	expiredIDs := make([]string, 0)
	for id, frame := range node.state.Pending {
		if now.UnixMilli() >= frame.ExpiresAtUnixMs {
			expiredIDs = append(expiredIDs, id)
		}
	}
	if len(expiredIDs) > 0 {
		if err := node.mutateLocked(func(state *persistentState) {
			for _, id := range expiredIDs {
				delete(state.Pending, id)
				state.Drops["expired"]++
			}
		}); err != nil {
			node.mu.Unlock()
			return err
		}
	}
	frames := make([]Frame, 0, len(node.state.Pending))
	for _, frame := range node.state.Pending {
		frames = append(frames, frame)
	}
	node.mu.Unlock()

	sort.Slice(frames, func(left, right int) bool {
		if frames[left].Kind != frames[right].Kind {
			return frames[left].Kind == FrameAck
		}
		return frames[left].ID < frames[right].ID
	})
	for _, frame := range frames {
		node.forward(frame)
	}
	return nil
}

func (node *Node) forward(frame Frame) {
	address, ok := node.config.Routes[frame.Destination]
	if !ok || frame.HopLimit == 0 {
		return
	}
	forwarded := frame
	forwarded.HopLimit--
	response, err := Call(address, Request{Operation: "receive", Frame: &forwarded}, node.config.DialTimeout)
	if err != nil {
		node.config.Logger.Debug("next_hop_unavailable", "node_id", node.config.NodeID, "frame_id", frame.ID, "destination", frame.Destination, "error", err)
		return
	}
	if !response.Accepted {
		node.config.Logger.Debug("next_hop_rejected", "node_id", node.config.NodeID, "frame_id", frame.ID, "reason", response.Reason)
		return
	}
	if frame.Kind != FrameAck {
		return
	}

	node.mu.Lock()
	defer node.mu.Unlock()
	if err := node.mutateLocked(func(state *persistentState) {
		if current, exists := state.Pending[frame.ID]; exists && current == frame {
			delete(state.Pending, frame.ID)
		}
	}); err != nil {
		node.config.Logger.Error("ack_custody_persist_failed", "node_id", node.config.NodeID, "frame_id", frame.ID, "error", err)
	}
}

func (node *Node) recordDrop(reason string) error {
	node.mu.Lock()
	defer node.mu.Unlock()
	return node.mutateLocked(func(state *persistentState) {
		state.Drops[reason]++
	})
}

func (node *Node) Status() Status {
	node.mu.Lock()
	defer node.mu.Unlock()

	status := Status{
		NodeID:          node.config.NodeID,
		Pending:         make([]string, 0, len(node.state.Pending)),
		Delivered:       make(map[string]int, len(node.state.Delivered)),
		Acked:           make([]string, 0, len(node.state.Acked)),
		Drops:           make(map[string]int, len(node.state.Drops)),
		DuplicateFrames: node.state.DuplicateFrames,
	}
	for id := range node.state.Pending {
		status.Pending = append(status.Pending, id)
	}
	for id, count := range node.state.Delivered {
		status.Delivered[id] = count
	}
	for id, acked := range node.state.Acked {
		if acked {
			status.Acked = append(status.Acked, id)
		}
	}
	for reason, count := range node.state.Drops {
		status.Drops[reason] = count
	}
	sort.Strings(status.Pending)
	sort.Strings(status.Acked)
	return status
}

func (node *Node) mutateLocked(mutation func(*persistentState)) error {
	previous := cloneState(node.state)
	mutation(&node.state)
	if err := node.store.Save(node.state); err != nil {
		node.state = previous
		return err
	}
	return nil
}

func cloneState(source persistentState) persistentState {
	clone := newPersistentState()
	clone.DuplicateFrames = source.DuplicateFrames
	for id, frame := range source.Pending {
		clone.Pending[id] = frame
	}
	for id, count := range source.Delivered {
		clone.Delivered[id] = count
	}
	for id, acked := range source.Acked {
		clone.Acked[id] = acked
	}
	for reason, count := range source.Drops {
		clone.Drops[reason] = count
	}
	return clone
}
