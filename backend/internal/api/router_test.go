package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"ai-investment-assistant/backend/internal/conversation"
	"ai-investment-assistant/backend/internal/store"
	"github.com/gin-gonic/gin"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var testDBSequence uint64

func TestRouterHealthReturnsOK(t *testing.T) {
	router, _ := newTestRouter(t)

	response := performRequest(router, http.MethodGet, "/api/health", nil)

	if response.Code != http.StatusOK {
		t.Fatalf("GET /api/health status = %d, want %d; body = %s", response.Code, http.StatusOK, response.Body.String())
	}
	assertJSONField(t, response.Body.Bytes(), "status", "ok")
}

func TestRouterCreatesListsRenamesAndDeletesConversation(t *testing.T) {
	router, _ := newTestRouter(t)

	createResponse := performRequest(router, http.MethodPost, "/api/conversations", nil)
	if createResponse.Code != http.StatusCreated {
		t.Fatalf("POST /api/conversations status = %d, want %d; body = %s", createResponse.Code, http.StatusCreated, createResponse.Body.String())
	}
	created := decodeObject(t, createResponse.Body.Bytes())
	conversationID := requireStringField(t, created, "id")
	assertObjectField(t, created, "title", "New chat")
	requireStringField(t, created, "createdAt")
	requireStringField(t, created, "updatedAt")

	renameResponse := performRequest(router, http.MethodPatch, "/api/conversations/"+conversationID, map[string]string{
		"title": "Investment thesis",
	})
	if renameResponse.Code != http.StatusOK {
		t.Fatalf("PATCH /api/conversations/:id status = %d, want %d; body = %s", renameResponse.Code, http.StatusOK, renameResponse.Body.String())
	}
	renamed := decodeObject(t, renameResponse.Body.Bytes())
	assertObjectField(t, renamed, "id", conversationID)
	assertObjectField(t, renamed, "title", "Investment thesis")

	listResponse := performRequest(router, http.MethodGet, "/api/conversations", nil)
	if listResponse.Code != http.StatusOK {
		t.Fatalf("GET /api/conversations status = %d, want %d; body = %s", listResponse.Code, http.StatusOK, listResponse.Body.String())
	}
	listed := decodeArray(t, listResponse.Body.Bytes())
	if len(listed) != 1 {
		t.Fatalf("GET /api/conversations returned %d conversations, want 1", len(listed))
	}
	assertObjectField(t, listed[0], "id", conversationID)
	assertObjectField(t, listed[0], "title", "Investment thesis")

	deleteResponse := performRequest(router, http.MethodDelete, "/api/conversations/"+conversationID, nil)
	if deleteResponse.Code != http.StatusNoContent {
		t.Fatalf("DELETE /api/conversations/:id status = %d, want %d; body = %s", deleteResponse.Code, http.StatusNoContent, deleteResponse.Body.String())
	}
}

func TestRouterListsAndEditsMessages(t *testing.T) {
	router, svc := newTestRouter(t)
	ctx := context.Background()
	conversationRow, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	message, err := svc.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: conversationRow.ID,
		Role:           "user",
		Content:        "Original question",
		Status:         "complete",
	})
	if err != nil {
		t.Fatalf("CreateMessage() error = %v", err)
	}

	listResponse := performRequest(router, http.MethodGet, "/api/conversations/"+conversationRow.ID+"/messages", nil)
	if listResponse.Code != http.StatusOK {
		t.Fatalf("GET /api/conversations/:id/messages status = %d, want %d; body = %s", listResponse.Code, http.StatusOK, listResponse.Body.String())
	}
	messages := decodeArray(t, listResponse.Body.Bytes())
	if len(messages) != 1 {
		t.Fatalf("GET /api/conversations/:id/messages returned %d messages, want 1", len(messages))
	}
	assertObjectField(t, messages[0], "id", message.ID)
	assertObjectField(t, messages[0], "conversationId", conversationRow.ID)
	assertObjectField(t, messages[0], "content", "Original question")

	editResponse := performRequest(router, http.MethodPatch, "/api/messages/"+message.ID, map[string]string{
		"content": "Revised question",
	})
	if editResponse.Code != http.StatusOK {
		t.Fatalf("PATCH /api/messages/:id status = %d, want %d; body = %s", editResponse.Code, http.StatusOK, editResponse.Body.String())
	}
	edited := decodeObject(t, editResponse.Body.Bytes())
	assertObjectField(t, edited, "id", message.ID)
	assertObjectField(t, edited, "conversationId", conversationRow.ID)
	assertObjectField(t, edited, "content", "Revised question")
}

