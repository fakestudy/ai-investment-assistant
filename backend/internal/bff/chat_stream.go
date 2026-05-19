package bff

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
)

type PageContext struct {
	Route          string `json:"route"`
	Symbol         string `json:"symbol"`
	EventID        string `json:"eventId"`
	ResearchCardID string `json:"researchCardId"`
}

type chatStreamRequest struct {
	ConversationID string      `json:"conversationId"`
	Content        string      `json:"content"`
	PageContext    PageContext `json:"pageContext"`
}

type AgentChunkType string

const (
	AgentChunkMetadata AgentChunkType = "metadata"
	AgentChunkDelta    AgentChunkType = "delta"
	AgentChunkDone     AgentChunkType = "done"
	AgentChunkError    AgentChunkType = "error"
)

type AgentChunk struct {
	Type               AgentChunkType
	ConversationID     string
	UserMessageID      string
	AssistantMessageID string
	Content            string
	FinishReason       string
	ErrorCode          string
	ErrorMessage       string
}

type AgentStreamClient interface {
	StreamAnswer(ctx context.Context, req AgentStreamRequest) (<-chan AgentChunk, error)
}

type AgentStreamRequest struct {
	UserID             string
	ConversationID     string
	UserMessageID      string
	AssistantMessageID string
	Content            string
	PageContext        PageContext
}

func validateChatRequest(req chatStreamRequest) error {
	content := strings.TrimSpace(req.Content)
	if content == "" {
		return errors.New("content is required")
	}
	if len([]rune(content)) > 4000 {
		return errors.New("content is too long")
	}
	return nil
}

func encodeSSE(event string, data string) string {
	return fmt.Sprintf("event: %s\ndata: %s\n\n", event, data)
}

func chunkToSSE(chunk AgentChunk) (string, error) {
	switch chunk.Type {
	case AgentChunkMetadata:
		payload := map[string]string{
			"conversationId":     chunk.ConversationID,
			"userMessageId":      chunk.UserMessageID,
			"assistantMessageId": chunk.AssistantMessageID,
		}
		data, err := json.Marshal(payload)
		if err != nil {
			return "", err
		}
		return encodeSSE("metadata", string(data)), nil
	case AgentChunkDelta:
		data, err := json.Marshal(map[string]string{"content": chunk.Content})
		if err != nil {
			return "", err
		}
		return encodeSSE("delta", string(data)), nil
	case AgentChunkDone:
		data, err := json.Marshal(map[string]string{"finishReason": chunk.FinishReason})
		if err != nil {
			return "", err
		}
		return encodeSSE("done", string(data)), nil
	case AgentChunkError:
		data, err := json.Marshal(map[string]string{
			"code":    chunk.ErrorCode,
			"message": chunk.ErrorMessage,
		})
		if err != nil {
			return "", err
		}
		return encodeSSE("error", string(data)), nil
	default:
		return "", fmt.Errorf("unsupported chunk type %q", chunk.Type)
	}
}

func decodeChatStreamRequest(r *http.Request) (chatStreamRequest, error) {
	var req chatStreamRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		return chatStreamRequest{}, err
	}
	return req, validateChatRequest(req)
}
