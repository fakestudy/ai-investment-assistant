package agent

type GraphSpec struct {
	Name       string
	Entrypoint string
	Nodes      []NodeSpec
	Edges      []EdgeSpec
	Model      ModelSpec
	Tools      []ToolSpec
}

type NodeSpec struct {
	Name string
	Kind string
}

type EdgeSpec struct {
	From      string
	To        string
	Condition string
}

type ModelSpec struct {
	Provider string
}

type ToolSpec struct {
	Name string
}

func DefaultChatGraphSpec() GraphSpec {
	return GraphSpec{
		Name:       "default_chat_agent",
		Entrypoint: "chat_model",
		Nodes: []NodeSpec{
			{Name: "chat_model", Kind: "chat_model"},
			{Name: "tools", Kind: "tools"},
		},
		Edges: []EdgeSpec{
			{From: "chat_model", To: "tools", Condition: "model_requests_tool"},
		},
		Model: ModelSpec{Provider: "deepseek_openai_compatible"},
		Tools: []ToolSpec{
			{Name: "web_search"},
			{Name: "fetch_url"},
		},
	}
}
