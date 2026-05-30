package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"ai-investment-assistant/backend/internal/chat"
	"ai-investment-assistant/backend/internal/conversation"
)

func TestWriteSSEEventsWritesDataLinesAndFlushes(t *testing.T) {
	events := make(chan chat.StreamEvent, 2)
	events <- chat.StreamEvent{Type: "delta", MessageID: "assistant-id", Text: "hello"}
	events <- chat.StreamEvent{Type: "done", MessageID: "assistant-id"}
	close(events)
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/chat/stream", nil)

	writeSSEEvents(response, request, events)

	if got := response.Header().Get("Content-Type"); got != "text/event-stream" {
		t.Fatalf("Content-Type = %q, want text/event-stream", got)
	}
	body := response.Body.String()
	if !strings.Contains(body, "data: {\"type\":\"delta\",\"messageId\":\"assistant-id\",\"text\":\"hello\"}\n\n") {
		t.Fatalf("SSE body = %q, want delta data line", body)
	}
	if !strings.Contains(body, "data: {\"type\":\"done\",\"messageId\":\"assistant-id\"}\n\n") {
		t.Fatalf("SSE body = %q, want done data line", body)
	}
}

func TestRouterStreamsChatSSE(t *testing.T) {
	router, conversations := newTestRouter(t)
	created, err := conversations.CreateConversation(t.Context())
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}

	response := performRequest(router, http.MethodPost, "/api/chat/stream", map[string]string{
		"conversationId": created.ID,
		"message":        "Hello assistant",
	})

	if response.Code != http.StatusOK {
		t.Fatalf("POST /api/chat/stream status = %d, want %d; body = %s", response.Code, http.StatusOK, response.Body.String())
	}
	if got := response.Header().Get("Content-Type"); got != "text/event-stream" {
		t.Fatalf("Content-Type = %q, want text/event-stream", got)
	}
	events := decodeSSEEvents(t, response.Body.String())
	assertSSEEventTypes(t, events, []string{"message_created", "delta", "title", "done"})
	if events[1]["text"] != "Hello assistant" {
		t.Fatalf("delta text = %#v, want Hello assistant", events[1]["text"])
	}
}

func TestRouterRejectsInvalidChatStreamRequest(t *testing.T) {
	router, _ := newTestRouter(t)

	response := performRequest(router, http.MethodPost, "/api/chat/stream", map[string]string{
		"conversationId": "conversation-id",
		"message":        "   ",
	})

	if response.Code != http.StatusBadRequest {
		t.Fatalf("POST /api/chat/stream status = %d, want %d; body = %s", response.Code, http.StatusBadRequest, response.Body.String())
	}
	assertJSONField(t, response.Body.Bytes(), "message", "message is required")
}

func decodeSSEEvents(t *testing.T, body string) []map[string]any {
	t.Helper()

	var events []map[string]any
	for _, block := range strings.Split(strings.TrimSpace(body), "\n\n") {
		line := strings.TrimPrefix(block, "data: ")
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatalf("json.Unmarshal SSE event error = %v; line = %q", err, line)
		}
		events = append(events, event)
	}
	return events
}

func assertSSEEventTypes(t *testing.T, events []map[string]any, want []string) {
	t.Helper()

	if len(events) != len(want) {
		t.Fatalf("SSE events len = %d, want %d; events = %+v", len(events), len(want), events)
	}
	for i, event := range events {
		if event["type"] != want[i] {
			t.Fatalf("SSE events[%d].type = %#v, want %q; events = %+v", i, event["type"], want[i], events)
		}
	}
}

var _ = conversation.ChatMessage{}
