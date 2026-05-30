package tools

import (
	"context"
	"net/http"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
)

func TestFetchTransportBlocksPrivateAddressDuringDial(t *testing.T) {
	client := newHTTPClient(config.Config{HTTPClientTimeout: time.Second})
	transport, ok := client.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("transport type = %T, want *http.Transport", client.Transport)
	}

	conn, err := transport.DialContext(context.Background(), "tcp", "127.0.0.1:80")
	if conn != nil {
		_ = conn.Close()
		t.Fatal("DialContext returned a connection, want private address blocked")
	}
	if err == nil {
		t.Fatal("DialContext error = nil, want private address blocked")
	}
	if !strings.Contains(err.Error(), "private") {
		t.Fatalf("DialContext error = %q, want private address message", err.Error())
	}
}

func TestFetchTransportCanAllowPrivateAddressForTests(t *testing.T) {
	client := newHTTPClient(config.Config{HTTPClientTimeout: time.Second, FetchAllowPrivate: true})
	transport, ok := client.Transport.(*http.Transport)
	if !ok {
		t.Fatalf("transport type = %T, want *http.Transport", client.Transport)
	}

	_, err := transport.DialContext(context.Background(), "tcp", "127.0.0.1:1")
	if err != nil && strings.Contains(err.Error(), "private") {
		t.Fatalf("DialContext error = %q, want no private address rejection when allowed", err.Error())
	}
}
