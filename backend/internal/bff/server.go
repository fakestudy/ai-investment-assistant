package bff

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
)

type Server struct {
	router chi.Router
	agent  AgentStreamClient
}

func NewServer(agent AgentStreamClient) *Server {
	s := &Server{router: chi.NewRouter(), agent: agent}
	s.router.Use(corsMiddleware)
	s.router.Options("/*", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	})
	s.router.Post("/api/chat/stream", s.handleChatStream)
	s.router.Get("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	return s
}

func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	s.router.ServeHTTP(w, r)
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if isAllowedOrigin(origin) {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Authorization, Content-Type, Accept")
		}
		next.ServeHTTP(w, r)
	})
}

func isAllowedOrigin(origin string) bool {
	switch origin {
	case "http://localhost:3000", "http://127.0.0.1:3000":
		return true
	default:
		return false
	}
}

func (s *Server) handleChatStream(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("Authorization") == "" {
		writeJSONError(w, http.StatusUnauthorized, "UNAUTHORIZED", "authorization is required")
		return
	}

	req, err := decodeChatStreamRequest(r)
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "INVALID_REQUEST", err.Error())
		return
	}

	conversationID := req.ConversationID
	if conversationID == "" {
		conversationID = newID("conversation")
	}
	userMessageID := newID("message-user")
	assistantMessageID := newID("message-assistant")

	stream, err := s.agent.StreamAnswer(r.Context(), AgentStreamRequest{
		UserID:             "local-user",
		ConversationID:     conversationID,
		UserMessageID:      userMessageID,
		AssistantMessageID: assistantMessageID,
		Content:            req.Content,
		PageContext:        req.PageContext,
	})
	if err != nil {
		writeJSONError(w, http.StatusBadGateway, "AGENT_UNAVAILABLE", err.Error())
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	flusher, _ := w.(http.Flusher)

	for chunk := range stream {
		if chunk.Type == AgentChunkMetadata {
			chunk.ConversationID = conversationID
			chunk.UserMessageID = userMessageID
			chunk.AssistantMessageID = assistantMessageID
		}
		event, err := chunkToSSE(chunk)
		if err != nil {
			event = encodeSSE("error", `{"code":"SSE_ENCODE_FAILED","message":"failed to encode stream event"}`)
		}
		_, _ = w.Write([]byte(event))
		if flusher != nil {
			flusher.Flush()
		}
	}
}

func writeJSONError(w http.ResponseWriter, status int, code string, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"code": code, "message": message})
}

func newID(prefix string) string {
	var bytes [8]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return prefix + "-0000000000000000"
	}
	return prefix + "-" + hex.EncodeToString(bytes[:])
}
