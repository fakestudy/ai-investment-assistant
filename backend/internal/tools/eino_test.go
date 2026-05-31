package tools_test

import (
	"context"
	"strings"
	"testing"
	"time"

	"ai-investment-assistant/backend/internal/config"
	"ai-investment-assistant/backend/internal/tools"
)

func TestRegistryBuildsEinoTools(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})

	einoTools, err := registry.EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	if len(einoTools) != 3 {
		t.Fatalf("EinoTools len = %d, want 3", len(einoTools))
	}

	names := map[string]bool{}
	for _, item := range einoTools {
		info, err := item.Info(context.Background())
		if err != nil {
			t.Fatalf("Info() error = %v", err)
		}
		if info.ParamsOneOf == nil {
			t.Fatalf("Info(%q).ParamsOneOf = nil, want inferred schema", info.Name)
		}
		names[info.Name] = true
	}
	if !names["web_search"] || !names["fetch_url"] || !names["current_time"] {
		t.Fatalf("tool names = %+v, want web_search, fetch_url, and current_time", names)
	}
}

func TestEinoWebSearchToolUsesExistingRegistryBehavior(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})
	einoTools, err := registry.EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	webSearch := requireEinoTool(t, einoTools, "web_search")

	output, err := webSearch.InvokableRun(context.Background(), `{"query":"AI moats"}`)
	if err != nil {
		t.Fatalf("InvokableRun(web_search) error = %v", err)
	}
	if !strings.Contains(output, `"configured":false`) {
		t.Fatalf("output = %s, want configured=false", output)
	}
}

func TestEinoWebSearchToolReturnsRegistryErrors(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})
	einoTools, err := registry.EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	webSearch := requireEinoTool(t, einoTools, "web_search")

	_, err = webSearch.InvokableRun(context.Background(), `{"query":"   "}`)
	if err == nil {
		t.Fatal("InvokableRun(web_search) error = nil, want query validation error")
	}
	if !strings.Contains(err.Error(), "query is required") {
		t.Fatalf("error = %q, want registry validation message", err.Error())
	}
}

func TestEinoCurrentTimeToolUsesExistingRegistryBehavior(t *testing.T) {
	registry := tools.NewRegistry(config.Config{HTTPClientTimeout: time.Second})
	einoTools, err := registry.EinoTools(context.Background())
	if err != nil {
		t.Fatalf("EinoTools() error = %v", err)
	}
	currentTime := requireEinoTool(t, einoTools, "current_time")

	output, err := currentTime.InvokableRun(context.Background(), `{}`)
	if err != nil {
		t.Fatalf("InvokableRun(current_time) error = %v", err)
	}
	if !strings.Contains(output, `"timezone":"Asia/Shanghai"`) {
		t.Fatalf("output = %s, want Asia/Shanghai timezone", output)
	}
}

func requireEinoTool(t *testing.T, items []tools.EinoInvokableTool, name string) tools.EinoInvokableTool {
	t.Helper()
	for _, item := range items {
		info, err := item.Info(context.Background())
		if err != nil {
			t.Fatalf("Info() error = %v", err)
		}
		if info.Name == name {
			return item
		}
	}
	t.Fatalf("tool %q not found", name)
	return nil
}
