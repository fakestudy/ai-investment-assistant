package bff

import (
	"strings"
	"testing"
)

func TestEncodeSSE(t *testing.T) {
	got := encodeSSE("delta", `{"content":"hello"}`)
	want := "event: delta\ndata: {\"content\":\"hello\"}\n\n"
	if got != want {
		t.Fatalf("encodeSSE() = %q, want %q", got, want)
	}
}

func TestValidateChatRequestRejectsEmptyContent(t *testing.T) {
	err := validateChatRequest(chatStreamRequest{Content: strings.Repeat(" ", 3)})
	if err == nil || err.Error() != "content is required" {
		t.Fatalf("expected content is required, got %v", err)
	}
}
