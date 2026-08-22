package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"sort"
	"strings"
	"syscall"
	"time"

	"radishlink.local/t0/internal/t0node"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(arguments []string) error {
	if len(arguments) == 0 {
		return errors.New("usage: t0node <serve|submit|status|wait|check|ensure-absent|probe>")
	}
	switch arguments[0] {
	case "serve":
		return runServe(arguments[1:])
	case "submit":
		return runSubmit(arguments[1:])
	case "status":
		return runStatus(arguments[1:])
	case "wait":
		return runWait(arguments[1:])
	case "check":
		return runCheck(arguments[1:])
	case "ensure-absent":
		return runEnsureAbsent(arguments[1:])
	case "probe":
		return runProbe(arguments[1:])
	default:
		return fmt.Errorf("unknown command: %s", arguments[0])
	}
}

func runServe(arguments []string) error {
	flags := flag.NewFlagSet("serve", flag.ContinueOnError)
	nodeID := flags.String("id", "", "test node id")
	listen := flags.String("listen", ":7000", "listen address")
	routesValue := flags.String("routes", "", "comma-separated destination=address routes")
	dataDirectory := flags.String("data-dir", "", "persistent state directory")
	retryInterval := flags.Duration("retry-interval", 100*time.Millisecond, "store-forward retry interval")
	dialTimeout := flags.Duration("dial-timeout", 500*time.Millisecond, "next-hop dial timeout")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	routes, err := parseRoutes(*routesValue)
	if err != nil {
		return err
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	node, err := t0node.New(t0node.Config{
		NodeID:        *nodeID,
		ListenAddress: *listen,
		Routes:        routes,
		DataDirectory: *dataDirectory,
		RetryInterval: *retryInterval,
		DialTimeout:   *dialTimeout,
		AckHopLimit:   8,
		Logger:        logger,
	})
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	return node.Run(ctx)
}

func parseRoutes(value string) (map[string]string, error) {
	routes := make(map[string]string)
	if value == "" {
		return routes, nil
	}
	for _, item := range strings.Split(value, ",") {
		destination, address, found := strings.Cut(item, "=")
		if !found || destination == "" || address == "" {
			return nil, fmt.Errorf("invalid route %q; expected destination=address", item)
		}
		if _, exists := routes[destination]; exists {
			return nil, fmt.Errorf("duplicate route for %s", destination)
		}
		routes[destination] = address
	}
	return routes, nil
}

func runSubmit(arguments []string) error {
	flags := flag.NewFlagSet("submit", flag.ContinueOnError)
	address := flags.String("address", "127.0.0.1:7000", "node control address")
	origin := flags.String("origin", "", "origin node id")
	destination := flags.String("destination", "", "destination node id")
	messageID := flags.String("id", "", "message id")
	testBody := flags.String("test-body", "synthetic-t0-payload", "unencrypted synthetic test body")
	hopLimit := flags.Int("hop-limit", 2, "maximum forwarding hops")
	lifetime := flags.Duration("lifetime", 10*time.Second, "message lifetime")
	force := flags.Bool("force", false, "resubmit an already acknowledged id for duplicate testing")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	frame := t0node.Frame{
		Version:         t0node.ProtocolVersion,
		Kind:            t0node.FrameMessage,
		ID:              *messageID,
		Origin:          *origin,
		Destination:     *destination,
		HopLimit:        *hopLimit,
		ExpiresAtUnixMs: time.Now().Add(*lifetime).UnixMilli(),
		TestBody:        *testBody,
	}
	response, err := t0node.Call(*address, t0node.Request{Operation: "submit", Frame: &frame, Force: *force}, 2*time.Second)
	if err != nil {
		return err
	}
	if err := printJSON(response); err != nil {
		return err
	}
	if !response.Accepted {
		return fmt.Errorf("submission rejected: %s", response.Reason)
	}
	return nil
}

func runStatus(arguments []string) error {
	flags := flag.NewFlagSet("status", flag.ContinueOnError)
	address := flags.String("address", "127.0.0.1:7000", "node control address")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	status, err := fetchStatus(*address)
	if err != nil {
		return err
	}
	return printJSON(status)
}

func runWait(arguments []string) error {
	flags := flag.NewFlagSet("wait", flag.ContinueOnError)
	address := flags.String("address", "127.0.0.1:7000", "node control address")
	condition := flags.String("condition", "ready", "ready, acked, delivered, pending, or not-pending")
	id := flags.String("id", "", "message id used by the condition")
	timeout := flags.Duration("timeout", 5*time.Second, "wait timeout")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	deadline := time.Now().Add(*timeout)
	var lastError error
	for {
		status, err := fetchStatus(*address)
		if err == nil {
			matched, matchErr := statusMatches(status, *condition, *id)
			if matchErr != nil {
				return matchErr
			}
			if matched {
				return printJSON(map[string]string{"condition": *condition, "id": *id, "result": "pass"})
			}
		} else {
			lastError = err
		}
		if time.Now().After(deadline) {
			if lastError != nil {
				return fmt.Errorf("condition %s timed out; last status error: %w", *condition, lastError)
			}
			return fmt.Errorf("condition %s for %s timed out", *condition, *id)
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func statusMatches(status t0node.Status, condition, id string) (bool, error) {
	switch condition {
	case "ready":
		return status.NodeID != "", nil
	case "acked":
		return contains(status.Acked, id), nil
	case "delivered":
		return status.Delivered[id] > 0, nil
	case "pending":
		return contains(status.Pending, id), nil
	case "not-pending":
		return !contains(status.Pending, id), nil
	default:
		return false, fmt.Errorf("unsupported condition: %s", condition)
	}
}

func runCheck(arguments []string) error {
	flags := flag.NewFlagSet("check", flag.ContinueOnError)
	address := flags.String("address", "127.0.0.1:7000", "node control address")
	deliveredID := flags.String("delivered-id", "", "message id whose delivery count is checked")
	deliveryCount := flags.Int("delivery-count", -1, "expected delivery count")
	dropReason := flags.String("drop-reason", "", "drop reason to check")
	dropMinimum := flags.Int("drop-min", -1, "minimum drop count")
	duplicateMinimum := flags.Int("duplicate-min", -1, "minimum duplicate frame count")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	status, err := fetchStatus(*address)
	if err != nil {
		return err
	}
	if *deliveryCount >= 0 && status.Delivered[*deliveredID] != *deliveryCount {
		return fmt.Errorf("delivery count for %s: got %d, want %d", *deliveredID, status.Delivered[*deliveredID], *deliveryCount)
	}
	if *dropMinimum >= 0 && status.Drops[*dropReason] < *dropMinimum {
		return fmt.Errorf("drop count for %s: got %d, want at least %d", *dropReason, status.Drops[*dropReason], *dropMinimum)
	}
	if *duplicateMinimum >= 0 && status.DuplicateFrames < *duplicateMinimum {
		return fmt.Errorf("duplicate frame count: got %d, want at least %d", status.DuplicateFrames, *duplicateMinimum)
	}
	return printJSON(map[string]string{"result": "pass", "node_id": status.NodeID})
}

func runEnsureAbsent(arguments []string) error {
	flags := flag.NewFlagSet("ensure-absent", flag.ContinueOnError)
	address := flags.String("address", "127.0.0.1:7000", "node control address")
	messageID := flags.String("delivered-id", "", "message id that must remain undelivered")
	duration := flags.Duration("duration", time.Second, "observation duration")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	deadline := time.Now().Add(*duration)
	for {
		status, err := fetchStatus(*address)
		if err != nil {
			return err
		}
		if status.Delivered[*messageID] != 0 {
			return fmt.Errorf("message %s was unexpectedly delivered", *messageID)
		}
		if time.Now().After(deadline) {
			return printJSON(map[string]string{"result": "pass", "id": *messageID})
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func runProbe(arguments []string) error {
	flags := flag.NewFlagSet("probe", flag.ContinueOnError)
	address := flags.String("address", "", "target address")
	expect := flags.String("expect", "reachable", "reachable or unreachable")
	timeout := flags.Duration("timeout", 500*time.Millisecond, "dial timeout")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	connection, err := net.DialTimeout("tcp", *address, *timeout)
	if err == nil {
		_ = connection.Close()
	}
	reachable := err == nil
	switch *expect {
	case "reachable":
		if !reachable {
			return fmt.Errorf("expected %s to be reachable: %w", *address, err)
		}
	case "unreachable":
		if reachable {
			return fmt.Errorf("expected %s to be unreachable", *address)
		}
	default:
		return fmt.Errorf("unsupported probe expectation: %s", *expect)
	}
	return printJSON(map[string]any{"address": *address, "expected": *expect, "result": "pass"})
}

func fetchStatus(address string) (t0node.Status, error) {
	response, err := t0node.Call(address, t0node.Request{Operation: "status"}, time.Second)
	if err != nil {
		return t0node.Status{}, err
	}
	if !response.Accepted || response.Status == nil {
		return t0node.Status{}, fmt.Errorf("status rejected: %s", response.Reason)
	}
	return *response.Status, nil
}

func contains(items []string, expected string) bool {
	index := sort.SearchStrings(items, expected)
	return index < len(items) && items[index] == expected
}

func printJSON(value any) error {
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	return encoder.Encode(value)
}
