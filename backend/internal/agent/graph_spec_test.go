package agent

import "testing"

func TestDefaultChatGraphSpec(t *testing.T) {
	spec := DefaultChatGraphSpec()

	if spec.Name != "default_chat_agent" {
		t.Fatalf("Name = %q, want default_chat_agent", spec.Name)
	}
	if spec.Entrypoint != "chat_model" {
		t.Fatalf("Entrypoint = %q, want chat_model", spec.Entrypoint)
	}
	if spec.Model.Provider != "deepseek_openai_compatible" {
		t.Fatalf("Model.Provider = %q", spec.Model.Provider)
	}
	if len(spec.Tools) != 3 {
		t.Fatalf("Tools len = %d, want 3", len(spec.Tools))
	}
	if spec.Tools[0].Name != "web_search" || spec.Tools[1].Name != "fetch_url" || spec.Tools[2].Name != "current_time" {
		t.Fatalf("Tools = %+v, want web_search, fetch_url, and current_time", spec.Tools)
	}
	if len(spec.Edges) != 1 {
		t.Fatalf("Edges len = %d, want 1", len(spec.Edges))
	}
	if spec.Edges[0].From != "chat_model" || spec.Edges[0].To != "tools" {
		t.Fatalf("Edge = %+v, want chat_model -> tools", spec.Edges[0])
	}
}
