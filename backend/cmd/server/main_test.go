package main

import (
	"net/http"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
)

func TestNewHTTPServerConfiguresTimeouts(t *testing.T) {
	server := newHTTPServer(config.Config{Port: "9090"}, http.NewServeMux())

	if server.Addr != ":9090" {
		t.Fatalf("Addr = %q, want :9090", server.Addr)
	}
	if server.ReadHeaderTimeout != 5*time.Second {
		t.Fatalf("ReadHeaderTimeout = %s, want 5s", server.ReadHeaderTimeout)
	}
	if server.ReadTimeout != 30*time.Second {
		t.Fatalf("ReadTimeout = %s, want 30s", server.ReadTimeout)
	}
	if server.WriteTimeout != 0 {
		t.Fatalf("WriteTimeout = %s, want 0 for streaming responses", server.WriteTimeout)
	}
	if server.IdleTimeout != 120*time.Second {
		t.Fatalf("IdleTimeout = %s, want 120s", server.IdleTimeout)
	}
}
