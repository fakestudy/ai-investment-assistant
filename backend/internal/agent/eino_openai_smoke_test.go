package agent_test

import (
	"testing"

	openai "github.com/cloudwego/eino-ext/components/model/openai"
	"github.com/cloudwego/eino/schema"
)

func TestEinoOpenAIConfigAndSchemaCompile(t *testing.T) {
	temperature := float32(0.2)
	config := openai.ChatModelConfig{
		APIKey:      "test-key",
		Model:       "test-model",
		Temperature: &temperature,
		ResponseFormat: &openai.ChatCompletionResponseFormat{
			Type: openai.ChatCompletionResponseFormatTypeJSONObject,
		},
	}
	message := schema.Message{
		Role:    schema.User,
		Content: "ping",
	}

	if config.Model == "" || message.Role != schema.User {
		t.Fatal("Eino/OpenAI smoke types are not initialized as expected")
	}
}
