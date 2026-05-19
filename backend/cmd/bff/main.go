package main

import (
	"context"
	"log"
	"net/http"

	"github.com/bytedance/ai-investment-assistant/backend/internal/bff"
)

type localAgent struct{}

func (localAgent) StreamAnswer(ctx context.Context, req bff.AgentStreamRequest) (<-chan bff.AgentChunk, error) {
	ch := make(chan bff.AgentChunk, 4)
	go func() {
		defer close(ch)
		ch <- bff.AgentChunk{Type: bff.AgentChunkMetadata}
		ch <- bff.AgentChunk{Type: bff.AgentChunkDelta, Content: "这是本地 BFF fake Agent 输出。"}
		ch <- bff.AgentChunk{Type: bff.AgentChunkDelta, Content: "真实 Agent 接入会在后续任务替换。"}
		ch <- bff.AgentChunk{Type: bff.AgentChunkDone, FinishReason: "stop"}
	}()
	return ch, nil
}

func main() {
	server := bff.NewServer(localAgent{})
	log.Println("BFF listening on :8080")
	if err := http.ListenAndServe(":8080", server); err != nil {
		log.Fatal(err)
	}
}
