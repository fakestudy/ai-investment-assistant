package bff

import (
	"testing"

	investmentv1 "github.com/bytedance/ai-investment-assistant/backend/gen/go/investment/v1"
)

func TestProtoChunkToAgentChunkMapsDelta(t *testing.T) {
	got := protoChunkToAgentChunk(&investmentv1.AnswerChunk{
		Type:    investmentv1.AnswerChunkType_ANSWER_CHUNK_TYPE_DELTA,
		Content: "hello",
	})

	if got.Type != AgentChunkDelta || got.Content != "hello" {
		t.Fatalf("unexpected mapped chunk: %#v", got)
	}
}
