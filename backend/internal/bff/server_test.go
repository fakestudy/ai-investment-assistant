package bff

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeAgentStreamClient struct{}

func (fakeAgentStreamClient) StreamAnswer(ctx context.Context, req AgentStreamRequest) (<-chan AgentChunk, error) {
	ch := make(chan AgentChunk, 4)
	ch <- AgentChunk{
		Type:               AgentChunkMetadata,
		ConversationID:     req.ConversationID,
		UserMessageID:      req.UserMessageID,
		AssistantMessageID: req.AssistantMessageID,
	}
	ch <- AgentChunk{Type: AgentChunkDelta, Content: "hello "}
	ch <- AgentChunk{Type: AgentChunkDelta, Content: "world"}
	ch <- AgentChunk{Type: AgentChunkDone, FinishReason: "stop"}
	close(ch)
	return ch, nil
}

func TestChatStreamRouteReturnsSSE(t *testing.T) {
	server := NewServer(fakeAgentStreamClient{})
	body := `{"content":"hello","pageContext":{"route":"/","symbol":"AAPL","eventId":"","researchCardId":""}}`
	req := httptest.NewRequest(http.MethodPost, "/api/chat/stream", strings.NewReader(body))
	req.Header.Set("Authorization", "Bearer local-dev")
	rec := httptest.NewRecorder()

	server.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Content-Type"); got != "text/event-stream" {
		t.Fatalf("Content-Type = %q, want text/event-stream", got)
	}
	bodyText := rec.Body.String()
	for _, want := range []string{"event: metadata", "event: delta", "hello ", "world", "event: done"} {
		if !strings.Contains(bodyText, want) {
			t.Fatalf("body missing %q: %s", want, bodyText)
		}
	}
}
