package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

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

func TestWriteSSEEventsSerializesErrorTextAsMessage(t *testing.T) {
	events := make(chan chat.StreamEvent, 1)
	events <- chat.StreamEvent{Type: "error", MessageID: "assistant-id", Text: "rate limited"}
	close(events)
	response := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/chat/stream", nil)

	writeSSEEvents(response, request, events)

	body := response.Body.String()
	if !strings.Contains(body, "data: {\"type\":\"error\",\"messageId\":\"assistant-id\",\"message\":\"rate limited\"}\n\n") {
		t.Fatalf("SSE body = %q, want error message field for frontend contract", body)
	}
	if strings.Contains(body, "\"text\":\"rate limited\"") {
		t.Fatalf("SSE body = %q, must not encode error text as text field", body)
	}
}

func TestRouterStreamsChatSSE(t *testing.T) {
	agent := newStaticAPIAgent(chat.AgentEvent{Kind: "delta", Text: "Hello assistant"})
	_, conversations := newTestRouterWithChat(t, nil)
	router := NewRouter(conversations, chat.NewService(conversations, agent))
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

func TestRouterResumesActiveChatStream(t *testing.T) {
	agent := newReleasedAPIAgent(
		chat.AgentEvent{Kind: "delta", Text: "first"},
		chat.AgentEvent{Kind: "delta", Text: " second"},
	)
	_, conversations := newTestRouterWithChat(t, nil)
	chats := chat.NewService(conversations, agent)
	router := NewRouter(conversations, chats)

	created, err := conversations.CreateConversation(t.Context())
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}

	streamCtx, cancel := context.WithCancel(context.Background())
	events, err := chats.Stream(streamCtx, chat.StreamChatRequest{
		ConversationID: created.ID,
		Message:        "Resume through route",
	})
	if err != nil {
		t.Fatalf("Stream() error = %v", err)
	}
	createdEvent := <-events
	if createdEvent.Type != "message_created" {
		t.Fatalf("first event type = %q, want message_created", createdEvent.Type)
	}
	firstDelta := <-events
	if firstDelta.Type != "delta" || firstDelta.Text != "first" {
		t.Fatalf("first delta = %+v, want first", firstDelta)
	}
	cancel()

	request := httptest.NewRequest(http.MethodGet, "/api/chat/streams/"+createdEvent.Message.ID, nil)
	response := newSignalingRecorder()
	done := make(chan struct{})
	go func() {
		router.ServeHTTP(response, request)
		close(done)
	}()
	waitForAPISignal(t, response.wrote, "resume route to write replayed events")
	agent.releaseSecond()
	waitForAPISignal(t, done, "resume route to finish")

	if response.Code != http.StatusOK {
		t.Fatalf("GET resume stream status = %d, want %d; body = %s", response.Code, http.StatusOK, response.Body.String())
	}
	resumed := decodeSSEEvents(t, response.Body.String())
	assertSSEEventTypes(t, resumed, []string{"message_created", "delta", "delta", "title", "done"})
	if resumed[1]["text"] != "first" || resumed[2]["text"] != " second" {
		t.Fatalf("resumed deltas = [%#v %#v], want replayed first and live second", resumed[1]["text"], resumed[2]["text"])
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

type staticAPIAgent struct {
	events []chat.AgentEvent
}

func newStaticAPIAgent(events ...chat.AgentEvent) staticAPIAgent {
	return staticAPIAgent{events: events}
}

func (a staticAPIAgent) Stream(ctx context.Context, messages []chat.AgentMessage) (<-chan chat.AgentEvent, <-chan error) {
	events := make(chan chat.AgentEvent)
	errs := make(chan error, 1)
	go func() {
		defer close(events)
		defer close(errs)
		for _, event := range a.events {
			select {
			case <-ctx.Done():
				errs <- ctx.Err()
				return
			case events <- event:
			}
		}
	}()
	return events, errs
}

type releasedAPIAgent struct {
	first   chat.AgentEvent
	second  chat.AgentEvent
	release chan struct{}
}

func newReleasedAPIAgent(first chat.AgentEvent, second chat.AgentEvent) *releasedAPIAgent {
	return &releasedAPIAgent{
		first:   first,
		second:  second,
		release: make(chan struct{}),
	}
}

func (a *releasedAPIAgent) Stream(ctx context.Context, messages []chat.AgentMessage) (<-chan chat.AgentEvent, <-chan error) {
	events := make(chan chat.AgentEvent)
	errs := make(chan error, 1)
	go func() {
		defer close(events)
		defer close(errs)
		select {
		case <-ctx.Done():
			errs <- ctx.Err()
			return
		case events <- a.first:
		}
		select {
		case <-ctx.Done():
			errs <- ctx.Err()
			return
		case <-a.release:
		}
		select {
		case <-ctx.Done():
			errs <- ctx.Err()
		case events <- a.second:
		}
	}()
	return events, errs
}

func (a *releasedAPIAgent) releaseSecond() {
	close(a.release)
}

type signalingRecorder struct {
	*httptest.ResponseRecorder
	once  sync.Once
	wrote chan struct{}
}

func newSignalingRecorder() *signalingRecorder {
	return &signalingRecorder{
		ResponseRecorder: httptest.NewRecorder(),
		wrote:            make(chan struct{}),
	}
}

func (r *signalingRecorder) Write(payload []byte) (int, error) {
	r.once.Do(func() {
		close(r.wrote)
	})
	return r.ResponseRecorder.Write(payload)
}

func waitForAPISignal(t *testing.T, signal <-chan struct{}, label string) {
	t.Helper()

	timer := time.NewTimer(500 * time.Millisecond)
	defer timer.Stop()
	select {
	case <-signal:
	case <-timer.C:
		t.Fatalf("timed out waiting for %s", label)
	}
}
