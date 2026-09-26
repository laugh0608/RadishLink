package harness

import "encoding/json"

// Observation DTOs are shared with the synthetic producer; the verifier never imports it.
type ObservedKey struct {
	Version int64  `json:"envelope_version"`
	Origin  string `json:"origin"`
	Scope   string `json:"replay_scope"`
	ID      string `json:"message_id"`
}
type ObservedMessage struct {
	Key          ObservedKey `json:"key"`
	Core         string      `json:"core_sha256"`
	Deadline     int64       `json:"deadline_ms"`
	State        string      `json:"state"`
	Custody      bool        `json:"custody_seen"`
	History      bool        `json:"history_retained"`
	Transport    bool        `json:"transport_retained"`
	BodyBytes    int64       `json:"body_bytes"`
	PayloadBytes int64       `json:"payload_bytes"`
	Tombstone    int64       `json:"tombstone_until_ms"`
}
type ObservedQueue struct {
	Key      ObservedKey `json:"key"`
	Kind     string      `json:"kind"`
	Neighbor string      `json:"neighbor"`
	Start    int64       `json:"start_ms"`
	Deadline int64       `json:"deadline_ms"`
	Hops     int64       `json:"remaining_hops"`
	Status   string      `json:"status"`
	Timed    int64       `json:"timed_consumed"`
	Recovery int64       `json:"recovery_consumed"`
}
type ObservedBucket struct {
	Neighbor string `json:"neighbor"`
	Class    string `json:"class"`
	Credit   int64  `json:"credit_millibytes"`
	Last     int64  `json:"last_ms"`
}
type ResourceUsage struct {
	PayloadObjects int64 `json:"payload_objects"`
	PayloadBytes   int64 `json:"payload_bytes"`
	HistoryObjects int64 `json:"history_objects"`
	HistoryBytes   int64 `json:"history_bytes"`
	ControlObjects int64 `json:"control_objects"`
	ControlBytes   int64 `json:"control_bytes"`
}
type ObservedState struct {
	Version      int64             `json:"observation_version"`
	Node         string            `json:"node"`
	Generation   int64             `json:"generation"`
	Now          int64             `json:"now_ms"`
	SendSteps    int64             `json:"send_steps"`
	ReceiveSteps int64             `json:"receive_steps"`
	ActionCount  int64             `json:"action_count"`
	Messages     []ObservedMessage `json:"messages"`
	Queues       []ObservedQueue   `json:"queues"`
	Buckets      []ObservedBucket  `json:"buckets"`
	Usage        ResourceUsage     `json:"usage"`
}
type ObservedRetry struct {
	Key            ObservedKey `json:"key"`
	Kind           string      `json:"queue_kind"`
	Neighbor       string      `json:"neighbor"`
	Start          int64       `json:"start_ms"`
	Deadline       int64       `json:"deadline_ms"`
	Reason         string      `json:"reason"`
	Attempt        bool        `json:"attempt"`
	Send           bool        `json:"send"`
	Missed         int64       `json:"missed_slots"`
	TimedBefore    int64       `json:"timed_before"`
	TimedAfter     int64       `json:"timed_after"`
	RecoveryBefore int64       `json:"recovery_before"`
	RecoveryAfter  int64       `json:"recovery_after"`
	Cost           int64       `json:"wire_cost"`
	GlobalBefore   int64       `json:"global_credit_before"`
	GlobalAfter    int64       `json:"global_credit_after"`
	NeighborBefore int64       `json:"neighbor_credit_before"`
	NeighborAfter  int64       `json:"neighbor_credit_after"`
}

// Control DTOs belong to the evidence contract, so both producer and verifier use one wire shape.
type ControlRequest struct {
	Version    int64           `json:"control_version"`
	Session    string          `json:"session"`
	Node       string          `json:"node"`
	Sequence   int64           `json:"request_sequence"`
	Epoch      string          `json:"clock_epoch"`
	Now        int64           `json:"logical_ms"`
	Generation int64           `json:"expected_generation"`
	Operation  string          `json:"operation"`
	Detail     json.RawMessage `json:"detail"`
}
type ControlResponse struct {
	Version    int64      `json:"control_version"`
	Session    string     `json:"session"`
	Node       string     `json:"node"`
	Sequence   int64      `json:"request_sequence"`
	Local      int64      `json:"local_sequence"`
	Epoch      string     `json:"clock_epoch"`
	Now        int64      `json:"logical_ms"`
	Generation int64      `json:"generation"`
	Operation  string     `json:"operation"`
	Error      string     `json:"error_code"`
	Result     NodeResult `json:"result"`
}
type NodeFact struct {
	Now      int64           `json:"logical_ms"`
	Kind     string          `json:"kind"`
	Before   int64           `json:"generation_before"`
	After    int64           `json:"generation_after"`
	Transfer string          `json:"transfer_id"`
	Detail   json.RawMessage `json:"detail"`
}
type NodeResult struct {
	Facts      []NodeFact   `json:"facts"`
	Sends      []SendHandle `json:"sends"`
	Pending    int64        `json:"pending"`
	StoreBytes int64        `json:"store_bytes"`
}
type SendHandle struct {
	Index    int64  `json:"index"`
	Kind     string `json:"kind"`
	Neighbor string `json:"neighbor"`
}
type NetworkPeer struct {
	Node string `json:"node"`
	AB   string `json:"ab_ip"`
	BC   string `json:"bc_ip"`
}
type NodeInit struct {
	Profile NetworkProfile `json:"profile"`
	Subcase string         `json:"subcase"`
	Peers   []NetworkPeer  `json:"peers"`
	Store   string         `json:"store_alias"`
}
type ControlLink struct {
	Neighbor string `json:"neighbor"`
	Event    string `json:"event"`
}
type NodeStep struct {
	Inputs []string      `json:"inputs"`
	Links  []ControlLink `json:"links"`
}
type ReceivePermit struct {
	ID         string `json:"transfer_id"`
	Sender     string `json:"sender"`
	Generation int64  `json:"generation"`
	Index      int64  `json:"transmission_index"`
	Ordinal    int64  `json:"direction_ordinal"`
}
type NodeSend struct {
	ID      string `json:"transfer_id"`
	Index   int64  `json:"index"`
	Ordinal int64  `json:"direction_ordinal"`
}
type NodeProbe struct {
	Target   string `json:"target"`
	Listen   bool   `json:"listen"`
	Expected bool   `json:"expected_reachable"`
}
type TransportFact struct {
	ID         string      `json:"transfer_id"`
	Sender     string      `json:"sender"`
	Receiver   string      `json:"receiver"`
	Generation int64       `json:"sender_generation"`
	Index      int64       `json:"transmission_index"`
	Ordinal    int64       `json:"direction_ordinal"`
	Frame      FrameDetail `json:"frame"`
	Dropped    bool        `json:"dropped"`
	Elapsed    int64       `json:"elapsed_ns"`
}
type ProbeFact struct {
	From      string `json:"from"`
	To        string `json:"to"`
	Address   string `json:"numeric_address"`
	Expected  bool   `json:"expected_reachable"`
	Reachable bool   `json:"reachable"`
	Received  bool   `json:"received"`
	Error     string `json:"error_code"`
}
type NodeEnvironment struct {
	Store      string   `json:"store_alias"`
	Epoch      string   `json:"clock_epoch"`
	Forwarding string   `json:"ip_forward"`
	Routes     string   `json:"routes_sha256"`
	Interfaces []string `json:"interface_ips"`
}