func TestRouterReturnsValidationErrors(t *testing.T) {
	router, svc := newTestRouter(t)
	ctx := context.Background()
	conversationRow, err := svc.CreateConversation(ctx)
	if err != nil {
		t.Fatalf("CreateConversation() error = %v", err)
	}
	message, err := svc.CreateMessage(ctx, conversation.CreateMessageInput{
		ConversationID: conversationRow.ID,
		Role:           "user",
		Content:        "Question",
		Status:         "complete",
	})
	if err != nil {
		t.Fatalf("CreateMessage() error = %v", err)
	}

	cases := []struct {
		name   string
		method string
		path   string
		body   any
	}{
		{name: "invalid JSON", method: http.MethodPatch, path: "/api/conversations/" + conversationRow.ID, body: "{not-json"},
		{name: "empty title", method: http.MethodPatch, path: "/api/conversations/" + conversationRow.ID, body: map[string]string{"title": "   "}},
		{name: "empty content", method: http.MethodPatch, path: "/api/messages/" + message.ID, body: map[string]string{"content": "   "}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			response := performRequest(router, tc.method, tc.path, tc.body)
			if response.Code != http.StatusBadRequest {
				t.Fatalf("%s %s status = %d, want %d; body = %s", tc.method, tc.path, response.Code, http.StatusBadRequest, response.Body.String())
			}
			requireStringField(t, decodeObject(t, response.Body.Bytes()), "message")
		})
	}
}

func TestRouterReturnsNotFoundErrors(t *testing.T) {
	router, _ := newTestRouter(t)

	cases := []struct {
		method string
		path   string
		body   any
	}{
		{method: http.MethodPatch, path: "/api/conversations/missing-conversation", body: map[string]string{"title": "Missing"}},
		{method: http.MethodDelete, path: "/api/conversations/missing-conversation", body: nil},
		{method: http.MethodGet, path: "/api/conversations/missing-conversation/messages", body: nil},
		{method: http.MethodPatch, path: "/api/messages/missing-message", body: map[string]string{"content": "Missing"}},
	}

	for _, tc := range cases {
		response := performRequest(router, tc.method, tc.path, tc.body)
		if response.Code != http.StatusNotFound {
			t.Fatalf("%s %s status = %d, want %d; body = %s", tc.method, tc.path, response.Code, http.StatusNotFound, response.Body.String())
		}
		assertJSONField(t, response.Body.Bytes(), "message", "not found")
	}
}

func newTestRouter(t *testing.T) (*gin.Engine, *conversation.Service) {
	t.Helper()
	gin.SetMode(gin.TestMode)

	sequence := atomic.AddUint64(&testDBSequence, 1)
	dbName := strings.NewReplacer("/", "_", " ", "_").Replace(t.Name())
	db, err := gorm.Open(sqlite.Open(fmt.Sprintf("file:%s_%d?mode=memory&cache=shared&_foreign_keys=on", dbName, sequence)), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		t.Fatalf("open test DB error = %v", err)
	}
	if err := store.AutoMigrate(t.Context(), db); err != nil {
		t.Fatalf("AutoMigrate() error = %v", err)
	}

	svc := conversation.NewService(db)
	return NewRouter(svc), svc
}

func performRequest(router http.Handler, method string, path string, body any) *httptest.ResponseRecorder {
	var requestBody *bytes.Reader
	switch value := body.(type) {
	case nil:
		requestBody = bytes.NewReader(nil)
	case string:
		requestBody = bytes.NewReader([]byte(value))
	default:
		payload, err := json.Marshal(value)
		if err != nil {
			panic(err)
		}
		requestBody = bytes.NewReader(payload)
	}

	request := httptest.NewRequest(method, path, requestBody)
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	return response
}

func decodeObject(t *testing.T, payload []byte) map[string]any {
	t.Helper()

	var object map[string]any
	if err := json.Unmarshal(payload, &object); err != nil {
		t.Fatalf("json.Unmarshal object error = %v; payload = %s", err, payload)
	}
	return object
}

func decodeArray(t *testing.T, payload []byte) []map[string]any {
	t.Helper()

	var array []map[string]any
	if err := json.Unmarshal(payload, &array); err != nil {
		t.Fatalf("json.Unmarshal array error = %v; payload = %s", err, payload)
	}
	return array
}

func assertJSONField(t *testing.T, payload []byte, field string, want string) {
	t.Helper()
	assertObjectField(t, decodeObject(t, payload), field, want)
}

func assertObjectField(t *testing.T, object map[string]any, field string, want string) {
	t.Helper()

	got, ok := object[field].(string)
	if !ok {
		t.Fatalf("field %q = %#v, want string %q", field, object[field], want)
	}
	if got != want {
		t.Fatalf("field %q = %q, want %q", field, got, want)
	}
}

func requireStringField(t *testing.T, object map[string]any, field string) string {
	t.Helper()

	value, ok := object[field].(string)
	if !ok || value == "" {
		t.Fatalf("field %q = %#v, want non-empty string", field, object[field])
	}
	return value
}
