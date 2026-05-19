package bff

import (
	"context"
	"io"

	investmentv1 "github.com/bytedance/ai-investment-assistant/backend/gen/go/investment/v1"
	"google.golang.org/grpc"
)

type AgentGRPCClient struct {
	client investmentv1.AgentServiceClient
}

func NewAgentGRPCClient(conn grpc.ClientConnInterface) *AgentGRPCClient {
	return &AgentGRPCClient{client: investmentv1.NewAgentServiceClient(conn)}
}

func (c *AgentGRPCClient) StreamAnswer(ctx context.Context, req AgentStreamRequest) (<-chan AgentChunk, error) {
	stream, err := c.client.StreamAnswerQuestion(ctx, &investmentv1.StreamAnswerQuestionRequest{
		UserId:             req.UserID,
		ConversationId:     req.ConversationID,
		UserMessageId:      req.UserMessageID,
		AssistantMessageId: req.AssistantMessageID,
		Content:            req.Content,
		PageContext: &investmentv1.PageContext{
			Route:          req.PageContext.Route,
			Symbol:         req.PageContext.Symbol,
			EventId:        req.PageContext.EventID,
			ResearchCardId: req.PageContext.ResearchCardID,
		},
	})
	if err != nil {
		return nil, err
	}

	out := make(chan AgentChunk)
	go func() {
		defer close(out)
		for {
			chunk, err := stream.Recv()
			if err == io.EOF {
				return
			}
			if err != nil {
				out <- AgentChunk{
					Type:         AgentChunkError,
					ErrorCode:    "AGENT_STREAM_INTERRUPTED",
					ErrorMessage: err.Error(),
				}
				return
			}
			out <- protoChunkToAgentChunk(chunk)
		}
	}()
	return out, nil
}

func protoChunkToAgentChunk(chunk *investmentv1.AnswerChunk) AgentChunk {
	switch chunk.Type {
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_METADATA:
		return AgentChunk{Type: AgentChunkMetadata}
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_DELTA:
		return AgentChunk{Type: AgentChunkDelta, Content: chunk.Content}
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_DONE:
		return AgentChunk{Type: AgentChunkDone, FinishReason: chunk.FinishReason}
	case investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_ERROR:
		return AgentChunk{
			Type:         AgentChunkError,
			ErrorCode:    chunk.ErrorCode,
			ErrorMessage: chunk.ErrorMessage,
		}
	default:
		return AgentChunk{
			Type:         AgentChunkError,
			ErrorCode:    "UNKNOWN_AGENT_CHUNK",
			ErrorMessage: "unknown agent chunk type",
		}
	}
}
