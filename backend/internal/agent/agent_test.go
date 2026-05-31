package agent_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/agent"
	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

func TestNewEinoAgentWithoutKeyReturnsConfigError(t *testing.T) {
	agentUnderTest := agent.NewEinoAgent(config.Config{
		HTTPClientTimeout: time.Second,
	}, tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second}))

	events, errs := agentUnderTest.Stream(context.Background(), []agent.Message{
		{Role: "user", Content: "Explain AI moats"},
	})

	err := collectAgentError(t, events, errs)
	if err == nil || !strings.Contains(err.Error(), "DEEPSEEK_API_KEY is required") {
		t.Fatalf("agent error = %v, want missing DEEPSEEK_API_KEY error", err)
	}
}

func collectAgentError(t *testing.T, events <-chan agent.Event, errs <-chan error) error {
	t.Helper()
	for events != nil || errs != nil {
		select {
		case _, ok := <-events:
			if !ok {
				events = nil
			}
		case err, ok := <-errs:
			if !ok {
				errs = nil
				continue
			}
			if err != nil {
				return err
			}
		case <-time.After(time.Second):
			t.Fatal("timed out collecting agent error")
		}
	}
	return nil
}
