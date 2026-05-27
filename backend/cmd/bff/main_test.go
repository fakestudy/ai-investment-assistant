package main

import "testing"

func TestBFFHTTPAddrDefaultsTo8081(t *testing.T) {
	t.Setenv("BFF_HTTP_ADDR", "")

	if got := bffHTTPAddr(); got != ":8081" {
		t.Fatalf("bffHTTPAddr() = %q, want %q", got, ":8081")
	}
}

func TestBFFHTTPAddrUsesEnvironmentOverride(t *testing.T) {
	t.Setenv("BFF_HTTP_ADDR", "127.0.0.1:9090")

	if got := bffHTTPAddr(); got != "127.0.0.1:9090" {
		t.Fatalf("bffHTTPAddr() = %q, want %q", got, "127.0.0.1:9090")
	}
}
