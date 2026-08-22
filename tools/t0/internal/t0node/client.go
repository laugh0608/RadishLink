package t0node

import (
	"encoding/json"
	"fmt"
	"net"
	"time"
)

func Call(address string, request Request, timeout time.Duration) (Response, error) {
	connection, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		return Response{}, fmt.Errorf("connect to %s: %w", address, err)
	}
	defer connection.Close()
	if err := connection.SetDeadline(time.Now().Add(timeout)); err != nil {
		return Response{}, fmt.Errorf("set connection deadline: %w", err)
	}

	if err := json.NewEncoder(connection).Encode(request); err != nil {
		return Response{}, fmt.Errorf("send request: %w", err)
	}
	var response Response
	if err := json.NewDecoder(connection).Decode(&response); err != nil {
		return Response{}, fmt.Errorf("receive response: %w", err)
	}
	return response, nil
}
